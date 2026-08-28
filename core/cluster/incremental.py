"""Clustering incrementale: ogni articolo nuovo si aggancia alla story più
simile nella finestra temporale, oppure ne apre una nuova.

Metodo (documentato in docs/METHODOLOGY.md §2):
- embedding di titolo+snippet (backend dichiarato in Article.embedding_method);
- KNN sulle story con last_seen entro `cluster_window_hours` (default 72);
- aggancio se similarità coseno >= `cluster_similarity_threshold`, soglia
  calibrata su data/seeds/calibration_pairs.yaml (scripts/calibrate_threshold.py);
- centroide = media incrementale rinormalizzata; titolo neutro = titolo
  dell'articolo più vicino al centroide (mai generato, salvo LLM esplicito),
  preferendo gli articoli col titolo editoriale intatto (dal feed, con
  snippet) a quelli via GDELT dai titoli ritokenizzati;
- una story è "lampo" se raggiunge `flash_min_sources` testate entro
  `flash_window_hours` dalla prima apparizione (e lo resta).
"""

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.models import Article, Story, utcnow
from core.nlp.embed import Embedder, cosine, get_embedder
from core.provenance import record

from .knn import StoryIndex, nearest_stories

log = logging.getLogger(__name__)


@dataclass
class ClusterStats:
    processed: int = 0
    attached: int = 0
    created: int = 0
    skipped: int = 0
    new_flash: list[int] = field(default_factory=list)
    touched_story_ids: list[int] = field(default_factory=list)


def _article_time(article: Article) -> datetime:
    return article.published_at or article.fetched_at or utcnow()


def _embedding_text(article: Article) -> str:
    return f"{article.title}. {article.snippet}".strip()


def _merge_centroid(old: list[float], count_old: int, new: list[float]) -> list[float]:
    merged = [
        (o * count_old + n) / (count_old + 1) for o, n in zip(old, new, strict=True)
    ]
    norm = math.sqrt(sum(x * x for x in merged))
    if norm > 0:
        merged = [x / norm for x in merged]
    return merged


async def ensure_embedding(
    article: Article, embedder: Embedder | None = None
) -> list[float]:
    if article.embedding is not None:
        return article.embedding
    embedder = embedder or get_embedder()
    article.embedding = embedder.embed(_embedding_text(article))
    article.embedding_method = embedder.name
    return article.embedding


async def _refresh_counts(session: AsyncSession, story: Story) -> None:
    counts = (
        await session.execute(
            select(
                func.count(Article.id), func.count(func.distinct(Article.source_id))
            ).where(Article.story_id == story.id)
        )
    ).one()
    story.article_count = int(counts[0])
    story.source_count = int(counts[1])


async def refresh_title_neutral(session: AsyncSession, story: Story) -> None:
    """Titolo neutro = titolo dell'articolo più vicino al centroide del cluster.

    A parità di appartenenza al cluster si preferiscono gli articoli CON
    snippet: sono quelli arrivati dal feed della testata, col titolo
    editoriale intatto. Gli articoli via GDELT (senza snippet) hanno titoli
    ritokenizzati — apostrofi persi, nomi di paese riscritti — e vincono
    solo quando il cluster non ha di meglio.
    """
    if story.centroid is None:
        return
    articles = (
        (
            await session.execute(
                select(Article).where(
                    Article.story_id == story.id, Article.embedding.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    if not articles:
        return
    best = max(
        articles,
        key=lambda a: (
            1 if (a.snippet or "").strip() else 0,
            cosine(a.embedding or [], story.centroid or []),
        ),
    )
    story.title_neutral = best.title
    story.title_method = "centroide"


def _maybe_flash(story: Story, attach_time: datetime) -> bool:
    settings = get_settings()
    if story.is_flash:
        return False
    if (
        story.source_count >= settings.flash_min_sources
        and attach_time - story.first_seen <= timedelta(hours=settings.flash_window_hours)
    ):
        story.is_flash = True
        return True
    return False


async def assign_story(
    session: AsyncSession,
    article: Article,
    embedder: Embedder | None = None,
    *,
    index: StoryIndex | None = None,
    refresh_title: bool = True,
) -> tuple[Story, bool]:
    """Aggancia l'articolo a una story esistente o ne crea una nuova.

    Con `index` (clustering a lotti) i candidati e gli embedding dei membri
    vengono dall'indice in memoria invece che da una scansione del DB per
    ogni articolo. Con `refresh_title=False` il titolo neutro NON viene
    ricalcolato qui: nel clustering a lotti si ricalcola UNA volta a fine
    giro per ogni story toccata — farlo a ogni aggancio ricaricava tutti
    gli articoli della story ed era quadratico sulle story grandi.
    Ritorna (story, created).
    """
    settings = get_settings()
    embedder = embedder or get_embedder()
    embedding = await ensure_embedding(article, embedder)
    when = _article_time(article)
    since = when - timedelta(hours=settings.cluster_window_hours)

    if index is not None:
        matches = index.nearest(embedding, since=since, limit=5)
    else:
        matches = await nearest_stories(session, embedding, since=since, limit=5)
    best = matches[0] if matches else None

    # Doppio criterio anti-concatenazione: oltre alla similarità col centroide
    # (che deriva man mano che il cluster cresce), l'articolo deve somigliare
    # ad ALMENO UN membro reale della story. Vedi docs/METHODOLOGY.md §2.
    if best is not None and best.similarity >= settings.cluster_similarity_threshold:
        if index is not None:
            import numpy as np

            membri = await index.members(session, best.story_id)
            vettore = np.asarray(embedding, dtype=np.float64)
            # Vettori normalizzati: il prodotto scalare È il coseno.
            best_member = max((float(m @ vettore) for m in membri), default=0.0)
        else:
            member_embeddings = (
                await session.execute(
                    select(Article.embedding).where(
                        Article.story_id == best.story_id,
                        Article.embedding.is_not(None),
                    )
                )
            ).scalars()
            best_member = max(
                (cosine(embedding, m) for m in member_embeddings if m is not None),
                default=0.0,
            )
        if best_member < settings.cluster_similarity_threshold:
            best = None

    if best is not None and best.similarity >= settings.cluster_similarity_threshold:
        if index is not None and best.story_id in index.stories:
            story = index.stories[best.story_id]
        else:
            story = (
                await session.execute(select(Story).where(Story.id == best.story_id))
            ).scalar_one()
        article.story_id = story.id
        if story.centroid is not None:
            story.centroid = _merge_centroid(
                story.centroid, max(story.article_count, 1), embedding
            )
        else:
            story.centroid = embedding
        story.last_seen = max(story.last_seen, when)
        story.first_seen = min(story.first_seen, when)
        await session.flush()
        await _refresh_counts(session, story)
        if refresh_title:
            await refresh_title_neutral(session, story)
        _maybe_flash(story, when)
        created = False
    else:
        story = Story(
            title_neutral=article.title,
            title_method="centroide",
            first_seen=when,
            last_seen=when,
            article_count=1,
            source_count=1,
            centroid=embedding,
        )
        session.add(story)
        await session.flush()
        article.story_id = story.id
        created = True
    if index is not None:
        index.register(story)
        index.note_member(story.id, embedding)

    await record(
        session,
        entity_type="story",
        entity_id=story.id,
        field="cluster",
        method="knn-incremental-v1",
        inputs={
            "threshold": settings.cluster_similarity_threshold,
            "window_hours": settings.cluster_window_hours,
            "embedder": embedder.name,
            "last_article_id": article.id,
        },
    )
    await session.flush()
    return story, created


async def cluster_pending(
    session: AsyncSession,
    *,
    embedder: Embedder | None = None,
    batch: int = 500,
    progress: Callable[[int, int], None] | None = None,
    deadline: float | None = None,
) -> ClusterStats:
    """Processa gli articoli senza story, in ordine temporale. Idempotente.

    I candidati vengono da un indice in memoria costruito UNA volta
    (StoryIndex): con migliaia di articoli in coda, la scansione dei
    centroidi per ogni articolo rendeva il primo seed un finto blocco.
    `deadline` (time.monotonic) ferma il giro con garbo: gli articoli
    rimasti restano in coda per il giro successivo. `progress(fatti,
    totale)` permette a chi chiama di mostrare l'avanzamento.
    """
    embedder = embedder or get_embedder()
    stats = ClusterStats()
    articles = (
        (
            await session.execute(
                select(Article)
                .where(Article.story_id.is_(None))
                .order_by(Article.published_at.asc().nulls_last(), Article.id.asc())
                .limit(batch)
            )
        )
        .scalars()
        .all()
    )
    if not articles:
        return stats
    settings = get_settings()
    piu_vecchio = min(_article_time(a) for a in articles)
    finestra = piu_vecchio - timedelta(hours=settings.cluster_window_hours)
    index = StoryIndex(settings.embedding_dim)
    for story in (
        await session.execute(
            select(Story).where(
                Story.centroid.is_not(None), Story.last_seen >= finestra
            )
        )
    ).scalars():
        index.register(story)
    for indice, article in enumerate(articles, start=1):
        if deadline is not None and time.monotonic() > deadline:
            break
        if not article.title.strip():
            stats.skipped += 1
            continue
        try:
            story, created = await assign_story(
                session, article, embedder, index=index, refresh_title=False
            )
        except Exception as exc:
            # Un articolo indigesto NON deve congelare il raggruppamento: la
            # coda è ordinata per data, un errore in testa bloccherebbe tutto
            # l'arrivo di notizie nuove per sempre. Si salta e si riprova al
            # giro dopo (l'errore resta nel registro).
            stats.skipped += 1
            log.warning("articolo %s non raggruppabile ora: %s", article.id, exc)
            continue
        stats.processed += 1
        if created:
            stats.created += 1
        else:
            stats.attached += 1
        if story.id not in stats.touched_story_ids:
            stats.touched_story_ids.append(story.id)
        if story.is_flash and story.id not in stats.new_flash:
            stats.new_flash.append(story.id)
        if progress is not None:
            progress(indice, len(articles))
    # Titolo neutro UNA volta per story toccata, a fine giro (vedi
    # assign_story: farlo a ogni aggancio era quadratico).
    for story_id in stats.touched_story_ids:
        toccata = index.stories.get(story_id)
        if toccata is None:
            toccata = (
                await session.execute(select(Story).where(Story.id == story_id))
            ).scalar_one()
        await refresh_title_neutral(session, toccata)
    return stats

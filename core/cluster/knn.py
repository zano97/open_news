"""Ricerca dei vicini tra le story: nativa pgvector su PostgreSQL, in Python su SQLite.

Su PostgreSQL la distanza coseno usa l'operatore ``<=>`` e l'indice HNSW creato
dalla migrazione 0001; su SQLite (test) i candidati nella finestra temporale
vengono caricati e confrontati in Python: stessi risultati, volumi piccoli.

Per il clustering a LOTTI (seed, cluster_job) c'è ``StoryIndex``: i centroidi
si caricano UNA volta in una matrice numpy e ogni ricerca è un prodotto
matrice-vettore. Prima, su SQLite, ogni articolo rileggeva e decodificava
TUTTI i centroidi dal database: col primo seed vero (migliaia di articoli in
coda) il clustering diventava quadratico e sembrava un blocco.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Article, Story
from core.nlp.embed import cosine


@dataclass(frozen=True)
class StoryMatch:
    story_id: int
    similarity: float


class StoryIndex:
    """Indice in memoria dei centroidi per un giro di clustering.

    Tiene anche gli embedding dei MEMBRI di ciascuna story (caricati
    pigramente, una volta sola) per il doppio criterio anti-concatenazione:
    prima venivano riletti dal database a ogni aggancio.
    I vettori dei nostri backend sono normalizzati: il prodotto scalare È
    la similarità coseno.
    """

    def __init__(self, dim: int) -> None:
        self._dim = dim
        self._matrix: NDArray[np.float64] = np.zeros((64, dim))
        self._n = 0
        self._ids: list[int] = []
        self._last_seen: list[datetime] = []
        self._pos: dict[int, int] = {}
        self.stories: dict[int, Story] = {}
        self._members: dict[int, list[NDArray[np.float64]]] = {}

    def register(self, story: Story) -> None:
        """Aggiunge o aggiorna una story (centroide e last_seen correnti)."""
        if story.centroid is None:
            return
        riga = np.asarray(story.centroid, dtype=np.float64)
        pos = self._pos.get(story.id)
        if pos is None:
            if self._n == self._matrix.shape[0]:
                nuova = np.zeros((self._matrix.shape[0] * 2, self._dim))
                nuova[: self._n] = self._matrix[: self._n]
                self._matrix = nuova
            pos = self._n
            self._n += 1
            self._ids.append(story.id)
            self._last_seen.append(story.last_seen)
            self._pos[story.id] = pos
        else:
            self._last_seen[pos] = story.last_seen
        self._matrix[pos] = riga
        self.stories[story.id] = story

    def nearest(
        self, embedding: list[float], *, since: datetime, limit: int = 5
    ) -> list[StoryMatch]:
        if self._n == 0:
            return []
        sims = self._matrix[: self._n] @ np.asarray(embedding, dtype=np.float64)
        out: list[StoryMatch] = []
        for i in np.argsort(-sims):
            if self._last_seen[int(i)] >= since:
                out.append(StoryMatch(self._ids[int(i)], float(sims[int(i)])))
                if len(out) >= limit:
                    break
        return out

    async def members(
        self, session: AsyncSession, story_id: int
    ) -> list[NDArray[np.float64]]:
        """Embedding dei membri della story, dal DB la prima volta e poi in memoria."""
        if story_id not in self._members:
            rows = (
                await session.execute(
                    select(Article.embedding).where(
                        Article.story_id == story_id, Article.embedding.is_not(None)
                    )
                )
            ).scalars()
            self._members[story_id] = [
                np.asarray(e, dtype=np.float64) for e in rows if e is not None
            ]
        return self._members[story_id]

    def note_member(self, story_id: int, embedding: list[float]) -> None:
        """Registra l'embedding di un articolo appena agganciato."""
        if story_id in self._members:
            self._members[story_id].append(np.asarray(embedding, dtype=np.float64))


async def nearest_stories(
    session: AsyncSession,
    embedding: list[float],
    *,
    since: datetime,
    limit: int = 5,
) -> list[StoryMatch]:
    """Le story più simili (per centroide) viste dopo `since`, ordinate per similarità."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        rows = (
            await session.execute(
                text(
                    "SELECT id, 1 - (centroid <=> CAST(:emb AS vector)) AS sim "
                    "FROM stories "
                    "WHERE centroid IS NOT NULL AND last_seen >= :since "
                    "ORDER BY centroid <=> CAST(:emb AS vector) "
                    "LIMIT :lim"
                ),
                {"emb": str(embedding), "since": since, "lim": limit},
            )
        ).all()
        return [StoryMatch(int(r[0]), float(r[1])) for r in rows]

    stories = (
        (
            await session.execute(
                select(Story).where(Story.centroid.is_not(None), Story.last_seen >= since)
            )
        )
        .scalars()
        .all()
    )
    matches = [
        StoryMatch(story.id, cosine(embedding, story.centroid))
        for story in stories
        if story.centroid is not None
    ]
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:limit]

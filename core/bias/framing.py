"""Livello 3 — Framing: lessico, attori citati, tono. Aggregati per fonte.

Tutto è conteggio dichiarato: niente giudizi sul singolo articolo. I testi
analizzati sono titolo+snippet (pubblici) e, quando disponibile, il testo
integrale scaricato per uso interno: dei contenuti interni escono solo
statistiche aggregate, mai il testo.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.bias.signals import write_signal
from core.models import Article, Source, utcnow
from core.nlp.actors import METHOD_NAME as ACTORS_METHOD
from core.nlp.actors import extract_citations
from core.nlp.lexicon import METHOD_NAME as LEXICON_METHOD
from core.nlp.lexicon import count_terms
from core.nlp.tone import METHOD_NAME as TONE_METHOD
from core.nlp.tone import score_title

log = logging.getLogger(__name__)

MIN_ARTICLES_FOR_FRAMING = 5


async def _articles_by_source(
    session: AsyncSession, since_days: int
) -> dict[int, list[Article]]:
    since = utcnow() - timedelta(days=since_days)
    articles = (
        (
            await session.execute(
                select(Article).where(Article.fetched_at >= since)
            )
        )
        .scalars()
        .all()
    )
    per_source: dict[int, list[Article]] = {}
    for article in articles:
        per_source.setdefault(article.source_id, []).append(article)
    return per_source


async def compute_framing(session: AsyncSession, *, window_days: int = 30) -> int:
    """Conteggio dei termini del lessico di framing per fonte."""
    until = utcnow()
    since = until - timedelta(days=window_days)
    per_source = await _articles_by_source(session, window_days)
    written = 0
    for source_id, articles in per_source.items():
        if len(articles) < MIN_ARTICLES_FOR_FRAMING:
            continue
        groups: dict[str, dict[str, int]] = {}
        for article in articles:
            text = " ".join(
                part for part in (article.title, article.snippet, article.full_text) if part
            )
            for group_id, counts in count_terms(text, article.language).items():
                bucket = groups.setdefault(group_id, {})
                for term, n in counts.items():
                    bucket[term] = bucket.get(term, 0) + n
        await write_signal(
            session,
            source_id=source_id,
            signal_type="framing",
            period_start=since.date(),
            period_end=until.date(),
            value={"groups": groups},
            n_articles=len(articles),
            method=LEXICON_METHOD,
            inputs={"lexicons": ["it", "en"]},
        )
        written += 1
    return written


async def compute_actors(session: AsyncSession, *, window_days: int = 30) -> int:
    """"Chi lascia parlare": ruoli e voci citate, aggregati per fonte."""
    until = utcnow()
    since = until - timedelta(days=window_days)
    per_source = await _articles_by_source(session, window_days)
    written = 0
    for source_id, articles in per_source.items():
        if len(articles) < MIN_ARTICLES_FOR_FRAMING:
            continue
        roles: dict[str, int] = {}
        speakers: dict[str, int] = {}
        analyzed = 0
        for article in articles:
            text = " ".join(
                part for part in (article.title, article.snippet, article.full_text) if part
            )
            citations = extract_citations(text)
            if citations:
                analyzed += 1
            for citation in citations:
                role = citation.role or "non classificato"
                roles[role] = roles.get(role, 0) + 1
                speakers[citation.speaker] = speakers.get(citation.speaker, 0) + 1
        top_speakers = sorted(speakers.items(), key=lambda kv: kv[1], reverse=True)[:15]
        await write_signal(
            session,
            source_id=source_id,
            signal_type="actors",
            period_start=since.date(),
            period_end=until.date(),
            value={
                "roles": roles,
                "top_speakers": [
                    {"name": name, "count": count} for name, count in top_speakers
                ],
                "articles_with_citations": analyzed,
            },
            n_articles=len(articles),
            method=ACTORS_METHOD,
        )
        written += 1
    return written


async def compute_tone(session: AsyncSession, *, window_days: int = 30) -> int:
    """Distribuzione del tono dei titoli per fonte (mai giudizio sul singolo)."""
    until = utcnow()
    since = until - timedelta(days=window_days)
    per_source = await _articles_by_source(session, window_days)
    written = 0
    for source_id, articles in per_source.items():
        if len(articles) < MIN_ARTICLES_FOR_FRAMING:
            continue
        distribution = {"negativo": 0, "neutro": 0, "positivo": 0}
        for article in articles:
            tone = score_title(article.title, article.language)
            distribution[tone.label] += 1
        await write_signal(
            session,
            source_id=source_id,
            signal_type="tone",
            period_start=since.date(),
            period_end=until.date(),
            value=distribution,
            n_articles=len(articles),
            method=TONE_METHOD,
        )
        written += 1
    return written


async def _source_name(session: AsyncSession, source_id: int) -> str:
    return (
        await session.execute(select(Source.name).where(Source.id == source_id))
    ).scalar_one()

"""Job di analisi: clustering incrementale, copertura, segnali settimanali."""

import logging

from sqlalchemy import select

from core.bias.aggregate import compute_weekly_signals
from core.cluster.coverage import compute_coverage
from core.cluster.incremental import cluster_pending
from core.db import get_sessionmaker
from core.models import Story
from core.net import build_client
from core.nlp.entities import assign_story_entities, link_entities_wikidata
from core.nlp.summarize import stories_needing_summary, summarize_story

log = logging.getLogger(__name__)


async def signals_job() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        await compute_weekly_signals(session)
        await session.commit()


async def cluster_job() -> None:
    import time

    from core.bias.selection import compute_blindspots
    from core.refresh_state import tracking

    maker = get_sessionmaker()
    async with tracking("clustering"), maker() as session:
        from core import refresh_state

        # Deadline sotto l'intervallo del job (10 min): un arretrato enorme
        # si smaltisce in più giri invece di accavallarli.
        stats = await cluster_pending(
            session, deadline=time.monotonic() + 480
        )
        # Gli agganci sono al sicuro SUBITO: coperture ed entità arrivano
        # dopo, in transazioni corte.
        await session.commit()
        refresh_state.set_progress("clustering", 0, len(stats.touched_story_ids) or 1)
        for indice, story_id in enumerate(stats.touched_story_ids, start=1):
            refresh_state.set_progress(
                "clustering", indice, len(stats.touched_story_ids)
            )
            story = (
                await session.execute(select(Story).where(Story.id == story_id))
            ).scalar_one()
            await compute_coverage(session, story)
            await assign_story_entities(session, story)
            if indice % 25 == 0:
                await session.commit()
        if stats.processed:
            # Notizie nuove = copertura cambiata: gli angoli ciechi si
            # ricalcolano SUBITO, a ogni aggiornamento (anche quello del
            # pulsante «Aggiorna ora», che finisce proprio qui).
            await compute_blindspots(session)
        await session.commit()
    if stats.processed:
        log.info(
            "clustering: %d articoli (%d agganciati, %d nuove story, %d lampo)",
            stats.processed, stats.attached, stats.created, len(stats.new_flash),
        )


async def link_entities_job() -> None:
    """Collega a Wikidata le entità delle story recenti (best-effort)."""
    maker = get_sessionmaker()
    async with build_client() as client, maker() as session:
        linked = await link_entities_wikidata(session, client, limit=15)
        await session.commit()
    if linked:
        log.info("entità collegate a Wikidata: %d", linked)


async def summarize_job() -> None:
    """Riassunti neutri per le story recenti multi-fonte (solo con ENABLE_LLM)."""
    from core.config import get_settings

    if not get_settings().enable_llm:
        return
    maker = get_sessionmaker()
    async with build_client(timeout=200) as client, maker() as session:
        stories = await stories_needing_summary(session, limit=10)
        done = 0
        for story in stories:
            if await summarize_story(session, story, client=client):
                done += 1
        await session.commit()
    if done:
        log.info("riassunti neutri generati: %d", done)


async def blindspot_job() -> None:
    """Ricalcola gli angoli ciechi (v2, test di significatività).

    Fuori dal giro settimanale: i flag devono aggiornarsi (e AZZERARSI,
    quando le condizioni non valgono più) entro ore, non entro lunedì.
    """
    from core.bias.selection import compute_blindspots
    from core.refresh_state import tracking

    maker = get_sessionmaker()
    async with tracking("angoli ciechi"), maker() as session:
        await compute_blindspots(session)
        await session.commit()


async def refresh_settings_job() -> None:
    """Ricarica gli override del pannello admin (prevalgono sull'ambiente)."""
    from core.runtime_settings import load_overrides

    maker = get_sessionmaker()
    try:
        async with maker() as session:
            await load_overrides(session)
    except Exception:  # DB non pronto: si riprova al prossimo giro
        log.info("override impostazioni non caricati (DB non pronto)")


async def translate_titles_job() -> None:
    """Traduce i titoli neutri delle story recenti, prima nelle lingue USATE.

    Solo Argos (offline; scarica da sé le coppie mancanti): il generatore
    LLM resta riservato ai riassunti, per scelta esplicita. Le lingue che
    il lettore sta davvero guardando passano davanti; un errore su una
    story non ferma le altre; un budget di tempo garantisce che il giro
    finisca prima del successivo (ogni 15 minuti).
    """
    import time

    from core.i18n import locales_by_priority
    from core.nlp.translate import (
        get_translator,
        stories_to_translate,
        translate_story_title,
    )
    from core.refresh_state import tracking

    if get_translator() is None:
        return
    maker = get_sessionmaker()
    scadenza = time.monotonic() + 480  # 8 minuti: mai oltre il giro dopo
    async with tracking("traduzioni"), maker() as session:
        # NELL'ORDINE della prima pagina (core.ranking): si traduce prima
        # ciò che il lettore sta per vedere, mai story che nessuno guarda.
        stories = await stories_to_translate(session, limit=200)
        from core import refresh_state

        targets = locales_by_priority()
        added = 0
        refresh_state.set_progress("traduzioni", 0, len(stories))
        for indice, story in enumerate(stories, start=1):
            if time.monotonic() > scadenza:
                break
            try:
                fatte = await translate_story_title(session, story, targets=targets)
                if fatte:
                    # Commit PER STORY: ogni traduzione è al sicuro subito,
                    # e la transazione resta corta (SQLite ringrazia).
                    await session.commit()
                added += fatte
            except Exception as exc:  # una story indigesta non ferma il giro
                await session.rollback()
                log.warning("titolo della story %s non tradotto: %s", story.id, exc)
            refresh_state.set_progress("traduzioni", indice, len(stories))
        await session.commit()
    if added:
        log.info("titoli neutri tradotti: %d", added)


async def enrich_owners_job() -> None:
    """Fatti Wikidata sui proprietari con QID confermato (best-effort, 1/giorno)."""
    from core.bias.structure import enrich_owner_from_wikidata
    from core.models import Owner

    maker = get_sessionmaker()
    async with build_client() as client, maker() as session:
        owners = (
            (
                await session.execute(
                    select(Owner).where(Owner.wikidata_qid.is_not(None)).limit(30)
                )
            )
            .scalars()
            .all()
        )
        arricchiti = 0
        for owner in owners:
            try:
                if await enrich_owner_from_wikidata(session, owner, client):
                    arricchiti += 1
            except Exception as exc:  # rete assente: si riprova domani
                log.info("arricchimento %s rimandato: %s", owner.name, exc)
                break
        await session.commit()
    if arricchiti:
        log.info("proprietari arricchiti da Wikidata: %d", arricchiti)

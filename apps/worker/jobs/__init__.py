"""Registro dei job del worker. Ogni fase aggiunge i propri."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from apps.worker.jobs.analyze import (
    blindspot_job,
    cluster_job,
    enrich_owners_job,
    link_entities_job,
    refresh_settings_job,
    signals_job,
    translate_titles_job,
)
from apps.worker.jobs.ingest import (
    fetch_fulltext_job,
    ingest_feeds_job,
    ingest_gdelt_job,
    ingest_social_job,
    osint_job,
    sync_catalog_job,
)

log = logging.getLogger("opennews.worker.jobs")


async def heartbeat() -> None:
    log.info("heartbeat: worker attivo")


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    # RECUPERO ALL'AVVIO: i job a intervallo, da soli, partirebbero solo
    # DOPO il primo intervallo — chi apre l'app per pochi minuti non
    # vedrebbe mai un aggiornamento. `next_run_time` scaglionato fa partire
    # la raccolta subito dopo l'avvio (dedup e cache condizionale rendono
    # il recupero economico anche quando non c'è nulla di nuovo).
    from datetime import datetime, timedelta

    def tra(secondi: int) -> datetime:
        return datetime.now(scheduler.timezone) + timedelta(seconds=secondi)

    scheduler.add_job(heartbeat, "interval", minutes=15, id="heartbeat")
    # Gli override del pannello admin: subito all'avvio e poi ogni 5 minuti.
    scheduler.add_job(refresh_settings_job, id="refresh_settings")
    scheduler.add_job(
        refresh_settings_job, "interval", minutes=5, id="refresh_settings_periodic"
    )
    # Il catalogo si sincronizza subito all'avvio e poi ogni 6 ore.
    scheduler.add_job(sync_catalog_job, id="sync_catalog")
    scheduler.add_job(sync_catalog_job, "interval", hours=6, id="sync_catalog_periodic")
    scheduler.add_job(
        ingest_feeds_job, "interval", minutes=10, id="ingest_feeds",
        max_instances=1, next_run_time=tra(10),
    )
    scheduler.add_job(
        ingest_gdelt_job, "interval", minutes=30, id="ingest_gdelt",
        max_instances=1, next_run_time=tra(40),
    )
    # Canali social ufficiali delle testate (Bluesky/Mastodon): pochi account,
    # API pubbliche leggere — ogni 30 minuti, poco dopo il primo giro feed.
    scheduler.add_job(
        ingest_social_job, "interval", minutes=30, id="ingest_social",
        max_instances=1, next_run_time=tra(70),
    )
    scheduler.add_job(
        fetch_fulltext_job, "interval", minutes=15, id="fetch_fulltext",
        max_instances=1, next_run_time=tra(240),
    )
    scheduler.add_job(
        cluster_job, "interval", minutes=10, id="cluster",
        max_instances=1, next_run_time=tra(120),
    )
    scheduler.add_job(
        link_entities_job, "interval", minutes=30, id="link_entities",
        max_instances=1, next_run_time=tra(300),
    )
    # Profilo pubblico delle testate (ads.txt, trasparenza dichiarata,
    # archivio): una volta al giorno, poche testate per giro.
    scheduler.add_job(
        osint_job, "interval", hours=24, id="osint",
        max_instances=1, next_run_time=tra(600),
    )
    # Fatti Wikidata sui proprietari con QID confermato: una volta al giorno.
    scheduler.add_job(
        enrich_owners_job, "interval", hours=24, id="enrich_owners", max_instances=1
    )
    # Traduzioni dei titoli neutri: attive solo con l'extra [translate].
    scheduler.add_job(
        translate_titles_job, "interval", minutes=15, id="translate_titles",
        max_instances=1, next_run_time=tra(180),
    )
    # Angoli ciechi: il ricalcolo VERO avviene a ogni clustering (cioè a
    # ogni aggiornamento delle notizie, pulsante compreso); questo giro
    # copre solo i passaggi di maturità quando non arriva nulla di nuovo.
    scheduler.add_job(
        blindspot_job, "interval", hours=2, id="blindspots",
        max_instances=1, next_run_time=tra(900),
    )
    # I riassunti NON girano in automatico: si generano solo su richiesta
    # del lettore (pulsante nella pagina story) o dell'admin (pannello).
    # Segnali dei livelli 2-3: ricalcolo settimanale, datato (metodologia §5).
    scheduler.add_job(
        signals_job, "cron", day_of_week="mon", hour=4, id="signals_weekly",
        max_instances=1,
    )

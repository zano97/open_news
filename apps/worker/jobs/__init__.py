"""Registro dei job del worker. Ogni fase aggiunge i propri."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = logging.getLogger("opennews.worker.jobs")


async def heartbeat() -> None:
    log.info("heartbeat: worker attivo")


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(heartbeat, "interval", minutes=15, id="heartbeat")

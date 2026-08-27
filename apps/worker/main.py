"""Worker: scheduler dei job di raccolta e analisi.

Ogni job è idempotente e loggato; i job veri vengono registrati per fase in
`apps.worker.jobs.register_jobs`. Il worker gira come processo separato nello
stack compose e condivide il DB con l'API.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from apps.worker.jobs import register_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("opennews.worker")


async def run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    register_jobs(scheduler)
    scheduler.start()
    log.info("worker avviato: %d job registrati", len(scheduler.get_jobs()))
    try:
        while True:  # il processo vive finché compose non lo ferma
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(run())

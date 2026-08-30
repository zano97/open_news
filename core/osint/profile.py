"""Profilo OSINT di una testata: raccolta, salvataggio, provenance.

Mette insieme i segnali pubblici (ads.txt, dati strutturati di
trasparenza, prima copia archiviata) in un unico blocco salvato su
``Source.osint``. Ogni raccolta lascia una riga di provenance con
metodo e URL dell'evidenza: in pagina il lettore vede sempre da dove
viene il dato e può controllarlo.
"""

import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.models import Source, utcnow
from core.osint.adstxt import conti_condivisi, fetch_ads_txt
from core.osint.fetch import scarica_pagina
from core.osint.trust import parse_trust_markup
from core.osint.wayback import prima_copia
from core.provenance import record

log = logging.getLogger(__name__)

METHOD_NAME = "osint-fonti-v1"
# Ogni testata si riprofila al più una volta ogni tot giorni: questi dati
# cambiano di rado e il rispetto per i siti viene prima della freschezza.
RIPETI_DOPO_GIORNI = 14
# Un tentativo ANDATO A VUOTO (rete assente, sito irraggiungibile) non deve
# bloccare la testata per due settimane: si riprova dopo poche ore.
RIPETI_SE_VUOTO_ORE = 6


def profilo_vuoto(dati: dict[str, Any]) -> bool:
    """Vero se dal tentativo non è uscito NIENTE di utile: né reti
    pubblicitarie, né impegni dichiarati, né data d'archivio."""
    pubblicita = dati.get("pubblicita") or {}
    trasparenza = dati.get("trasparenza") or {}
    return not (
        pubblicita.get("reti")
        or trasparenza.get("impegni")
        or dati.get("prima_copia_archiviata")
        # ads.txt assente è un ESITO valido: la testata non lo pubblica.
        or pubblicita.get("stato") == "assente"
    )


def _da_rinfrescare(source: Source, adesso: datetime) -> bool:
    dati = source.osint or {}
    quando = dati.get("aggiornato_il")
    if not isinstance(quando, str):
        return True
    try:
        ultimo = datetime.fromisoformat(quando)
    except ValueError:
        return True
    trascorso = adesso - ultimo
    if profilo_vuoto(dati):
        return trascorso.total_seconds() >= RIPETI_SE_VUOTO_ORE * 3600
    return trascorso.days >= RIPETI_DOPO_GIORNI


async def profila_fonte(
    session: AsyncSession,
    source: Source,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
    rendi: bool = True,
) -> dict[str, Any]:
    """Raccoglie i segnali pubblici di una testata e li salva. Idempotente.

    Con ``rendi=False`` niente rendering browser (Scrapling): è la via
    rapida per la raccolta su richiesta dalla scheda — il giro di sfondo
    ripassa con calma e con il browser dove serve.
    """
    dominio = source.domain
    profilo: dict[str, Any] = {"aggiornato_il": utcnow().isoformat()}

    ads = await fetch_ads_txt(dominio, client=client, limiter=limiter)
    profilo["pubblicita"] = {
        "url": ads.url,
        "stato": ads.error or "letto",
        "reti": ads.reti(),
        "conti_diretti": [
            {"rete": e.exchange, "id": e.publisher_id} for e in ads.diretti
        ],
        "n_righe": len(ads.entries),
    }

    home = await scarica_pagina(
        f"https://{dominio}/", client=client, limiter=limiter, robots=robots,
        rendi=rendi,
    )
    if home.ok:
        trust = parse_trust_markup(home.html)
        profilo["trasparenza"] = {
            "nome_dichiarato": trust.nome_dichiarato,
            "fondazione_dichiarata": trust.fondazione,
            "editore_dichiarato": trust.editore,
            "impegni": trust.impegni,
            "punteggio": trust.punteggio,
            "motore": home.motore,
        }
    else:
        profilo["trasparenza"] = {"errore": home.error or "pagina non letta"}

    archiviato = await prima_copia(dominio, client=client, limiter=limiter)
    if archiviato:
        profilo["prima_copia_archiviata"] = archiviato

    source.osint = profilo
    source.last_checked_at = utcnow()
    await record(
        session,
        entity_type="source",
        entity_id=source.id,
        field="osint",
        method=METHOD_NAME,
        inputs={
            "ads_txt": ads.url,
            "trasparenza": f"https://{dominio}/",
            "archivio": "https://web.archive.org/",
        },
        source_name="Fonti pubbliche della testata + Internet Archive",
        source_url=ads.url,
    )
    await session.flush()
    return profilo


async def profila_fonti(
    session: AsyncSession,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
    limite: int = 20,
    scadenza: float | None = None,
) -> int:
    """Profila le testate mai viste o più stantie. Ritorna quante fatte."""
    import time

    adesso = utcnow()
    fonti = (
        (
            await session.execute(
                select(Source).where(Source.enabled.is_(True)).order_by(
                    Source.last_checked_at.asc().nulls_first(), Source.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    fatte = 0
    for source in fonti:
        if fatte >= limite:
            break
        if scadenza is not None and time.monotonic() > scadenza:
            break
        if not _da_rinfrescare(source, adesso):
            continue
        try:
            await profila_fonte(
                session, source, client=client, limiter=limiter, robots=robots
            )
            # Ogni profilo al sicuro subito: transazioni corte.
            await session.commit()
            fatte += 1
        except Exception as exc:  # una testata ostile non ferma le altre
            await session.rollback()
            log.warning("profilo OSINT di %s rimandato: %s", source.slug, exc)
    return fatte


async def rete_di_conti(session: AsyncSession) -> list[dict[str, Any]]:
    """Indizi di gestione comune: conti pubblicitari diretti condivisi.

    Legge i profili già salvati (nessuna richiesta di rete) e restituisce
    i gruppi di testate che dichiarano lo stesso conto presso la stessa
    rete. Indizio, non verdetto: l'interfaccia mostra l'evidenza.
    """
    from core.osint.adstxt import AdsEntry, AdsProfile

    profili: dict[str, AdsProfile] = {}
    for source in (
        await session.execute(select(Source).where(Source.enabled.is_(True)))
    ).scalars():
        dati = (source.osint or {}).get("pubblicita") or {}
        conti = dati.get("conti_diretti") or []
        if not conti:
            continue
        profili[source.slug] = AdsProfile(
            url=str(dati.get("url") or ""),
            entries=[
                AdsEntry(str(c.get("rete")), str(c.get("id")), "direct")
                for c in conti
                if c.get("rete") and c.get("id")
            ],
        )
    return conti_condivisi(profili)


# Testate già in lavorazione on-demand: mai due volte lo stesso lavoro.
_KICK_IN_CORSO: set[str] = set()


def profilo_in_corso(slug: str) -> bool:
    return slug in _KICK_IN_CORSO


def kick_profilo(slug: str) -> object | None:
    """Fuoco-e-dimentica dalla scheda della testata: se il profilo manca,
    lo si raccoglie SUBITO in sottofondo invece di aspettare il giro.

    Il lettore che apre una scheda è il segnale più chiaro di quale
    testata interessa: profilarla in quel momento è più utile (e più
    gentile verso i siti) che macinare tutto il catalogo a vuoto.
    """
    import asyncio

    if slug in _KICK_IN_CORSO:
        return None
    _KICK_IN_CORSO.add(slug)

    async def _run() -> None:
        try:
            from core.db import get_sessionmaker
            from core.ingest.ratelimit import DomainRateLimiter
            from core.ingest.robots import RobotsCache
            from core.net import build_client

            maker = get_sessionmaker()
            async with build_client() as client, maker() as session:
                source = (
                    await session.execute(select(Source).where(Source.slug == slug))
                ).scalar_one_or_none()
                if source is None:
                    return
                await profila_fonte(
                    session,
                    source,
                    client=client,
                    limiter=DomainRateLimiter(),
                    robots=RobotsCache(client),
                    rendi=False,  # via rapida: il lettore sta aspettando
                )
                await session.commit()
            log.info("profilo pubblico raccolto su richiesta: %s", slug)
        except Exception as exc:  # sito irraggiungibile: riproverà il giro
            log.info("profilo pubblico di %s rimandato: %s", slug, exc)
        finally:
            _KICK_IN_CORSO.discard(slug)

    return asyncio.create_task(_run())


async def conteggio_profili(session: AsyncSession) -> tuple[int, int]:
    """(testate con profilo, testate attive): per il pannello Diagnostica."""
    from sqlalchemy import func

    attive = (
        await session.execute(
            select(func.count()).select_from(Source).where(Source.enabled.is_(True))
        )
    ).scalar_one()
    con_profilo = 0
    for source in (
        await session.execute(select(Source).where(Source.enabled.is_(True)))
    ).scalars():
        if source.osint:
            con_profilo += 1
    return con_profilo, int(attive)

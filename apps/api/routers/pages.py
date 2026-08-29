"""Pagine HTML (Jinja2 + HTMX)."""

import json
import logging
import math
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.signal_views import shape_signals
from apps.api.svg import cocoverage_scatter_svg, coverage_bar_svg, ownership_graph_svg
from apps.api.templating import templates
from core import refresh_state
from core.auth import SESSION_COOKIE, read_session_token
from core.bias.selection import cocoverage_map
from core.bias.structure import source_profile
from core.db import get_session
from core.i18n import (
    LOCALE_COOKIE,
    LOCALE_NAMES,
    SUPPORTED_LOCALES,
    make_translator,
    normalize_locale,
    resolve_locale,
)
from core.models import (
    AnnotatorProfile,
    Article,
    BiasSignal,
    Coverage,
    Owner,
    Ownership,
    Source,
    Story,
    utcnow,
)
from core.nlp.topics import load_topics
from core.provenance import for_entity
from core.ranking import (
    finestra_attualita,
    finestra_ultima_ora,
    peso_attualita,
)

log = logging.getLogger(__name__)

router = APIRouter()


def topic_labels_for(locale: str) -> dict[str, str]:
    """Etichette dei temi: italiano per 'it', inglese per le altre lingue."""
    return {
        t.id: (t.label_it if locale == "it" else t.label_en) for t in load_topics()
    }


def request_locale(request: Request) -> str:
    """Lingua della richiesta: ?lang=xx > cookie > default (deterministico)."""
    locale = resolve_locale(
        request.query_params.get("lang"), request.cookies.get(LOCALE_COOKIE)
    )
    # Il job di traduzione dei titoli dà precedenza alle lingue davvero usate.
    from core.i18n import note_locale_use

    note_locale_use(locale)
    return locale


async def _session_user(
    request: Request, session: AsyncSession
) -> AnnotatorProfile | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    annotator_id = read_session_token(token)
    if annotator_id is None:
        return None
    return (
        await session.execute(
            select(AnnotatorProfile).where(AnnotatorProfile.id == annotator_id)
        )
    ).scalar_one_or_none()


async def refresh_runtime_settings(session: AsyncSession) -> None:
    """Applica gli override del pannello a QUESTO processo, a ogni richiesta.

    L'API gira con più worker uvicorn: un salvataggio dal pannello aggiorna
    il processo che lo riceve e il DB, ma gli altri processi resterebbero
    indietro. Una piccola SELECT per richiesta li tiene tutti allineati.
    """
    try:
        from core.runtime_settings import load_overrides

        await load_overrides(session)
    except Exception:  # tabella assente (primo avvio): valgono i default
        pass


async def page_context(
    request: Request, session: AsyncSession
) -> dict[str, Any]:
    """Contesto comune a tutte le pagine: numeri di testata + lingua + t()."""
    await refresh_runtime_settings(session)
    locale = request_locale(request)
    return {
        **await masthead_context(session),
        "locale": locale,
        "t": make_translator(locale),
        "locales": [
            (code, LOCALE_NAMES[code]) for code in SUPPORTED_LOCALES
        ],
        "current_path": request.url.path,
        "current_user": await _session_user(request, session),
        # Istanza personale (un solo utente, legata a 127.0.0.1): niente
        # account obbligatorio per le impostazioni, livello 4 ridimensionato.
        "personal_mode": os.environ.get("OPENNEWS_EMBEDDED_WORKER") == "1",
        "aggiornamento_in_corso": (
            bool(_aggiornamento["in_corso"]) or refresh_state.is_running()
        ),
    }


# Aggiornamento su richiesta: UN task in sottofondo alla volta. L'app
# continua a servire ogni pagina (server asincrono); a fine giro il
# client ricarica e mostra le notizie nuove.
_aggiornamento: dict[str, Any] = {"in_corso": False, "task": None}


def _puo_aggiornare(personal_mode: bool, user: AnnotatorProfile | None) -> bool:
    return personal_mode or (user is not None and user.is_admin)


async def _giro_di_aggiornamento() -> None:
    from apps.worker.jobs.analyze import cluster_job
    from apps.worker.jobs.ingest import ingest_feeds_job, ingest_gdelt_job

    refresh_state.begin_manual()
    try:
        await ingest_feeds_job()
        await ingest_gdelt_job()
        await cluster_job()
        log.info("aggiornamento su richiesta completato")
    except Exception:
        log.exception("aggiornamento su richiesta fallito")
    finally:
        refresh_state.end_manual()
        _aggiornamento["in_corso"] = False
        _aggiornamento["task"] = None


@router.post("/aggiorna")
async def aggiorna_ora(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    """Avvia subito feed + GDELT + clustering, in sottofondo."""
    import asyncio

    personal = os.environ.get("OPENNEWS_EMBEDDED_WORKER") == "1"
    user = await _session_user(request, session)
    if not _puo_aggiornare(personal, user):
        raise HTTPException(status_code=403, detail="solo admin")
    if not _aggiornamento["in_corso"]:
        _aggiornamento["in_corso"] = True
        _aggiornamento["task"] = asyncio.create_task(_giro_di_aggiornamento())
    ritorno = request.headers.get("referer") or "/"
    if not ritorno.startswith(("http://" + request.url.netloc,
                               "https://" + request.url.netloc, "/")):
        ritorno = "/"
    return RedirectResponse(ritorno, status_code=303)


@router.get("/api/aggiornamento")
async def stato_aggiornamento(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Per il client: barra col progresso VERO (feed e gruppi contati)."""
    percento, fase = refresh_state.overall()
    ultimo = (
        await session.execute(select(func.max(Article.fetched_at)))
    ).scalar_one_or_none()
    return {
        "in_corso": bool(_aggiornamento["in_corso"]) or refresh_state.is_running(),
        "giro_manuale": bool(_aggiornamento["in_corso"]),
        "percento": percento,
        "fase": fase,
        # Ora LOCALE dell'ultimo articolo raccolto: la testata la mostra viva.
        "ultimo": ultimo.astimezone().strftime("%H:%M") if ultimo else None,
    }


@router.get("/api/osint/{slug}")
async def stato_osint(
    slug: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict[str, bool]:
    """Per la scheda testata: il profilo pubblico è pronto? (sonda leggera)"""
    from core.osint.profile import profilo_in_corso, profilo_vuoto

    source = (
        await session.execute(select(Source).where(Source.slug == slug))
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="fonte sconosciuta")
    dati = source.osint or {}
    return {
        "pronto": bool(dati) and not profilo_vuoto(dati),
        "in_corso": profilo_in_corso(slug),
    }


@router.get("/lingua/{code}")
async def cambia_lingua(code: str, next: str = "/") -> RedirectResponse:
    """Imposta la lingua dell'interfaccia (cookie) e torna alla pagina."""
    locale = normalize_locale(code)
    if locale is None:
        raise HTTPException(status_code=404, detail="lingua non supportata")
    # Guardia anti open-redirect: solo percorsi interni.
    destination = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        LOCALE_COOKIE, locale, max_age=60 * 60 * 24 * 365, samesite="lax"
    )
    return response


# Finestra e peso vivono in core.ranking (condivisi col job di traduzione
# dei titoli, che serve prima ciò che il lettore sta per vedere).


async def _conteggi_per_paese(session: AsyncSession) -> list[tuple[str, int]]:
    """(paese, story coperte) per il filtro e la mappa, per copertura.

    Conta sulla stessa finestra di attualità della prima pagina: i numeri
    dei chip e della mappa descrivono il giornale di OGGI, non l'archivio.
    """
    rows = (
        await session.execute(
            select(Source.country, func.count(func.distinct(Article.story_id)))
            .join(Article, Article.source_id == Source.id)
            .join(Story, Story.id == Article.story_id)
            .where(Story.last_seen >= finestra_attualita())
            .group_by(Source.country)
        )
    ).all()
    return sorted(
        ((c, int(n)) for c, n in rows if n), key=lambda cn: (-cn[1], cn[0])
    )


@router.get("/paesi", response_class=HTMLResponse)
async def mappa_paesi(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    """La mappa del mondo: colore = copertura, clic = filtro per paese."""
    countries = await _conteggi_per_paese(session)
    massimo = countries[0][1] if countries else 1
    return templates.TemplateResponse(
        request,
        "mappa_paesi.html",
        {
            **await page_context(request, session),
            "countries": countries,
            "massimo": massimo,
            "conteggi_json": json.dumps(dict(countries)),
        },
    )


async def _owners_by_source(
    session: AsyncSession, source_ids: list[int]
) -> dict[int, str]:
    """Primo proprietario registrato per fonte (per la stampigliatura piccola)."""
    if not source_ids:
        return {}
    rows = (
        await session.execute(
            select(Ownership.source_id, Owner.name)
            .join(Owner, Ownership.owner_id == Owner.id)
            .where(Ownership.source_id.in_(source_ids))
            .order_by(Owner.name)
        )
    ).all()
    owners: dict[int, str] = {}
    for source_id, name in rows:
        owners.setdefault(source_id, name)
    return owners


async def _coverages_for(
    session: AsyncSession, story_ids: list[int]
) -> dict[int, Coverage]:
    if not story_ids:
        return {}
    rows = (
        await session.execute(select(Coverage).where(Coverage.story_id.in_(story_ids)))
    ).scalars()
    return {c.story_id: c for c in rows}


async def _cocoverage_positions(
    session: AsyncSession,
) -> dict[int, tuple[float, float]]:
    """Ultima posizione di co-copertura per fonte (per la scelta di versioni diverse)."""
    rows = (
        (
            await session.execute(
                select(BiasSignal)
                .where(BiasSignal.signal_type == "cocoverage")
                .order_by(BiasSignal.period_end.desc())
            )
        )
        .scalars()
        .all()
    )
    positions: dict[int, tuple[float, float]] = {}
    for signal in rows:
        if signal.source_id not in positions and isinstance(signal.value, dict):
            positions[signal.source_id] = (
                float(signal.value.get("x", 0)),
                float(signal.value.get("y", 0)),
            )
    return positions


def diverse_articles(
    articles: list[Article],
    positions: dict[int, tuple[float, float]],
    k: int = 3,
) -> list[Article]:
    """Fino a k articoli di fonti diverse, scelti per massimizzare la diversità.

    Con le posizioni di co-copertura (livello 2) si massimizza la distanza
    reciproca; senza, si privilegiano paesi e fonti diverse. Metodo dichiarato
    nella pagina /metodo.
    """
    per_source: dict[int, Article] = {}
    for article in articles:
        per_source.setdefault(article.source_id, article)
    candidates = list(per_source.values())
    if len(candidates) <= k:
        return candidates

    def dist(a: Article, b: Article) -> float:
        pa, pb = positions.get(a.source_id), positions.get(b.source_id)
        if pa is not None and pb is not None:
            return math.hypot(pa[0] - pb[0], pa[1] - pb[1])
        score = 0.0
        if a.source.country != b.source.country:
            score += 1.0
        if a.source.language != b.source.language:
            score += 0.5
        return score

    chosen = [candidates[0]]
    while len(chosen) < k:
        best = max(
            (c for c in candidates if c not in chosen),
            key=lambda c: min(dist(c, ch) for ch in chosen),
        )
        chosen.append(best)
    return chosen


def order_versions(
    articles: list[Article], paese: str | None, locale: str
) -> list[Article]:
    """Versioni in ordine utile al lettore: prima le testate del paese
    filtrato, poi quelle nella lingua dell'interfaccia, poi le altre."""
    return sorted(
        articles,
        key=lambda a: (
            0 if paese and a.source.country == paese else 1,
            0 if a.language == locale else 1,
            a.published_at or a.fetched_at,
        ),
    )


async def masthead_context(session: AsyncSession) -> dict[str, Any]:
    """Numeri del colonnino di testata, presenti su ogni pagina."""
    source_count = (
        await session.execute(select(func.count()).select_from(Source).where(Source.enabled))
    ).scalar_one()
    # Trasparenza: se in archivio ci sono notizie dimostrative (seed offline),
    # il giornale lo dichiara con un banner. Mai spacciare demo per reale.
    demo_articles = (
        await session.execute(
            select(func.count())
            .select_from(Article)
            .join(Source, Article.source_id == Source.id)
            .where(Source.slug.like("demo-%"))
        )
    ).scalar_one()
    story_count = (
        await session.execute(select(func.count()).select_from(Story))
    ).scalar_one()
    last_update = (
        await session.execute(select(func.max(Article.fetched_at)))
    ).scalar_one_or_none()
    return {
        "source_count": source_count,
        "story_count": story_count,
        "last_update": last_update,
        "demo_mode": demo_articles > 0,
    }


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    paese: str | None = None,
) -> HTMLResponse:
    # Filtro per paese: solo paesi con almeno una story ATTUALE, col conteggio
    # accanto (così l'effetto del filtro è verificabile a colpo d'occhio).
    countries = await _conteggi_per_paese(session)
    valid = {c for c, _ in countries}
    paese = paese.lower() if paese and paese.lower() in valid else None

    locale = request_locale(request)
    # La prima pagina è il giornale di OGGI: candidate = story viste nella
    # finestra di attualità, ordinate per copertura scontata del tempo
    # (_peso_attualita). Senza finestra, le story più grandi dell'archivio
    # restavano in cima per sempre e le notizie del giorno non entravano mai.
    since = finestra_attualita()
    if paese:
        # Solo story coperte da almeno una testata del paese; il peso usa
        # quanto QUEL paese le ha coperte.
        from_country = (
            select(Article.story_id, func.count(Article.id).label("n"))
            .join(Source, Article.source_id == Source.id)
            .where(Source.country == paese, Article.story_id.is_not(None))
            .group_by(Article.story_id)
            .subquery()
        )
        rows = (
            await session.execute(
                select(Story, from_country.c.n)
                .join(from_country, Story.id == from_country.c.story_id)
                .where(Story.last_seen >= since)
                .order_by(Story.last_seen.desc())
                .limit(200)
            )
        ).all()
        if not rows:
            # Archivio fermo (o dati dimostrativi datati): meglio le più
            # recenti di quel paese che una pagina vuota.
            rows = (
                await session.execute(
                    select(Story, from_country.c.n)
                    .join(from_country, Story.id == from_country.c.story_id)
                    .order_by(Story.last_seen.desc())
                    .limit(36)
                )
            ).all()
        ordinate = sorted(
            rows, key=lambda r: -peso_attualita(int(r[1]), r[0].last_seen)
        )
        stories = [story for story, _ in ordinate][:36]
    else:
        candidate = list(
            (
                await session.execute(
                    select(Story)
                    .where(Story.last_seen >= since)
                    .order_by(Story.last_seen.desc())
                    .limit(200)
                )
            ).scalars()
        )
        if not candidate:
            candidate = list(
                (
                    await session.execute(
                        select(Story).order_by(Story.last_seen.desc()).limit(36)
                    )
                ).scalars()
            )
        stories = sorted(
            candidate,
            key=lambda s: -peso_attualita(s.source_count, s.last_seen),
        )[:36]
    # «Ultima ora»: le notizie appena arrivate, in ordine di orario. Nella
    # griglia sotto contano copertura e peso — qui conta solo essere nuove,
    # così una notizia di venti minuti fa non aspetta di essere ripresa da
    # dieci testate per comparire.
    ultima_ora = list(
        (
            await session.execute(
                select(Story)
                .where(Story.last_seen >= finestra_ultima_ora())
                .order_by(Story.last_seen.desc())
                .limit(6)
            )
        ).scalars()
    )

    # Le breaking con copertura VERA (più testate) meritano una scheda nel
    # feed principale anche quando il peso da solo non le farebbe entrare
    # tra le 36: si rimpiazza la coda della classifica e si riordina per
    # peso, così ognuna siede dove la porta la sua importanza.
    if not paese:
        garantite = [
            s
            for s in ultima_ora
            if s.source_count >= 3 and s.id not in {v.id for v in stories}
        ]
        if garantite:
            stories = sorted(
                stories[: max(len(stories) - len(garantite), 0)] + garantite,
                key=lambda s: -peso_attualita(s.source_count, s.last_seen),
            )

    coverages = await _coverages_for(session, [s.id for s in stories])
    versions_map = {
        s.id: order_versions(s.articles, paese, locale) for s in stories
    }
    topic_labels = topic_labels_for(locale)
    # Le story VISIBILI senza traduzione nella lingua del lettore si
    # traducono subito in background: al prossimo caricamento la riga
    # tra parentesi c'è, senza aspettare il giro dei 15 minuti.
    from core.nlp.translate import kick_translations, neutral_title_language

    # Anche la fascia «Ultima ora»: sono le story più nuove, cioè quelle
    # che quasi mai hanno già la traduzione pronta.
    visibili = {s.id: s for s in [*ultima_ora, *stories]}.values()
    mancanti = [
        s.id
        for s in visibili
        if s.title_translations is not None
        and locale not in (s.title_translations or {})
        and neutral_title_language(s) not in (None, locale)
    ]
    if mancanti:
        kick_translations(mancanti, locale)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            **await page_context(request, session),
            "stories": stories,
            "ultima_ora": ultima_ora,
            "coverages": coverages,
            "versions_map": versions_map,
            "topic_labels": topic_labels,
            "countries": countries,
            "paese": paese,
            "n_story": len(stories),
        },
    )


@router.get("/storia/{story_id}", response_class=HTMLResponse)
async def storia(
    request: Request,
    story_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    story = (
        await session.execute(select(Story).where(Story.id == story_id))
    ).scalar_one_or_none()
    if story is None:
        raise HTTPException(status_code=404, detail="story sconosciuta")
    locale = request_locale(request)
    coverage = (
        await session.execute(select(Coverage).where(Coverage.story_id == story.id))
    ).scalar_one_or_none()
    owners = await _owners_by_source(session, [a.source_id for a in story.articles])
    timeline = sorted(
        story.articles, key=lambda a: (a.published_at or a.fetched_at)
    )
    paesi_svg = None
    if coverage and coverage.by_country:
        paesi_svg = coverage_bar_svg(
            coverage.by_country,
            label=f"Coverage by country — story {story.id}",
            locale=locale,
        )
    provenances = await for_entity(session, "story", story.id)
    topic_labels = topic_labels_for(locale)
    from core.config import get_settings as _gs

    return templates.TemplateResponse(
        request,
        "storia.html",
        {
            **await page_context(request, session),
            "story": story,
            "coverage": coverage,
            "owners": owners,
            "timeline": timeline,
            "paesi_svg": paesi_svg,
            "provenances": provenances,
            "topic_labels": topic_labels,
            "llm_on": _gs().enable_llm,
            "riassunto_locale": _riassunto_per(story, locale, _gs().enable_llm),
            "riassunto_altro": _riassunto_altro(story, locale, _gs().enable_llm),
            "riassunto_base": _input_stats(story),
        },
    )


def _input_stats(story: Story) -> tuple[int, int, int]:
    from core.nlp.summarize import input_stats

    return input_stats(story)


def _riassunto_altro(story: Story, locale: str, llm_on: bool) -> tuple[str, str] | None:
    """(lingua, testo) di un riassunto già generato in un'altra lingua,
    mostrato accanto al pulsante «genera nella tua lingua»."""
    if _riassunto_per(story, locale, llm_on) is not None:
        return None
    summaries = story.summaries or {}
    for lang, testo in summaries.items():
        if lang != locale and testo:
            return lang, testo
    return None


def _riassunto_per(story: Story, locale: str, llm_on: bool) -> str | None:
    """Riassunto da mostrare per la lingua dell'interfaccia.

    Nella lingua giusta se c'è; un riassunto legacy (solo summary_neutral)
    vale comunque; uno in un'altra lingua si mostra SOLO quando il
    generatore è spento — acceso, meglio il pulsante «genera nella tua
    lingua».
    """
    summaries = story.summaries or {}
    testo = summaries.get(locale)
    if testo:
        return testo
    if not summaries and story.summary_neutral:
        return story.summary_neutral
    if summaries and not llm_on:
        return next(iter(summaries.values()))
    return None


# Story con una generazione già in corso (mai due richieste sovrapposte).
_riassunti_in_corso: set[int] = set()


def _errore_ollama(exc_or_body: object) -> str:
    """Messaggio leggibile da un'eccezione httpx o dal corpo d'errore di Ollama."""
    if isinstance(exc_or_body, Exception):
        text = str(exc_or_body).strip()
        name = exc_or_body.__class__.__name__
        return f"{name}: {text}" if text else name
    try:
        detail = json.loads(str(exc_or_body)).get("error", "")
    except ValueError:
        detail = ""
    return str(detail or exc_or_body)[:200]


@router.post("/storia/{story_id}/riassunto", response_model=None)
async def genera_riassunto(
    request: Request,
    story_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlainTextResponse | StreamingResponse:
    """Riassunto SOLO su richiesta del lettore, con streaming dei token.

    Generato in locale (Ollama) dai soli titoli ed estratti; al termine viene
    salvato, marcato come automatico, con provenance. Se esiste già, si
    restituisce quello salvato senza rigenerare. Un fallimento non è MAI
    silenzioso: prima del flusso diventa un errore HTTP con la causa; a
    flusso avviato diventa una riga di avviso nel testo, e finisce nei log.
    """
    from core.config import get_settings
    from core.net import build_client
    from core.nlp.summarize import (
        METHOD_NAME,
        ThinkFilter,
        build_prompt,
        generation_payload,
        input_stats,
        record_generation,
        think_rejected,
    )
    from core.provenance import record as record_provenance

    t = make_translator(request_locale(request))
    await refresh_runtime_settings(session)
    settings = get_settings()
    story = (
        await session.execute(select(Story).where(Story.id == story_id))
    ).scalar_one_or_none()
    if story is None:
        raise HTTPException(status_code=404, detail="story sconosciuta")
    locale = request_locale(request)
    esistenti = story.summaries or {}
    if esistenti.get(locale):
        return PlainTextResponse(esistenti[locale])
    if not settings.enable_llm:
        raise HTTPException(status_code=503, detail=t("storia.riassunto_spento"))
    if not story.articles:
        raise HTTPException(status_code=409, detail="story senza articoli")
    if story_id in _riassunti_in_corso:
        raise HTTPException(
            status_code=409, detail=t("storia.riassunto_in_corso")
        )

    # L'agente va sui siti ADESSO: scarica il testo integrale mancante degli
    # articoli scelti (robots e cortesia rispettati, tempo massimo 45 s),
    # così il riassunto legge gli articoli veri, non solo gli estratti.
    from core.extract.fulltext import fetch_fulltext
    from core.ingest.ratelimit import DomainRateLimiter
    from core.ingest.robots import RobotsCache
    from core.nlp.summarize import select_input_articles

    mancanti = [a for a in select_input_articles(story) if not a.full_text][:6]
    if mancanti:
        import asyncio as _asyncio

        async def _scarica() -> None:
            async with build_client() as cf:
                limiter = DomainRateLimiter()
                robots = RobotsCache(cf)
                for articolo in mancanti:
                    try:
                        await fetch_fulltext(
                            session, articolo,
                            client=cf, limiter=limiter, robots=robots,
                        )
                    except Exception:  # un sito ostile non blocca il riassunto
                        log.info("testo non scaricabile ora: %s", articolo.url)

        try:
            await _asyncio.wait_for(_scarica(), timeout=45)
        except TimeoutError:
            log.info("recupero testi oltre i 45 s: proseguo con quel che c'è")
        await session.commit()

    prompt = build_prompt(story, locale)
    n_articles, _n_testate, n_full = input_stats(story)

    # Pre-flight: la connessione a Ollama viene aperta PRIMA di rispondere,
    # così "non raggiungibile", "modello mancante" (404) o un errore del
    # server diventano un vero errore HTTP col motivo, non un flusso vuoto.
    _riassunti_in_corso.add(story_id)
    client = build_client(timeout=300)
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    stream_cm = client.stream("POST", url, json=generation_payload(prompt, stream=True))
    try:
        resp = await stream_cm.__aenter__()
        if resp.status_code != 200:
            body = (await resp.aread()).decode("utf-8", "replace")
            await stream_cm.__aexit__(None, None, None)
            if think_rejected(resp.status_code, body):
                # Il server rifiuta il parametro think: si riprova senza.
                stream_cm = client.stream(
                    "POST", url,
                    json=generation_payload(prompt, stream=True, include_think=False),
                )
                resp = await stream_cm.__aenter__()
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    await stream_cm.__aexit__(None, None, None)
                    record_generation(_errore_ollama(body), ok=False)
                    raise HTTPException(
                        status_code=502,
                        detail=t(
                            "storia.riassunto_fallito", errore=_errore_ollama(body)
                        ),
                    )
            else:
                record_generation(_errore_ollama(body), ok=False)
                raise HTTPException(
                    status_code=502,
                    detail=t("storia.riassunto_fallito", errore=_errore_ollama(body)),
                )
    except httpx.HTTPError as exc:
        _riassunti_in_corso.discard(story_id)
        await client.aclose()
        log.warning("riassunto story %d: Ollama non risponde (%s)", story_id, _errore_ollama(exc))
        record_generation(_errore_ollama(exc), ok=False)
        raise HTTPException(
            status_code=502,
            detail=t("storia.riassunto_fallito", errore=_errore_ollama(exc)),
        ) from exc
    except BaseException:
        _riassunti_in_corso.discard(story_id)
        await client.aclose()
        raise

    async def stream() -> AsyncIterator[str]:
        parts: list[str] = []
        filtro = ThinkFilter()  # mai mostrare/salvare il ragionamento inline
        try:
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
                token = filtro.feed(str(payload.get("response", "")))
                if token:
                    parts.append(token)
                    yield token
                if payload.get("done"):
                    break
            testo = "".join(parts).strip()
            if len(testo) < 40:
                # Mai un fallimento muto: il modello non ha prodotto testo
                # utilizzabile (capita coi modelli "pensanti" o troppo
                # piccoli) e il lettore deve saperlo.
                log.warning(
                    "riassunto story %d: risposta inutilizzabile (%d caratteri)",
                    story_id, len(testo),
                )
                record_generation(
                    f"risposta inutilizzabile ({len(testo)} caratteri)", ok=False
                )
                yield "\n⚠ " + t("storia.riassunto_vuoto")
            if len(testo) >= 40:
                record_generation(
                    f"riassunto generato per la story {story_id} ({locale})", ok=True
                )
                riassunti = dict(story.summaries or {})
                riassunti[locale] = testo
                story.summaries = riassunti
                if not story.summary_neutral:
                    story.summary_neutral = testo  # compatibilità ed export
                story.summary_method = "llm"
                await record_provenance(
                    session,
                    entity_type="story",
                    entity_id=story.id,
                    field="summary",
                    method=METHOD_NAME,
                    inputs={
                        "model": settings.ollama_model,
                        "n_articles": n_articles,
                        "n_full_text": n_full,
                        "locale": locale,
                        "trigger": "richiesta del lettore",
                        "input": "titoli+estratti+testo integrale (uso interno, mai mostrato)",
                    },
                )
                await session.commit()
        except httpx.HTTPError as exc:
            log.warning(
                "riassunto story %d interrotto: %s", story_id, _errore_ollama(exc)
            )
            record_generation(_errore_ollama(exc), ok=False)
            yield "\n⚠ " + t(
                "storia.riassunto_fallito", errore=_errore_ollama(exc)
            )
        finally:
            _riassunti_in_corso.discard(story_id)
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/lampo", response_class=HTMLResponse)
async def lampo(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    since = utcnow() - timedelta(hours=12)
    stories = (
        (
            await session.execute(
                select(Story)
                .where(Story.is_flash, Story.last_seen >= since)
                .order_by(Story.last_seen.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    positions = await _cocoverage_positions(session)
    coverages = await _coverages_for(session, [s.id for s in stories])
    all_source_ids = sorted(
        {a.source_id for s in stories for a in s.articles}
    )
    owners = await _owners_by_source(session, all_source_ids)
    schede = []
    for story in stories:
        countries = {a.source.country for a in story.articles}
        schede.append(
            {
                "story": story,
                "countries": len(countries),
                "versions": diverse_articles(story.articles, positions),
                "coverage": coverages.get(story.id),
            }
        )
    from core.config import get_settings

    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "lampo.html",
        {
            **await page_context(request, session),
            "schede": schede,
            "owners": owners,
            "flash_min": settings.flash_min_sources,
            "flash_window": settings.flash_window_hours,
        },
    )


@router.get("/fonti", response_class=HTMLResponse)
async def fonti(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    sources = (
        (await session.execute(select(Source).order_by(Source.region, Source.name)))
        .scalars()
        .all()
    )
    regioni: dict[str, list[Source]] = {"italy": [], "europe": [], "world": []}
    for src in sources:
        regioni.setdefault(src.region, []).append(src)
    return templates.TemplateResponse(
        request,
        "fonti.html",
        {**await page_context(request, session), "regioni": regioni},
    )


@router.get("/fonte/{slug}", response_class=HTMLResponse)
async def fonte(
    request: Request,
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    profile = await source_profile(session, slug)
    if profile is None:
        raise HTTPException(status_code=404, detail="fonte sconosciuta")
    article_count = (
        await session.execute(
            select(func.count()).select_from(Article).where(
                Article.source_id == profile.source.id
            )
        )
    ).scalar_one()
    locale = request_locale(request)
    provenances = await for_entity(session, "source", profile.source.id)
    topic_labels = topic_labels_for(locale)
    signal_views = shape_signals(profile.signals, topic_labels)

    mappa_svg = None
    if "cocoverage" in signal_views:
        mappa = await cocoverage_map(session)
        if mappa.positions:
            nomi = {
                s.slug: s.name
                for s in (await session.execute(select(Source))).scalars()
            }
            mappa_svg = cocoverage_scatter_svg(
                mappa.positions, highlight=slug, names=nomi, locale=locale
            )

    tono_svg = None
    if "tone" in signal_views:
        tono_svg = coverage_bar_svg(
            signal_views["tone"].data["distribution"],
            label=f"Tone distribution — {profile.source.name}",
            locale=locale,
        )

    # Profilo pubblico: se manca, si raccoglie SUBITO in sottofondo — chi
    # apre una scheda dice quale testata gli interessa (vedi ADR-0028).
    from core.osint.profile import (
        kick_profilo,
        profilo_in_corso,
        profilo_vuoto,
        rete_di_conti,
    )

    osint_in_corso = False
    if not profile.source.osint or profilo_vuoto(profile.source.osint):
        kick_profilo(profile.source.slug)
        osint_in_corso = profilo_in_corso(profile.source.slug)

    conti_condivisi = [
        gruppo
        for gruppo in await rete_di_conti(session)
        if slug in gruppo["testate"]
    ]

    return templates.TemplateResponse(
        request,
        "fonte.html",
        {
            **await page_context(request, session),
            "profile": profile,
            "osint": profile.source.osint or {},
            "osint_in_corso": osint_in_corso,
            "conti_condivisi": conti_condivisi,
            "article_count": article_count,
            "grafo_svg": ownership_graph_svg(profile, locale),
            "provenances": provenances,
            "signal_views": signal_views,
            "mappa_svg": mappa_svg,
            "tono_svg": tono_svg,
        },
    )


@router.get("/mappa", response_class=HTMLResponse)
async def mappa(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    result = await cocoverage_map(session)
    nomi = {
        s.slug: s.name for s in (await session.execute(select(Source))).scalars()
    }
    svg = cocoverage_scatter_svg(
        result.positions, names=nomi, locale=request_locale(request)
    )
    return templates.TemplateResponse(
        request,
        "mappa.html",
        {
            **await page_context(request, session),
            "result": result,
            "mappa_svg": svg,
        },
    )

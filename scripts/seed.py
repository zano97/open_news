"""`make seed`: popola il sistema con le fonti del catalogo e ~24h di notizie.

Modalità:
- predefinita (rete necessaria): verifica lo schema, sincronizza il catalogo,
  importa gli assetti proprietari, scarica i feed RSS (max 4 per fonte, in
  parallelo) e la copertura GDELT (a batch di domini, in parallelo all'RSS),
  poi esegue clustering, coperture, entità, temi e segnali. Pensata per
  stare in pochi minuti su una macchina modesta.
- `--offline-demo` (nessuna rete): crea 8 testate dimostrative dichiarate
  come tali e un giorno di notizie plausibili MA INVENTATE, poi esegue la
  stessa pipeline. Serve per provare l'interfaccia; nessun titolo inventato
  viene mai attribuito a una testata reale.
"""

import argparse
import asyncio
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.bias.aggregate import compute_weekly_signals
from core.bias.structure import load_ownership_seed
from core.cluster.coverage import compute_coverage
from core.cluster.incremental import cluster_pending
from core.config import get_settings
from core.db import get_engine, get_sessionmaker
from core.ingest.catalog import sync_catalog
from core.ingest.pipeline import ingest_all_feeds, ingest_gdelt_all
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.ingest.rss import IngestStats
from core.models import Article, Base, Source, Story
from core.net import build_client
from core.nlp.entities import assign_story_entities

MAX_FEEDS_PER_SOURCE = 4

# Eventi dimostrativi: inventati, attribuiti SOLO a testate dimostrative.
_DEMO_SOURCES = [
    ("demo-corriere-del-porto", "Corriere del Porto (demo)", "it", "it"),
    ("demo-gazzetta-del-nord", "Gazzetta del Nord (demo)", "it", "it"),
    ("demo-voce-della-sera", "La Voce della Sera (demo)", "it", "it"),
    ("demo-journal-du-fleuve", "Journal du Fleuve (demo)", "fr", "fr"),
    ("demo-tageszeitung-sued", "Tageszeitung Süd (demo)", "de", "de"),
    ("demo-morning-ledger", "The Morning Ledger (demo)", "gb", "en"),
    ("demo-diario-del-este", "Diario del Este (demo)", "es", "es"),
    ("demo-daily-observer", "The Daily Observer (demo)", "us", "en"),
]

_DEMO_EVENTS: list[dict[str, object]] = [
    {
        "hours_ago": 1.0, "spread_minutes": 15,
        "titles": [
            "Alluvione nel nord: migliaia di sfollati dopo l'esondazione del fiume",
            "Esondazione del fiume, migliaia di sfollati nel nord: soccorsi in azione",
            "Il fiume rompe gli argini: sfollati e danni ingenti nel nord",
            "Alluvione al nord, la protezione civile: migliaia di sfollati",
            "Nord in ginocchio per l'alluvione: sfollati a migliaia",
            "Floods in the north leave thousands displaced after river bursts banks",
        ],
    },
    {
        "hours_ago": 3.0, "spread_minutes": 30,
        "titles": [
            "Il governo approva la riforma delle pensioni dopo mesi di trattative",
            "Pensioni, via libera del governo alla riforma: cosa cambia",
            "Riforma delle pensioni approvata: le novità per i lavoratori",
            "Pensioni, l'esecutivo approva la riforma tra le proteste dei sindacati",
            "Government approves pension reform after months of talks",
        ],
    },
    {
        "hours_ago": 5.0, "spread_minutes": 45,
        "titles": [
            "Sciopero dei trasporti: adesione altissima, città paralizzate",
            "Trasporti fermi per lo sciopero: disagi in tutte le città",
            "Sciopero generale dei trasporti, i sindacati: adesione record",
            "Transport strike brings cities to a standstill",
        ],
    },
    {
        "hours_ago": 8.0, "spread_minutes": 60,
        "titles": [
            "Vertice europeo sull'energia: intesa raggiunta a notte fonda",
            "Energia, i leader europei trovano l'accordo dopo una notte di trattative",
            "Accordo al vertice europeo sull'energia: cosa prevede l'intesa",
            "EU energy summit ends with late-night agreement",
            "Energie: accord arraché au sommet européen",
        ],
    },
    {
        "hours_ago": 10.0, "spread_minutes": 90,
        "titles": [
            "Elezioni regionali: affluenza in calo, urne aperte fino alle 23",
            "Regionali, seggi aperti: affluenza sotto il 40 per cento",
            "Elezioni regionali al via, l'affluenza preoccupa i partiti",
        ],
    },
    {
        "hours_ago": 12.0, "spread_minutes": 60,
        "titles": [
            "Terremoto di magnitudo 5.2: paura tra i residenti, nessuna vittima",
            "Scossa di terremoto magnitudo 5.2, tanta paura ma nessun ferito",
            "Terremoto nella notte: magnitudo 5.2, controlli sugli edifici",
            "Magnitude 5.2 earthquake shakes region, no casualties reported",
        ],
    },
    {
        "hours_ago": 15.0, "spread_minutes": 120,
        "titles": [
            "Sanità, liste d'attesa record: il piano del ministero",
            "Liste d'attesa negli ospedali, nuovo piano del ministero della salute",
            "Sanità pubblica, il ministero annuncia il piano contro le liste d'attesa",
        ],
    },
    {
        "hours_ago": 18.0, "spread_minutes": 90,
        "titles": [
            "La nazionale vince la finale ai rigori: festa in tutto il paese",
            "Trionfo della nazionale: la finale si decide ai rigori",
            "Nazionale campione: battuta la finalista ai calci di rigore",
            "National team wins final on penalties as fans celebrate",
        ],
    },
    {
        "hours_ago": 20.0, "spread_minutes": 120,
        "titles": [
            "Migranti, nuovo sbarco nella notte: oltre duecento arrivi",
            "Sbarchi, notte di arrivi: più di duecento migranti soccorsi",
            "Oltre duecento migranti sbarcati nella notte: l'accoglienza è al limite",
        ],
    },
    {
        "hours_ago": 22.0, "spread_minutes": 150,
        "titles": [
            "Intelligenza artificiale, il parlamento discute le nuove regole",
            "Nuove regole sull'intelligenza artificiale: il dibattito in parlamento",
            "AI rules under debate in parliament as vote nears",
        ],
    },
]


async def ensure_schema() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def run_pipeline() -> None:
    """Clustering, coperture, entità e segnali — con avanzamento VISIBILE
    e un tetto di tempo: il primo avvio non deve mai sembrare bloccato.
    Quello che non entra nel budget lo completano i cicli automatici."""
    budget = get_settings().seed_budget_seconds
    scadenza = time.monotonic() + budget
    maker = get_sessionmaker()
    async with maker() as session:
        in_coda = (
            await session.execute(
                select(Article.id).where(Article.story_id.is_(None)).limit(5000)
            )
        ).scalars()
        totale = len(list(in_coda))
        if totale:
            print(f"analisi: raggruppo {totale} articoli in notizie…", flush=True)

        def avanzamento(fatti: int, tot: int) -> None:
            if fatti % 200 == 0 or fatti == tot:
                print(f"  raggruppati {fatti}/{tot}", flush=True)

        stats = await cluster_pending(
            session, batch=5000, progress=avanzamento, deadline=scadenza
        )
        if stats.processed + stats.skipped < totale:
            print(
                "  tempo massimo raggiunto: il resto lo raggruppano i cicli "
                "automatici nei prossimi minuti", flush=True,
            )
        for indice, story_id in enumerate(stats.touched_story_ids, start=1):
            if indice % 100 == 0:
                print(
                    f"  coperture {indice}/{len(stats.touched_story_ids)}",
                    flush=True,
                )
            story = (
                await session.execute(select(Story).where(Story.id == story_id))
            ).scalar_one()
            await compute_coverage(session, story)
            await assign_story_entities(session, story)
        await session.commit()
        print(
            f"clustering: {stats.processed} articoli -> {stats.created} story nuove, "
            f"{stats.attached} agganci, {len(stats.new_flash)} lampo"
        )
    async with maker() as session:
        summary = await compute_weekly_signals(session)
        await session.commit()
        print(f"segnali: {summary}")


async def seed_online() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        cat = await sync_catalog(session)
        own = await load_ownership_seed(session)
        await session.commit()
        print(f"catalogo: {cat} · assetti: {own}")

    def stampa_feed(slug: str, feed_url: str, stats: IngestStats) -> None:
        # Solo le righe informative: errori e articoli nuovi. I "+0" (feed
        # invariato o già scaricato: è il dedup al lavoro) restano muti.
        if stats.error:
            print(f"  {slug}: {stats.error}")
        elif stats.created:
            print(f"  {slug}: +{stats.created} articoli")

    def stampa_gdelt(slug: str, created: int) -> None:
        if created:
            print(f"  {slug}: +{created} articoli (GDELT)")

    async with build_client() as client:
        limiter = DomainRateLimiter()
        robots = RobotsCache(client)
        # Rete in parallelo (i rate limit per host restano rispettati),
        # database in sequenza tramite un lock condiviso; RSS e GDELT
        # girano insieme perché parlano con host diversi.
        db_lock = asyncio.Lock()
        da_feed: dict[str, int] = {}
        da_gdelt: dict[str, int] = {}
        budget = get_settings().seed_budget_seconds
        try:
            # Tetto di tempo rigido: l'esperienza del primo avvio non deve
            # mai dipendere dal sito più lento. Ogni feed viene salvato
            # appena arriva, quindi allo scadere nulla di già scaricato
            # va perso; il resto lo colmano i cicli automatici.
            da_feed, da_gdelt = await asyncio.wait_for(
                asyncio.gather(
                    ingest_all_feeds(
                        maker,
                        client=client,
                        limiter=limiter,
                        robots=robots,
                        max_feeds_per_source=MAX_FEEDS_PER_SOURCE,
                        retry_failed=True,
                        db_lock=db_lock,
                        progress=stampa_feed,
                    ),
                    ingest_gdelt_all(
                        maker,
                        client=client,
                        limiter=limiter,
                        db_lock=db_lock,
                        progress=stampa_gdelt,
                    ),
                ),
                timeout=budget,
            )
        except TimeoutError:
            print(
                f"  tempo massimo raggiunto ({budget // 60} minuti): continuo "
                "con quanto già scaricato — il resto arriva da solo coi "
                "cicli automatici (feed ogni 10 minuti, GDELT ogni 30)"
            )
    if da_feed or da_gdelt:
        print(
            f"raccolta: +{sum(da_feed.values())} articoli dai feed, "
            f"+{sum(da_gdelt.values())} da GDELT "
            f"({len({*da_feed, *da_gdelt})} testate con novità)"
        )

    await run_pipeline()


async def seed_offline_demo() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        cat = await sync_catalog(session)
        own = await load_ownership_seed(session)
        print(f"catalogo: {cat} · assetti: {own}")

        demo_sources: list[Source] = []
        for slug, name, country, language in _DEMO_SOURCES:
            existing = (
                await session.execute(select(Source).where(Source.slug == slug))
            ).scalar_one_or_none()
            if existing is None:
                existing = Source(
                    slug=slug, name=name, domain=f"{slug}.invalid",
                    country=country, language=language, region="world",
                    feed_urls=[], enabled=True,
                    terms_note=(
                        "Fonte dimostrativa creata da `make seed` in modalità "
                        "offline: le notizie associate sono inventate."
                    ),
                )
                session.add(existing)
            demo_sources.append(existing)
        await session.flush()

        now = datetime.now(UTC)
        created = 0
        for event in _DEMO_EVENTS:
            titles: list[str] = event["titles"]  # type: ignore[assignment]
            base_time = now - timedelta(hours=float(event["hours_ago"]))  # type: ignore[arg-type]
            spread = int(event["spread_minutes"])  # type: ignore[call-overload]
            for i, title in enumerate(titles):
                source = demo_sources[i % len(demo_sources)]
                url = f"https://{source.domain}/{abs(hash(title))}"
                exists = (
                    await session.execute(select(Article).where(Article.url == url))
                ).scalar_one_or_none()
                if exists is not None:
                    continue
                session.add(
                    Article(
                        source_id=source.id,
                        url=url,
                        title=title,
                        # Snippet vuoto: uno snippet identico per tutti dominerebbe
                        # l'embedding (titolo+snippet) e fonderebbe eventi diversi.
                        snippet="",
                        published_at=base_time
                        + timedelta(minutes=spread * i / max(len(titles) - 1, 1)),
                        language=source.language,
                    )
                )
                created += 1
        await session.commit()
        print(f"demo: {created} articoli inventati su {len(demo_sources)} testate demo")

    await run_pipeline()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline-demo", action="store_true",
        help="nessuna rete: testate dimostrative e notizie inventate",
    )
    args = parser.parse_args()
    start = time.monotonic()

    async def run() -> None:
        await ensure_schema()
        if args.offline_demo:
            await seed_offline_demo()
        else:
            await seed_online()

    asyncio.run(run())
    print(f"seed completato in {time.monotonic() - start:.0f} secondi")


if __name__ == "__main__":
    main()

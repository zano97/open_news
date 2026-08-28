<img src="apps/web/static/icons/opennews.svg" alt="" width="84" align="right">

# Open News

**Who pays for the news · how they tell it · what they ignore.**

*Leggilo in italiano: [README.it.md](README.it.md)*

Open News is an open-source news aggregator that does not claim to
"remove bias" from the news: it **measures it, documents it and shows it**,
always citing the provenance of every figure. For every piece of news you
see who covered it and with which headlines; for every outlet you see who
owns it, how much public money it receives, which topics it covers more
than average and which stories it ignores.

The interface is a **newspaper in your browser**, styled like an
early-20th-century broadsheet, in **five languages** (Italian, English,
French, German, Spanish — switchable from the masthead):

| | |
|---|---|
| ![Front page](docs/screenshots/01-prima-pagina.png) | ![Front page in English](docs/screenshots/06-front-page-en.png) |
| *The front page: competing headlines side by side for every story* | *The same newspaper with the interface in English* |
| ![Outlet record card](docs/screenshots/04-fonte-libero.png) | ![Story page in English](docs/screenshots/03-storia-en.png) |
| *An outlet's record card: owners, political offices, public money* | *A story: every outlet's version, who published first* |
| ![Flash edition](docs/screenshots/02-lampo.png) | ![Mobile, night edition](docs/screenshots/07-mobile-notte.png) |
| *The "flash edition": a paper reel of the hottest stories* | *On a phone, in the night edition* |

- Open-source software and free resources only: **no paid APIs**, no
  commercial service keys (a test enforces it)
- Every figure shown carries its **source, computation date and method**
- Software licence: **AGPL-3.0** · derived data: **CC BY-SA 4.0**

**Contents**: [How it works](#how-it-works) ·
[Install](#installation-pick-your-mode) · [Update](#updating) ·
[How to use it](#how-to-use-it) · [Administration](#administration) ·
[Optional features](#optional-features) ·
[Common problems](#common-problems) ·
[The methodology](#bias-on-four-levels-never-a-single-score) ·
[For developers](#for-developers)

---

## How it works

The collector reads the **RSS feeds of 120+ outlets from 59 countries**
(143 feeds: front pages plus the world/politics/business sections of the
major ones) and complements them with **GDELT** (free) for articles the
feeds miss — including Reuters and AP, which have no public feeds. Articles
about the same event are grouped into "stories", so you see **how different
outlets headline the same fact**. On top of the data run the four levels of
the [methodology](#bias-on-four-levels-never-a-single-score). All of it
respects the outlets: robots.txt, at most one request every 2 seconds per
site, and on page only headline + short excerpt + link to the source
(never the full article: that belongs to the outlets).

While the app is open, the news refreshes by itself: feeds every 10
minutes, GDELT every 30, bias signals every Monday.

## Installation: pick your mode

| | **Personal — no Docker** (recommended) | **Server — with Docker** |
|---|---|---|
| For whom | you read the newspaper on your own computer | you publish it online for others |
| Requires | nothing: the script fetches everything itself | Docker, an always-on machine |
| Database | SQLite in `~/.opennews` | PostgreSQL + pgvector (+ Meilisearch) |
| HTTPS/domain | not needed (runs on localhost) | automatic via Caddy |
| Starts with | the "Open News" icon or the `opennews` command | `docker compose up -d` |

### Personal mode — no Docker (Linux, macOS, Windows)

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
```

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/zano97/open_news/main/install.ps1 | iex"
```

The script does everything by itself, **no Docker and no prerequisites**:
it downloads the app into `~/.opennews`, fetches its own Python 3.12 (via
[uv](https://github.com/astral-sh/uv)), creates the **"Open News" icon**
(applications menu on Linux, `~/Applications` on macOS, Start menu on
Windows) and the `opennews` command, downloads the last 24 hours of real
news (a few minutes: collection runs in parallel) and opens the newspaper in your
browser.

The newspaper opens in a **dedicated app window** — no tabs, no address
bar, with the Open News emblem in the Dock or taskbar: a native window on
macOS (system WebKit), and on Windows and Linux a Chrome/Chromium/Edge/
Brave app window when available; failing everything, your default
browser. From then on:

- **start** it by clicking the icon, or with `opennews` in a terminal
  (`opennews --port 8100` for another port, `--tab` to open in a normal
  browser tab, `--no-browser` to open nothing);
- **stop** it with Ctrl+C (or, on macOS, by closing the window: it shuts
  everything down); on the next start it **catches up immediately** on
  missed news, then resumes the normal cadence;
- your **data** (news, settings, annotations) lives in `~/.opennews` and
  survives updates and reinstalls;
- `opennews seed` re-downloads the last 24 hours whenever you want.

Just want to **see the interface, without fetching real news**? Demo mode
(30 seconds; demo outlets clearly declared as such, with a banner as a
reminder — an invented headline is never attributed to a real outlet):

```bash
OPENNEWS_DEMO=1 curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
```

<details>
<summary><strong>Manual install without Docker</strong> (if you prefer doing every step yourself)</summary>

All you need is Python ≥ 3.12 and git:

```bash
git clone https://github.com/zano97/open_news.git
cd open_news
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/opennews seed        # download the news (or: seed --demo)
.venv/bin/opennews             # serve on http://127.0.0.1:8000 and open the browser
```

`opennews` creates the SQLite database in `~/.opennews` by itself, runs the
migrations and runs site and collector in a single process.

</details>

### Server mode — publishing an instance with Docker

For a newspaper **reachable by others** (domain, automatic HTTPS,
PostgreSQL database): you need an always-on machine with
[Docker](https://docs.docker.com/engine/install/) — 4 cores / 8 GB is
plenty, ARM works too (Oracle Cloud Always Free, Raspberry Pi 5).

```bash
OPENNEWS_DOCKER=1 curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
```

The script clones the repository, generates the secrets, starts the stack
(PostgreSQL + pgvector, Meilisearch, api, worker, Caddy) and downloads the
news. To go public: set `DOMAIN=news.yourdomain.org` in `.env` (DNS
pointing at the machine, ports 80/443 open) and `docker compose up -d` —
Caddy obtains and renews the HTTPS certificates by itself. Full guide
(Oracle Free ARM, Raspberry Pi, backups, monitoring, manual steps):
[docs/DEPLOY.md](docs/DEPLOY.md).

## Updating

One line, identical for both modes — it detects your install type by
itself, and **your data stays**:

```bash
curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/update.sh | bash
```

In personal mode you then relaunch `opennews`; in server mode everything
restarts by itself, database migrations included.

## How to use it

There is nothing to learn: **the interface is the website itself**, from
the browser, phones included. In the masthead you find the language
(IT·EN·FR·DE·ES), the **night edition**, and below it the **country bar**
to focus on one country's outlets (by default you see the whole world).
The pages:

| Page | What you find there |
|---|---|
| **/** — Front page | Today's stories in broadsheet style: neutral headline, **the outlets' competing headlines side by side**, coverage by country, "flash" and "blind spot" badges. Country filter with counts. |
| **/lampo** — Flash edition | The "paper reel": stories covered by ≥5 outlets in <2 hours, one full-screen card each; scroll or use ↑ ↓. Three contrasting headlines from the most diverse outlets, owner in small print. |
| **/storia/{id}** | One story: all versions side by side (headline + excerpt + link to the source), who published first, coverage by country, Wikidata entities. With the generator on, the **"Generate the story in brief"** button: a neutral summary streamed live, generated locally only on your request, always marked as automatic. |
| **/fonti** and **/fonte/{slug}** | The outlet catalog and each outlet's "record card": ownership graph, **political offices with dates**, "Who the owner is (according to Wikidata)" — parties, occupations, companies — public money per year, self-declared line, and the 4-level signals. Where data is insufficient you read "under evaluation", never a hidden estimate. |
| **/mappa** | The co-coverage map: outlets sit close together when they cover the same stories. The axes **emerge from the data** and must be read through the stories listed below. |
| **/metodo** | The full methodology in plain language, with calibration figures and known limits. |
| **/dati** | Open exports (CSV, CC BY-SA 4.0) and the JSON API documented at **/docs**. |
| **/annota** | Become an annotator: judge headlines **blind** (without knowing the outlet) on two axes. Labels are published only with ≥50 articles, ≥3 annotators of different declared orientations and agreement α ≥ 0.6. |
| **/impostazioni** | The admin panel (see below). |

## Administration

In **personal mode** Settings opens directly, no account needed: the app
is yours. On a **shared server** the **first profile registered** on
`/annota` becomes the instance administrator: they see the "Settings" link in the masthead and the
`/impostazioni` panel, where they tune — with an explanation next to every
field — the Ollama model and URL, the embedding engine, clustering and
"flash" thresholds, the collection courtesy interval, the signal windows.
Changes are stored in the database, override `.env` and apply immediately.
The **methodology** parameters (level-4 thresholds, taxonomy, lexicon) are
deliberately excluded: they change in the repository, with a method version
bump.

## Optional features

**AI summaries ("The story in brief").** Generated by an open model
**locally** via [Ollama](https://ollama.com), never a paid service, and
**only when the reader presses the button** on a story page (live
streaming). To enable them:

```bash
ollama pull qwen2.5:7b      # a real model tag (qwen2.5:3b on small machines)
```

then flip the switch in `/impostazioni` and save. In **personal mode** the
default URL (`http://localhost:11434`) just works. In **Docker server
mode** the default is `http://host.docker.internal:11434` — the address
containers use to reach your machine — and Ollama must be started with
`OLLAMA_HOST=0.0.0.0 ollama serve` so it accepts their connections. The
"Generator status" in the panel checks everything live and tells you
exactly what is missing; "Generate 3 summaries now" gives instant proof.

**Headlines in your language.** Outlet headlines stay in their original
language (their wording is the data). The *neutral* story titles can be
translated with [Argos Translate](https://www.argosopentech.com/) (open
source, offline), always marked "automatic translation":

```bash
# personal mode:
~/.opennews/app/.venv/bin/pip install argostranslate
~/.opennews/app/.venv/bin/python -m scripts.fetch_translation_models
# server mode:
docker compose exec worker pip install argostranslate
docker compose exec worker python -m scripts.fetch_translation_models
```

**Better multilingual clustering.** The default engine downloads nothing;
to link stories across languages better, switch to `e5` from the panel
(needs the `[ml]` extras; then `make calibrate` — details in
[docs/DEPLOY.md](docs/DEPLOY.md)).

## Common problems

- **Empty front page** → the first download hasn't finished: `opennews
  seed` (personal) or `docker compose logs worker` (server).
- **The summary button doesn't appear / doesn't generate** → open
  `/impostazioni`: the "Generator status" says whether Ollama is reachable
  and the model installed, with the exact command to fix it.
- **"Demo news" banner** → you are looking at the demo: `opennews seed`
  fetches the real news.
- **`opennews` not found** → open a new terminal, or add `~/.local/bin`
  to your PATH (the installer tells you).
- Anything else → [docs/DEPLOY.md](docs/DEPLOY.md), "Troubleshooting".

## Bias on four levels (never a single score)

1. **Structure (facts):** ownership, corporate chains, owners' political
   offices, public subsidies — from public registers (ROC AGCOM, EurOMo,
   Wikidata, DIE), always with evidence and date.
2. **Selection (statistics):** agenda profile against the average (with
   confidence intervals), co-coverage map, blind spots.
3. **Framing (lexical):** a curated lexicon of connoted terms, who gets
   quoted, headline tone distribution.
4. **Positioning (human judgement with a protocol):** blind annotation
   with measured inter-annotator agreement and explicit publication rules.

The four levels are shown **separately** and are never summed. Everything
is explained, with the numbers, at `/metodo`.

## For developers

<details>
<summary>Local development, commands, architecture</summary>

```bash
make install       # creates .venv and installs dependencies (Python 3.12+)
make test          # 174 tests on SQLite, no external service needed
make check         # ruff + mypy --strict + tests (core coverage >= 80%)
make test-e2e      # Playwright browser tests (desktop + mobile)
make seed-demo     # populate a local DB with no network
.venv/bin/opennews # run in personal mode
```

```
apps/
  api/         FastAPI: HTML pages (Jinja2+HTMX) and JSON API, OpenAPI at /docs
  web/         templates, hand-written CSS, self-hosted fonts, translations (5 languages)
  worker/      APScheduler: RSS/GDELT ingestion, clustering, entities, signals
  launcher.py  the `opennews` command (personal mode, embedded worker)
core/
  models/    SQLAlchemy 2 async (portable PostgreSQL/SQLite)
  ingest/    RSS with conditional caching, robots.txt, rate limiting, GDELT
  extract/   canonical URLs, SimHash, language, full text (never exposed)
  nlp/       embeddings, topics, lexicon, quoted actors, tone, entities, summaries
  cluster/   incremental clustering with a calibrated threshold
  bias/      the 4 levels of the methodology + Krippendorff's alpha
  i18n.py    interface languages with per-key fallback
  net.py     the ONLY network exit point, with an allowlist (no paid services)
data/        source catalog, lexicons, topic taxonomy, evidence-backed seeds
docs/        METHODOLOGY (it/en) · DECISIONS (ADR) · LEGAL · DEPLOY
```

</details>

## Contributing

The data files grow via pull request, every entry with a rationale and a
source: `data/sources.yaml` (outlets), `data/lexicon_it.yaml` /
`lexicon_en.yaml` (framing lexicon), `data/topics.yaml` (topics),
`data/seeds/ownership_it.yaml` (ownership **with evidence**: never an
invented figure — `null` with a note beats a guess),
`apps/web/translations/*.yaml` (interface languages; a test enforces key
parity). Quality bar: `make check` must pass.

## Documentation and licences

[`docs/METHODOLOGY.en.md`](docs/METHODOLOGY.en.md) (the methodology;
Italian original [here](docs/METHODOLOGY.md)) ·
[`docs/DEPLOY.md`](docs/DEPLOY.md) (server, backups, monitoring) ·
[`docs/LEGAL.md`](docs/LEGAL.md) (what we show and how we collect) ·
[`docs/DECISIONS.md`](docs/DECISIONS.md) (architecture decision records).

Code **AGPL-3.0-only** ([LICENSE](LICENSE)) · derived data **CC BY-SA 4.0**
(from `/dati`) · attributions in [NOTICE](NOTICE). Headlines and excerpts
remain the property of their outlets, shown within the limits of quotation
with a link to the source.

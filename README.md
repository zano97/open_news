# Open News

**Chi paga l'informazione · come la racconta · che cosa ignora.**

Open News è un aggregatore di notizie open source che non pretende di
"eliminare il bias" dei giornali: lo **misura, lo documenta e lo mostra**,
citando sempre la provenienza di ogni dato. Per ogni notizia vedi chi l'ha
coperta e con quali titoli; per ogni testata vedi chi la possiede, quanti
soldi pubblici riceve, quali temi copre più della media e quali storie ignora.

- Solo software open source e risorse gratuite: **nessuna API a pagamento**,
  nessuna chiave di servizi commerciali (un test lo garantisce)
- Ogni numero mostrato ha accanto **fonte, data del calcolo e metodo**
- Licenza software: **AGPL-3.0** · dati derivati: **CC BY-SA 4.0**

---

## Avvio rapido (Docker, consigliato)

Requisiti: una macchina con 4 core / 8 GB RAM (anche ARM: Oracle Free,
Raspberry Pi 5), Docker con il plugin `docker compose`.

```bash
git clone https://github.com/zano97/open_news.git
cd open_news
cp .env.example .env            # 1. configura (vedi sotto)
docker compose up --build -d    # 2. avvia lo stack completo
docker compose exec api python -m scripts.verify_feeds   # 3. verifica i feed reali
docker compose exec api python -m scripts.seed           # 4. popola (~10-15 minuti)
```

Poi apri **<http://localhost:8000>**. Il worker continua da solo: feed ogni
10 minuti, GDELT ogni 30, clustering ogni 10, segnali di bias ogni lunedì.

Nel file `.env` imposta almeno:

| Variabile | A cosa serve |
|---|---|
| `POSTGRES_PASSWORD` | password del database (generane una: `openssl rand -hex 32`) |
| `MEILI_MASTER_KEY` | chiave di Meilisearch |
| `SECRET_KEY` | firma dei cookie di sessione degli annotatori |
| `DOMAIN` | (solo in produzione) il tuo dominio: Caddy ottiene da solo l'HTTPS |
| `EMBEDDING_BACKEND` | `hashing` (default, zero download) o `e5` (multilingue, consigliato in produzione — vedi [docs/DEPLOY.md](docs/DEPLOY.md)) |

### Provare l'interfaccia senza rete

Se vuoi solo vedere com'è fatta l'applicazione, senza scaricare notizie vere:

```bash
docker compose exec api python -m scripts.seed --offline-demo
```

Crea 8 **testate dimostrative** (dichiarate come tali) con un giorno di
notizie inventate: mai un titolo inventato viene attribuito a una testata
reale.

## Come si usa l'applicazione

| Pagina | Che cosa ci trovi |
|---|---|
| **/** — Prima pagina | Il giornale: le story del giorno in stile broadsheet. Ogni story mostra il titolo neutro, **i titoli delle diverse testate a confronto** (per vedere il framing a colpo d'occhio), la copertura per paese, i badge «lampo» e «angolo cieco». |
| **/lampo** — Edizione lampo | Il "reel di carta": le notizie coperte da ≥5 testate in <2 ore, una scheda a schermo intero per notizia. Scorri, oppure usa i tasti ↑ ↓. Tre titoli a confronto scelti tra le testate più diverse tra loro, col proprietario in piccolo. Funziona anche senza JavaScript. |
| **/storia/{id}** | Una notizia, tutte le versioni affiancate (titolo + snippet + link alla fonte), la timeline di chi l'ha pubblicata per prima, la copertura per paese, le entità collegate a Wikidata. |
| **/fonti** | Il catalogo delle testate, comprese quelle disabilitate con la motivazione (es. ANSA per i suoi termini d'uso). |
| **/fonte/{slug}** | La "scheda anagrafica" di una testata: grafo dei proprietari, cariche politiche, soldi pubblici per anno, linea auto-dichiarata, e i segnali dei 4 livelli (che cosa copre, come racconta, posizionamento). Dove i dati non bastano leggi "in valutazione", mai una stima nascosta. |
| **/mappa** | La mappa di co-copertura: testate vicine = coprono le stesse story. Gli assi **emergono dai dati** e vanno letti con le story elencate sotto la mappa. |
| **/metodo** | La metodologia completa, in italiano semplice: come si calcola ogni cosa, con i numeri di calibrazione e i limiti noti. |
| **/dati** | Gli export aperti (CSV, CC BY-SA 4.0): story, coperture, segnali, annotazioni anonime. API JSON documentata su **/docs**. |
| **/annota** | Diventa annotatore: valuti titoli **senza sapere da che testata vengono** (annotazione cieca) su due assi. Le etichette di posizionamento si pubblicano solo con ≥50 articoli, ≥3 annotatori con orientamenti dichiarati diversi e accordo α ≥ 0,6. |

In alto a destra trovi l'**edizione notturna** (tema scuro); tutto il sito è
navigabile da tastiera e rispetta `prefers-reduced-motion`.

### Il bias su quattro livelli (mai un punteggio unico)

1. **Struttura (fatti):** proprietà, catene societarie, cariche politiche
   dei proprietari, finanziamenti pubblici — da registri pubblici (ROC
   AGCOM, EurOMo, Wikidata, DIE), sempre con evidenza e data.
2. **Selezione (statistica):** profilo di agenda rispetto alla media (con
   intervalli di confidenza), mappa di co-copertura, angoli ciechi.
3. **Framing (lessicale):** lessico curato di termini connotati, chi viene
   citato, distribuzione del tono dei titoli.
4. **Posizionamento (giudizio umano con protocollo):** annotazione cieca con
   accordo inter-annotatore misurato e regole di pubblicazione esplicite.

I quattro livelli sono mostrati **separati** e non si sommano mai.

## Comandi utili

```bash
make help          # elenco completo dei comandi
make seed          # popola con le fonti reali (~24h di notizie; richiede rete)
make seed-demo     # senza rete: testate dimostrative e notizie inventate
make verify-feeds  # verifica HTTP reale di tutti i feed e aggiorna il catalogo
make calibrate     # precision/recall della soglia di clustering sul set annotato
make test          # test unit/integrazione con coverage (core >= 80%)
make test-e2e      # test Playwright nel browser (desktop + mobile)
make check         # ruff + mypy --strict + test
```

## Sviluppo locale senza Docker

```bash
make install       # crea .venv e installa le dipendenze (Python 3.12+)
make test          # 127 test su SQLite, nessun servizio esterno richiesto
.venv/bin/python -m scripts.seed --offline-demo   # popola un DB locale
DATABASE_URL=sqlite+aiosqlite:///dev.sqlite3 \
  .venv/bin/uvicorn apps.api.main:app --reload    # avvia su :8000
```

(In sviluppo puoi usare SQLite; in produzione lo stack compose usa
PostgreSQL 16 + pgvector.)

## Architettura

```
apps/
  api/      FastAPI: pagine HTML (Jinja2+HTMX) e API JSON, OpenAPI su /docs
  web/      template, CSS scritto a mano, font self-hosted, JS minimo
  worker/   APScheduler: ingest RSS/GDELT, clustering, entità, segnali
core/
  models/   SQLAlchemy 2 async (portabile PostgreSQL/SQLite)
  ingest/   RSS con cache condizionale, robots.txt, rate limit, GDELT
  extract/  URL canonici, SimHash, lingua, testo integrale (mai esposto)
  nlp/      embedding, temi, lessico, attori citati, tono, entità
  cluster/  clustering incrementale con soglia calibrata
  bias/     i 4 livelli della metodologia + Krippendorff's alpha
  net.py    UNICO punto di uscita rete, con allowlist (niente servizi a pagamento)
data/       catalogo fonti, lessici, tassonomia temi, seed con evidenze
docs/       METHODOLOGY · DECISIONS (ADR) · LEGAL · DEPLOY
```

## Documentazione

- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — la metodologia completa,
  leggibile da non tecnici (è la pagina pubblica `/metodo`)
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — deploy su VPS, **Oracle Cloud Always
  Free (ARM)**, **Raspberry Pi 5**, backup e monitoraggio
- [`docs/LEGAL.md`](docs/LEGAL.md) — cosa mostriamo dei contenuti altrui,
  robots/rate-limit, termini per fonte, dati personali
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — le decisioni architetturali (ADR)

## Contribuire

I file dati crescono via pull request, ogni voce con motivazione e fonte:

- `data/sources.yaml` — nuove testate (con `terms_note` e feed verificati)
- `data/lexicon_it.yaml` / `lexicon_en.yaml` — il lessico di framing
- `data/topics.yaml` — le parole chiave della tassonomia dei temi
- `data/seeds/ownership_it.yaml` — assetti proprietari **con evidenza**;
  la regola è: mai un dato inventato, meglio `null` con una nota

Qualità: `make check` deve passare (ruff, mypy `--strict`, coverage ≥ 80%).

## Licenze

Codice **AGPL-3.0-only** ([LICENSE](LICENSE)) · dati derivati **CC BY-SA
4.0** (esportabili da `/dati`) · attribuzioni di terze parti in
[NOTICE](NOTICE). I titoli e gli snippet restano delle rispettive testate e
sono mostrati nei limiti della citazione con link alla fonte.

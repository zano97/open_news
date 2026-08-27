# Open News

**Chi paga l'informazione · come la racconta · che cosa ignora.**

Open News è un aggregatore di notizie open source che non pretende di
"eliminare il bias": lo **misura, lo documenta e lo mostra**, citando sempre la
provenienza di ogni dato. Per ogni notizia vedi chi l'ha coperta e con quali
titoli; per ogni testata vedi chi la possiede, quanti soldi pubblici riceve,
quali temi copre più della media e quali storie ignora.

- Licenza software: **AGPL-3.0** · dati derivati: **CC BY-SA 4.0** (vedi `NOTICE`)
- Solo software open source e risorse gratuite: nessuna API a pagamento, nessuna chiave commerciale
- Ogni valore mostrato ha accanto **fonte, data del calcolo e metodo** (record di *provenance*)

## Avvio rapido

```bash
cp .env.example .env          # personalizza se vuoi
docker compose up --build -d  # postgres+pgvector, meilisearch, api, worker, caddy
make seed                     # ~40 fonti + 24 ore di notizie in < 15 minuti
```

Poi apri <http://localhost:8000> (o <http://localhost> via Caddy).

Sviluppo locale senza Docker:

```bash
make install                  # venv + dipendenze
make check                    # ruff + mypy --strict + pytest (coverage core >= 80%)
```

## Architettura

```
apps/
  api/      FastAPI: router HTML (Jinja2+HTMX) e API JSON, OpenAPI automatico
  web/      template, CSS scritto a mano, JS minimo self-hosted (niente CDN)
  worker/   APScheduler: ingest RSS/GDELT, estrazione, embedding, clustering, segnali
core/
  models/   SQLAlchemy 2 async: Source, Owner, Ownership, PublicFunding, Article,
            Story, Coverage, BiasSignal, Annotation, Provenance
  ingest/   RSS (ETag/Last-Modified), robots.txt, rate limit per dominio, GDELT DOC 2.0
  extract/  trafilatura, dedup (URL canonico + simhash), language detection
  nlp/      embedding (e5 o hashing), NER, entity linking Wikidata, lessico, tono
  cluster/  clustering incrementale delle story (finestra 72h, KNN pgvector)
  bias/     livelli 2-4: agenda, co-copertura, blind spot, framing, annotazione
data/       sources.yaml, lexicon_*.yaml, topics.yaml, seed
docs/       METHODOLOGY, DECISIONS (ADR), LEGAL, DEPLOY
```

Database: **PostgreSQL 16 + pgvector** (un solo DB per relazionale e vettori);
nei test SQLite. Ricerca full-text: **Meilisearch**. Reverse proxy:
**Caddy** con HTTPS automatico.

## La metodologia in breve

Il bias non è un numero unico: si misura su **quattro livelli**, dal più
oggettivo al più interpretativo, mostrati sempre separatamente
(mai sommati in un "punteggio"):

1. **Struttura (fatti):** proprietà, catene societarie, cariche politiche dei
   proprietari, finanziamenti pubblici, linea auto-dichiarata — importati da
   registri pubblici (ROC AGCOM, EurOMo, Wikidata, DIE) con evidenza e data.
2. **Selezione (statistica):** profilo di agenda rispetto alla media,
   mappa di co-copertura a dimensioni emergenti, blind spot per fonte.
3. **Framing (lessicale):** lessico curato di termini con stessa denotazione e
   connotazione diversa, attori e voci citate, distribuzione del tono.
4. **Posizionamento (giudizio umano con protocollo):** annotazione cieca su due
   assi (economico e culturale) con accordo inter-annotatore misurato
   (Krippendorff's α) e regole di pubblicazione esplicite.

Tutto è spiegato in linguaggio semplice nella pagina pubblica `/metodo`
(sorgente: `docs/METHODOLOGY.md`).

## Stato delle fasi

- [x] **Fase 0** — Scheletro: compose, modelli, migrazioni, CI, test
- [x] **Fase 1** — Ingestione: RSS, robots/rate-limit, dedup, GDELT
- [x] **Fase 2** — Story clustering incrementale (soglia calibrata su 100 coppie annotate)
- [x] **Fase 3** — Trasparenza strutturale (proprietà, finanziamenti, grafo SVG)
- [x] **Fase 4** — Bias livelli 2-3 (agenda con IC bootstrap, co-copertura PCA, blind spot, lessico, attori, tono)
- [x] **Fase 5** — UI giornale d'epoca + reel `/lampo` (e2e Playwright)
- [x] **Fase 6** — Annotazione umana cieca (Krippendorff's α, regole di pubblicazione)
- [x] **Fase 7** — `/metodo`, `/dati`, LEGAL, DEPLOY, seed, test egress

## Comandi utili

```bash
make seed          # popola con le fonti reali (~24h di notizie; richiede rete)
make seed-demo     # senza rete: testate dimostrative dichiarate e notizie inventate
make verify-feeds  # verifica HTTP reale di tutti i feed del catalogo
make calibrate     # precision/recall della soglia di clustering sul set annotato
make test-e2e      # test Playwright nel browser (desktop + mobile)
```

## Documentazione

- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — la metodologia completa,
  leggibile da non tecnici (è la pagina pubblica `/metodo`)
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — le decisioni architetturali (ADR)
- [`docs/LEGAL.md`](docs/LEGAL.md) — cosa mostriamo, come raccogliamo, licenze
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — deploy su VPS, Oracle Always Free ARM,
  Raspberry Pi 5, backup e monitoraggio

## Contribuire

Il lessico di framing (`data/lexicon_it.yaml`, `data/lexicon_en.yaml`) e il
catalogo fonti (`data/sources.yaml`) sono pensati per crescere via pull
request: ogni voce richiede una motivazione e una fonte. Vedi
`docs/DECISIONS.md` per le scelte architetturali e `docs/LEGAL.md` per i
limiti d'uso dei contenuti delle testate.

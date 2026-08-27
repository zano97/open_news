# Decisioni architetturali (ADR)

Registro delle decisioni, in ordine cronologico. Ogni decisione ambigua viene
risolta scegliendo l'opzione più semplice e più trasparente, e annotata qui.

---

## ADR-0001 — Licenza AGPL-3.0, dati derivati CC BY-SA 4.0

**Contesto.** Il repository conteneva un `LICENSE` MIT segnaposto creato alla
nascita del repo. Il progetto richiede AGPL-3.0.
**Decisione.** `LICENSE` sostituito con il testo integrale AGPL-3.0-only
(fonte: SPDX license-list-data). I dati derivati (etichette, mappe di
copertura, segnali aggregati) sono pubblicati in CC BY-SA 4.0, dichiarato in
`NOTICE` e nella pagina `/dati`.
**Conseguenze.** Chi eroga il servizio modificato deve pubblicare i sorgenti
(clausola network della AGPL): coerente con la missione di trasparenza.

## ADR-0002 — Layout del repository: package `core/` e `apps/`

**Decisione.** Struttura a package top-level `core/` (dominio: modelli,
ingestione, NLP, cluster, bias, provenance) e `apps/` (API+web, worker), come
da specifica di progetto. Installazione con `pip install -e .`; niente
`src/`-layout per mantenere gli import identici a come appaiono nel repo.

## ADR-0003 — PostgreSQL 16 + pgvector in produzione, SQLite nei test

**Contesto.** Serve un solo DB per dati relazionali e vettori; i test devono
girare ovunque senza servizi esterni.
**Decisione.** Tipi di colonna portabili (`core/models/types.py`):
`EmbeddingVector` è `vector(768)` su PostgreSQL e JSON testuale su SQLite;
`TZDateTime` garantisce datetime sempre timezone-aware UTC su entrambi;
JSON è `JSONB` su PostgreSQL. La KNN nativa esiste solo su PostgreSQL; su
SQLite la similarità si calcola in Python (adeguato ai volumi dei test).
**Conseguenze.** Nessun mock del DB nei test; lo stesso codice gira su
entrambi i backend.

## ADR-0004 — Migrazione iniziale da metadati, migrazioni successive incrementali

**Decisione.** La migrazione Alembic `0001` crea lo schema con
`Base.metadata.create_all` (unica fonte di verità allo stato iniziale) più
`CREATE EXTENSION vector` e l'indice HNSW. Le migrazioni successive saranno
scritte a mano, incrementali.
**Motivo.** Evita la duplicazione integrale dello schema a mano in fase 0 e
il rischio di divergenza modelli/migrazione; il costo (non poter fare
`downgrade` parziale della 0001) è accettabile per un progetto nuovo.

## ADR-0005 — HTMX self-hosted; niente Alpine.js

**Decisione.** HTMX 2.0.4 è vendorizzato in `apps/web/static/js/htmx.min.js`
(licenza 0BSD/BSD — vedi NOTICE). Alpine.js non viene usato: le poche
interazioni (tema notturno, reel) sono vanilla JS/Web Components e tutto
degrada bene senza JavaScript.
**Motivo.** Meno dipendenze, CSP severa senza CDN esterni, requisito "il reel
funziona anche senza JS".

## ADR-0006 — Verifica dei feed al setup, non in fase di build

**Contesto.** La specifica chiede feed "verificati via richiesta HTTP reale al
momento del setup". L'ambiente di sviluppo/CI ha egress limitato verso i
domini delle testate.
**Decisione.** La verifica reale è lo script idempotente
`make verify-feeds` (`scripts/verify_feeds.py`): interroga ogni feed del
catalogo, aggiorna `enabled`/`disabled_reason`/`last_checked_at` e stampa un
rapporto. Va eseguito al primo deploy e periodicamente. I test usano fixture
HTTP registrate, senza rete.

## ADR-0007 — respx al posto di vcrpy per le fixture HTTP

**Decisione.** I test di ingestione usano `respx` (mock nativo di httpx,
anche async) con corpi di risposta registrati come file in
`tests/fixtures/`. vcrpy ha un supporto fragile per httpx async.
**Conseguenze.** Le fixture sono file leggibili e diffabili nel repo.

## ADR-0008 — Doppio backend di embedding, sempre dichiarato

**Contesto.** `sentence-transformers` (e5-base) pesa centinaia di MB e
richiede download di modello: inadatto a test/CI e a macchine minime.
**Decisione.** Interfaccia unica `core/nlp/embed.py` con due backend:
`hashing` (n-gram hashing deterministico, nessun download, qualità inferiore
ma sufficiente a raggruppare titoli quasi-identici) ed `e5`
(`intfloat/multilingual-e5-base`, extra `[ml]`, raccomandato in produzione).
Il backend usato finisce in `Article.embedding_method` e nella provenance:
mai un numero senza il suo metodo.

## ADR-0009 — Python 3.12

**Decisione.** `requires-python >= 3.12`; l'immagine Docker usa
`python:3.12-slim`; mypy e ruff hanno target 3.12.

## ADR-0010 — Niente valutazioni di bias importate da terzi

**Decisione (vincolo di progetto, registrato qui per riferimento).** Le fonti
esterne (Wikidata, EurOMo, ROC AGCOM, DIE) si usano solo per fatti
verificabili: proprietà, cariche, finanziamenti. Nessuna etichetta di
orientamento viene importata; il bias è calcolato dalla metodologia interna
(docs/METHODOLOGY.md) su quattro livelli mostrati separatamente, mai sommati
in un punteggio unico.

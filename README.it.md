# Open News

**Chi paga l'informazione · come la racconta · che cosa ignora.**

*Read it in English: [README.md](README.md)*

Open News è un aggregatore di notizie open source che non pretende di
"eliminare il bias" dei giornali: lo **misura, lo documenta e lo mostra**,
citando sempre la provenienza di ogni dato. Per ogni notizia vedi chi l'ha
coperta e con quali titoli; per ogni testata vedi chi la possiede, quanti
soldi pubblici riceve, quali temi copre più della media e quali storie ignora.

L'interfaccia è un **giornale nel browser**, in stile quotidiano d'inizio
Novecento, in **cinque lingue** (italiano, inglese, francese, tedesco,
spagnolo — si cambia dalla testata):

| | |
|---|---|
| ![Prima pagina](docs/screenshots/01-prima-pagina.png) | ![Prima pagina in inglese](docs/screenshots/06-front-page-en.png) |
| *La prima pagina: i titoli delle testate a confronto per ogni notizia* | *Lo stesso giornale con l'interfaccia in inglese* |
| ![Scheda di una testata](docs/screenshots/04-fonte-libero.png) | ![Pagina story in inglese](docs/screenshots/03-storia-en.png) |
| *La scheda di una testata: proprietari, cariche politiche, soldi pubblici* | *Una story: tutte le versioni, chi l'ha pubblicata per prima* |
| ![Edizione lampo](docs/screenshots/02-lampo.png) | ![Mobile, edizione notturna](docs/screenshots/07-mobile-notte.png) |
| *L'«edizione lampo»: il reel di carta delle notizie più calde* | *Su telefono, con l'edizione notturna* |

- Solo software open source e risorse gratuite: **nessuna API a pagamento**,
  nessuna chiave di servizi commerciali (un test lo garantisce)
- Ogni numero mostrato ha accanto **fonte, data del calcolo e metodo**
- Licenza software: **AGPL-3.0** · dati derivati: **CC BY-SA 4.0**

**Indice**: [Come funziona](#come-funziona) ·
[Installazione](#installazione-scegli-la-modalità) ·
[Aggiornare](#aggiornare) · [Come si usa](#come-si-usa) ·
[Amministrazione](#amministrazione) ·
[Funzioni opzionali](#funzioni-opzionali) ·
[Problemi comuni](#problemi-comuni) ·
[La metodologia](#il-bias-su-quattro-livelli-mai-un-punteggio-unico) ·
[Per sviluppatori](#per-sviluppatori)

---

## Come funziona

Il raccoglitore legge i **feed RSS di 47 testate di 19 paesi** (92 feed:
prime pagine più le sezioni esteri/politica/economia delle testate maggiori)
e integra con **GDELT** (gratuito) gli articoli che nei feed non compaiono —
comprese Reuters e AP, che feed pubblici non ne hanno. Gli articoli sullo
stesso evento vengono raggruppati in «story», così vedi **come testate
diverse titolano lo stesso fatto**. Sopra i dati girano i quattro livelli
della [metodologia](#il-bias-su-quattro-livelli-mai-un-punteggio-unico).
Tutto nel rispetto delle testate: robots.txt, massimo una richiesta ogni 2
secondi per sito, e in pagina solo titolo + estratto breve + link alla fonte
(mai l'articolo intero: è delle testate).

Finché l'app è aperta, le notizie si aggiornano da sole: feed ogni 10
minuti, GDELT ogni 30, segnali di bias ogni lunedì.

## Installazione: scegli la modalità

| | **Personale — senza Docker** (consigliata) | **Server — con Docker** |
|---|---|---|
| Per chi | usi il giornale tu, sul tuo computer | vuoi pubblicarlo online per altri |
| Richiede | niente: lo script si procura tutto da solo | Docker, una macchina sempre accesa |
| Database | SQLite in `~/.opennews` | PostgreSQL + pgvector (+ Meilisearch) |
| HTTPS/dominio | non serve (gira su localhost) | automatico con Caddy |
| Si avvia con | icona «Open News» o comando `opennews` | `docker compose up -d` |

### Modalità personale — senza Docker (Linux, macOS, Windows)

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
```

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/zano97/open_news/main/install.ps1 | iex"
```

Lo script fa tutto da solo, **senza Docker e senza prerequisiti**: scarica
l'app in `~/.opennews`, si procura Python 3.12 per conto suo (tramite
[uv](https://github.com/astral-sh/uv)), crea **l'icona «Open News»** (menu
applicazioni su Linux, `~/Applications` su macOS, menu Start su Windows) e
il comando `opennews`, scarica le ultime 24 ore di notizie vere (~10-15
minuti, solo la prima volta) e apre il giornale nel browser.

Da lì in poi:

- **avvii** con un clic sull'icona, oppure con `opennews` nel terminale
  (`opennews --port 8100` per un'altra porta, `--no-browser` per non aprire
  il browser);
- **fermi** con Ctrl+C nel terminale (o chiudendo la finestra): alla
  prossima apertura riparte da dov'era;
- i **dati** (notizie, impostazioni, annotazioni) vivono in `~/.opennews`
  e sopravvivono ad aggiornamenti e reinstallazioni;
- `opennews seed` riscarica le ultime 24 ore quando vuoi.

Vuoi solo **vedere com'è fatta, senza scaricare notizie vere**? Modalità
demo (30 secondi; testate dimostrative dichiarate come tali, con un banner
che lo ricorda — mai un titolo inventato attribuito a una testata reale):

```bash
OPENNEWS_DEMO=1 curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
```

<details>
<summary><strong>Installazione manuale senza Docker</strong> (se preferisci fare ogni passo a mano)</summary>

Serve solo Python ≥ 3.12 e git:

```bash
git clone https://github.com/zano97/open_news.git
cd open_news
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/opennews seed        # scarica le notizie (oppure: seed --demo)
.venv/bin/opennews             # avvia su http://127.0.0.1:8000 e apre il browser
```

`opennews` crea da solo il database SQLite in `~/.opennews`, esegue le
migrazioni e fa girare sito e raccoglitore nello stesso processo.

</details>

### Modalità server — pubblicare un'istanza con Docker

Per un giornale **raggiungibile da altri** (dominio, HTTPS automatico,
database PostgreSQL): serve una macchina con
[Docker](https://docs.docker.com/engine/install/) sempre accesa — bastano
4 core / 8 GB, va bene anche ARM (Oracle Cloud Always Free, Raspberry Pi 5).

```bash
OPENNEWS_DOCKER=1 curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
```

Lo script clona il repository, genera i segreti, avvia lo stack (PostgreSQL
+ pgvector, Meilisearch, api, worker, Caddy) e scarica le notizie. Poi, per
andare online: metti `DOMAIN=notizie.tuodominio.org` nel file `.env` (il
DNS deve puntare alla macchina, porte 80/443 aperte) e `docker compose up
-d` — Caddy ottiene e rinnova i certificati HTTPS da solo. Guida completa
(Oracle Free ARM, Raspberry Pi, backup, monitoraggio, passi manuali):
[docs/DEPLOY.md](docs/DEPLOY.md).

## Aggiornare

Una riga, identica per entrambe le modalità — riconosce da sola che
installazione hai, e **i dati restano**:

```bash
curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/update.sh | bash
```

In modalità personale poi rilanci `opennews`; in modalità server riavvia
tutto da solo, migrazioni del database comprese.

## Come si usa

Non c'è niente da imparare: **l'interfaccia è il sito stesso**, dal browser,
anche da telefono. In testata trovi la lingua (IT·EN·FR·DE·ES),
l'**edizione notturna**, e sotto la barra dei **paesi** per concentrarti
sulle testate di un paese (di default vedi il mondo intero). Le pagine:

| Pagina | Che cosa ci trovi |
|---|---|
| **/** — Prima pagina | Le story del giorno in stile broadsheet: titolo neutro, **i titoli delle diverse testate a confronto**, copertura per paese, badge «lampo» e «angolo cieco». Filtro per paese con i conteggi. |
| **/lampo** — Edizione lampo | Il "reel di carta": le notizie coperte da ≥5 testate in <2 ore, una schermata per notizia; scorri o usa ↑ ↓. Tre titoli a confronto dalle testate più diverse tra loro, col proprietario in piccolo. |
| **/storia/{id}** | Una notizia: tutte le versioni affiancate (titolo + estratto + link alla fonte), chi l'ha pubblicata per prima, copertura per paese, entità Wikidata. Col generatore attivo, il pulsante **«Genera "Il fatto in breve"»**: riassunto neutro in streaming, generato in locale solo su tua richiesta, sempre marcato come automatico. |
| **/fonti** e **/fonte/{slug}** | Il catalogo delle testate e la "scheda anagrafica" di ciascuna: grafo dei proprietari, **cariche politiche con date**, «Chi è il proprietario (secondo Wikidata)» — partiti, occupazioni, aziende — soldi pubblici per anno, linea auto-dichiarata, e i segnali dei 4 livelli. Dove i dati non bastano leggi "in valutazione", mai una stima nascosta. |
| **/mappa** | La mappa di co-copertura: testate vicine = coprono le stesse story. Gli assi **emergono dai dati** e vanno letti con le story elencate sotto. |
| **/metodo** | La metodologia completa in linguaggio semplice, con i numeri di calibrazione e i limiti noti. |
| **/dati** | Export aperti (CSV, CC BY-SA 4.0) e API JSON documentata su **/docs**. |
| **/annota** | Diventa annotatore: valuti titoli **alla cieca** (senza sapere la testata) su due assi. Le etichette si pubblicano solo con ≥50 articoli, ≥3 annotatori di orientamenti dichiarati diversi e accordo α ≥ 0,6. |
| **/impostazioni** | Il pannello di amministrazione (vedi sotto). |

## Amministrazione

Il **primo profilo che si registra** su `/annota` diventa l'amministratore
dell'istanza: vede il link «Impostazioni» in testata e il pannello
`/impostazioni`, dove regola — con la spiegazione accanto a ogni campo —
modello e URL di Ollama, motore di embedding, soglie del clustering e delle
story «lampo», intervallo di cortesia della raccolta, finestre dei segnali.
Le modifiche si salvano nel database, prevalgono su `.env` e valgono subito.
I parametri della **metodologia** (soglie del livello 4, tassonomia,
lessico) sono esclusi di proposito: si cambiano nel repository, con la
versione del metodo.

## Funzioni opzionali

**Riassunti con l'AI («Il fatto in breve»).** Generati da un modello aperto
**in locale** via [Ollama](https://ollama.com), mai un servizio a pagamento,
e **solo quando il lettore preme il pulsante** nella pagina della notizia
(streaming in diretta). Per attivarli:

```bash
ollama pull qwen2.5:7b      # un modello vero (qwen2.5:3b su macchine piccole)
```

poi in `/impostazioni` accendi l'interruttore e salva. In **modalità
personale** l'URL predefinito (`http://localhost:11434`) funziona subito.
In **modalità server Docker** il predefinito è
`http://host.docker.internal:11434` — l'indirizzo con cui i container
raggiungono il tuo computer — e Ollama va avviato con
`OLLAMA_HOST=0.0.0.0 ollama serve` perché accetti le loro connessioni. Lo
«Stato del generatore» nel pannello verifica tutto in diretta e ti dice
esattamente cosa manca; «Genera 3 riassunti ora» fa la prova immediata.

**Titoli nella tua lingua.** I titoli delle testate restano in lingua
originale (la loro formulazione è il dato). I titoli *neutri* delle story
possono essere tradotti con [Argos Translate](https://www.argosopentech.com/)
(open source, offline), sempre marcati «traduzione automatica»:

```bash
# modalità personale:
~/.opennews/app/.venv/bin/pip install argostranslate
~/.opennews/app/.venv/bin/python -m scripts.fetch_translation_models
# modalità server:
docker compose exec worker pip install argostranslate
docker compose exec worker python -m scripts.fetch_translation_models
```

**Clustering multilingue migliore.** Il motore predefinito non scarica
nulla; per agganciare meglio le story tra lingue diverse passa a `e5` dal
pannello (richiede gli extra `[ml]`; poi `make calibrate` — dettagli in
[docs/DEPLOY.md](docs/DEPLOY.md)).

## Problemi comuni

- **Homepage vuota** → il primo scaricamento non è finito: `opennews seed`
  (personale) o `docker compose logs worker` (server).
- **Il pulsante dei riassunti non appare / non genera** → apri
  `/impostazioni`: lo «Stato del generatore» dice se Ollama è raggiungibile
  e se il modello è installato, col comando esatto per rimediare.
- **Banner «notizie dimostrative»** → stai vedendo la demo: `opennews seed`
  scarica quelle vere.
- **`opennews` non trovato** → apri un nuovo terminale, oppure aggiungi
  `~/.local/bin` al PATH (l'installer te lo segnala).
- Altro → [docs/DEPLOY.md](docs/DEPLOY.md), sezione «Risoluzione problemi».

## Il bias su quattro livelli (mai un punteggio unico)

1. **Struttura (fatti):** proprietà, catene societarie, cariche politiche
   dei proprietari, finanziamenti pubblici — da registri pubblici (ROC
   AGCOM, EurOMo, Wikidata, DIE), sempre con evidenza e data.
2. **Selezione (statistica):** profilo di agenda rispetto alla media (con
   intervalli di confidenza), mappa di co-copertura, angoli ciechi.
3. **Framing (lessicale):** lessico curato di termini connotati, chi viene
   citato, distribuzione del tono dei titoli.
4. **Posizionamento (giudizio umano con protocollo):** annotazione cieca con
   accordo inter-annotatore misurato e regole di pubblicazione esplicite.

I quattro livelli sono mostrati **separati** e non si sommano mai. Tutto è
spiegato, con i numeri, su `/metodo`.

## Per sviluppatori

<details>
<summary>Sviluppo locale, comandi, architettura</summary>

```bash
make install       # crea .venv e installa le dipendenze (Python 3.12+)
make test          # 174 test su SQLite, nessun servizio esterno richiesto
make check         # ruff + mypy --strict + test (coverage core >= 80%)
make test-e2e      # test Playwright nel browser (desktop + mobile)
make seed-demo     # popola un DB locale senza rete
.venv/bin/opennews # avvia in modalità personale
```

```
apps/
  api/         FastAPI: pagine HTML (Jinja2+HTMX) e API JSON, OpenAPI su /docs
  web/         template, CSS scritto a mano, font self-hosted, traduzioni (5 lingue)
  worker/      APScheduler: ingest RSS/GDELT, clustering, entità, segnali
  launcher.py  comando `opennews` (modalità personale, worker incorporato)
core/
  models/    SQLAlchemy 2 async (portabile PostgreSQL/SQLite)
  ingest/    RSS con cache condizionale, robots.txt, rate limit, GDELT
  extract/   URL canonici, SimHash, lingua, testo integrale (mai esposto)
  nlp/       embedding, temi, lessico, attori citati, tono, entità, riassunti
  cluster/   clustering incrementale con soglia calibrata
  bias/      i 4 livelli della metodologia + Krippendorff's alpha
  i18n.py    lingue dell'interfaccia con fallback per chiave
  net.py     UNICO punto di uscita rete, con allowlist (niente servizi a pagamento)
data/        catalogo fonti, lessici, tassonomia temi, seed con evidenze
docs/        METHODOLOGY (it/en) · DECISIONS (ADR) · LEGAL · DEPLOY
```

</details>

## Contribuire

I file dati crescono via pull request, ogni voce con motivazione e fonte:
`data/sources.yaml` (testate), `data/lexicon_it.yaml` / `lexicon_en.yaml`
(lessico di framing), `data/topics.yaml` (temi),
`data/seeds/ownership_it.yaml` (assetti proprietari **con evidenza**: mai
un dato inventato, meglio `null` con una nota),
`apps/web/translations/*.yaml` (lingue dell'interfaccia; un test garantisce
la parità delle chiavi). Qualità: `make check` deve passare.

## Documentazione e licenze

[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) (la metodologia, anche
[in inglese](docs/METHODOLOGY.en.md)) ·
[`docs/DEPLOY.md`](docs/DEPLOY.md) (server, backup, monitoraggio) ·
[`docs/LEGAL.md`](docs/LEGAL.md) (cosa mostriamo e come raccogliamo) ·
[`docs/DECISIONS.md`](docs/DECISIONS.md) (le decisioni architetturali).

Codice **AGPL-3.0-only** ([LICENSE](LICENSE)) · dati derivati **CC BY-SA
4.0** (da `/dati`) · attribuzioni in [NOTICE](NOTICE). Titoli ed estratti
restano delle rispettive testate, mostrati nei limiti della citazione con
link alla fonte.

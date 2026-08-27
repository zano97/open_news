# Guida al deploy

Open News gira su una macchina modesta: 4 core, 8 GB di RAM, senza GPU.
Tutto lo stack è `docker compose`; il reverse proxy Caddy ottiene e rinnova
da solo i certificati HTTPS.

## Requisiti

- Docker Engine ≥ 24 con il plugin `docker compose`
- un dominio (facoltativo ma consigliato, per l'HTTPS automatico)
- porte 80 e 443 raggiungibili

## Installazione in una riga

```bash
curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
```

Lo script genera i segreti, avvia lo stack e popola il giornale. Per il
deploy pubblico, dopo l'installazione imposta `DOMAIN=...` in `.env` e
riavvia (`docker compose up -d`): Caddy ottiene da solo il certificato.
I passi manuali equivalenti sono qui sotto.

## Installazione manuale (qualsiasi VPS Linux)

```bash
git clone https://github.com/zano97/open_news.git && cd open_news
cp .env.example .env
# imposta in .env: POSTGRES_PASSWORD, MEILI_MASTER_KEY, SECRET_KEY
# (generali con: openssl rand -hex 32) e DOMAIN=notizie.esempio.org
docker compose up --build -d
docker compose exec api python -m scripts.verify_feeds   # verifica reale dei feed
docker compose exec api python -m scripts.seed           # ~40 fonti + 24h di notizie
```

Dopo qualche minuto la homepage è popolata; il worker continua da solo
(feed ogni 10', GDELT ogni 30', clustering ogni 10', segnali ogni lunedì).

### Embedding di qualità (consigliato in produzione)

Il default (`EMBEDDING_BACKEND=hashing`) non scarica nulla ed è adatto a
macchine minime, ma è debole tra lingue diverse. Su macchine con ≥8 GB:

```bash
# nel Dockerfile aggiungi: RUN pip install --no-cache-dir ".[ml]"
# in .env: EMBEDDING_BACKEND=e5
# poi ricalibra la soglia e aggiornala in .env:
docker compose exec api python -m scripts.calibrate_threshold
```

### Riassunti neutri "il fatto in breve" (opzionale, LLM locale)

Nella pagina di ogni story può comparire un riassunto neutro generato in
locale (mai un servizio a pagamento, nessun dato lascia la macchina):

```bash
docker compose --profile llm up -d          # avvia Ollama
docker compose exec ollama ollama pull qwen2.5:7b
```

Poi attiva i riassunti dal **pannello /impostazioni** (accedi col primo
profilo registrato, che è amministratore): lì scegli anche il modello e
l'URL di Ollama. In alternativa: `ENABLE_LLM=true` in `.env` e
`docker compose up -d api worker`.

Il worker riassume le story multi-fonte ogni 15 minuti; il riassunto è
sempre marcato "automatico" e usa solo titoli ed estratti (mai il testo
integrale). Su macchine con 8 GB scegli un modello quantizzato piccolo
(es. `qwen2.5:3b`) dal pannello /impostazioni.

### Pannello /impostazioni

Il **primo profilo registrato** su /annota è l'amministratore dell'istanza
e vede il pannello `/impostazioni`: modello e URL di Ollama, motore di
embedding, soglia e finestra del clustering, soglia «lampo», intervallo di
cortesia della raccolta (mai sotto 2 s), finestre dei segnali. Le modifiche
sono salvate nel database, prevalgono su `.env`, si applicano subito
all'API e al worker entro 5 minuti. I parametri della **metodologia**
(soglie del livello 4, tassonomia, lessico) restano fuori dal pannello di
proposito: si cambiano nel repository, con la versione del metodo.

## Oracle Cloud Always Free (ARM)

Il tier Always Free di Oracle offre fino a 4 OCPU ARM Ampere e 24 GB di RAM
a costo zero a tempo indeterminato (verifica le condizioni correnti al
momento della registrazione).

1. Crea una VM `VM.Standard.A1.Flex` (consigliato: 4 OCPU / 12-24 GB),
   immagine Ubuntu 24.04 (aarch64).
2. Nella VCN apri le porte 80 e 443 (Security List / NSG, ingress TCP).
3. Sulla VM, oltre al firewall di Oracle, apri iptables locali:
   `sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT` (e 443), poi rendile
   persistenti con `netfilter-persistent`.
4. Installa Docker (`curl -fsSL https://get.docker.com | sh`) e segui
   l'installazione standard qui sopra. Tutte le immagini usate
   (postgres/pgvector, meilisearch, caddy, python) hanno build multi-arch
   arm64.

## Raspberry Pi 5 (8 GB)

1. Raspberry Pi OS Lite 64-bit (o Ubuntu Server 24.04 arm64).
2. Usa un SSD USB, non la microSD, per i volumi Docker (Postgres e
   Meilisearch scrivono molto).
3. Installazione standard come sopra. Consigli per i 8 GB:
   - lascia `EMBEDDING_BACKEND=hashing` oppure prova `e5` con
     `--workers 1` per uvicorn;
   - riduci la frequenza dei job pesanti se necessario (vedi
     `apps/worker/jobs/__init__.py`).
4. Dietro NAT domestico: apri 80/443 sul router o usa un tunnel
   (es. WireGuard verso un VPS con IP pubblico).

## Backup

I dati vivono in due volumi Docker: `pgdata` (tutto il DB) e `meilidata`
(indice ricostruibile). Basta il dump di Postgres:

```bash
docker compose exec db pg_dump -U opennews -Fc opennews > backup_$(date +%F).dump
# ripristino:
docker compose exec -T db pg_restore -U opennews -d opennews --clean < backup_YYYY-MM-DD.dump
```

Metti il comando in cron (giornaliero) e copia i dump fuori dalla macchina
(rclone/restic verso qualsiasi storage). Anche `data/sources.yaml` e i seed
sono dati preziosi: vivono nel repository, quindi committali.

## Monitoraggio

- **Healthcheck**: `GET /healthz` risponde `{"status":"ok","db":"ok"}`;
  i container hanno healthcheck compose e `restart: unless-stopped`.
- **Log**: `docker compose logs -f api worker`. Il worker logga ogni job
  (feed, clustering, segnali) con conteggi.
- Un check esterno gratuito (es. Uptime Kuma self-hosted su /healthz)
  completa il quadro.

## Aggiornamenti

```bash
git pull
docker compose up --build -d     # le migrazioni Alembic girano all'avvio dell'api
```

## Risoluzione problemi

- **Homepage vuota**: il worker non ha ancora girato → `make seed` oppure
  attendi il primo ciclo (10'). Controlla `docker compose logs worker`.
- **Feed disabilitati**: `python -m scripts.verify_feeds` scrive nel
  catalogo il motivo per ciascun feed non raggiungibile.
- **Meilisearch non parte su ARM a 32 bit**: usa un OS a 64 bit (aarch64).
- **Certificato non emesso**: verifica che `DOMAIN` punti all'IP della
  macchina e che le porte 80/443 siano aperte end-to-end.

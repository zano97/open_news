#!/usr/bin/env bash
# Open News — installazione in una riga:
#
#   curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
#
# Varianti (variabili d'ambiente prima del comando):
#   OPENNEWS_DEMO=1   popola con testate dimostrative e notizie inventate (nessuna rete
#                     verso le testate; ideale per provare subito l'interfaccia)
#   OPENNEWS_DIR=...  cartella di installazione (default: ./open_news)
#
# Lo script: verifica Docker, clona il repository, genera i segreti in .env,
# avvia lo stack (postgres+pgvector, meilisearch, api, worker, caddy) e popola
# il giornale. Alla fine l'interfaccia è su http://localhost:8000
set -euo pipefail

REPO_URL="https://github.com/zano97/open_news.git"
DIR="${OPENNEWS_DIR:-open_news}"
DEMO="${OPENNEWS_DEMO:-0}"
URL="http://localhost:8000"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1mERRORE:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. Requisiti: git e Docker con il plugin compose --------------------------------
command -v git >/dev/null 2>&1 || fail "serve git (es. 'sudo apt install git')."

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'EOF'

Docker non è installato. Installalo con il metodo ufficiale:

    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"   # poi riapri la sessione

e rilancia questo script.
EOF
  exit 1
fi
docker compose version >/dev/null 2>&1 \
  || fail "il plugin 'docker compose' non è disponibile (Docker troppo vecchio?)."
docker info >/dev/null 2>&1 \
  || fail "il demone Docker non risponde (prova con sudo, o aggiungi il tuo utente al gruppo docker)."

# --- 2. Codice sorgente ---------------------------------------------------------------
if [ -d "$DIR/.git" ]; then
  say "Aggiorno il repository esistente in $DIR"
  git -C "$DIR" pull --ff-only
else
  say "Clono Open News in $DIR"
  git clone --depth 1 "$REPO_URL" "$DIR"
fi
cd "$DIR"

# --- 3. Segreti: generati una sola volta, mai sovrascritti ----------------------------
gen_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 32
  else head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}
if [ ! -f .env ]; then
  say "Genero .env con segreti casuali"
  cat > .env <<EOF
POSTGRES_PASSWORD=$(gen_secret)
MEILI_MASTER_KEY=$(gen_secret)
SECRET_KEY=$(gen_secret)
EMBEDDING_BACKEND=hashing
ENABLE_LLM=false
# Per il deploy pubblico con HTTPS automatico, decommenta e imposta il dominio:
# DOMAIN=notizie.esempio.org
EOF
else
  say ".env già presente: non lo tocco"
fi

# --- 4. Avvio dello stack -------------------------------------------------------------
say "Costruisco e avvio lo stack (la prima volta servono alcuni minuti)"
docker compose up --build -d

say "Aspetto che l'applicazione risponda"
for _ in $(seq 1 120); do
  if curl -fsS "$URL/healthz" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "$URL/healthz" >/dev/null 2>&1 || fail "l'API non risponde su $URL (vedi: docker compose logs api)."

# --- 5. Popolamento -------------------------------------------------------------------
if [ "$DEMO" = "1" ]; then
  say "Popolo con testate dimostrative (modalità demo, nessuna rete verso le testate)"
  docker compose exec -T api python -m scripts.seed --offline-demo
else
  say "Verifico i feed reali del catalogo (qualche minuto)"
  docker compose exec -T api python -m scripts.verify_feeds || true
  say "Scarico le ultime 24 ore di notizie (~10-15 minuti; il worker poi continua da solo)"
  docker compose exec -T api python -m scripts.seed
fi

# --- 6. Fine --------------------------------------------------------------------------
say "Fatto. Il giornale è qui: $URL"
cat <<EOF

Comandi utili (dalla cartella $DIR):
  docker compose logs -f api worker    # log
  docker compose down                  # ferma tutto (i dati restano nei volumi)
  docker compose up -d                 # riavvia

EOF
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true; fi

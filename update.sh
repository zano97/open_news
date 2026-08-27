#!/usr/bin/env bash
# Open News — aggiornamento in una riga:
#
#   curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/update.sh | bash
#
# Riconosce da solo il tipo di installazione:
# - personale (senza Docker, ~/.opennews): riscarica l'app e reinstalla;
#   i dati (database, impostazioni) vivono fuori dalla cartella app e restano.
# - server Docker (cartella con docker-compose.yml): git pull + rebuild +
#   riavvio; le migrazioni del database girano da sole.
set -euo pipefail

OPENNEWS_HOME="${OPENNEWS_HOME:-$HOME/.opennews}"
URL="http://127.0.0.1:8000"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1mERRORE:\033[0m %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------ installazione personale (default)
if [ -d "$OPENNEWS_HOME/app" ]; then
  say "Aggiorno l'installazione personale in $OPENNEWS_HOME"
  # L'installer è idempotente: riscarica il codice, conserva venv e dati.
  OPENNEWS_NO_SEED=1 bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh)" \
    || fail "aggiornamento non riuscito."
  say "Aggiornato. Se il giornale era aperto, chiudilo e rilancia «opennews»."
  exit 0
fi

# ------------------------------------------------ installazione server Docker
DIR="${OPENNEWS_DIR:-.}"
if [ ! -f "$DIR/docker-compose.yml" ] && [ -f "$DIR/open_news/docker-compose.yml" ]; then
  DIR="$DIR/open_news"
fi
[ -f "$DIR/docker-compose.yml" ] \
  || fail "nessuna installazione trovata (né $OPENNEWS_HOME/app né una cartella Docker; imposta OPENNEWS_DIR=/percorso)."
cd "$DIR"

command -v git >/dev/null 2>&1 || fail "serve git."
docker info >/dev/null 2>&1 || fail "il demone Docker non risponde."

say "Scarico l'ultima versione"
git fetch origin main
VECCHIA=$(git rev-parse --short HEAD)
git pull --ff-only origin main
NUOVA=$(git rev-parse --short HEAD)
[ "$VECCHIA" = "$NUOVA" ] && say "Già aggiornato ($NUOVA)" || say "Aggiornato: $VECCHIA → $NUOVA"

say "Ricostruisco e riavvio (le migrazioni del DB girano da sole)"
docker compose up --build -d

say "Verifico che l'applicazione risponda"
for _ in $(seq 1 60); do curl -fsS "$URL/healthz" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS "$URL/healthz" >/dev/null 2>&1 \
  || fail "l'API non risponde su $URL (vedi: docker compose logs api)."

say "Fatto. Il giornale aggiornato è su $URL"
docker image prune -f >/dev/null 2>&1 || true

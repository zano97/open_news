#!/usr/bin/env bash
# Open News — aggiornamento in una riga (dalla cartella dell'installazione):
#
#   ./update.sh
#
# oppure, senza clonare a mano:
#
#   curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/update.sh | bash
#
# Cosa fa: scarica l'ultima versione, ricostruisce le immagini, riavvia lo
# stack (le migrazioni del database girano da sole all'avvio dell'api) e
# verifica l'healthcheck. I dati restano nei volumi Docker: nessuna perdita.
set -euo pipefail

DIR="${OPENNEWS_DIR:-.}"
URL="http://localhost:8000"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1mERRORE:\033[0m %s\n' "$*" >&2; exit 1; }

# Se lanciato via curl fuori dalla cartella, prova ./open_news
if [ ! -f "$DIR/docker-compose.yml" ] && [ -f "$DIR/open_news/docker-compose.yml" ]; then
  DIR="$DIR/open_news"
fi
[ -f "$DIR/docker-compose.yml" ] \
  || fail "cartella di Open News non trovata (imposta OPENNEWS_DIR=/percorso)."
cd "$DIR"

command -v git >/dev/null 2>&1 || fail "serve git."
docker info >/dev/null 2>&1 || fail "il demone Docker non risponde."

say "Scarico l'ultima versione"
git fetch origin main
VECCHIA=$(git rev-parse --short HEAD)
git pull --ff-only origin main
NUOVA=$(git rev-parse --short HEAD)
if [ "$VECCHIA" = "$NUOVA" ]; then
  say "Già aggiornato ($NUOVA)"
else
  say "Aggiornato: $VECCHIA → $NUOVA"
fi

say "Ricostruisco e riavvio (le migrazioni del DB girano da sole)"
docker compose up --build -d

say "Verifico che l'applicazione risponda"
for _ in $(seq 1 60); do
  if curl -fsS "$URL/healthz" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "$URL/healthz" >/dev/null 2>&1 \
  || fail "l'API non risponde su $URL (vedi: docker compose logs api)."

say "Fatto. Il giornale aggiornato è su $URL"
docker image prune -f >/dev/null 2>&1 || true

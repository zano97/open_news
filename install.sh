#!/usr/bin/env bash
# Open News — installazione in una riga (Linux e macOS):
#
#   curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/install.sh | bash
#
# Non serve Docker: lo script scarica l'app, si procura Python da solo (via
# uv), crea l'icona e il comando `opennews`, scarica le notizie e apre il
# giornale nel browser. Varianti:
#   OPENNEWS_DEMO=1    notizie dimostrative invece di quelle vere (30 secondi)
#   OPENNEWS_DOCKER=1  installazione server con Docker (stack completo)
#   OPENNEWS_NO_SEED=1 salta il primo scaricamento delle notizie
#
# Windows: usa install.ps1 (vedi README).
set -euo pipefail

REPO_TARBALL="https://codeload.github.com/zano97/open_news/tar.gz/refs/heads/main"
OPENNEWS_HOME="${OPENNEWS_HOME:-$HOME/.opennews}"
APP="$OPENNEWS_HOME/app"
BIN_DIR="$HOME/.local/bin"
URL="http://127.0.0.1:8000"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1mERRORE:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- modalità Docker (server)
if [ "${OPENNEWS_DOCKER:-0}" = "1" ]; then
  command -v git >/dev/null 2>&1 || fail "serve git."
  docker info >/dev/null 2>&1 || fail "il demone Docker non risponde."
  DIR="${OPENNEWS_DIR:-open_news}"
  if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only
  else git clone --depth 1 https://github.com/zano97/open_news.git "$DIR"; fi
  cd "$DIR"
  if [ ! -f .env ]; then
    gen() { command -v openssl >/dev/null 2>&1 && openssl rand -hex 32 \
            || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
    printf 'POSTGRES_PASSWORD=%s\nMEILI_MASTER_KEY=%s\nSECRET_KEY=%s\n' \
      "$(gen)" "$(gen)" "$(gen)" > .env
  fi
  docker compose up --build -d
  say "Aspetto l'applicazione"
  for _ in $(seq 1 120); do curl -fsS "$URL/healthz" >/dev/null 2>&1 && break; sleep 2; done
  if [ "${OPENNEWS_DEMO:-0}" = "1" ]; then
    docker compose exec -T api python -m scripts.seed --offline-demo
  elif [ "${OPENNEWS_NO_SEED:-0}" != "1" ]; then
    docker compose exec -T api python -m scripts.verify_feeds || true
    docker compose exec -T api python -m scripts.seed
  fi
  say "Fatto (modalità server Docker). Il giornale è su $URL"
  exit 0
fi

# ---------------------------------------------------------------- modalità personale (default)
say "Installo Open News in $OPENNEWS_HOME (senza Docker)"
command -v curl >/dev/null 2>&1 || fail "serve curl."
command -v tar  >/dev/null 2>&1 || fail "serve tar."

say "Scarico l'applicazione"
TMP="$(mktemp -d)"
curl -fsSL "$REPO_TARBALL" | tar -xz -C "$TMP"
mkdir -p "$OPENNEWS_HOME"
SRC="$(find "$TMP" -maxdepth 1 -type d -name 'open_news-*' | head -1)"
[ -n "$SRC" ] || fail "archivio inatteso."
# Il codice è usa-e-getta (i dati vivono fuori, in $OPENNEWS_HOME): si sostituisce.
VENV_BACKUP=""
if [ -d "$APP/.venv" ]; then VENV_BACKUP="$OPENNEWS_HOME/.venv-keep"; mv "$APP/.venv" "$VENV_BACKUP"; fi
rm -rf "$APP"; mv "$SRC" "$APP"
if [ -n "$VENV_BACKUP" ]; then mv "$VENV_BACKUP" "$APP/.venv"; fi
rm -rf "$TMP"

say "Preparo Python (via uv, si scarica da solo se manca)"
UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  UV="$HOME/.local/bin/uv"
  [ -x "$UV" ] || UV="$HOME/.cargo/bin/uv"
  [ -x "$UV" ] || fail "installazione di uv non riuscita."
fi
cd "$APP"
"$UV" venv --quiet --allow-existing --python 3.12 .venv
"$UV" pip install --quiet --python .venv/bin/python -e .

say "Creo il comando «opennews» e l'icona"
mkdir -p "$BIN_DIR"
ln -sf "$APP/.venv/bin/opennews" "$BIN_DIR/opennews"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *)
  printf '\nNota: aggiungi %s al PATH per usare `opennews` ovunque:\n  export PATH="$HOME/.local/bin:$PATH"\n' "$BIN_DIR";;
esac
case "$(uname -s)" in
  Linux)
    mkdir -p "$HOME/.local/share/applications"
    cat > "$HOME/.local/share/applications/opennews.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Open News
Comment=Chi paga l'informazione · come la racconta · che cosa ignora
Exec=$APP/.venv/bin/opennews
Icon=$APP/apps/web/static/icons/opennews-256.png
Terminal=false
StartupWMClass=OpenNews
Categories=News;Network;
DESK
    ;;
  Darwin)
    MACAPP="$HOME/Applications/Open News.app/Contents/MacOS"
    mkdir -p "$MACAPP" "$HOME/Applications/Open News.app/Contents/Resources"
    printf '#!/bin/bash\nexec "%s"\n' "$APP/.venv/bin/opennews" > "$MACAPP/OpenNews"
    chmod +x "$MACAPP/OpenNews"
    cp "$APP/apps/web/static/icons/opennews.icns" \
       "$HOME/Applications/Open News.app/Contents/Resources/opennews.icns"
    cat > "$HOME/Applications/Open News.app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Open News</string>
  <key>CFBundleExecutable</key><string>OpenNews</string>
  <key>CFBundleIdentifier</key><string>org.opennews.app</string>
  <key>CFBundleIconFile</key><string>opennews</string>
</dict></plist>
PLIST
    ;;
esac

if [ "${OPENNEWS_DEMO:-0}" = "1" ]; then
  say "Popolo con notizie dimostrative (dichiarate come tali)"
  "$APP/.venv/bin/opennews" seed --demo
elif [ "${OPENNEWS_NO_SEED:-0}" != "1" ]; then
  say "Scarico le ultime 24 ore di notizie vere (pochi minuti, solo la prima volta)"
  "$APP/.venv/bin/opennews" seed
fi

say "Avvio il giornale"
nohup "$APP/.venv/bin/opennews" --no-browser > "$OPENNEWS_HOME/log.txt" 2>&1 &
for _ in $(seq 1 40); do curl -fsS "$URL/healthz" >/dev/null 2>&1 && break; sleep 1; done
# Finestra applicazione dedicata se c'è un browser Chromium; altrimenti tab.
if ! "$APP/.venv/bin/python" -c "import sys; from apps.launcher import open_app_window; sys.exit(0 if open_app_window('$URL') else 1)" 2>/dev/null; then
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true; fi
fi

say "Fatto. Il giornale è su $URL"
cat <<EOF

Come si usa da adesso in poi:
  • icona «Open News» nel menu applicazioni (Linux) o in ~/Applications (macOS)
  • oppure dal terminale:  opennews
  • notizie:               si aggiornano da sole ogni 10 minuti finché è aperto
  • aggiornare l'app:      curl -fsSL https://raw.githubusercontent.com/zano97/open_news/main/update.sh | bash
  • dati e log:            $OPENNEWS_HOME

EOF

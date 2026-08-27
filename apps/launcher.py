"""`opennews`: avvio in modalità personale, senza Docker.

Un solo processo: sito + raccoglitore (scheduler) insieme, database SQLite
in ~/.opennews/. Pensato per l'uso personale sul proprio computer; per un
server pubblico resta lo stack Docker (docs/DEPLOY.md).

Comandi:
    opennews                 avvia il giornale e apre il browser
    opennews seed            scarica le ultime 24 ore di notizie vere
    opennews seed --demo     notizie dimostrative (nessuna rete)
    opennews --port 8100     porta diversa
    opennews --no-browser    non aprire il browser
"""

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def home_dir() -> Path:
    return Path(os.environ.get("OPENNEWS_HOME", str(Path.home() / ".opennews")))


def db_path() -> Path:
    return home_dir() / "opennews.sqlite3"


def _ensure_env() -> None:
    """DATABASE_URL su SQLite personale (se non impostata) e chiave firmata."""
    home_dir().mkdir(parents=True, exist_ok=True)
    os.environ.setdefault(
        "DATABASE_URL", f"sqlite+aiosqlite:///{db_path().as_posix()}"
    )
    secret_file = home_dir() / "secret_key"
    if "SECRET_KEY" not in os.environ:
        if not secret_file.exists():
            import secrets

            secret_file.write_text(secrets.token_hex(32))
            secret_file.chmod(0o600)
        os.environ["SECRET_KEY"] = secret_file.read_text().strip()


def _migrate() -> None:
    """Porta il database all'ultima versione (le migrazioni sono idempotenti)."""
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(APP_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
    command.upgrade(cfg, "head")


def _open_browser_later(url: str, delay: float = 1.5) -> None:
    def apri() -> None:
        import time

        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=apri, daemon=True).start()


def cmd_run(port: int, open_browser: bool) -> None:
    import uvicorn

    _ensure_env()
    _migrate()
    # Il raccoglitore gira nello stesso processo (un solo worker uvicorn).
    os.environ["OPENNEWS_EMBEDDED_WORKER"] = "1"
    url = f"http://127.0.0.1:{port}"
    print(f"Open News → {url}   (Ctrl+C per fermare; dati in {home_dir()})")
    if open_browser:
        _open_browser_later(url)
    uvicorn.run(
        "apps.api.main:app", host="127.0.0.1", port=port, workers=1, log_level="warning"
    )


def cmd_seed(demo: bool) -> None:
    _ensure_env()
    _migrate()
    from scripts.seed import main as seed_main

    argv = ["seed"] + (["--offline-demo"] if demo else [])
    old = sys.argv
    try:
        sys.argv = argv
        seed_main()
    finally:
        sys.argv = old


def main() -> None:
    parser = argparse.ArgumentParser(prog="opennews", description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    sub = parser.add_subparsers(dest="comando")
    seed = sub.add_parser("seed", help="scarica le notizie (o --demo)")
    seed.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    if args.comando == "seed":
        cmd_seed(demo=args.demo)
    else:
        cmd_run(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()

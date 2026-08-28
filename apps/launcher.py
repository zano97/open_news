"""`opennews`: avvio in modalità personale, senza Docker.

Un solo processo: sito + raccoglitore (scheduler) insieme, database SQLite
in ~/.opennews/. Pensato per l'uso personale sul proprio computer; per un
server pubblico resta lo stack Docker (docs/DEPLOY.md).

Il giornale si apre in una FINESTRA APPLICAZIONE dedicata (senza tab né
barra degli indirizzi) se sul computer c'è un browser della famiglia
Chromium — Chrome, Chromium, Edge, Brave, Vivaldi —, altrimenti nel
browser predefinito come pagina normale.

Comandi:
    opennews                 avvia il giornale e apre la finestra
    opennews seed            scarica le ultime 24 ore di notizie vere
    opennews seed --demo     notizie dimostrative (nessuna rete)
    opennews --port 8100     porta diversa
    opennews --tab           apri nel browser normale invece che in finestra
    opennews --no-browser    non aprire niente
"""

import argparse
import os
import shutil
import subprocess
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


def _app_browser_command() -> list[str] | None:
    """Comando per una finestra applicazione (browser famiglia Chromium)."""
    if sys.platform == "darwin":
        for nome in (
            "Google Chrome", "Chromium", "Brave Browser", "Microsoft Edge", "Vivaldi"
        ):
            if Path(f"/Applications/{nome}.app").exists():
                return ["open", "-na", nome, "--args"]
        return None
    if sys.platform == "win32":
        program_files = [
            # Nomi canonici Windows (l'ambiente lì è case-insensitive).
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),  # noqa: SIM112
            os.environ.get("ProgramFiles", r"C:\Program Files"),  # noqa: SIM112
            os.environ.get("LOCALAPPDATA", ""),
        ]
        relativi = [
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
        for base in program_files:
            for rel in relativi:
                exe = Path(base) / rel
                if base and exe.exists():
                    return [str(exe)]
        return None
    for nome in (
        "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
        "brave-browser", "microsoft-edge", "microsoft-edge-stable", "vivaldi",
    ):
        exe = shutil.which(nome)
        if exe:
            return [exe]
    return None


def open_native_window(url: str) -> bool:
    """Su macOS: finestra WebKit nativa con l'icona di Open News nel Dock.

    Il browser in modalità --app mostrerebbe l'icona del browser; la
    finestra nativa (apps/mac_window.py, extra [mac]) mostra la nostra.
    Falso se pyobjc non è disponibile: si ripiega sulla modalità --app.
    """
    if sys.platform == "darwin":
        import importlib.util

        if (
            importlib.util.find_spec("AppKit") is None
            or importlib.util.find_spec("WebKit") is None
        ):
            return False
        try:
            subprocess.Popen(
                [sys.executable, "-m", "apps.mac_window", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return False
        return True
    return False


def open_app_window(url: str) -> bool:
    """Apre l'URL come finestra applicazione. Falso se non c'è un browser adatto."""
    cmd = _app_browser_command()
    if cmd is None:
        return False
    argv = [*cmd, f"--app={url}", "--window-size=1280,900"]
    if sys.platform.startswith("linux"):
        argv.append("--class=OpenNews")  # icona e raggruppamento corretti nel dock
    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def _open_ui_later(url: str, *, app_window: bool, delay: float = 1.5) -> None:
    def apri() -> None:
        import time

        time.sleep(delay)
        if app_window and (open_native_window(url) or open_app_window(url)):
            return
        webbrowser.open(url)

    threading.Thread(target=apri, daemon=True).start()


def _file_logging() -> None:
    """Log su file in ~/.opennews/opennews.log: raggiungibile senza terminale
    (il pannello /impostazioni ne mostra il percorso e gli ultimi eventi)."""
    import logging
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(
        home_dir() / "opennews.log",
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)


def _shutdown_token() -> str:
    """Token per l'endpoint /spegni: la finestra lo usa per chiudere tutto.

    Vive in un file 0600 dentro OPENNEWS_HOME così anche una finestra
    aperta da un processo diverso (es. dall'installer) può leggerlo.
    """
    import secrets

    token_file = home_dir() / "shutdown_token"
    token = secrets.token_hex(16)
    token_file.write_text(token)
    token_file.chmod(0o600)
    return token


def cmd_run(port: int, open_browser: bool, app_window: bool = True) -> None:
    import uvicorn

    _ensure_env()
    _file_logging()
    _migrate()
    # Il raccoglitore gira nello stesso processo (un solo worker uvicorn).
    os.environ["OPENNEWS_EMBEDDED_WORKER"] = "1"
    os.environ["OPENNEWS_SHUTDOWN_TOKEN"] = _shutdown_token()
    url = f"http://127.0.0.1:{port}"
    print(f"Open News → {url}   (Ctrl+C per fermare; dati in {home_dir()})")
    if open_browser:
        _open_ui_later(url, app_window=app_window)
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
    parser.add_argument(
        "--tab", action="store_true",
        help="apri nel browser normale invece che in finestra applicazione",
    )
    sub = parser.add_subparsers(dest="comando")
    seed = sub.add_parser("seed", help="scarica le notizie (o --demo)")
    seed.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    if args.comando == "seed":
        cmd_seed(demo=args.demo)
    else:
        cmd_run(
            port=args.port,
            open_browser=not args.no_browser,
            app_window=not args.tab,
        )


if __name__ == "__main__":
    main()

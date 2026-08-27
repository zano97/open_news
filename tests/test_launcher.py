"""Launcher `opennews` (modalità personale, senza Docker)."""

import os
from pathlib import Path

import pytest

from apps import launcher


def test_home_dir_da_variabile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENNEWS_HOME", str(tmp_path / "casa"))
    assert launcher.home_dir() == tmp_path / "casa"
    assert launcher.db_path() == tmp_path / "casa" / "opennews.sqlite3"


def test_ensure_env_prepara_db_e_segreto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENNEWS_HOME", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    launcher._ensure_env()
    assert os.environ["DATABASE_URL"].startswith("sqlite+aiosqlite:///")
    assert os.environ["DATABASE_URL"].endswith("opennews.sqlite3")
    segreto = os.environ["SECRET_KEY"]
    assert len(segreto) == 64
    # Il segreto è persistente: una seconda chiamata non lo rigenera.
    monkeypatch.delenv("SECRET_KEY", raising=False)
    launcher._ensure_env()
    assert os.environ["SECRET_KEY"] == segreto
    assert (tmp_path / "secret_key").exists()


def test_argomenti_instradati(monkeypatch: pytest.MonkeyPatch) -> None:
    chiamate: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        launcher, "cmd_run",
        lambda port, open_browser: chiamate.append(("run", port, open_browser)),
    )
    monkeypatch.setattr(
        launcher, "cmd_seed", lambda demo: chiamate.append(("seed", demo))
    )

    monkeypatch.setattr("sys.argv", ["opennews", "--port", "8100", "--no-browser"])
    launcher.main()
    monkeypatch.setattr("sys.argv", ["opennews", "seed", "--demo"])
    launcher.main()

    assert chiamate == [("run", 8100, False), ("seed", True)]

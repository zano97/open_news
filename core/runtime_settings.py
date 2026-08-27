"""Impostazioni modificabili a runtime dal pannello admin (/impostazioni).

Allowlist esplicita: solo parametri operativi (LLM locale, clustering,
raccolta, finestre dei segnali). I parametri della metodologia — le soglie di
pubblicazione del livello 4, la tassonomia, il lessico — restano fuori di
proposito: cambiarli è un cambio di metodo e passa dal repository, con la
versione che cambia (vedi /metodo).

Gli override vivono nella tabella `app_settings`, prevalgono sulle variabili
d'ambiente e vengono applicati all'istanza (cache) di Settings: API e worker
li ricaricano all'avvio e periodicamente.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from core.models import AppSetting, utcnow


class InvalidSetting(ValueError):
    """Valore rifiutato: `reason_key` è una chiave i18n, `params` i suoi dati."""

    def __init__(self, reason_key: str, **params: object) -> None:
        super().__init__(reason_key)
        self.reason_key = reason_key
        self.params = params


def _parse_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "on", "yes", "si", "sì"):
        return True
    if lowered in ("false", "0", "off", "no", ""):
        return False
    raise InvalidSetting("imp.err_scelta")


def _parse_choice(*allowed: str) -> Callable[[str], str]:
    def parse(raw: str) -> str:
        value = raw.strip().lower()
        if value not in allowed:
            raise InvalidSetting("imp.err_scelta")
        return value

    return parse


def _parse_int(lo: int, hi: int) -> Callable[[str], int]:
    def parse(raw: str) -> int:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise InvalidSetting("imp.err_numero", min=lo, max=hi) from exc
        if not lo <= value <= hi:
            raise InvalidSetting("imp.err_numero", min=lo, max=hi)
        return value

    return parse


def _parse_float(lo: float, hi: float) -> Callable[[str], float]:
    def parse(raw: str) -> float:
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError as exc:
            raise InvalidSetting("imp.err_numero", min=lo, max=hi) from exc
        if not lo <= value <= hi:
            raise InvalidSetting("imp.err_numero", min=lo, max=hi)
        return round(value, 4)

    return parse


def _parse_ollama_url(raw: str) -> str:
    """URL http(s) verso un host consentito dall'allowlist di rete.

    Impedisce di usare il pannello per far parlare il server con host
    arbitrari: valgono le stesse regole di core.net (host interni, locali,
    o dell'infrastruttura documentata).
    """
    from core.net import host_allowed

    value = raw.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidSetting("imp.err_url")
    if not host_allowed(parts.hostname):
        raise InvalidSetting("imp.err_url")
    return value


_MODEL_RE = re.compile(r"^[\w][\w.:/-]{0,80}$")


def _parse_model(raw: str) -> str:
    value = raw.strip()
    if not _MODEL_RE.match(value):
        raise InvalidSetting("imp.err_modello")
    return value


@dataclass(frozen=True)
class EditableSetting:
    key: str  # attributo di Settings e chiave in app_settings
    group: str  # llm | clustering | raccolta | segnali
    input_type: str  # bool | text | number | choice
    parse: Callable[[str], object]
    choices: tuple[str, ...] = ()
    step: str = "1"


EDITABLE: tuple[EditableSetting, ...] = (
    EditableSetting("enable_llm", "llm", "bool", _parse_bool),
    EditableSetting("ollama_url", "llm", "text", _parse_ollama_url),
    EditableSetting("ollama_model", "llm", "text", _parse_model),
    EditableSetting(
        "embedding_backend", "clustering", "choice",
        _parse_choice("hashing", "e5"), choices=("hashing", "e5"),
    ),
    EditableSetting(
        "cluster_similarity_threshold", "clustering", "number",
        _parse_float(0.01, 0.99), step="0.01",
    ),
    EditableSetting(
        "cluster_window_hours", "clustering", "number", _parse_int(6, 168)
    ),
    EditableSetting("flash_min_sources", "clustering", "number", _parse_int(2, 20)),
    EditableSetting("flash_window_hours", "clustering", "number", _parse_int(1, 24)),
    # Mai sotto 2 secondi: cortesia di rete promessa in docs/LEGAL.md.
    EditableSetting(
        "rate_limit_seconds", "raccolta", "number", _parse_float(2.0, 60.0), step="0.5"
    ),
    EditableSetting("signal_window_days", "segnali", "number", _parse_int(7, 365)),
    EditableSetting(
        "blindspot_coverage_pct", "segnali", "number",
        _parse_float(0.1, 0.9), step="0.05",
    ),
)

_BY_KEY = {spec.key: spec for spec in EDITABLE}


def _apply(settings: Settings, key: str, parsed: object) -> None:
    setattr(settings, key, parsed)


async def load_overrides(session: AsyncSession) -> int:
    """Applica gli override dal DB all'istanza Settings. Ritorna quanti."""
    settings = get_settings()
    applied = 0
    rows = (await session.execute(select(AppSetting))).scalars()
    for row in rows:
        spec = _BY_KEY.get(row.key)
        if spec is None:
            continue  # chiave sconosciuta o non più in allowlist: ignorata
        try:
            _apply(settings, row.key, spec.parse(row.value))
            applied += 1
        except InvalidSetting:
            continue  # valore corrotto: resta il default, mai un crash
    return applied


async def save_overrides(
    session: AsyncSession, form: dict[str, str], updated_by: str
) -> dict[str, InvalidSetting]:
    """Valida e salva; applica subito i validi. Ritorna {chiave: errore}."""
    settings = get_settings()
    errors: dict[str, InvalidSetting] = {}
    existing = {
        row.key: row for row in (await session.execute(select(AppSetting))).scalars()
    }
    for spec in EDITABLE:
        if spec.input_type == "bool":
            raw: str = form.get(spec.key, "false")  # checkbox assente = false
        else:
            candidate = form.get(spec.key)
            if candidate is None or candidate.strip() == "":
                continue  # campo non toccato: si tiene il valore corrente
            raw = candidate
        try:
            parsed = spec.parse(raw)
        except InvalidSetting as exc:
            errors[spec.key] = exc
            continue
        _apply(settings, spec.key, parsed)
        stored = str(parsed).lower() if isinstance(parsed, bool) else str(parsed)
        row = existing.get(spec.key)
        if row is None:
            row = AppSetting(key=spec.key, value=stored)
            session.add(row)
        else:
            row.value = stored
        row.updated_by = updated_by
        row.updated_at = utcnow()
    await session.flush()
    return errors


async def last_update(session: AsyncSession) -> AppSetting | None:
    return (
        await session.execute(
            select(AppSetting).order_by(AppSetting.updated_at.desc()).limit(1)
        )
    ).scalars().first()


def current_values() -> dict[str, object]:
    settings = get_settings()
    return {spec.key: getattr(settings, spec.key) for spec in EDITABLE}

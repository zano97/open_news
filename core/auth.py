"""Autenticazione locale per gli annotatori: nessun servizio esterno.

Password con PBKDF2-HMAC-SHA256 (solo libreria standard), sessione in cookie
firmato (itsdangerous) con scadenza. Le POST sono protette da SameSite=Lax.
"""

import hashlib
import hmac
import secrets

from itsdangerous import BadSignature, URLSafeTimedSerializer

from core.config import get_settings

_PBKDF2_ITERATIONS = 480_000
SESSION_COOKIE = "opennews_sessione"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 giorni


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2-sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _scheme, iterations, salt, digest = stored.split("$")
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
        return hmac.compare_digest(computed, digest)
    except (ValueError, TypeError):
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="sessione-annotatore")


def make_session_token(annotator_id: int) -> str:
    return str(_serializer().dumps({"annotator_id": annotator_id}))


def read_session_token(token: str) -> int | None:
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    value = data.get("annotator_id")
    return int(value) if isinstance(value, int) else None

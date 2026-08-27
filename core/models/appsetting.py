"""Impostazioni di runtime modificabili dall'interfaccia (solo admin).

Solo le chiavi in allowlist (core/runtime_settings.py) sono accettate; i
parametri della metodologia (soglie di pubblicazione del livello 4, ecc.)
restano volutamente fuori: si cambiano nel codice, con la versione del
metodo, mai da un pannello.
"""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, utcnow
from core.models.types import TZDateTime


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))
    updated_by: Mapped[str] = mapped_column(String(120), default="")
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

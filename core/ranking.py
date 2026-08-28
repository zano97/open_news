"""Attualità della prima pagina: finestra e peso, condivisi.

Vive in ``core`` perché DEVE essere identica per chi mostra (apps.api) e
per chi prepara (worker): il job di traduzione dei titoli serve prima
esattamente le story che il lettore sta per vedere — quando le due liste
divergevano, la prima pagina restava piena di titoli mai tradotti mentre
il job lavorava su story che nessuno guardava.
"""

import math
from datetime import datetime, timedelta

from core.config import get_settings
from core.models import utcnow

# La copertura si sconta del tempo trascorso dall'ultimo aggiornamento:
# dimezza ogni PESO_DIMEZZAMENTO_ORE. Così una story enorme di ieri non
# copre per sempre una story nata oggi, ma una ancora viva resta in alto.
PESO_DIMEZZAMENTO_ORE = 12.0


def finestra_attualita() -> datetime:
    """Inizio della finestra di attualità della prima pagina (last_seen)."""
    return utcnow() - timedelta(hours=get_settings().front_page_window_hours)


def peso_attualita(copertura: int, last_seen: datetime) -> float:
    ore = max((utcnow() - last_seen).total_seconds() / 3600.0, 0.0)
    return max(int(copertura), 1) * math.pow(0.5, ore / PESO_DIMEZZAMENTO_ORE)

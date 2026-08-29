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
# Spinta alle notizie appena arrivate: nelle prime ore una story ha poche
# testate e la sola copertura non basterebbe MAI a farla entrare tra le
# 36 mostrate. Il bonus vale come qualche testata e si spegne in fretta
# (dimezza ogni due ore), così apre la strada senza falsare la classifica.
BONUS_NOVITA = 6.0
BONUS_DIMEZZAMENTO_ORE = 2.0


def finestra_attualita() -> datetime:
    """Inizio della finestra di attualità della prima pagina (last_seen)."""
    return utcnow() - timedelta(hours=get_settings().front_page_window_hours)


def finestra_ultima_ora() -> datetime:
    """Inizio della fascia «ultima ora» (le notizie appena arrivate)."""
    return utcnow() - timedelta(hours=get_settings().front_page_breaking_hours)


def _ore_da(last_seen: datetime) -> float:
    return max((utcnow() - last_seen).total_seconds() / 3600.0, 0.0)


def peso_attualita(copertura: int, last_seen: datetime) -> float:
    ore = _ore_da(last_seen)
    coperta = max(int(copertura), 1) * math.pow(0.5, ore / PESO_DIMEZZAMENTO_ORE)
    novita = BONUS_NOVITA * math.pow(0.5, ore / BONUS_DIMEZZAMENTO_ORE)
    return coperta + novita

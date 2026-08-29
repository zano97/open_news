"""Trasparenza DICHIARATA dalla testata: dati strutturati schema.org.

Molte testate pubblicano in homepage un blocco JSON-LD
`NewsMediaOrganization` — un vocabolario nato dal lavoro del Trust
Project — con i riferimenti a: assetto proprietario e finanziamenti
(`ownershipFundingInfo`), codice etico (`ethicsPolicy`), politica
delle rettifiche (`correctionsPolicy`), politica sulla diversità
(`diversityPolicy`), redazione (`masthead`), politica dei contenuti
sponsorizzati (`unnamedSourcesPolicy`, `actionableFeedbackPolicy`).

È la testata a dichiararlo, in un formato pensato per le macchine:
leggerlo non è né intrusivo né interpretativo. Noi non giudichiamo il
CONTENUTO di quelle pagine: contiamo quali impegni la testata rende
pubblici e verificabili, e mostriamo i link perché il lettore vada a
controllare di persona.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_JSONLD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

# Impegni di trasparenza del vocabolario NewsMediaOrganization, con il
# nome interno che usiamo nell'interfaccia.
IMPEGNI: dict[str, str] = {
    "ownershipFundingInfo": "proprieta_e_finanziamenti",
    "ethicsPolicy": "codice_etico",
    "correctionsPolicy": "rettifiche",
    "diversityPolicy": "diversita",
    "diversityStaffingReport": "rapporto_diversita",
    "masthead": "redazione",
    "actionableFeedbackPolicy": "segnalazioni",
    "unnamedSourcesPolicy": "fonti_anonime",
    "verificationFactCheckingPolicy": "verifica_dei_fatti",
    "noBylinesPolicy": "firme",
}

_ORG_TYPES = {"newsmediaorganization", "organization", "newspaper", "corporation"}


@dataclass
class TrustProfile:
    """Cosa la testata dichiara di sé, in modo leggibile da una macchina."""

    nome_dichiarato: str | None = None
    fondazione: str | None = None
    editore: str | None = None
    impegni: dict[str, str] = field(default_factory=dict)  # nome interno -> URL
    error: str | None = None

    @property
    def punteggio(self) -> int:
        """Quanti impegni di trasparenza sono dichiarati (0-10). NON è un
        giudizio sulla qualità: misura solo quanto la testata si espone."""
        return len(self.impegni)


def _blocchi_jsonld(html: str) -> list[Any]:
    blocchi: list[Any] = []
    for grezzo in _JSONLD_RE.findall(html):
        try:
            blocchi.append(json.loads(grezzo.strip()))
        except (ValueError, TypeError):
            continue
    return blocchi


def _appiattisci(dato: Any) -> list[dict[str, Any]]:
    """JSON-LD ammette oggetti, liste e @graph: qui diventano una lista piatta."""
    fuori: list[dict[str, Any]] = []
    if isinstance(dato, list):
        for voce in dato:
            fuori.extend(_appiattisci(voce))
    elif isinstance(dato, dict):
        fuori.append(dato)
        for chiave in ("@graph", "publisher", "parentOrganization", "sourceOrganization"):
            if chiave in dato:
                fuori.extend(_appiattisci(dato[chiave]))
    return fuori


def _testo(valore: Any) -> str | None:
    """Un campo schema.org può essere stringa, oggetto {url}, o lista."""
    if isinstance(valore, str):
        return valore.strip() or None
    if isinstance(valore, dict):
        for chiave in ("url", "@id", "name"):
            if isinstance(valore.get(chiave), str) and valore[chiave].strip():
                return str(valore[chiave]).strip()
    if isinstance(valore, list):
        for voce in valore:
            trovato = _testo(voce)
            if trovato:
                return trovato
    return None


def parse_trust_markup(html: str) -> TrustProfile:
    """Estrae gli impegni di trasparenza dai dati strutturati della pagina."""
    profilo = TrustProfile()
    organizzazioni = [
        nodo
        for blocco in _blocchi_jsonld(html)
        for nodo in _appiattisci(blocco)
        if isinstance(nodo.get("@type"), str | list)
        and any(
            str(t).lower() in _ORG_TYPES
            for t in (
                nodo["@type"] if isinstance(nodo["@type"], list) else [nodo["@type"]]
            )
        )
    ]
    if not organizzazioni:
        profilo.error = "nessun dato strutturato dell'organizzazione"
        return profilo
    for nodo in organizzazioni:
        profilo.nome_dichiarato = profilo.nome_dichiarato or _testo(nodo.get("name"))
        profilo.fondazione = profilo.fondazione or _testo(nodo.get("foundingDate"))
        profilo.editore = profilo.editore or _testo(nodo.get("parentOrganization"))
        for campo, nome_interno in IMPEGNI.items():
            if nome_interno in profilo.impegni:
                continue
            valore = _testo(nodo.get(campo))
            if valore and valore.startswith("http"):
                profilo.impegni[nome_interno] = valore
    return profilo

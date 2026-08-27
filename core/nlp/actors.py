"""Chi parla negli articoli: citazioni tra virgolette e attribuzioni.

Metodo "actors-heuristic-v1", dichiaratamente euristico e documentato:
- individua il discorso riportato tra virgolette («...», "...", “...”);
- cerca il parlante come sequenza di parole capitalizzate vicino a un verbo
  di attribuzione (dice, afferma, secondo, says, said, ...);
- classifica il ruolo con un piccolo dizionario di contesto
  (governo / opposizione / istituzione / esperto / cittadino / azienda).
Con l'extra [ml] (spaCy/GLiNER) o l'LLM locale la qualità può salire, ma il
metodo resta sempre dichiarato accanto al dato.
"""

import re
from dataclasses import dataclass

METHOD_NAME = "actors-heuristic-v1"

_QUOTE_RE = re.compile(r"«([^»]{10,400})»|“([^”]{10,400})”|\"([^\"]{10,400})\"")

_ATTRIBUTION_VERBS = (
    "dice|ha detto|dichiara|ha dichiarato|afferma|ha affermato|sostiene|annuncia|"
    "denuncia|spiega|ha spiegato|aggiunge|commenta|ribadisce|avverte|attacca|"
    "says|said|told|declared|announced|added|warned|claims|according to|secondo"
)

_NAME = (
    r"(?:[A-ZÀ-Þ][\wà-þ'’-]+)"
    r"(?:\s+(?:di|de|del|della|van|von|al|el|bin)?\s?[A-ZÀ-Þ][\wà-þ'’-]+){0,3}"
)

_SPEAKER_PATTERNS = [
    # «...», ha detto Mario Rossi / "...", said Jane Doe
    re.compile(rf"[»”\"],?\s*(?:{_ATTRIBUTION_VERBS})\s+(?:il |la |l'|lo )?({_NAME})"),
    # Mario Rossi dice/afferma...
    re.compile(rf"({_NAME})\s+(?:{_ATTRIBUTION_VERBS})"),
    # secondo Mario Rossi / According to Jane Doe
    re.compile(rf"(?:[Ss]econdo|[Aa]ccording to)\s+(?:il |la |l'|lo )?({_NAME})"),
]

# Parole istituzionali che il pattern del nome può catturare per errore quando
# il nome segue un titolo ("il ministro dell'Economia Mario Rossi").
_TITLE_WORDS = frozenset(
    {
        "economia", "interno", "esteri", "difesa", "salute", "giustizia",
        "lavoro", "istruzione", "cultura", "repubblica", "consiglio",
        "camera", "senato", "regione", "comune", "stato", "unione",
    }
)

_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "governo": (
        "ministro", "ministra", "premier", "presidente del consiglio", "governo",
        "sottosegretario", "viceministro", "palazzo chigi", "minister",
        "prime minister", "government", "chancellor", "white house",
    ),
    "opposizione": (
        "opposizione", "leader dell'opposizione", "minoranza", "opposition",
        "segretario del partito", "capogruppo",
    ),
    "istituzione": (
        "presidente della repubblica", "quirinale", "corte", "tribunale", "giudice",
        "procura", "procuratore", "commissione europea", "parlamento", "bce",
        "banca centrale", "onu", "nazioni unite", "nato", "oms", "authority",
        "garante", "prefetto", "questura", "court", "judge", "parliament",
        "commission", "united nations", "central bank",
    ),
    "esperto": (
        "professore", "professoressa", "economista", "analista", "esperto",
        "esperta", "ricercatore", "ricercatrice", "docente", "virologo",
        "epidemiologo", "sociologo", "storico", "professor", "economist",
        "analyst", "expert", "researcher", "scientist",
    ),
    "cittadino": (
        "residente", "testimone", "cittadino", "cittadina", "abitante",
        "passante", "familiare", "resident", "witness", "bystander",
    ),
    "azienda": (
        "amministratore delegato", "portavoce", "azienda", "società", "gruppo",
        "ceo", "spokesperson", "company", "corporation", "manager",
    ),
}


@dataclass(frozen=True)
class Citation:
    speaker: str
    role: str | None
    quote: str | None


def _classify_role(context: str) -> str | None:
    lowered = context.lower()
    best: tuple[int, str] | None = None
    for role, keywords in _ROLE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits and (best is None or hits > best[0]):
            best = (hits, role)
    return best[1] if best else None


def extract_citations(text: str) -> list[Citation]:
    """Citazioni con parlante e ruolo (euristica dichiarata). Deduplicate per parlante."""
    citations: dict[str, Citation] = {}

    quotes = [next(g for g in m.groups() if g) for m in _QUOTE_RE.finditer(text)]

    for pattern in _SPEAKER_PATTERNS:
        for match in pattern.finditer(text):
            speaker = match.group(1).strip()
            # "dell'Economia Mario Rossi": scarta la parola-titolo iniziale.
            words = speaker.split()
            while len(words) > 1 and words[0].lower().strip("'’") in _TITLE_WORDS:
                words = words[1:]
            speaker = " ".join(words)
            if len(speaker) < 3 or speaker.lower() in ("il", "la", "lo"):
                continue
            # Il ruolo di solito precede il nome ("il ministro X dice"):
            # finestra asimmetrica, più larga all'indietro.
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 60)
            role = _classify_role(text[start:end])
            if speaker not in citations:
                citations[speaker] = Citation(
                    speaker=speaker,
                    role=role,
                    quote=quotes[0] if quotes else None,
                )
            elif citations[speaker].role is None and role is not None:
                citations[speaker] = Citation(
                    speaker=speaker, role=role, quote=citations[speaker].quote
                )
    return list(citations.values())

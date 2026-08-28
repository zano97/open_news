"""Backfill: titoli GDELT già in archivio ripuliti come i nuovi.

Gli articoli ingeriti via GDELT prima dell'introduzione di tidy_title hanno
titoli ritokenizzati ("9 / 11", "morta , addio") e nomi di paese riscritti
in minuscolo ("united states erhöhen…"). Qui si applica la stessa pulizia ai
titoli in archivio; le story il cui titolo neutro era uno di quei titoli
vengono corrette e le loro traduzioni azzerate (si rigenerano dal titolo
pulito al primo giro utile). Gli apostrofi persi alla fonte non sono
recuperabili. I titoli arrivati dai feed non si toccano.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-28

"""
import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copia CONGELATA di core.ingest.gdelt.tidy_title al momento della migrazione:
# una migrazione non deve cambiare esito se il codice dell'app evolve.
_SPAZI_PUNTEGGIATURA = re.compile(r"\s+([,.;:!?%)\]])")
_PUNTEGGIATURA_APERTA = re.compile(r"([(\[])\s+")
_BARRA = re.compile(r"(?<=\w)\s+/\s+(?=\w)")
_PAESI_GDELT = {
    "united states": "USA",
    "united kingdom": "UK",
    "united arab emirates": "United Arab Emirates",
    "new zealand": "New Zealand",
    "saudi arabia": "Saudi Arabia",
    "south korea": "South Korea",
    "north korea": "North Korea",
    "south africa": "South Africa",
    "czech republic": "Czech Republic",
}
_PAESI_GDELT_RE = re.compile(
    r"\b(" + "|".join(sorted(_PAESI_GDELT, key=len, reverse=True)) + r")\b"
)


def _tidy(title: str) -> str:
    title = _PAESI_GDELT_RE.sub(lambda m: _PAESI_GDELT[m.group(1)], title)
    title = _BARRA.sub("/", title)
    title = _SPAZI_PUNTEGGIATURA.sub(r"\1", title)
    title = _PUNTEGGIATURA_APERTA.sub(r"\1", title)
    return re.sub(r"\s{2,}", " ", title).strip()


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"articles", "stories", "provenances"} <= tables:
        return  # schema appena creato: nessun dato da sanare

    # Solo gli articoli arrivati via GDELT: quelli dei feed hanno il titolo
    # editoriale vero, che non va mai riscritto.
    gdelt_ids = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT entity_id FROM provenances WHERE entity_type = 'article' "
                "AND field = 'ingest' AND method = 'gdelt-doc-2.0'"
            )
        )
    ]
    for start in range(0, len(gdelt_ids), 500):
        chunk = gdelt_ids[start : start + 500]
        rows = bind.execute(
            sa.text(
                "SELECT id, title, story_id FROM articles WHERE id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": chunk},
        ).fetchall()
        for article_id, title, story_id in rows:
            pulito = _tidy(title or "")
            if not pulito or pulito == title:
                continue
            bind.execute(
                sa.text("UPDATE articles SET title = :t WHERE id = :i"),
                {"t": pulito, "i": article_id},
            )
            if story_id is not None:
                # Se il titolo storpiato era diventato il titolo neutro della
                # story, si corregge anche lì; le traduzioni erano fatte sul
                # testo storpiato e si rigenerano dal titolo pulito.
                bind.execute(
                    sa.text(
                        "UPDATE stories SET title_neutral = :t, "
                        "title_translations = :vuote "
                        "WHERE id = :s AND title_neutral = :vecchio"
                    ),
                    {"t": pulito, "vuote": "{}", "s": story_id, "vecchio": title},
                )


def downgrade() -> None:
    # Pulizia di dati non reversibile (i titoli storpiati non si ripristinano).
    pass

"""Grafici SVG disegnati server-side, senza librerie: si integrano nel foglio
di stile della pagina (ereditano font e variabili colore CSS).

Ogni funzione ritorna una stringa SVG da inserire inline nei template con
`| safe`; tutti i testi passano da `escape`.
"""

from html import escape

from core.bias.structure import SourceProfile


def _box(x: int, y: int, w: int, h: int, cls: str) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'class="{cls}" rx="3" ry="3" />'
    )


def ownership_graph_svg(profile: SourceProfile) -> str:
    """Grafo delle partecipazioni: proprietari a sinistra, testata a destra.

    Le quote note compaiono sull'arco; quelle ignote sono dichiarate
    "quota n.d.". I proprietari con cariche politiche portano un contrassegno.
    """
    owners = profile.ownerships
    if not owners:
        return (
            '<p class="dato-mancante">Assetto proprietario: dato non disponibile '
            "(nessuna evidenza importata).</p>"
        )

    row_h = 64
    gap = 18
    width = 720
    box_w = 300
    height = max(len(owners) * (row_h + gap) - gap, row_h) + 20
    source_y = height // 2 - row_h // 2

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" role="img" class="grafo-proprieta" '
        f'aria-label="Grafo delle partecipazioni di {escape(profile.source.name)}">'
    ]
    # Nodo testata a destra.
    sx = width - box_w - 10
    parts.append(_box(sx, source_y, box_w, row_h, "grafo-nodo grafo-testata"))
    parts.append(
        f'<text x="{sx + box_w / 2}" y="{source_y + 27}" text-anchor="middle" '
        f'class="grafo-etichetta grafo-etichetta-forte">{escape(profile.source.name)}</text>'
    )
    parts.append(
        f'<text x="{sx + box_w / 2}" y="{source_y + 47}" text-anchor="middle" '
        f'class="grafo-etichetta-piccola">{escape(profile.source.domain)}</text>'
    )

    for i, entry in enumerate(owners):
        y = 10 + i * (row_h + gap)
        parts.append(_box(10, y, box_w, row_h, "grafo-nodo"))
        nome = escape(entry.owner.name)
        tipo = escape(entry.owner.type)
        parts.append(
            f'<text x="{10 + box_w / 2}" y="{y + 24}" text-anchor="middle" '
            f'class="grafo-etichetta">{nome}</text>'
        )
        marker = " · carica politica" if entry.owner.political_offices else ""
        parts.append(
            f'<text x="{10 + box_w / 2}" y="{y + 44}" text-anchor="middle" '
            f'class="grafo-etichetta-piccola">{tipo}{escape(marker)}</text>'
        )
        # Arco proprietario -> testata.
        x1 = 10 + box_w
        y1 = y + row_h // 2
        x2 = sx
        y2 = source_y + row_h // 2
        mid_x = (x1 + x2) / 2
        parts.append(
            f'<path d="M {x1} {y1} C {mid_x} {y1}, {mid_x} {y2}, {x2} {y2}" '
            f'class="grafo-arco" fill="none" />'
        )
        share = entry.ownership.share_pct
        label = f"{share:g}%" if share is not None else "quota n.d."
        parts.append(
            f'<text x="{mid_x}" y="{(y1 + y2) / 2 - 6}" text-anchor="middle" '
            f'class="grafo-etichetta-piccola">{escape(label)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def coverage_bar_svg(
    by_group: dict[str, int], *, label: str, width: int = 360
) -> str:
    """Barra di copertura proporzionale (per paese o per fascia)."""
    total = sum(by_group.values())
    if total == 0:
        return '<p class="dato-mancante">dato non disponibile</p>'
    height = 44
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" class="barra-copertura" '
        f'aria-label="{escape(label)}">'
    ]
    x = 0.0
    classi = ["cop-a", "cop-b", "cop-c", "cop-d", "cop-e", "cop-f"]
    ordered = sorted(by_group.items(), key=lambda kv: kv[1], reverse=True)
    for i, (group, count) in enumerate(ordered):
        w = width * count / total
        cls = classi[i % len(classi)]
        parts.append(
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="18" class="{cls}" />'
        )
        if w > 28:
            parts.append(
                f'<text x="{x + w / 2:.1f}" y="34" text-anchor="middle" '
                f'class="grafo-etichetta-piccola">{escape(group)} ({count})</text>'
            )
        x += w
    parts.append("</svg>")
    return "".join(parts)

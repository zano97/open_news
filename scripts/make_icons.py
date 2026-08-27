"""Genera logo e icone di Open News (uso per sviluppatori, output nel repo).

Il logo è un emblema da testata d'epoca: monogramma «ON» in Playfair Display
(il font display del giornale, convertito in tracciati vettoriali), cornice a
doppio filetto e fregi tipografici, nei colori della carta e dell'inchiostro
dell'interfaccia. Output in apps/web/static/icons/:

- opennews.svg                  logo vettoriale (testo in tracciati: nessuna
                                dipendenza dai font di sistema)
- opennews-{16..512}.png        raster per .desktop, apple-touch, ecc.
- favicon.ico                   multi-dimensione per i browser
- opennews.icns                 per il bundle .app su macOS

Dipendenze (solo per rigenerare): pillow, icnsutil, fonttools, playwright.
"""

from io import BytesIO
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "apps/web/static/fonts/PlayfairDisplay-Variable.ttf"
OUT = ROOT / "apps/web/static/icons"

CARTA = "#f4ecd8"
INCHIOSTRO = "#221c14"
BRUNO = "#6b4a2b"
BRUNO_SCURO = "#4a3118"


def glyph_path(font: TTFont, char: str) -> tuple[str, float]:
    """Tracciato SVG (coordinate font, y in giù) e advance width del glifo."""
    cmap = font.getBestCmap()
    glyph_name = cmap[ord(char)]
    glyph_set = font.getGlyphSet()
    pen = SVGPathPen(glyph_set)
    # Il sistema di coordinate dei font ha la y verso l'alto: ribaltiamo.
    glyph_set[glyph_name].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
    return pen.getCommands(), glyph_set[glyph_name].width


def build_svg() -> str:
    font = TTFont(FONT)
    instantiateVariableFont(font, {"wght": 800}, inplace=True)
    upm = font["head"].unitsPerEm
    path_o, adv_o = glyph_path(font, "O")
    path_n, adv_n = glyph_path(font, "N")
    cap_height = font["OS/2"].sCapHeight or int(upm * 0.7)

    # Monogramma: "ON" centrato tra i fregi, dentro la cornice interna.
    spazio = upm * 0.02
    largh_font = adv_o + spazio + adv_n
    scala = min(190 / cap_height, 296 / largh_font)
    largh = largh_font * scala
    x0 = (512 - largh) / 2
    y_base = 256 + (cap_height * scala) / 2  # baseline: centro ottico verticale

    fregio = (
        '<g stroke="{c}" stroke-width="7" fill="none">'
        '<line x1="118" y1="{y}" x2="222" y2="{y}"/>'
        '<line x1="290" y1="{y}" x2="394" y2="{y}"/>'
        "</g>"
        '<path d="M256 {yr} l 13 13 -13 13 -13 -13 Z" fill="{c}"/>'
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <title>Open News</title>
  <!-- Carta -->
  <rect x="0" y="0" width="512" height="512" rx="92" fill="{CARTA}"/>
  <!-- Cornice a doppio filetto -->
  <rect x="26" y="26" width="460" height="460" rx="70" fill="none"
        stroke="{BRUNO_SCURO}" stroke-width="14"/>
  <rect x="52" y="52" width="408" height="408" rx="50" fill="none"
        stroke="{BRUNO}" stroke-width="5"/>
  <!-- Fregi tipografici -->
  {fregio.format(c=BRUNO, y=118, yr=105)}
  {fregio.format(c=BRUNO, y=394, yr=381)}
  <!-- Monogramma ON (Playfair Display 800, in tracciati) -->
  <g fill="{INCHIOSTRO}" transform="translate({x0:.1f} {y_base:.1f}) scale({scala:.6f})">
    <path d="{path_o}"/>
    <path transform="translate({adv_o + spazio:.1f} 0)" d="{path_n}"/>
  </g>
</svg>
'''


def render_pngs(svg: str) -> None:
    from PIL import Image
    from playwright.sync_api import sync_playwright

    html = f"<!doctype html><body style='margin:0'>{svg}</body>"
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page(viewport={"width": 1024, "height": 1024})
        page.set_content(html.replace('viewBox="0 0 512 512"',
                                      'viewBox="0 0 512 512" width="1024" height="1024"'))
        buf = page.locator("svg").screenshot(omit_background=True)
        browser.close()

    master = Image.open(BytesIO(buf)).convert("RGBA")
    for size in (512, 256, 180, 128, 64, 48, 32, 16):
        master.resize((size, size), Image.LANCZOS).save(OUT / f"opennews-{size}.png")

    # favicon.ico multi-dimensione
    Image.open(OUT / "opennews-48.png").save(
        OUT / "favicon.ico",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[Image.open(OUT / "opennews-16.png"),
                       Image.open(OUT / "opennews-32.png")],
    )


def build_icns() -> None:
    import icnsutil

    icns = icnsutil.IcnsFile()
    tipi = {16: "icp4", 32: "icp5", 64: "icp6", 128: "ic07", 256: "ic08", 512: "ic09"}
    for size, chiave in tipi.items():
        icns.add_media(chiave, file=str(OUT / f"opennews-{size}.png"))
    icns.write(str(OUT / "opennews.icns"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    svg = build_svg()
    (OUT / "opennews.svg").write_text(svg, encoding="utf-8")
    render_pngs(svg)
    build_icns()
    print(f"icone scritte in {OUT}")


if __name__ == "__main__":
    main()

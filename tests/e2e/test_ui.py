"""E2E Playwright: il giornale funziona davvero nel browser, desktop e mobile."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_prima_pagina_desktop(page: Page, base_url: str) -> None:
    page.goto(base_url + "/")
    expect(page.locator(".masthead-titolo")).to_contain_text("OPEN NEWS")
    expect(page.locator(".masthead-nav a", has_text="Edizione lampo")).to_be_visible()
    expect(page.locator(".masthead-edizione")).to_contain_text("Edizione n.")
    # La story di apertura mostra le versioni delle testate.
    expect(page.locator(".story-apertura .story-versioni li").first).to_be_visible()


def test_edizione_notturna(page: Page, base_url: str) -> None:
    page.goto(base_url + "/")
    html = page.locator("html")
    page.get_by_role("button", name="Passa all'edizione notturna").click()
    expect(html).to_have_attribute("data-theme", "notte")
    page.reload()
    expect(html).to_have_attribute("data-theme", "notte")  # persistita
    page.get_by_role("button", name="Passa all'edizione diurna").click()
    expect(html).to_have_attribute("data-theme", "giorno")


def test_pagina_storia_dal_giornale(page: Page, base_url: str) -> None:
    page.goto(base_url + "/")
    page.locator(".story-apertura .story-titolo a").click()
    expect(page.locator(".storia-titolo")).to_be_visible()
    expect(page.locator(".versione-card")).to_have_count(5)
    expect(page.get_by_text("Chi l'ha pubblicata per prima")).to_be_visible()
    expect(page.get_by_text("Da dove vengono questi dati?")).to_be_visible()


def test_reel_lampo_scroll_e_tastiera(page: Page, base_url: str) -> None:
    page.goto(base_url + "/lampo")
    schede = page.locator(".reel-scheda")
    expect(schede).to_have_count(2)
    expect(schede.first).to_contain_text("Coperta da")
    expect(schede.first.get_by_text("Leggi le fonti")).to_be_visible()
    # La rotella scorre la pagina (regressione: niente riquadri annidati).
    page.mouse.wheel(0, 800)
    page.wait_for_function("window.scrollY > 100")
    # Navigazione da tastiera (miglioramento progressivo).
    prima = page.evaluate("window.scrollY")
    page.keyboard.press("ArrowDown")
    page.wait_for_function("prev => window.scrollY > prev", arg=prima)


def test_scheda_fonte_e_ansa_disabilitata(page: Page, base_url: str) -> None:
    page.goto(base_url + "/fonti")
    expect(page.get_by_role("link", name="la Repubblica")).to_be_visible()
    page.goto(base_url + "/fonte/ansa")
    expect(page.get_by_text("Fonte disabilitata.")).to_be_visible()
    expect(page.get_by_text("solo uso personale", exact=False).first).to_be_visible()


def test_mobile(page: Page, base_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url + "/")
    expect(page.locator(".masthead-titolo")).to_be_visible()
    page.goto(base_url + "/lampo")
    expect(page.locator(".reel-scheda").first).to_be_visible()


def test_accessibilita_di_base(page: Page, base_url: str) -> None:
    page.goto(base_url + "/")
    assert page.locator("html").get_attribute("lang") == "it"
    # Il link "salta al contenuto" diventa visibile al primo Tab.
    page.keyboard.press("Tab")
    expect(page.locator(".salta")).to_be_focused()
    # Tutte le immagini hanno l'attributo alt (anche vuoto, se decorative).
    senza_alt = page.eval_on_selector_all(
        "img", "imgs => imgs.filter(i => i.getAttribute('alt') === null).length"
    )
    assert senza_alt == 0

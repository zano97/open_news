"""Multilingua: cataloghi completi e coerenti, negoziazione, pagine tradotte."""

import re

from httpx import AsyncClient

from core.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    catalog,
    normalize_locale,
    resolve_locale,
    translate,
)

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class TestCataloghi:
    def test_lingue_supportate(self) -> None:
        assert SUPPORTED_LOCALES == ("it", "en", "fr", "de", "es")
        assert DEFAULT_LOCALE == "it"

    def test_stesse_chiavi_in_tutte_le_lingue(self) -> None:
        riferimento = set(catalog("it"))
        assert riferimento, "il catalogo italiano deve esistere"
        for locale in SUPPORTED_LOCALES[1:]:
            chiavi = set(catalog(locale))
            assert chiavi == riferimento, (
                f"{locale}: mancanti={riferimento - chiavi}, extra={chiavi - riferimento}"
            )

    def test_stessi_segnaposto_in_tutte_le_lingue(self) -> None:
        """Un {segnaposto} perso in traduzione romperebbe il format a runtime."""
        it = catalog("it")
        for locale in SUPPORTED_LOCALES[1:]:
            other = catalog(locale)
            for key, value in it.items():
                attesi = set(_PLACEHOLDER_RE.findall(value))
                trovati = set(_PLACEHOLDER_RE.findall(other[key]))
                assert attesi == trovati, f"{locale}:{key}: {attesi} != {trovati}"

    def test_html_conservato(self) -> None:
        """Le voci con markup devono conservare i tag in ogni lingua."""
        it = catalog("it")
        for locale in SUPPORTED_LOCALES[1:]:
            other = catalog(locale)
            for key, value in it.items():
                assert ("<a " in value) == ("<a " in other[key]), f"{locale}:{key}"


class TestNegoziazione:
    def test_priorita_query_poi_cookie(self) -> None:
        assert resolve_locale("en", "fr") == "en"
        assert resolve_locale(None, "fr") == "fr"
        assert resolve_locale(None, None) == "it"

    def test_valori_invalidi_ignorati(self) -> None:
        assert resolve_locale("xx", "yy") == "it"
        assert normalize_locale("EN-us") == "en"
        assert normalize_locale("") is None

    def test_fallback_traduzione(self) -> None:
        assert translate("it", "nav.prima_pagina") == "Prima pagina"
        assert translate("en", "nav.prima_pagina") == "Front page"
        # Chiave inesistente: torna la chiave, mai una pagina rotta.
        assert translate("de", "chiave.inventata") == "chiave.inventata"


async def test_homepage_in_inglese(client: AsyncClient) -> None:
    resp = await client.get("/?lang=en")
    assert resp.status_code == 200
    assert "Front page" in resp.text
    assert "Prima pagina" not in resp.text
    assert "Who pays for the news" in resp.text


async def test_default_resta_italiano(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert "Prima pagina" in resp.text
    assert "Front page" not in resp.text


async def test_cambio_lingua_con_cookie(client: AsyncClient) -> None:
    resp = await client.get("/lingua/fr?next=/fonti", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/fonti"
    client.cookies.update(resp.cookies)

    fonti = await client.get("/fonti")
    assert translate("fr", "fonti.titolo") in fonti.text

    # Guardia anti open-redirect.
    esterno = await client.get(
        "/lingua/en?next=//evil.example.com", follow_redirects=False
    )
    assert esterno.headers["location"] == "/"

    sconosciuta = await client.get("/lingua/xx", follow_redirects=False)
    assert sconosciuta.status_code == 404


async def test_tutte_le_lingue_rendono_la_homepage(client: AsyncClient) -> None:
    for locale in SUPPORTED_LOCALES:
        resp = await client.get(f"/?lang={locale}")
        assert resp.status_code == 200
        assert translate(locale, "nav.lampo") in resp.text


async def test_metodo_fallback_inglese(client: AsyncClient) -> None:
    # Il documento lungo esiste in it/en: il tedesco riceve l'inglese con nota.
    resp = await client.get("/metodo?lang=de")
    assert resp.status_code == 200
    assert "How we compute it" in resp.text
    assert translate("de", "metodo.fallback", lingua="Deutsch") in resp.text

    inglese = await client.get("/metodo?lang=en")
    assert "How we compute it" in inglese.text
    assert 'id="agenda"' in inglese.text
    assert 'id="livello4"' in inglese.text

    italiano = await client.get("/metodo")
    assert "quattro livelli" in italiano.text


async def test_date_localizzate(client: AsyncClient) -> None:
    from datetime import UTC, datetime

    from apps.api.templating import data_in_lettere

    dt = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)  # giovedì
    assert data_in_lettere(dt, "it") == "Giovedì 27 agosto 2026"
    assert data_in_lettere(dt, "en") == "Thursday, August 27, 2026"
    assert data_in_lettere(dt, "de") == "Donnerstag, 27. August 2026"
    assert data_in_lettere(dt, "fr") == "Jeudi 27 août 2026"
    assert data_in_lettere(dt, "es") == "Jueves 27 agosto 2026"


def test_lingue_usate_hanno_priorita() -> None:
    """Il job di traduzione serve prima le lingue davvero guardate."""
    from core import i18n

    i18n._LOCALE_USES.clear()
    try:
        # Nessun uso registrato: ordine di default (italiano per primo).
        assert i18n.locales_by_priority() == i18n.SUPPORTED_LOCALES
        i18n.note_locale_use("de")
        i18n.note_locale_use("es")
        prime = i18n.locales_by_priority()[:2]
        assert prime == ("es", "de")  # le usate, dalla più recente
        assert set(i18n.locales_by_priority()) == set(i18n.SUPPORTED_LOCALES)
        i18n.note_locale_use("xx")  # lingua ignota: ignorata
        assert "xx" not in i18n.locales_by_priority()
    finally:
        i18n._LOCALE_USES.clear()

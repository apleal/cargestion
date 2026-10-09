"""Limpieza de APP_TOKEN y APP_URL pegados a mano en EasyPanel."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper_auto1"))

import pytest  # noqa: E402
from ajustes import limpiar_token, limpiar_url  # noqa: E402

TOKEN = "91a06749139fe8b30936c2a0789bc882e0060666"


@pytest.mark.parametrize(
    "pegado",
    [
        TOKEN,
        f"Token {TOKEN}",
        f"token {TOKEN}",
        f"  {TOKEN}  ",
        f'"{TOKEN}"',
        f"'{TOKEN}'",
        f'"Token {TOKEN}"',
        f"{TOKEN}\n",
    ],
)
def test_limpiar_token_deja_solo_el_token(pegado):
    assert limpiar_token(pegado) == TOKEN


def test_limpiar_token_vacio():
    assert limpiar_token("") == ""
    assert limpiar_token(None) == ""


@pytest.mark.parametrize(
    "pegado",
    [
        "https://autogestion-appautogestion.xnpd6m.easypanel.host",
        "https://autogestion-appautogestion.xnpd6m.easypanel.host/",
        ' "https://autogestion-appautogestion.xnpd6m.easypanel.host/" ',
    ],
)
def test_limpiar_url_quita_comillas_espacios_y_barra_final(pegado):
    assert limpiar_url(pegado) == "https://autogestion-appautogestion.xnpd6m.easypanel.host"


@pytest.mark.parametrize(
    "pegado",
    [f"({TOKEN})", f"[{TOKEN}]", f"<{TOKEN}>", f"{{{TOKEN}}}", f'("Token {TOKEN}")', f" ( {TOKEN} ) "],
)
def test_limpiar_token_quita_parentesis_y_otros_envoltorios(pegado):
    # el ejemplo «(tu token)» dejaba 42 caracteres y la app lo rechazaba
    assert len(f"({TOKEN})") == 42
    assert limpiar_token(pegado) == TOKEN


def test_limpiar_texto_para_email_y_telegram():
    from ajustes import limpiar_texto

    assert limpiar_texto("(administracion@garageclub.es)") == "administracion@garageclub.es"
    assert limpiar_texto(' "1413275357" ') == "1413275357"
    assert limpiar_texto("") == ""


def test_caracteres_raros_explica_un_token_mal_pegado_sin_enseñarlo():
    from ajustes import caracteres_raros

    assert caracteres_raros(TOKEN) == ""
    assert caracteres_raros(f"({TOKEN})") == "'(' ')'"

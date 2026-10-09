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

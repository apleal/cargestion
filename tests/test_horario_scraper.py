"""Cuándo toca la pasada diaria del servicio de seguimiento (08:30)."""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper_auto1"))

from horario import parse_hora, toca_pasada_programada  # noqa: E402

HORA = parse_hora("08:30")
HOY = date(2026, 10, 8)
AYER = date(2026, 10, 7)


def test_parse_hora():
    assert (HORA.hour, HORA.minute) == (8, 30)


def test_antes_de_la_hora_no_toca():
    assert not toca_pasada_programada(datetime(2026, 10, 8, 8, 29), HORA, AYER, None)


def test_a_partir_de_la_hora_toca_si_no_hay_pasada_de_hoy():
    assert toca_pasada_programada(datetime(2026, 10, 8, 8, 30), HORA, AYER, None)
    assert toca_pasada_programada(datetime(2026, 10, 8, 8, 30), HORA, None, None)


def test_si_ya_hay_pasada_de_hoy_no_se_repite():
    assert not toca_pasada_programada(datetime(2026, 10, 8, 9, 0), HORA, HOY, None)


def test_si_el_servicio_arranca_tarde_la_recupera_una_vez():
    ahora = datetime(2026, 10, 8, 10, 0)
    assert toca_pasada_programada(ahora, HORA, AYER, None)
    assert not toca_pasada_programada(ahora, HORA, AYER, HOY)  # ya intentada hoy


def test_si_la_pasada_falla_no_se_reintenta_en_bucle():
    assert not toca_pasada_programada(datetime(2026, 10, 8, 12, 0), HORA, AYER, HOY)


def test_al_dia_siguiente_vuelve_a_tocar():
    assert toca_pasada_programada(datetime(2026, 10, 9, 8, 31), HORA, HOY, HOY)

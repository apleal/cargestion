"""Cuándo toca la pasada diaria (lógica pura, sin dependencias, testeable)."""
from __future__ import annotations

from datetime import date, datetime, time


def parse_hora(texto: str) -> time:
    """"08:30" -> time(8, 30). Lanza ValueError si el formato no vale."""
    h, m = texto.strip().split(":")
    return time(int(h), int(m))


def toca_pasada_programada(
    ahora: datetime,
    hora: time,
    ultima_pasada: date | None,
    intentada: date | None,
) -> bool:
    """¿Toca la pasada diaria ahora?

    Sí si ya ha pasado la hora de hoy y todavía no hay una pasada de hoy
    (``ultima_pasada``, según la app) ni este proceso la ha intentado ya
    (``intentada``). Así, si el servicio se reinicia a las 10:00 sin pasada
    hecha, la recupera una vez; y si la pasada falla, no se reintenta en
    bucle: el Panel ya lo avisa y queda el botón manual.
    """
    hoy = ahora.date()
    return ahora.time() >= hora and ultima_pasada != hoy and intentada != hoy

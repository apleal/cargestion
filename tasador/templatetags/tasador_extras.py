"""Formato de números en castellano: miles con punto, sin espacios."""
from __future__ import annotations

from django import template

register = template.Library()


def _entero(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


@register.filter
def miles(value) -> str:
    """39558 -> "39.558". Vacío si no es número."""
    n = _entero(value)
    return "" if n is None else f"{n:,}".replace(",", ".")


@register.filter
def eur(value) -> str:
    """13648 -> "13.648 €". "—" si no es número."""
    n = _entero(value)
    return "—" if n is None else f"{n:,}".replace(",", ".") + " €"


@register.filter
def pct(value, dec=1) -> str:
    """0.153 -> "15,3 %"."""
    try:
        return f"{float(value) * 100:.{int(dec)}f}".replace(".", ",") + " %"
    except (TypeError, ValueError):
        return "—"

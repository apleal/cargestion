"""Limpieza de los valores de configuración que se pegan a mano en EasyPanel
(lógica pura, sin dependencias, testeable)."""
from __future__ import annotations


def _sin_comillas(texto: str) -> str:
    texto = texto.strip()
    while len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "\"'":
        texto = texto[1:-1].strip()
    return texto


def limpiar_token(valor: str) -> str:
    """Deja solo el token: sin comillas, sin espacios y sin la palabra «Token»
    delante (el servicio ya la añade en la cabecera)."""
    valor = _sin_comillas(valor or "")
    if valor.lower().startswith("token "):
        valor = valor[6:].strip()
    return _sin_comillas(valor)


def limpiar_url(valor: str) -> str:
    """Dirección de la app sin comillas, espacios ni barra final."""
    return _sin_comillas(valor or "").rstrip("/")

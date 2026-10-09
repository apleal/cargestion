"""Limpieza de los valores de configuración que se pegan a mano en EasyPanel
(lógica pura, sin dependencias, testeable)."""
from __future__ import annotations

_ENVOLTORIOS = {'"': '"', "'": "'", "(": ")", "[": "]", "<": ">", "{": "}"}


def _sin_envoltorios(texto: str) -> str:
    """Quita espacios y los pares de comillas/paréntesis/corchetes que rodean
    el valor (típico al sustituir un ejemplo como «(tu token)»)."""
    texto = texto.strip()
    while len(texto) >= 2 and _ENVOLTORIOS.get(texto[0]) == texto[-1]:
        texto = texto[1:-1].strip()
    return texto


def limpiar_texto(valor: str) -> str:
    """Para valores sin espacios internos (email, token del bot, id de chat)."""
    return _sin_envoltorios(valor or "")


def limpiar_token(valor: str) -> str:
    """Deja solo el token: sin envoltorios y sin la palabra «Token» delante
    (el servicio ya la añade en la cabecera)."""
    valor = _sin_envoltorios(valor or "")
    if valor.lower().startswith("token "):
        valor = valor[6:]
    return _sin_envoltorios(valor)


def limpiar_url(valor: str) -> str:
    """Dirección de la app sin envoltorios, espacios ni barra final."""
    return _sin_envoltorios(valor or "").rstrip("/")


def caracteres_raros(token: str) -> str:
    """Caracteres de un token que no pueden estar en uno válido (hexadecimal),
    para explicar un 401 sin enseñar el token."""
    raros = sorted({c for c in token if c.lower() not in "0123456789abcdef"})
    return " ".join(repr(c) for c in raros)

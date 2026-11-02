"""Lector de listados de Auto1 (Oportunidades).

Dos partes:

- ``parsear_tarjetas(html)`` y ``filtrar(...)``: puras (sin navegador), se
  prueban con el HTML real de las tarjetas.
- ``leer_listado(driver, url, ...)``: abre el listado con la sesión ya iniciada,
  recorre las páginas (parámetro ``page=``) y devuelve las tarjetas.

El precio se localiza por los ``data-qa-id`` de Auto1 (estables), no por las
clases ofuscadas (``BK_Kxc6…``), que cambian con cada despliegue de su web.

Lo que trae la tarjeta del listado: nombre, referencia, km, 1ª matriculación,
potencia, combustible, cambio, ubicación y UN precio según el estado del coche:

    subasta     «Puja mínima» (naranja de siempre)
    particular  «Puja mínima» + «Expectativa del cliente» (verde)
    compra_ya   «Compra ahora», precio fijo fuera de subasta

La tarjeta NO trae la tarifa ni el IVA: esos solo salen en la ficha.
"""
from __future__ import annotations

import html as _html
import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

AUTO1_ORIGEN = "https://www.auto1.com"

_INICIO_TARJETA = re.compile(r'<div\b[^>]*\bclass="[^"]*\bbig-car-card__container(?![\w-])')
_INICIO_TITULO = re.compile(r'<a\b[^>]*data-qa-id="car-card-title"')
_TAG = re.compile(r"<[^>]+>")
_FILA_SPEC = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S)
_NUMERO_EUROS = re.compile(r"(\d[\d.]*)\s*€")


def _texto(fragmento: str) -> str:
    t = _html.unescape(_TAG.sub(" ", fragmento)).replace("\xa0", " ")
    return " ".join(t.split())


def _entero(texto: str | None) -> int | None:
    digitos = re.sub(r"\D", "", texto or "")
    return int(digitos) if digitos else None


def _precio_tras(chunk: str, qa_id: str) -> int | None:
    """Importe (€) que viene justo después de un data-qa-id."""
    i = chunk.find(f'data-qa-id="{qa_id}"')
    if i < 0:
        return None
    m = _NUMERO_EUROS.search(_texto(chunk[i : i + 600]))
    return _entero(m.group(1)) if m else None


def _normalizar_cambio(texto: str) -> str:
    t = texto.lower()
    if "autom" in t:
        return "automatico"
    if "manual" in t:
        return "manual"
    return ""


def _trocear(html: str) -> list[str]:
    for patron in (_INICIO_TARJETA, _INICIO_TITULO):
        inicios = [m.start() for m in patron.finditer(html)]
        if inicios:
            return [html[a:b] for a, b in zip(inicios, inicios[1:] + [len(html)])]
    return []


def _limpiar_url(href: str) -> str:
    ruta = urlparse(_html.unescape(href)).path
    return AUTO1_ORIGEN + ruta if ruta.startswith("/") else ruta


def parsear_tarjeta(chunk: str) -> dict | None:
    m = _INICIO_TITULO.search(chunk)
    if not m:
        return None
    etiqueta = chunk[m.start() : chunk.find(">", m.start()) + 1]
    href = re.search(r'href="([^"]+)"', etiqueta)
    fin = chunk.find("</a>", m.start())
    nombre = _texto(chunk[chunk.find(">", m.start()) + 1 : fin])

    specs = {
        _texto(k).rstrip(":").lower(): _texto(v) for k, v in _FILA_SPEC.findall(chunk)
    }

    def spec(*claves):
        for clave in claves:
            for k, v in specs.items():
                if clave in k:
                    return v
        return ""

    url = _limpiar_url(href.group(1)) if href else ""
    referencia = spec("referencia") or (url.rsplit("/", 1)[-1] if url else "")
    matric = re.search(r"(\d{1,2})\s*/\s*(\d{4})", spec("matricul"))
    cv = re.search(r"(\d+)\s*CV", spec("potencia"), re.I)
    kw = re.search(r"(\d+)\s*KW", spec("potencia"), re.I)

    puja_minima = _precio_tras(chunk, "bigSearchCard__status--minimumBidValue")
    precio_ya = _precio_tras(chunk, "bigSearchCard__status--IPPrice")
    expectativa = _precio_tras(chunk, "bigSearchCard__status--expectationValue")
    if expectativa is not None and puja_minima is not None:
        tipo, precio = "particular", puja_minima
    elif puja_minima is not None:
        tipo, precio = "subasta", puja_minima
    elif precio_ya is not None:
        tipo, precio = "compra_ya", precio_ya
    else:
        tipo, precio = "", None

    return {
        "referencia": referencia,
        "nombre": nombre,
        "url": url,
        "tipo": tipo,
        "precio": precio,
        "expectativa": expectativa,
        "km": _entero(spec("cuentakil", "km")),
        "mes": int(matric.group(1)) if matric else None,
        "anio": int(matric.group(2)) if matric else None,
        "cv": int(cv.group(1)) if cv else None,
        "kw": int(kw.group(1)) if kw else None,
        "combustible": spec("combustible"),
        "cambio": _normalizar_cambio(spec("caja de cambios", "cambio")),
        "ubicacion": spec("ubicaci"),
    }


def parsear_tarjetas(html: str) -> list[dict]:
    """Todas las tarjetas de coche de una página de listado, sin repetidos."""
    vistos: set[str] = set()
    salida = []
    for chunk in _trocear(html):
        d = parsear_tarjeta(chunk)
        if d and d["referencia"] and d["referencia"] not in vistos:
            vistos.add(d["referencia"])
            salida.append(d)
    return salida


def filtrar(tarjetas: list[dict], busqueda: dict) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Separa las tarjetas que encajan con la búsqueda de las que no (con el motivo).

    ``busqueda`` trae: km_min, km_max, potencia_cv, tolerancia_cv, cambio,
    palabras_titulo. Lo que la tarjeta no informa (p. ej. sin CV) no descarta:
    solo se descarta con un dato que contradice.
    """
    palabras = [p.lower() for p in (busqueda.get("palabras_titulo") or "").split() if p]
    cv_ref = busqueda.get("potencia_cv")
    tol_cv = busqueda.get("tolerancia_cv") or 0
    cambio = busqueda.get("cambio") or ""
    km_min, km_max = busqueda.get("km_min"), busqueda.get("km_max")

    aceptadas, descartadas = [], []
    for t in tarjetas:
        motivo = ""
        if t["precio"] is None:
            motivo = "sin precio en la tarjeta"
        elif t["km"] is None and (km_min is not None or km_max is not None):
            motivo = "sin km"
        elif t["km"] is not None and km_min is not None and t["km"] < km_min:
            motivo = f"km por debajo ({t['km']})"
        elif t["km"] is not None and km_max is not None and t["km"] > km_max:
            motivo = f"km por encima ({t['km']})"
        elif cv_ref and t["cv"] is not None and abs(t["cv"] - cv_ref) > tol_cv:
            motivo = f"potencia distinta ({t['cv']} CV)"
        elif cambio and t["cambio"] and t["cambio"] != cambio:
            motivo = f"cambio distinto ({t['cambio']})"
        elif palabras and not all(p in t["nombre"].lower() for p in palabras):
            motivo = "el título no lleva las palabras pedidas"
        (descartadas.append((t, motivo)) if motivo else aceptadas.append(t))
    return aceptadas, descartadas


def url_pagina(url: str, pagina: int) -> str:
    """La misma URL del listado, con ``page=<pagina>``."""
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "page"]
    q.append(("page", str(pagina)))
    return urlunparse(p._replace(query=urlencode(q)))


JS_BAJAR = "window.scrollTo(0, document.body.scrollHeight);"


def _ahora() -> float:
    return time.monotonic()


def _dormir(segundos: float) -> None:
    time.sleep(segundos)


def _esperar_tarjetas(driver, segundos: float, sin_tarjetas: float | None = None) -> str:
    """Espera a que haya tarjetas y a que dejen de aparecer (carga perezosa).

    ``sin_tarjetas``: si pasado ese tiempo no hay ni una tarjeta se da la página
    por vacía (p. ej. la página siguiente a la última), en vez de esperar todo
    ``segundos``."""
    inicio = _ahora()
    fin = inicio + segundos
    ultimo, estable = -1, 0
    html = ""
    while _ahora() < fin:
        try:
            driver.execute_script(JS_BAJAR)
            html = driver.page_source
        except Exception:
            _dormir(0.5)
            continue
        n = len(_trocear(html))
        if n and n == ultimo:
            estable += 1
            if estable >= 2:
                return html
        else:
            estable = 0
        if n == 0 and sin_tarjetas is not None and _ahora() - inicio >= sin_tarjetas:
            return html
        ultimo = n
        _dormir(0.8)
    return html


def leer_listado(driver, url: str, max_paginas: int = 15, pausa: float = 3.0, log=print) -> dict:
    """Recorre las páginas del listado (con la sesión ya iniciada).

    Devuelve {"tarjetas": [...], "paginas": N, "aviso": "" | texto}. Se para al
    llegar a una página sin tarjetas nuevas o al límite de páginas.
    """
    todas: dict[str, dict] = {}
    paginas = 0
    aviso = ""
    for n in range(1, max_paginas + 1):
        driver.get(url_pagina(url, n))
        # la 1ª página puede tardar en cargar; una página posterior sin coches es solo «no hay más»
        html = _esperar_tarjetas(driver, 25, sin_tarjetas=None if n == 1 else 6)
        tarjetas = parsear_tarjetas(html)
        if not tarjetas:
            if "signin" in driver.current_url:
                raise RuntimeError("Se ha caído la sesión de Auto1 (pide iniciar sesión otra vez).")
            if n == 1:
                aviso = "La primera página no tiene ninguna tarjeta reconocible (¿filtros sin resultados o ha cambiado la web?)."
            break
        nuevas = [t for t in tarjetas if t["referencia"] not in todas]
        log(f"  página {n}: {len(tarjetas)} coches ({len(nuevas)} nuevos)")
        paginas += 1
        if not nuevas:
            break
        for t in nuevas:
            todas[t["referencia"]] = t
        _dormir(pausa)
    else:
        aviso = f"Se ha parado en el límite de {max_paginas} páginas: puede haber más coches sin leer."
    return {"tarjetas": list(todas.values()), "paginas": paginas, "aviso": aviso}

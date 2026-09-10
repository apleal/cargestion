"""Parser del texto que genera la extensión de Chrome para BCA.

La extensión copia 6 campos separados por tabulador:

    lote \\t modelo \\t ficha \\t matrícula \\t fecha matriculación \\t ubicación

Ejemplo real (con tabuladores; aquí se muestran como ·):
    3 · Citroën C1 C1 1.0 VTI FEEL 72 · 53 KW (72 CV), Gasolina, Manual, 79328 Km, 2019 · 9553LDF · 17/12/2019 · BCA Madrid

Diseñado para ser tolerante y admitir más formatos en el futuro.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_FICHA = re.compile(
    r"(?P<kw>\d+)\s*KW\s*\(\s*(?P<cv>\d+)\s*CV\s*\)\s*,\s*"
    r"(?P<combustible>[^,]+?)\s*,\s*"
    r"(?P<cambio>[^,]+?)\s*,\s*"
    r"(?P<km>[\d.\s]+)\s*Km\s*,\s*"
    r"(?P<anio>\d{4})",
    re.IGNORECASE,
)
_FECHA = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

_COMBUSTIBLE = {
    "gasolina": "gasolina",
    "diesel": "diesel",
    "diésel": "diesel",
    "hev petrol": "hibrido",
    "mhev petrol": "hibrido",
    "hev diesel": "hibrido",
    "mhev diesel": "hibrido",
    "phev petrol": "phev",
    "eléctrico": "electrico",
    "electrico": "electrico",
}
_CAMBIO = {
    "manual": "manual",
    "automático": "automatico",
    "automatico": "automatico",
    "secuencial": "automatico",
    "cvt": "automatico",
    "doble embrague": "automatico",
}


@dataclass
class LoteParseado:
    texto_original: str
    formato: str = "bca"
    lote: str = ""
    lote_num: int | None = None
    referencia: str = ""  # Auto1: código de referencia del anuncio
    precio_subasta: int | None = None  # Auto1: puja mínima actual
    iva_anuncio: str = ""  # Auto1: tarifa (IVA del anuncio)
    marca: str = ""
    modelo: str = ""
    version: str = ""
    potencia_kw: int | None = None
    potencia_cv: int | None = None
    combustible: str = ""
    cambio: str = ""
    kilometros: int | None = None
    anio: int | None = None
    matricula: str = ""
    fecha_matriculacion: str = ""
    ubicacion: str = ""
    zona_origen: str = ""
    dudosos: list[str] = field(default_factory=list)
    no_reconocidos: list[str] = field(default_factory=list)


def _num(texto: str) -> int | None:
    digitos = re.sub(r"[^\d]", "", texto or "")
    return int(digitos) if digitos else None


def parsear_linea(linea: str) -> LoteParseado:
    r = LoteParseado(texto_original=linea)
    partes = [p.strip() for p in linea.split("\t")]
    if len(partes) < 4:
        # sin tabuladores: intento por espacios múltiples
        partes = [p.strip() for p in re.split(r"\s{2,}|\t", linea) if p.strip()]

    campos = ["lote", "modelo_completo", "ficha", "matricula", "fecha", "ubicacion"]
    datos = dict(zip(campos, partes))

    r.lote = datos.get("lote", "").strip()
    if not r.lote or not re.match(r"^[\w-]+$", r.lote):
        r.dudosos.append("lote")
    m_lote = re.search(r"\d+", r.lote)
    if m_lote:
        r.lote_num = int(m_lote.group())

    modelo_completo = datos.get("modelo_completo", "").strip()
    if modelo_completo:
        trozos = modelo_completo.split()
        r.marca = trozos[0]
        r.modelo = trozos[1] if len(trozos) > 1 else ""
        r.version = " ".join(trozos[2:])
        if len(trozos) < 2:
            r.dudosos.append("modelo")
    else:
        r.dudosos.append("modelo")

    ficha = datos.get("ficha", "")
    m = _FICHA.search(ficha)
    if m:
        r.potencia_kw = _num(m.group("kw"))
        r.potencia_cv = _num(m.group("cv"))
        r.kilometros = _num(m.group("km"))
        r.anio = _num(m.group("anio"))
        comb = m.group("combustible").strip().lower()
        r.combustible = _COMBUSTIBLE.get(comb, "")
        if not r.combustible:
            r.no_reconocidos.append(f"combustible: {comb}")
        camb = m.group("cambio").strip().lower()
        r.cambio = _CAMBIO.get(camb, "")
        if not r.cambio:
            r.no_reconocidos.append(f"cambio: {camb}")
    else:
        r.dudosos.append("ficha")
        if ficha:
            r.no_reconocidos.append(f"ficha: {ficha[:60]}")

    r.matricula = datos.get("matricula", "").strip().upper()
    if not re.match(r"^[0-9]{4}[A-Z]{3}$", r.matricula.replace(" ", "")):
        r.dudosos.append("matricula")

    fecha = datos.get("fecha", "").strip()
    fm = _FECHA.search(fecha)
    if fm:
        d, mth, y = fm.groups()
        r.fecha_matriculacion = f"{y}-{int(mth):02d}-{int(d):02d}"
    elif fecha:
        r.dudosos.append("fecha")

    r.ubicacion = datos.get("ubicacion", "").strip()
    r.zona_origen = normalizar_zona(r.ubicacion)
    return r


def normalizar_zona(texto: str) -> str:
    """"BCA Madrid" -> "Madrid"; "BCA - Sevilla" -> "Sevilla"."""
    t = (texto or "").strip()
    for prefijo in ("BCA -", "BCA-", "BCA"):
        if t.upper().startswith(prefijo):
            t = t[len(prefijo):]
            break
    return t.strip(" -·")


_COMBUSTIBLE_AUTO1 = {
    "gasolina": "gasolina",
    "diésel": "diesel",
    "diesel": "diesel",
    "híbrido": "hibrido",
    "hibrido": "hibrido",
    "híbrido enchufable": "phev",
    "eléctrico": "electrico",
    "electrico": "electrico",
    "gas licuado del petróleo (glp)": "glp",
}


def _cambio_auto1(texto: str) -> str:
    t = (texto or "").strip().lower()
    if "manual" in t:
        return "manual"
    if any(x in t for x in ("automátic", "automatic", "doble embrague", "secuencial", "cvt")):
        return "automatico"
    return ""


def parsear_linea_auto1(linea: str) -> LoteParseado:
    """Formato del scraper de Auto1: 8 campos separados por tabulador.

    nombre · precio_subasta · IVA(tarifa) · referencia · año · km · combustible · cambio
    """
    r = LoteParseado(texto_original=linea, formato="auto1")
    partes = [p.strip() for p in linea.split("\t")]
    campos = ["nombre", "precio", "iva", "referencia", "anio", "km", "combustible", "cambio"]
    d = dict(zip(campos, partes))

    nombre = d.get("nombre", "").strip()
    if nombre and nombre.lower() != "null":
        trozos = nombre.split()
        r.marca = trozos[0]
        r.modelo = trozos[1] if len(trozos) > 1 else ""
        r.version = " ".join(trozos[2:])
    else:
        r.dudosos.append("modelo")

    r.precio_subasta = _num(d.get("precio", ""))
    if not r.precio_subasta:
        r.dudosos.append("precio")

    iva = (d.get("iva", "") or "").replace(",", ".").strip()
    if iva and iva.lower() != "null":
        try:
            float(iva)
            r.iva_anuncio = iva
        except ValueError:
            r.no_reconocidos.append(f"iva: {iva}")
    else:
        r.dudosos.append("iva")

    r.referencia = d.get("referencia", "").strip()
    if not r.referencia or r.referencia.lower() == "null":
        r.dudosos.append("referencia")

    r.anio = _num(d.get("anio", ""))
    r.kilometros = _num(d.get("km", ""))

    comb = (d.get("combustible", "") or "").strip().lower()
    r.combustible = _COMBUSTIBLE_AUTO1.get(comb, "")
    if comb and comb != "null" and not r.combustible:
        r.no_reconocidos.append(f"combustible: {comb}")

    r.cambio = _cambio_auto1(d.get("cambio", ""))
    return r


def parsear_texto(texto: str, formato: str = "bca") -> list[LoteParseado]:
    fn = parsear_linea_auto1 if formato == "auto1" else parsear_linea
    return [fn(linea) for linea in texto.splitlines() if linea.strip()]

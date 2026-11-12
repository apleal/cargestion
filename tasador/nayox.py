"""Fichas de inspección de Nayox (PDF): extrae los datos del coche.

El PDF es una «ficha de inspección» con un expediente por coche: cabecera con
marca, modelo, año, versión/acabado, cambio y km, y varias secciones de etiqueta y
valor (cada valor en la línea siguiente a su etiqueta). No trae precio.

``leer_ficha(bytes)`` -> ``FichaNayox``. Lanza ``NayoxError`` con un mensaje que se le
puede enseñar a la persona. Los PDF son datos de terceros: solo se extrae texto.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGINAS = 30


class NayoxError(Exception):
    """Algo que se le puede explicar a la persona (no un fallo del programa)."""


@dataclass
class FichaNayox:
    expediente: str = ""
    vin: str = ""
    matricula: str = ""
    marca: str = ""
    modelo: str = ""
    version: str = ""
    anio: int | None = None
    fecha_matriculacion: date | None = None
    km: int | None = None
    combustible: str = ""  # clave de Combustible (gasolina, diesel, hibrido, phev…)
    combustible_texto: str = ""
    cambio: str = ""  # manual / automatico
    potencia_kw: int | None = None
    potencia_cv: int | None = None
    cilindrada: int | None = None
    puertas: int | None = None
    color: str = ""
    pintura_metalizada: bool | None = None
    primera_mano: bool | None = None
    importado: bool | None = None
    danos_carroceria: str = ""
    danos_interior: str = ""
    neumaticos_delanteros_cambiar: bool | None = None
    neumaticos_traseros_cambiar: bool | None = None
    iva_deducible: bool | None = None
    reserva_dominio: bool | None = None
    uso: str = ""
    adquirido_en: str = ""
    mantenimiento: str = ""
    mantenimiento_red_oficial: bool | None = None
    proxima_itv: date | None = None
    accidentado: bool | None = None
    equipamiento: list[str] = field(default_factory=list)

    @property
    def acabado(self) -> str:
        return adivinar_acabado(self.version)

    @property
    def nombre(self) -> str:
        return " ".join(x for x in (self.marca, self.modelo, self.version) if x)

    @property
    def carroceria_sin_danos(self) -> bool:
        t = _clave(self.danos_carroceria)
        return t in ("nada que indicar", "ninguno", "ninguna", "sin danos", "no")

    def avisos(self, hoy: date | None = None) -> list[str]:
        """Lo que conviene mirar antes de comprar."""
        hoy = hoy or date.today()
        a = []
        if self.reserva_dominio:
            a.append("Tiene reserva de dominio: hay que cancelarla antes de poder transferirlo.")
        if self.accidentado:
            a.append("Declarado como accidentado.")
        if self.importado:
            a.append("Es un coche importado.")
        if self.iva_deducible is False:
            a.append("El IVA no es deducible.")
        if self.danos_carroceria and not self.carroceria_sin_danos:
            a.append(f"Daños de carrocería: {self.danos_carroceria}.")
        if self.neumaticos_delanteros_cambiar or self.neumaticos_traseros_cambiar:
            donde = " y ".join(
                n for n, c in (("delanteros", self.neumaticos_delanteros_cambiar), ("traseros", self.neumaticos_traseros_cambiar)) if c
            )
            a.append(f"Neumáticos {donde} a cambiar.")
        if self.proxima_itv and self.proxima_itv < hoy:
            a.append(f"La ITV está caducada ({self.proxima_itv:%d/%m/%Y}).")
        return a


# ---------------------------------------------------------------- texto
def _norm(texto: str) -> str:
    """Normaliza el texto del PDF: ligaduras («ﬁ» -> «fi»), espacios raros y de más."""
    t = unicodedata.normalize("NFKC", texto or "").replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", t).strip()


def _clave(texto: str) -> str:
    """Para comparar etiquetas: sin acentos, minúsculas, sin signos ni ':' final."""
    sin = unicodedata.normalize("NFD", _norm(texto)).encode("ascii", "ignore").decode().lower()
    sin = re.sub(r"[¿?¡!:]", "", sin)
    return re.sub(r"\s+", " ", sin).strip()


def extraer_texto(contenido: bytes) -> str:
    if not contenido or not contenido.lstrip()[:5].startswith(b"%PDF"):
        raise NayoxError("El archivo no es un PDF.")
    if len(contenido) > MAX_BYTES:
        raise NayoxError("El PDF pesa demasiado (máximo 10 MB).")
    try:
        from pypdf import PdfReader

        lector = PdfReader(io.BytesIO(contenido))
        if lector.is_encrypted:
            raise NayoxError("El PDF está protegido con contraseña.")
        if len(lector.pages) > MAX_PAGINAS:
            raise NayoxError(f"El PDF tiene demasiadas páginas ({len(lector.pages)}): no parece una ficha de Nayox.")
        return "\n".join((p.extract_text() or "") for p in lector.pages)
    except NayoxError:
        raise
    except Exception as e:  # noqa: BLE001 - un PDF roto no debe tumbar nada
        raise NayoxError("No he podido leer el PDF (¿está dañado?).") from e


# ---------------------------------------------------------------- interpretación
_CABECERA_MODELO = re.compile(r"^(?P<marca>.+?)\s+-\s+(?P<modelo>.+?)\s+(?P<anio>(?:19|20)\d\d)$")
_CABECERA_KM = re.compile(r"^(?P<cambio>[A-ZÁÉÍÓÚa-záéíóú]+)\s*-\s*(?P<km>[\d .]+)\s*km$", re.I)


def _entero(texto) -> int | None:
    d = re.sub(r"\D", "", str(texto or ""))
    return int(d) if d else None


def _fecha(texto: str) -> date | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
    except ValueError:
        return None


def _si_no(texto: str) -> bool | None:
    c = _clave(texto)
    if c in ("si", "yes", "true"):
        return True
    if c in ("no", "false"):
        return False
    return None


def _combustible(texto: str, version: str) -> str:
    c = _clave(texto)
    v = _clave(version)
    if "phev" in v or "enchufable" in c or "plug" in c:
        return "phev"
    if "hibrido" in c:
        return "hibrido"
    if "electrico" in c and "gasolina" not in c and "diesel" not in c:
        return "electrico"
    if "diesel" in c or "gasoil" in c:
        return "diesel"
    if "gasolina" in c:
        return "gasolina"
    if "glp" in c or "gas" in c:
        return "glp"
    return "otro" if c else ""


def _cambio(texto: str) -> str:
    c = _clave(texto)
    if "automat" in c:
        return "automatico"
    if "manual" in c:
        return "manual"
    return ""


_CAMBIO_Y_TRACCION = {
    "DSG", "S-TRONIC", "STRONIC", "TIPTRONIC", "AUT", "AUTO", "AUTOMATICO", "AUTOMÁTICO", "MANUAL", "CVT", "EDC", "EAT",
    "XTRONIC", "MT", "AT", "4X4", "4X2", "4WD", "2WD", "AWD", "QUATTRO",
}
_NO_ES_ACABADO = _CAMBIO_Y_TRACCION | {
    "TSI", "TDI", "TFSI", "FSI", "DCI", "HDI", "CDTI", "TCE", "GDI", "CRDI", "ECOBOOST", "BLUEHDI", "PURETECH", "MULTIJET",
    "HYBRID", "HIBRIDO", "PHEV", "MHEV", "HEV", "EV", "TURBO", "DIESEL", "GASOLINA", "CV", "KW", "KWH", "HP", "CC", "E-HYBRID",
}


def adivinar_acabado(version: str) -> str:
    """El acabado suele ser la última «palabra» de la versión antes del cambio: «… VZ DSG» -> «VZ».
    Es una suposición (se puede corregir): si lo último parece motor o potencia, no inventa nada."""
    for token in reversed(_norm(version).split(" ")):
        limpio = token.strip(",.;")
        if limpio.upper() in _CAMBIO_Y_TRACCION:
            continue  # el cambio y la tracción van detrás del acabado
        # una sola letra («X») no sirve de filtro: coincidiría con casi cualquier título
        if re.fullmatch(r"[A-Za-zÁÉÍÓÚáéíóú][A-Za-z0-9+\-]{1,11}", limpio) and limpio.upper() not in _NO_ES_ACABADO:
            return limpio.upper()
        return ""
    return ""


def _capitalizar(texto: str) -> str:
    """CUPRA -> Cupra, SERIE 3 -> Serie 3; las siglas cortas (BMW, GTI, A3) se quedan como están."""
    palabras = []
    for p in _norm(texto).split(" "):
        palabras.append(p.capitalize() if p.isupper() and len(p) > 3 and p.isalpha() else p)
    return " ".join(palabras)


class _Lineas:
    """Las líneas del PDF y búsquedas de «etiqueta -> valor en la línea siguiente»."""

    def __init__(self, texto: str):
        self.l = [_norm(x) for x in texto.splitlines() if _norm(x)]
        self.k = [_clave(x) for x in self.l]

    def valor(self, *etiquetas: str) -> str:
        buscadas = {_clave(e) for e in etiquetas}
        for i, k in enumerate(self.k):
            # una pregunta larga puede venir partida en dos líneas: «¿… en la red» + «oficial?»
            partida = (
                self.l[i].startswith("¿") and "?" not in self.l[i] and len(k) > 20
                and any(b.startswith(k) for b in buscadas)
            )
            if (k in buscadas or partida) and i + 1 < len(self.l):
                j = i + 1
                # etiqueta partida en dos líneas: «¿Se ha efectuado … en la red» / «oficial?»
                if self.l[i].startswith("¿") and "?" not in self.l[i] and self.l[j].endswith("?") and j + 1 < len(self.l):
                    j += 1
                return self.l[j]
        return ""

    def seccion(self, titulo: str, max_lineas: int = 6) -> str:
        """Lo que hay bajo un título en mayúsculas, hasta el siguiente título."""
        buscado = _clave(titulo)
        for i, k in enumerate(self.k):
            if k == buscado:
                partes = []
                for x in self.l[i + 1 : i + 1 + max_lineas]:
                    if x == x.upper() and len(x.split()) >= 2 and any(c.isalpha() for c in x):
                        break
                    partes.append(x)
                return "; ".join(partes)
        return ""

    def lista_hasta(self, etiqueta: str, paradas: set[str], maximo: int = 14) -> list[str]:
        buscada = _clave(etiqueta)
        for i, k in enumerate(self.k):
            if k == buscada:
                salida = []
                for x, kx in zip(self.l[i + 1 : i + 1 + maximo], self.k[i + 1 : i + 1 + maximo]):
                    if kx in paradas or x.startswith("*"):
                        break
                    salida.append(x)
                return salida
        return []


def interpretar(texto: str) -> FichaNayox:
    t = _Lineas(texto)
    f = FichaNayox()

    # cabecera: «MARCA - MODELO AÑO» / versión / «CAMBIO - KM»
    for i, linea in enumerate(t.l):
        m_km = _CABECERA_KM.match(linea)
        if m_km and i >= 2:
            m_mod = _CABECERA_MODELO.match(t.l[i - 2])
            if m_mod:
                f.marca, f.modelo = m_mod.group("marca"), m_mod.group("modelo")
                f.anio = int(m_mod.group("anio"))
                f.version = t.l[i - 1]
                f.cambio = _cambio(m_km.group("cambio"))
                f.km = _entero(m_km.group("km"))
                break

    for linea in t.l:
        m = re.match(r"^N[úu]mero de expediente\s*:\s*(\S+)", linea, re.I)
        if m and not f.expediente:
            f.expediente = m.group(1).upper()
        m = re.match(r"^VIN\s*:\s*([A-Z0-9]{11,20})\b", linea, re.I)
        if m and not f.vin:
            f.vin = m.group(1).upper()
        m = re.match(r"^Matr[íi]cula\s*:\s*([A-Z0-9]{4,10})\b", linea, re.I)
        if m and not f.matricula:
            f.matricula = m.group(1).upper()

    # sección de datos del vehículo: manda sobre la cabecera
    f.matricula = (t.valor("Matrícula") or f.matricula).upper().replace(" ", "")
    f.vin = (t.valor("VIN") or f.vin).upper()
    f.marca = t.valor("Marca") or f.marca
    f.modelo = t.valor("Modelo") or f.modelo
    f.fecha_matriculacion = _fecha(t.valor("Fecha de matriculación"))
    if f.fecha_matriculacion:
        f.anio = f.fecha_matriculacion.year
    f.combustible_texto = t.valor("Combustible")
    f.combustible = _combustible(f.combustible_texto, f.version)
    f.cambio = _cambio(t.valor("Transmisión")) or f.cambio
    f.potencia_kw = _entero(t.valor("kW"))
    f.cilindrada = _entero(t.valor("Cilindrada"))
    f.puertas = _entero(t.valor("Número de puertas"))
    # «272H» en la versión es la potencia total de un híbrido; si no, los kW pasados a CV
    m_cv = re.search(r"\b(\d{2,3})H\b", f.version)
    f.potencia_cv = int(m_cv.group(1)) if m_cv else (round(f.potencia_kw * 1.36) if f.potencia_kw else None)
    km_actuales = _entero(t.valor("KM actuales"))
    f.km = km_actuales or f.km

    f.primera_mano = _si_no(t.valor("Primera mano"))
    f.importado = _si_no(t.valor("Importado (via base de datos)"))
    if _si_no(t.valor("Importado (via inspección)")) is True:
        f.importado = True
    f.danos_carroceria = t.seccion("DAÑOS CARROCERÍA")
    f.danos_interior = t.seccion("DAÑOS INTERIOR")
    f.neumaticos_delanteros_cambiar = _si_no(t.valor("Neumáticos delanteros a cambiar"))
    f.neumaticos_traseros_cambiar = _si_no(t.valor("Neumáticos traseros a cambiar"))
    f.iva_deducible = _si_no(t.valor("IVA deducible"))
    f.reserva_dominio = _si_no(t.valor("¿Tiene reserva de dominio?"))
    f.uso = t.valor("Uso del vehículo")
    f.adquirido_en = t.valor("Adquirido en:")
    f.mantenimiento = t.valor("Histórico mantenimiento")
    f.mantenimiento_red_oficial = _si_no(t.valor("¿Se ha efectuado el mantenimiento en la red oficial?"))
    f.proxima_itv = _fecha(t.valor("Fecha de la próxima ITV"))
    f.accidentado = _si_no(t.valor("Accidentado (declarado por cliente)"))
    f.color = t.valor("Color del coche")
    f.pintura_metalizada = _si_no(t.valor("Pintura metalizada o premium"))
    f.equipamiento = t.lista_hasta("Equipamiento", {"transmision", "direccion", "embrague", "frenado", "ejes"})
    return f


def leer_ficha(contenido: bytes) -> FichaNayox:
    """PDF (bytes) -> datos del coche. ``NayoxError`` si no es una ficha de Nayox o falta lo esencial."""
    ficha = interpretar(extraer_texto(contenido))
    faltan = [n for n, v in (("marca", ficha.marca), ("modelo", ficha.modelo), ("kilómetros", ficha.km)) if not v]
    if faltan:
        raise NayoxError(
            "No reconozco este PDF como una ficha de inspección de Nayox (no encuentro: " + ", ".join(faltan) + ")."
        )
    if not (ficha.expediente or ficha.matricula or ficha.vin):
        raise NayoxError("La ficha no trae número de expediente, matrícula ni VIN: no puedo identificar el coche.")
    return ficha

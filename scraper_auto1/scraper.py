"""Seguimiento automático de precios de Auto1.

Servicio independiente de la app web: entra en Auto1 con un navegador sin
pantalla, visita la ficha de cada coche en seguimiento, lee el precio y el IVA
(con los mismos selectores que el plugin de Chrome) y se los manda a la API de
la app, que hace todo el cálculo. Si algo entra en precio o baja, avisa.

Variables de entorno (las credenciales NUNCA van en el repositorio):

    APP_URL          https://tu-dominio-de-la-app            (obligatoria)
    APP_TOKEN        token de `manage.py crear_token_api`    (obligatoria)
    AUTO1_EMAIL      email de tu cuenta de Auto1             (obligatoria)
    AUTO1_PASSWORD   contraseña de tu cuenta de Auto1        (obligatoria)
    SCAN_AT          hora diaria de la pasada, HH:MM (def. 08:30)
    TZ_NAME          zona horaria de esa hora (def. Europe/Madrid)
    POLL_SECONDS     cada cuántos segundos avisa a la app y mira si hay una
                     pasada pedida desde su botón (def. 30)
    RUN_ONCE         1 = una sola pasada inmediata y salir (para probar)
    PAUSE_SECONDS    pausa entre coches, para no ir a ráfagas (def. 4)
    MAX_CARS         límite de coches por pasada; 0 = todos (def. 0)
    DRY_RUN          1 = no envía nada a la app, solo muestra lo leído
    NOTIFY_WEBHOOK   URL opcional a la que se manda el resumen/avisos (JSON)
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  opcionales: avisos por Telegram
    HEADLESS         0 = muestra el navegador (para depurar en tu PC)
    CHROME_BIN       ruta de Chrome si no está en el sitio habitual (opcional)
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ajustes import caracteres_raros, limpiar_texto, limpiar_token, limpiar_url
from horario import parse_hora, toca_pasada_programada

AUTO1_HOME = "https://www.auto1.com"

# Misma lógica que el plugin de Chrome. Devuelve los 8 campos de la línea.
JS_EXTRAER = r"""
() => {
  const buscar = (etiqueta) => {
    for (const fila of document.querySelectorAll('tr')) {
      const celdas = fila.querySelectorAll('td');
      if (celdas.length >= 2 && celdas[0].innerText.replace(':', '').trim() === etiqueta) {
        return celdas[1].innerText.trim();
      }
    }
    return null;
  };
  const h2 = document.querySelector('h2.no-score');
  const sp = document.querySelector('.minimumBid .money-value');
  const sv = document.querySelector('span[data-qa-id="serviceFee-vatValue"]');
  let tarifa = null;
  if (sv) {
    const m = sv.innerText.match(/[0-9]+([,.][0-9]+)?/);
    if (m) tarifa = m[0].replace(',', '.');
  }
  const km = buscar('Lectura cuentakilómetros');
  return {
    nombre: h2 ? h2.innerText.trim() : null,
    precio: sp ? sp.innerText.replace('€', '').replace(/\./g, '').trim() : null,
    tarifa: tarifa,
    referencia: buscar('Referencia'),
    anio: buscar('Año de fabricación'),
    km: km ? km.replace(' km', '').replace(/\./g, '') : null,
    combustible: buscar('Combustible'),
    cambio: buscar('Caja de cambios'),
  };
}
"""


# Estado de la ficha cuando NO es una subasta normal con precio. Se busca por
# texto (las clases con nombres aleatorios cambian) y solo se usan las clases
# con nombre propio (.car-sold, .icon-indicator-description) dentro de #car-main-info.
JS_ESTADO = r"""
() => {
  const norm = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const cuerpo = norm(document.body ? document.body.innerText : '');
  if (cuerpo.includes('ya no esta disponible')) return {estado: 'no_disponible'};
  if (cuerpo.includes('el particular no acepto tu oferta')) return {estado: 'particular_rechazo'};
  const zona = document.querySelector('#car-main-info') || document;
  const sold = zona.querySelector('.car-sold');
  if (sold && /vendido/.test(norm(sold.innerText))) return {estado: 'adjudicado'};
  const ind = Array.from(zona.querySelectorAll('.icon-indicator-description'))
    .find((e) => /compra directa/.test(norm(e.innerText)));
  if (ind) {
    let precio = null;
    const nodo = document.evaluate(
      '//*[@id="car-main-info"]/div[3]/div[2]/div[3]/div/div/div[1]/div', document, null,
      XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    const m = nodo ? nodo.innerText.match(/[0-9][0-9.]*(?:,[0-9]+)?/) : null;
    if (m) {
      const n = parseFloat(m[0].replace(/\./g, '').replace(',', '.'));
      if (!isNaN(n)) precio = n;
    }
    return {estado: 'compra_directa', precio: precio};
  }
  return {estado: null};
}
"""

ESTADOS_ESPECIALES = ("compra_directa", "no_disponible", "adjudicado", "particular_rechazo")

_LOG_BUFFER: list[str] = []


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)
    # Las últimas líneas viajan a la app en el siguiente latido (pantalla de seguimiento).
    _LOG_BUFFER.append(msg[:280])
    del _LOG_BUFFER[:-200]


def config() -> dict:
    cfg = {
        "app_url": limpiar_url(os.environ.get("APP_URL", "")),
        "app_token": limpiar_token(os.environ.get("APP_TOKEN", "")),
        "email": limpiar_texto(os.environ.get("AUTO1_EMAIL", "")),
        "password": os.environ.get("AUTO1_PASSWORD", ""),
        "scan_at": os.environ.get("SCAN_AT", "08:30"),
        "tz": os.environ.get("TZ_NAME", "Europe/Madrid"),
        "poll": float(os.environ.get("POLL_SECONDS", "30")),
        "run_once": os.environ.get("RUN_ONCE", "0") == "1",
        "pause": float(os.environ.get("PAUSE_SECONDS", "4")),
        "max_cars": int(os.environ.get("MAX_CARS", "0")),
        "dry_run": os.environ.get("DRY_RUN", "0") == "1",
        "webhook": os.environ.get("NOTIFY_WEBHOOK", ""),
        "tg_token": limpiar_texto(os.environ.get("TELEGRAM_BOT_TOKEN", "")),
        "tg_chat": limpiar_texto(os.environ.get("TELEGRAM_CHAT_ID", "")),
        "headless": os.environ.get("HEADLESS", "1") != "0",
    }
    if not cfg["app_url"] or not cfg["app_token"]:
        sys.exit(
            "Faltan APP_URL y/o APP_TOKEN: sin ellas el servicio no puede ni avisar a la app."
        )
    # Lo demás no impide avisar a la app: se queda vivo y le cuenta el problema,
    # así se ve en su pantalla de seguimiento y no solo en los logs.
    problemas = []
    faltan = [n for n, k in (("AUTO1_EMAIL", "email"), ("AUTO1_PASSWORD", "password")) if not cfg[k]]
    if faltan:
        problemas.append("Faltan variables de entorno: " + ", ".join(faltan) + ".")
    try:
        parse_hora(cfg["scan_at"])
        ZoneInfo(cfg["tz"])
    except Exception:
        problemas.append("SCAN_AT debe ser HH:MM (p. ej. 08:30) y TZ_NAME una zona válida.")
    cfg["problemas"] = " ".join(problemas)
    return cfg


def api_headers(cfg: dict) -> dict:
    return {"Authorization": f"Token {cfg['app_token']}"}


def coches_en_seguimiento(cfg: dict) -> list[dict]:
    r = requests.get(
        f"{cfg['app_url']}/api/auto1/seguimiento/", headers=api_headers(cfg), timeout=60
    )
    r.raise_for_status()
    return r.json()


def crear_driver(cfg: dict):
    """Chrome controlado con Selenium (el mismo enfoque que ya funcionaba con tu
    cuenta). Selenium Manager descarga el chromedriver que toque."""
    opts = Options()
    if cfg["headless"]:
        opts.add_argument("--headless=new")
    for arg in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1366,900",
        "--lang=es-ES",
        "--disable-blink-features=AutomationControlled",
    ):
        opts.add_argument(arg)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if cfg["headless"]:
        # El modo sin ventana se anuncia como "HeadlessChrome"; se disfraza de Chrome normal.
        so = "X11; Linux x86_64" if sys.platform.startswith("linux") else "Windows NT 10.0; Win64; x64"
        opts.add_argument(
            f"--user-agent=Mozilla/5.0 ({so}) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    binario = os.environ.get("CHROME_BIN")
    if binario:
        opts.binary_location = binario
    return webdriver.Chrome(options=opts)


def _primer_visible(driver, por, valor, segundos: float):
    """Primer elemento visible que coincida (la página puede tener varios
    formularios, algunos ocultos), o None si no aparece a tiempo."""
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        for e in driver.find_elements(por, valor):
            try:
                if e.is_displayed():
                    return e
            except WebDriverException:
                pass
        time.sleep(0.3)
    return None


def login(driver, cfg: dict) -> None:
    """Portada -> cookies -> «Accede» -> email/contraseña -> Enter."""
    driver.get(AUTO1_HOME)
    time.sleep(3)

    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[data-testid='cookie-banner-accept-all-cookies-button']")
            )
        ).click()
        log("Cookies de Auto1 aceptadas.")
        time.sleep(2)
    except TimeoutException:
        log("Sin aviso de cookies (o ya aceptado).")

    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='header-login-button']"))
        ).click()
    except TimeoutException:
        raise RuntimeError(
            "No encuentro el botón «Accede» de la portada de Auto1: la página ha podido cambiar."
        )

    email = _primer_visible(driver, By.NAME, "email", 15)
    password = _primer_visible(driver, By.NAME, "password", 15)
    if not email or not password:
        raise RuntimeError("No aparecen los campos de email y contraseña tras pulsar «Accede».")
    email.send_keys(cfg["email"])
    password.send_keys(cfg["password"])
    password.send_keys(Keys.RETURN)

    # Entrado = el formulario de contraseña deja de verse.
    fin = time.monotonic() + 30
    while time.monotonic() < fin:
        if _primer_visible(driver, By.NAME, "password", 0.5) is None:
            break
    else:
        texto = driver.find_element(By.TAG_NAME, "body").text.lower()
        if any(p in texto for p in ("captcha", "verific", "código", "codigo", "robot")):
            raise RuntimeError(
                "Auto1 pide verificación adicional (captcha o código): "
                "no se puede automatizar el acceso."
            )
        raise RuntimeError("El login de Auto1 no ha avanzado: revisa email/contraseña.")
    time.sleep(3)
    log("Login en Auto1 correcto.")


def leer_ficha(driver, url: str) -> dict:
    """Lee una ficha y devuelve su estado:

    {"estado": "ok", "datos": {...}}                     subasta normal con precio
    {"estado": "compra_directa", "precio": 9800.0|None}  sigue vigente, en compra directa
    {"estado": "no_disponible"|"adjudicado"|"particular_rechazo"}   el coche se acabó
    {"estado": "sin_precio"}                             nada reconocible (¿vendida?)
    Si lo que ha pasado es que se cayó la sesión, lanza error.
    """
    driver.get(url)
    fin = time.monotonic() + 12
    while time.monotonic() < fin:
        try:
            e = driver.execute_script("return (" + JS_ESTADO + ")()")
        except WebDriverException:
            e = None  # la página aún está cargando
        if e and e.get("estado"):
            return e
        if driver.find_elements(By.CSS_SELECTOR, ".minimumBid .money-value"):
            return {"estado": "ok", "datos": driver.execute_script("return (" + JS_EXTRAER + ")()")}
        time.sleep(0.5)
    if "signin" in driver.current_url or _primer_visible(driver, By.NAME, "password", 1):
        raise RuntimeError("Se ha caído la sesión de Auto1 (pide iniciar sesión otra vez).")
    return {"estado": "sin_precio"}


def linea_para_api(d: dict) -> str:
    """La línea de 8 campos tabulados que espera la API (como el plugin)."""

    def v(x):
        return "" if x is None else str(x)

    # Sin elemento de tarifa = anuncio sin IVA: la API exige el campo, va a 0.
    tarifa = d["tarifa"] if d.get("tarifa") is not None else "0"
    return "\t".join(
        [
            v(d["nombre"]), v(d["precio"]), v(tarifa), v(d["referencia"]),
            v(d["anio"]), v(d["km"]), v(d["combustible"]), v(d["cambio"]),
        ]
    )


def enviar_escaneo(cfg: dict, linea: str) -> dict:
    r = requests.post(
        f"{cfg['app_url']}/api/auto1/escaneo/",
        headers=api_headers(cfg),
        json={"texto": linea},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"La app rechazó el escaneo ({r.status_code}): {r.text[:300]}")
    return r.json()


def marcar_no_disponible(cfg: dict, referencia: str) -> dict:
    r = requests.post(
        f"{cfg['app_url']}/api/auto1/no-disponible/",
        headers=api_headers(cfg),
        json={"referencia": referencia},
        timeout=60,
    )
    if r.status_code == 404:
        return {}  # referencia que la app no conoce: se ignora
    if r.status_code >= 400:
        raise RuntimeError(f"La app rechazó el aviso ({r.status_code}): {r.text[:200]}")
    return r.json()


def enviar_estado_ficha(cfg: dict, referencia: str, estado: str, precio=None) -> dict:
    cuerpo = {"referencia": referencia, "estado": estado}
    if precio is not None:
        cuerpo["precio"] = precio
    r = requests.post(
        f"{cfg['app_url']}/api/auto1/estado-ficha/",
        headers=api_headers(cfg),
        json=cuerpo,
        timeout=60,
    )
    if r.status_code == 404:
        return {}  # referencia que la app no conoce: se ignora
    if r.status_code >= 400:
        raise RuntimeError(f"La app rechazó el estado de ficha ({r.status_code}): {r.text[:200]}")
    return r.json()


ETIQUETA_ESTADO = {
    "no_disponible": "ya no está disponible",
    "adjudicado": "Vendido (adjudicado)",
    "particular_rechazo": "el particular no aceptó la oferta",
    "compra_directa": "Compra Directa",
}


def pasada(cfg: dict, on_progress=None) -> None:
    coches = coches_en_seguimiento(cfg)
    if cfg["max_cars"]:
        coches = coches[: cfg["max_cars"]]
    log(f"{len(coches)} coches en seguimiento.")
    if not coches:
        registrar_pasada(cfg, True, 0, 0, 0, 0, 0, "No había coches en seguimiento.")
        return

    avisos: list[str] = []
    sin_ficha: list[str] = []
    errores: list[str] = []
    cerrados: list[str] = []
    en_directa: list[str] = []
    cambios = sin_cambios = con_precio = explicitos = procesados = 0
    detenida = False

    driver = crear_driver(cfg)
    try:
        login(driver, cfg)

        for i, c in enumerate(coches, 1):
            ref = c["referencia"]
            if on_progress and on_progress(i, len(coches), ref):
                detenida = True
                log(f"Pasada detenida desde la app tras {procesados} coches.")
                break
            procesados = i
            try:
                lectura = leer_ficha(driver, c["url"])
            except WebDriverException as e:
                errores.append(f"{ref}: {str(e)[:120]}")
                continue
            estado = lectura["estado"]
            nombre = f"{c['marca']} {c['modelo']} ({ref})"

            if estado in ESTADOS_ESPECIALES:
                explicitos += 1  # un mensaje de Auto1 prueba que la sesión es válida
                log(f"[{i}/{len(coches)}] {ref}: {ETIQUETA_ESTADO[estado]}.")
                if cfg["dry_run"]:
                    continue
                try:
                    res = enviar_estado_ficha(cfg, ref, estado, lectura.get("precio"))
                except RuntimeError as e:
                    errores.append(f"{ref}: {e}")
                    continue
                if estado == "compra_directa":
                    en_directa.append(ref)
                    if res.get("cambio"):
                        precio = lectura.get("precio")
                        avisos.append(
                            f"🛒 {nombre} ha pasado a Compra Directa"
                            + (f" · {precio:,.0f} €".replace(",", ".") if precio else "")
                        )
                elif res.get("cerrado"):
                    cerrados.append(f"{ref} ({ETIQUETA_ESTADO[estado]})")
                    avisos.append(
                        f"🏆 {nombre}: Auto1 lo marca como Vendido (adjudicado)"
                        if estado == "adjudicado"
                        else f"🚫 {nombre}: {ETIQUETA_ESTADO[estado]}, cerrado"
                    )
            elif estado == "sin_precio":
                sin_ficha.append(ref)
                log(f"[{i}/{len(coches)}] {ref}: sin precio en la ficha.")
            else:
                datos = lectura["datos"]
                if datos.get("referencia") != ref:
                    errores.append(f"{ref}: la ficha dice {datos.get('referencia')}")
                    continue
                con_precio += 1
                linea = linea_para_api(datos)
                if cfg["dry_run"]:
                    log(f"[{i}/{len(coches)}] DRY_RUN {linea!r}")
                else:
                    try:
                        res = enviar_escaneo(cfg, linea)
                    except RuntimeError as e:
                        errores.append(f"{ref}: {e}")
                        continue
                    if res.get("sin_cambios"):
                        sin_cambios += 1
                    else:
                        cambios += 1
                        variacion = res.get("variacion")
                        log(
                            f"[{i}/{len(coches)}] {ref}: {res.get('precio_anterior')} -> "
                            f"{res.get('precio_salida')} (tier {res.get('tier')})"
                        )
                        if res.get("tier") or (variacion and float(variacion) < 0):
                            avisos.append(
                                f"{'🎯 ' + res['tier'] + '% ' if res.get('tier') else ''}"
                                f"{nombre}: "
                                f"{res.get('precio_anterior')} -> {res.get('precio_salida')} €"
                                f" · puja máx. 15%: {res.get('puja_maxima_15')} €"
                            )
            time.sleep(cfg["pause"] + random.uniform(0, 2))

    finally:
        driver.quit()

    if con_precio + explicitos == 0 and not detenida:
        raise RuntimeError(
            "Ninguna ficha mostró precio ni un estado reconocible: Auto1 ha cambiado la "
            "página o la sesión no es válida. No se ha marcado nada como vendido."
        )

    # Las fichas sin precio y sin mensaje reconocible (con la sesión comprobada
    # buena) se comunican a la app, que las da por vendidas tras dos pasadas.
    vendidos_auto: list[str] = []
    if not cfg["dry_run"] and not detenida:
        for ref in sin_ficha:
            try:
                if marcar_no_disponible(cfg, ref).get("marcado_vendido"):
                    vendidos_auto.append(ref)
            except RuntimeError as e:
                errores.append(f"{ref}: {e}")

    resumen = (
        f"Auto1: {procesados} de {len(coches)} coches revisados"
        f"{' (detenida)' if detenida else ''} · {cambios} con cambios · "
        f"{sin_cambios} sin cambios · {len(cerrados)} cerrados · {len(en_directa)} en compra directa · "
        f"{len(sin_ficha)} sin precio · {len(errores)} errores"
    )
    log(resumen)
    for e in errores[:10]:
        log(f"  error: {e}")
    if cerrados:
        log(f"  cerrados: {', '.join(cerrados)}")
    if sin_ficha:
        log(f"  sin precio (¿vendidos?): {', '.join(sin_ficha[:20])}")
    if vendidos_auto:
        log(f"  marcados como vendidos: {', '.join(vendidos_auto)}")
    detalle = "\n".join(
        (["Detenida manualmente desde la app."] if detenida else [])
        + ([f"Cerrados: {', '.join(cerrados[:20])}"] if cerrados else [])
        + ([f"En compra directa: {', '.join(en_directa[:20])}"] if en_directa else [])
        + ([f"Sin precio: {', '.join(sin_ficha[:20])}"] if sin_ficha else [])
        + [f"Error: {e}" for e in errores[:10]]
    )
    registrar_pasada(
        cfg, True, procesados, cambios, sin_cambios, len(sin_ficha), len(errores), detalle
    )
    notificar(cfg, resumen, avisos, vendidos_auto, errores)


def registrar_pasada(
    cfg, ok, revisados, con_cambios, sin_cambios, sin_precio, errores, detalle
) -> None:
    """Deja el parte de la pasada en la app (también si falla): el Panel avisa
    si los partes dejan de llegar o el último es un fallo."""
    if cfg["dry_run"]:
        return
    try:
        requests.post(
            f"{cfg['app_url']}/api/auto1/pasada/",
            headers=api_headers(cfg),
            json={
                "ok": ok, "revisados": revisados, "con_cambios": con_cambios,
                "sin_cambios": sin_cambios, "sin_precio": sin_precio,
                "errores": errores, "detalle": detalle[:2000],
            },
            timeout=30,
        )
    except requests.RequestException as e:
        log(f"No se pudo registrar el parte en la app: {e}")


def enviar_aviso(cfg, texto: str, extra: dict | None = None) -> None:
    """Manda un aviso por los canales configurados (Telegram y/o webhook)."""
    if cfg["dry_run"]:
        return
    if cfg["tg_token"] and cfg["tg_chat"]:
        try:
            requests.post(
                f"https://api.telegram.org/bot{cfg['tg_token']}/sendMessage",
                json={"chat_id": cfg["tg_chat"], "text": texto[:4000]},
                timeout=30,
            )
        except requests.RequestException as e:
            log(f"No se pudo avisar por Telegram: {e}")
    if cfg["webhook"]:
        try:
            requests.post(
                cfg["webhook"], json={"mensaje": texto, **(extra or {})}, timeout=30
            )
        except requests.RequestException as e:
            log(f"No se pudo avisar al webhook: {e}")


def notificar(cfg, resumen, avisos, vendidos_auto, errores) -> None:
    if not (avisos or vendidos_auto or errores):
        return  # solo molesta si hay algo que decir
    partes = [resumen, *avisos]
    if vendidos_auto:
        partes.append("🚫 Ya no disponibles en Auto1 (marcados vendidos): " + ", ".join(vendidos_auto))
    enviar_aviso(
        cfg, "\n".join(partes),
        {"avisos": avisos, "vendidos": vendidos_auto, "errores": errores},
    )


def latido(cfg, en_curso: bool = False, consumir: bool = False, progreso=None) -> dict | None:
    """Avisa a la app de que el servicio está vivo, le cuenta qué hace (progreso,
    problemas, últimas líneas del log) y recoge sus órdenes (pasada pedida,
    pausa, detener). Devuelve su respuesta, o None si la app no contesta."""
    enviadas = len(_LOG_BUFFER)
    cuerpo = {
        "programada": cfg["scan_at"],
        "en_curso": en_curso,
        "consumir_solicitud": consumir,
        "problemas": cfg.get("problemas", ""),
        "log": list(_LOG_BUFFER[:enviadas]),
    }
    if progreso:
        cuerpo["progreso"] = progreso
    try:
        r = requests.post(
            f"{cfg['app_url']}/api/auto1/latido/",
            headers=api_headers(cfg),
            json=cuerpo,
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        resp = getattr(e, "response", None)
        if resp is not None and resp.status_code == 401:
            texto = (
                "La app rechaza el token (401). APP_TOKEN tiene "
                f"{len(cfg['app_token'])} caracteres y uno válido tiene 40"
                + (
                    f"; contiene caracteres que no son de un token: {caracteres_raros(cfg['app_token'])}"
                    if caracteres_raros(cfg["app_token"])
                    else ""
                )
                + ". Consulta el vigente con «python manage.py crear_token_api --usuario n8n» "
                "en la consola de la web y pégalo tal cual, sin comillas, paréntesis ni la palabra «Token»."
            )
        elif resp is not None and resp.status_code in (400, 403, 404):
            texto = f"La app responde {resp.status_code} en {cfg['app_url']}: ¿APP_URL es la dirección correcta?"
        else:
            texto = f"No se pudo avisar a la app (latido): {e}"
        print(time.strftime("%Y-%m-%d %H:%M:%S"), texto, flush=True)
        return None
    del _LOG_BUFFER[:enviadas]
    return r.json()


def ejecutar_pasada(cfg) -> None:
    """Una pasada completa, informando a la app de que está en curso (con su
    progreso) y obedeciendo la orden de detener, sin que un fallo tumbe el servicio."""
    latido(cfg, en_curso=True, consumir=True)
    estado = {"ultimo": -1e9, "detener": False}

    def progreso(i, total, ref):
        # Cada ~15 s: latido con progreso. Una pasada larga no debe parecer un
        # servicio caído, y así se recoge la orden de detener.
        if time.monotonic() - estado["ultimo"] >= 15:
            r = latido(
                cfg, en_curso=True, progreso={"actual": i, "total": total, "referencia": ref}
            )
            estado["ultimo"] = time.monotonic()
            if r and r.get("detener"):
                estado["detener"] = True
        return estado["detener"]

    try:
        pasada(cfg, on_progress=progreso)
    except Exception as e:
        log(f"Pasada fallida: {e}")
        registrar_pasada(cfg, False, 0, 0, 0, 0, 1, str(e))
        enviar_aviso(cfg, f"⚠️ Seguimiento Auto1 falló: {e}")
        if cfg["run_once"]:
            sys.exit(1)
    finally:
        latido(cfg, en_curso=False)


def main() -> None:
    cfg = config()
    if cfg["run_once"]:
        if cfg["problemas"]:
            sys.exit(cfg["problemas"])
        ejecutar_pasada(cfg)
        return

    try:
        hora = parse_hora(cfg["scan_at"])
        tz = ZoneInfo(cfg["tz"])
    except Exception:  # configuración inválida: ya consta en cfg["problemas"]
        hora, tz = parse_hora("08:30"), ZoneInfo("Europe/Madrid")
    log(f"Servicio activo. Pasada diaria a las {cfg['scan_at']} ({cfg['tz']}) y botón de la app.")
    if cfg["problemas"]:
        log(f"Configuración incompleta, no hará pasadas: {cfg['problemas']}")

    intentada: date | None = None
    while True:
        try:
            info = latido(cfg)
            if info is not None and not cfg["problemas"]:
                ahora = datetime.now(tz)
                ultima = (
                    date.fromisoformat(info["ultima_pasada_fecha"])
                    if info.get("ultima_pasada_fecha")
                    else None
                )
                programada = not info.get("pausado") and toca_pasada_programada(
                    ahora, hora, ultima, intentada
                )
                if programada or info.get("pasada_solicitada"):
                    if programada:
                        intentada = ahora.date()
                    log("Pasada " + ("programada." if programada else "pedida desde la app."))
                    ejecutar_pasada(cfg)
        except Exception as e:  # nada debe tumbar el servicio
            log(f"Error inesperado en el bucle principal: {e}")
        time.sleep(cfg["poll"])


if __name__ == "__main__":
    main()

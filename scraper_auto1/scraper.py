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
    SCAN_EVERY_HOURS cada cuántas horas repetir; 0 = una sola pasada (def. 24)
    PAUSE_SECONDS    pausa entre coches, para no ir a ráfagas (def. 4)
    MAX_CARS         límite de coches por pasada; 0 = todos (def. 0)
    DRY_RUN          1 = no envía nada a la app, solo muestra lo leído
    NOTIFY_WEBHOOK   URL opcional a la que se manda el resumen/avisos (JSON)
    HEADLESS         0 = muestra el navegador (para depurar en tu PC)
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

import requests
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

AUTO1_LOGIN = "https://www.auto1.com/es/merchant/signin"

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


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def config() -> dict:
    cfg = {
        "app_url": os.environ.get("APP_URL", "").rstrip("/"),
        "app_token": os.environ.get("APP_TOKEN", ""),
        "email": os.environ.get("AUTO1_EMAIL", ""),
        "password": os.environ.get("AUTO1_PASSWORD", ""),
        "every_hours": float(os.environ.get("SCAN_EVERY_HOURS", "24")),
        "pause": float(os.environ.get("PAUSE_SECONDS", "4")),
        "max_cars": int(os.environ.get("MAX_CARS", "0")),
        "dry_run": os.environ.get("DRY_RUN", "0") == "1",
        "webhook": os.environ.get("NOTIFY_WEBHOOK", ""),
        "headless": os.environ.get("HEADLESS", "1") != "0",
    }
    faltan = [
        k for k in ("app_url", "app_token", "email", "password") if not cfg[k]
    ]
    if faltan:
        sys.exit(f"Faltan variables de entorno: {', '.join(faltan)}")
    return cfg


def api_headers(cfg: dict) -> dict:
    return {"Authorization": f"Token {cfg['app_token']}"}


def coches_en_seguimiento(cfg: dict) -> list[dict]:
    r = requests.get(
        f"{cfg['app_url']}/api/auto1/seguimiento/", headers=api_headers(cfg), timeout=60
    )
    r.raise_for_status()
    return r.json()


def login(page, cfg: dict) -> None:
    page.goto(AUTO1_LOGIN, wait_until="domcontentloaded")
    email = page.locator('input[placeholder="Email"]:visible').first
    password = page.locator('input[type="password"]:visible').first
    email.fill(cfg["email"])
    password.fill(cfg["password"])
    password.press("Enter")
    try:
        page.wait_for_url(lambda url: "signin" not in url, timeout=30_000)
    except PlaywrightTimeout:
        texto = page.inner_text("body").lower()
        if any(p in texto for p in ("captcha", "verific", "código", "codigo")):
            raise RuntimeError(
                "Auto1 pide verificación adicional (captcha o código): "
                "no se puede automatizar el acceso."
            )
        raise RuntimeError("El login de Auto1 no ha avanzado: revisa email/contraseña.")
    log("Login en Auto1 correcto.")


def leer_ficha(page, url: str) -> dict | None:
    """Datos de una ficha, o None si la ficha no muestra precio (vendida,
    retirada o sesión caída)."""
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector(".minimumBid .money-value", timeout=15_000)
    except PlaywrightTimeout:
        return None
    return page.evaluate(JS_EXTRAER)


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


def pasada(cfg: dict) -> None:
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
    cambios = sin_cambios = 0
    fallos_seguidos = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg["headless"])
        context = browser.new_context(
            locale="es-ES",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        login(page, cfg)

        for i, c in enumerate(coches, 1):
            ref = c["referencia"]
            try:
                datos = leer_ficha(page, c["url"])
            except PlaywrightError as e:
                errores.append(f"{ref}: {str(e)[:120]}")
                continue

            if datos is None:
                sin_ficha.append(ref)
                fallos_seguidos += 1
                log(f"[{i}/{len(coches)}] {ref}: sin precio en la ficha.")
                if fallos_seguidos >= 5:
                    raise RuntimeError(
                        "5 fichas seguidas sin precio: probablemente se ha caído la "
                        "sesión o Auto1 ha cambiado la página. Pasada abortada."
                    )
            else:
                fallos_seguidos = 0
                if datos.get("referencia") != ref:
                    errores.append(f"{ref}: la ficha dice {datos.get('referencia')}")
                    continue
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
                                f"{c['marca']} {c['modelo']} ({ref}): "
                                f"{res.get('precio_anterior')} -> {res.get('precio_salida')} €"
                                f" · puja máx. 15%: {res.get('puja_maxima_15')} €"
                            )
            time.sleep(cfg["pause"] + random.uniform(0, 2))

        browser.close()

    resumen = (
        f"Auto1: {len(coches)} coches revisados · {cambios} con cambios · "
        f"{sin_cambios} sin cambios · {len(sin_ficha)} sin precio · {len(errores)} errores"
    )
    log(resumen)
    for e in errores[:10]:
        log(f"  error: {e}")
    if sin_ficha:
        log(f"  sin precio (¿vendidos?): {', '.join(sin_ficha[:20])}")
    detalle = "\n".join(
        ([f"Sin precio: {', '.join(sin_ficha[:20])}"] if sin_ficha else [])
        + [f"Error: {e}" for e in errores[:10]]
    )
    registrar_pasada(
        cfg, True, len(coches), cambios, sin_cambios, len(sin_ficha), len(errores), detalle
    )
    notificar(cfg, resumen, avisos, sin_ficha, errores)


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


def notificar(cfg, resumen, avisos, sin_ficha, errores) -> None:
    if not cfg["webhook"] or cfg["dry_run"]:
        return
    if not (avisos or errores):
        return  # solo molesta si hay algo que decir
    texto = "\n".join([resumen, *avisos])
    try:
        requests.post(
            cfg["webhook"],
            json={"mensaje": texto, "avisos": avisos, "sin_ficha": sin_ficha, "errores": errores},
            timeout=30,
        )
    except requests.RequestException as e:
        log(f"No se pudo avisar al webhook: {e}")


def main() -> None:
    cfg = config()
    while True:
        try:
            pasada(cfg)
        except Exception as e:  # una pasada fallida no debe tumbar el servicio
            log(f"Pasada fallida: {e}")
            registrar_pasada(cfg, False, 0, 0, 0, 0, 1, str(e))
            if cfg["webhook"] and not cfg["dry_run"]:
                try:
                    requests.post(
                        cfg["webhook"], json={"mensaje": f"⚠️ Seguimiento Auto1 falló: {e}"},
                        timeout=30,
                    )
                except requests.RequestException:
                    pass
            if cfg["every_hours"] == 0:
                sys.exit(1)
        if cfg["every_hours"] == 0:
            return
        log(f"Próxima pasada en {cfg['every_hours']} h.")
        time.sleep(cfg["every_hours"] * 3600)


if __name__ == "__main__":
    main()

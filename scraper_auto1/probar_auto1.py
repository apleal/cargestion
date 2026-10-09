"""Prueba paso a paso, en TU PC: ¿se conecta a Auto1 y lee una ficha?

Usa exactamente el mismo código que el servicio (scraper.py), con Chrome y
Selenium como tu script que ya funcionaba. No envía nada a ningún sitio ni
toca tu app. La contraseña solo se escribe aquí (oculta): no se imprime ni se
guarda.

    cd C:\\claude\\cargestion\\scraper_auto1
    ..\\.venv\\Scripts\\python.exe probar_auto1.py
"""
from __future__ import annotations

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scraper  # noqa: E402

FICHA_BASE = "https://www.auto1.com/es/app/merchant/car/"
CARPETA = os.path.dirname(os.path.abspath(__file__))


def ok(msg):
    print(f"  OK    {msg}")


def fallo(msg):
    print(f"  FALLO {msg}")


def captura(driver, nombre):
    ruta = os.path.join(CARPETA, nombre)
    try:
        driver.save_screenshot(ruta)
        print(f"        (captura guardada en {ruta})")
    except Exception:
        pass


def pedir_datos():
    email = os.environ.get("AUTO1_EMAIL") or input("Email de Auto1: ").strip()
    password = os.environ.get("AUTO1_PASSWORD") or getpass.getpass(
        "Contraseña de Auto1 (no se ve al escribir): "
    )
    ficha = os.environ.get("AUTO1_FICHA") or input(
        "Referencia o enlace de una ficha de ejemplo [Enter = JV37038]: "
    ).strip() or "JV37038"
    url = ficha if ficha.startswith("http") else FICHA_BASE + ficha
    return email, password, url


def main() -> int:
    email, password, url = pedir_datos()
    cfg = {
        "email": email,
        "password": password,
        "headless": os.environ.get("HEADLESS", "0") != "0",
    }
    if os.environ.get("AUTO1_HOME"):
        scraper.AUTO1_HOME = os.environ["AUTO1_HOME"]

    print("\nPaso 1: abrir Chrome")
    try:
        driver = scraper.crear_driver(cfg)
    except Exception as e:
        fallo(f"no se pudo arrancar Chrome: {str(e)[:300]}")
        print("        Comprueba que Chrome está instalado y que hay conexión a internet")
        print("        (la primera vez descarga el controlador de Chrome).")
        return 1
    ok("Chrome abierto")

    try:
        print("Paso 2: entrar en Auto1 (portada, cookies, «Accede», usuario y contraseña)")
        try:
            scraper.login(driver, cfg)
        except RuntimeError as e:
            fallo(str(e))
            captura(driver, "probar_auto1_login.png")
            return 1
        ok(f"sesión iniciada (estás en {driver.current_url[:70]})")

        print("Paso 3: abrir la ficha de ejemplo")
        print(f"        {url}")
        try:
            d = scraper.leer_ficha(driver, url)
        except RuntimeError as e:
            fallo(str(e))
            captura(driver, "probar_auto1_ficha.png")
            return 1
        if d is None:
            fallo("la ficha se abre pero no encuentro el precio (¿vendida, o ha cambiado la página?)")
            print("        Prueba con otra referencia que sepas que sigue a la venta.")
            captura(driver, "probar_auto1_ficha.png")
            return 1
        ok("ficha abierta y con precio")

        print("Paso 4: datos leídos de la ficha")
        for clave in ("nombre", "precio", "tarifa", "referencia", "anio", "km", "combustible", "cambio"):
            print(f"        {clave:12} = {d.get(clave)}")
        captura(driver, "probar_auto1_ficha.png")
        faltan = [k for k in ("nombre", "precio", "referencia") if not d.get(k)]
        if faltan:
            fallo(f"faltan datos importantes: {', '.join(faltan)}")
            return 1
        ok("datos leídos")
        print("\n        Línea que se enviaría a tu app:")
        print("        " + scraper.linea_para_api(d).replace("\t", "  |  "))
    finally:
        driver.quit()

    print("\nRESULTADO: TODO CORRECTO. El servicio podrá entrar en Auto1 y leer precios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

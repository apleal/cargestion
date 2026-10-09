"""Prueba paso a paso, en TU PC: ¿se conecta a Auto1 y lee una ficha?

No envía nada a ningún sitio ni toca tu app: abre un navegador, entra en Auto1
con tu usuario y contraseña, abre una ficha de ejemplo y te dice qué ha leído.
La contraseña solo se escribe aquí (oculta) y no se imprime ni se guarda.

    cd C:\\claude\\cargestion\\scraper_auto1
    ..\\.venv\\Scripts\\python.exe probar_auto1.py
"""
from __future__ import annotations

import getpass
import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import AUTO1_LOGIN, JS_EXTRAER, linea_para_api  # noqa: E402

LOGIN_URL = os.environ.get("AUTO1_LOGIN_URL", AUTO1_LOGIN)
FICHA_BASE = "https://www.auto1.com/es/app/merchant/car/"
CARPETA = os.path.dirname(os.path.abspath(__file__))


def ok(msg):
    print(f"  OK   {msg}")


def fallo(msg):
    print(f"  FALLO {msg}")


def captura(page, nombre):
    ruta = os.path.join(CARPETA, nombre)
    try:
        page.screenshot(path=ruta)
        print(f"       (captura guardada en {ruta})")
    except Exception:
        pass


def pedir_datos():
    email = os.environ.get("AUTO1_EMAIL") or input("Email de Auto1: ").strip()
    password = os.environ.get("AUTO1_PASSWORD") or getpass.getpass("Contraseña de Auto1 (no se ve al escribir): ")
    ficha = os.environ.get("AUTO1_FICHA") or input(
        "Referencia o enlace de una ficha de ejemplo [Enter = JV37038]: "
    ).strip() or "JV37038"
    url = ficha if ficha.startswith("http") else FICHA_BASE + ficha
    return email, password, url


def main() -> int:
    email, password, url = pedir_datos()
    visible = os.environ.get("HEADLESS", "0") == "0"
    print("\nEmpiezo la prueba (se abrirá un navegador).\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not visible, slow_mo=250 if visible else 0)
        page = browser.new_context(locale="es-ES", viewport={"width": 1366, "height": 900}).new_page()

        print("Paso 1: abrir la página de acceso de Auto1")
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
        except Exception as e:
            fallo(f"no se pudo abrir {LOGIN_URL}: {str(e)[:150]}")
            browser.close()
            return 1
        campo_email = page.locator('input[placeholder="Email"]:visible').first
        campo_pass = page.locator('input[type="password"]:visible').first
        try:
            campo_email.wait_for(timeout=15_000)
            campo_pass.wait_for(timeout=5_000)
        except PlaywrightTimeout:
            fallo("la página se abre pero no encuentro los campos de email/contraseña")
            captura(page, "probar_auto1_paso1.png")
            browser.close()
            return 1
        ok("página de acceso abierta y con sus campos")

        print("Paso 2: iniciar sesión con tu usuario")
        campo_email.fill(email)
        campo_pass.fill(password)
        campo_pass.press("Enter")
        try:
            page.wait_for_url(lambda u: "signin" not in u, timeout=30_000)
        except PlaywrightTimeout:
            fallo("el login no avanza (sigue en la página de acceso)")
            texto = page.inner_text("body").lower()
            if any(w in texto for w in ("captcha", "verific", "código", "codigo", "robot")):
                print("       Auto1 parece pedir una verificación extra (captcha o código).")
                print("       Eso impide automatizar el acceso tal cual: dímelo y vemos alternativas.")
            else:
                print("       Revisa que el email y la contraseña sean correctos.")
            captura(page, "probar_auto1_paso2.png")
            browser.close()
            return 1
        ok(f"sesión iniciada (ahora estás en {page.url[:70]})")

        print("Paso 3: abrir la ficha de ejemplo")
        print(f"       {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_selector(".minimumBid .money-value", timeout=20_000)
        except PlaywrightTimeout:
            if "signin" in page.url:
                fallo("al abrir la ficha te devuelve al login: la sesión no se mantiene")
            else:
                fallo("la ficha se abre pero no encuentro el precio (¿ficha vendida o cambió la página?)")
            captura(page, "probar_auto1_paso3.png")
            browser.close()
            return 1
        ok("ficha abierta y con precio")

        print("Paso 4: leer los datos de la ficha")
        d = page.evaluate(JS_EXTRAER)
        for clave in ("nombre", "precio", "tarifa", "referencia", "anio", "km", "combustible", "cambio"):
            print(f"       {clave:12} = {d.get(clave)}")
        captura(page, "probar_auto1_ficha.png")
        faltan = [k for k in ("nombre", "precio", "referencia") if not d.get(k)]
        if faltan:
            fallo(f"faltan datos importantes: {', '.join(faltan)}")
            browser.close()
            return 1
        ok("datos leídos")
        print("\n       Línea que se enviaría a tu app:")
        print("       " + linea_para_api(d).replace("\t", "  |  "))
        browser.close()

    print("\nRESULTADO: TODO CORRECTO. El servicio podrá entrar en Auto1 y leer precios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

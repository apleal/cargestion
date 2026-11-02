"""Prueba en TU PC: ¿lee bien un listado de Auto1 (todas sus páginas)?

Entra en Auto1 con tu cuenta (el mismo código que el servicio), abre el listado
que le des, recorre las páginas y enseña, coche a coche, lo que ha leído y qué
descartaría el filtro (km, CV, cambio, palabras). No envía nada a ningún sitio.
La contraseña solo se escribe aquí (oculta): no se imprime ni se guarda.

    cd C:\\claude\\cargestion\\scraper_auto1
    ..\\.venv\\Scripts\\python.exe probar_listado.py

Opcional, para probar el filtro: define antes KM_REF (km del coche de referencia),
KM_TOL (def. 10000), CV, CV_TOL (def. 5), CAMBIO (manual/automatico), PALABRAS.
"""
from __future__ import annotations

import getpass
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import listado  # noqa: E402
import scraper  # noqa: E402

CARPETA = os.path.dirname(os.path.abspath(__file__))


def ok(msg):
    print(f"  OK    {msg}")


def fallo(msg):
    print(f"  FALLO {msg}")


def _eur(n):
    return "—" if n is None else f"{n:,.0f} €".replace(",", ".")


def filtro_desde_entorno() -> dict:
    km_ref = os.environ.get("KM_REF")
    tol = int(os.environ.get("KM_TOL", "10000"))
    return {
        "km_min": max(0, int(km_ref) - tol) if km_ref else None,
        "km_max": int(km_ref) + tol if km_ref else None,
        "potencia_cv": int(os.environ["CV"]) if os.environ.get("CV") else None,
        "tolerancia_cv": int(os.environ.get("CV_TOL", "5")),
        "cambio": os.environ.get("CAMBIO", ""),
        "palabras_titulo": os.environ.get("PALABRAS", ""),
    }


def main() -> int:
    email = os.environ.get("AUTO1_EMAIL") or input("Email de Auto1: ").strip()
    password = os.environ.get("AUTO1_PASSWORD") or getpass.getpass(
        "Contraseña de Auto1 (no se ve al escribir): "
    )
    url = os.environ.get("AUTO1_LISTADO") or input("Enlace del listado de Auto1 (con tus filtros): ").strip()
    if "/merchant/cars" not in url:
        fallo("ese enlace no es un listado de Auto1 (debe contener /merchant/cars)")
        return 1
    filtro = filtro_desde_entorno()
    max_paginas = int(os.environ.get("MAX_PAGINAS", "15"))

    cfg = {"email": email, "password": password, "headless": os.environ.get("HEADLESS", "0") != "0"}

    print("\nPaso 1: abrir Chrome")
    try:
        driver = scraper.crear_driver(cfg)
    except Exception as e:
        fallo(f"no se pudo arrancar Chrome: {str(e)[:300]}")
        return 1
    ok("Chrome abierto")

    try:
        print("Paso 2: entrar en Auto1")
        try:
            scraper.login(driver, cfg)
        except RuntimeError as e:
            fallo(str(e))
            return 1
        ok("sesión iniciada")

        print(f"Paso 3: leer el listado (hasta {max_paginas} páginas)")
        try:
            res = listado.leer_listado(driver, url, max_paginas=max_paginas, log=print)
        except RuntimeError as e:
            fallo(str(e))
            return 1
        tarjetas = res["tarjetas"]
        if not tarjetas:
            fallo(res["aviso"] or "no se ha leído ningún coche")
            ruta = os.path.join(CARPETA, "probar_listado.html")
            try:
                with open(ruta, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                driver.save_screenshot(os.path.join(CARPETA, "probar_listado.png"))
                print(f"        (guardados {ruta} y probar_listado.png: mándamelos para ver qué ha pasado)")
            except Exception:
                pass
            return 1
        ok(f"{len(tarjetas)} coches leídos en {res['paginas']} página(s)")
        if res["aviso"]:
            print(f"        AVISO: {res['aviso']}")

        tipos = Counter(t["tipo"] or "sin precio" for t in tarjetas)
        print("        Por tipo: " + ", ".join(f"{k}: {v}" for k, v in tipos.items()))

        print("Paso 4: aplicar el filtro")
        activo = {k: v for k, v in filtro.items() if v not in (None, "", 0)}
        print(f"        Filtro: {activo or 'ninguno (define KM_REF, CV, CAMBIO… para probarlo)'}")
        buenas, malas = listado.filtrar(tarjetas, filtro)
        ok(f"{len(buenas)} encajan, {len(malas)} descartados")

        print("\n  ENCAJAN (ordenados por precio):")
        print(f"  {'Ref':8} {'Tipo':10} {'Precio':>10} {'Km':>8} {'Año':>5} {'CV':>4} {'Cambio':9} Título")
        for t in sorted(buenas, key=lambda x: x["precio"] or 0):
            print(
                f"  {t['referencia']:8} {t['tipo'] or '-':10} {_eur(t['precio']):>10} "
                f"{(t['km'] or 0):>8} {t['anio'] or 0:>5} {t['cv'] or 0:>4} {t['cambio'] or '-':9} {t['nombre'][:50]}"
            )
        if malas:
            print("\n  DESCARTADOS (motivos):")
            for motivo, n in Counter(m.split(" (")[0] for _, m in malas).most_common():
                print(f"    {n:3} × {motivo}")
    finally:
        driver.quit()

    print("\nRESULTADO: listado leído. Pásame el resumen (o la captura si algo no cuadra).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

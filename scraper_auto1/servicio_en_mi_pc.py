"""Ejecuta el servicio de Auto1 en TU PC (sin depender de EasyPanel).

Hace exactamente lo mismo que el servicio del servidor: avisa a la app (latido),
recoge el botón «Buscar ahora» y «Actualizar ahora», y hace la pasada diaria y
las búsquedas de las 07:00 si el PC está encendido y esta ventana abierta.

Los datos se piden aquí, por pantalla; no se guardan en ningún fichero. Si ya
están definidos como variables de entorno (APP_URL, APP_TOKEN, AUTO1_EMAIL,
AUTO1_PASSWORD) no los pregunta.

    cd C:\\claude\\cargestion\\scraper_auto1
    ..\\.venv\\Scripts\\python.exe servicio_en_mi_pc.py

Para parar: Ctrl+C. IMPORTANTE: si también está encendido el servicio de
EasyPanel, apágalo mientras uses este (o haréis la misma pasada los dos).
"""
from __future__ import annotations

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def pedir(nombre: str, pregunta: str, secreto: bool = False) -> None:
    if os.environ.get(nombre):
        return
    valor = (getpass.getpass(pregunta + " (no se ve al escribir): ") if secreto else input(pregunta + ": ")).strip()
    if not valor:
        sys.exit(f"Falta {nombre}.")
    os.environ[nombre] = valor


def main() -> None:
    print(__doc__.split("Los datos")[0])
    pedir("APP_URL", "Dirección de tu app (p. ej. https://tu-dominio)")
    pedir(
        "APP_TOKEN",
        "Token de la API (el de «python manage.py crear_token_api --usuario n8n»; sin la palabra Token)",
        secreto=True,
    )
    pedir("AUTO1_EMAIL", "Email de Auto1")
    pedir("AUTO1_PASSWORD", "Contraseña de Auto1", secreto=True)
    # En tu PC se ve el navegador (así ves lo que hace); HEADLESS=1 para ocultarlo.
    os.environ.setdefault("HEADLESS", "0")
    os.environ.setdefault("TZ_NAME", "Europe/Madrid")

    import scraper  # noqa: E402  (lee las variables de entorno al importar config())

    print("\nServicio en marcha. Deja esta ventana abierta. Ctrl+C para parar.\n")
    try:
        scraper.main()
    except KeyboardInterrupt:
        print("\nServicio parado.")


if __name__ == "__main__":
    main()

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


def pedir_url_app() -> None:
    """La dirección de TU app (PujaAuto), no la de Auto1: se comprueba antes de seguir."""
    while True:
        pedir_url = os.environ.get("APP_URL") or input(
            "Dirección de TU app PujaAuto, la que abres en el navegador para entrar\n"
            "(solo el dominio, p. ej. https://tu-dominio.com): "
        )
        url = pedir_url.strip().rstrip("/")
        if not url:
            sys.exit("Falta APP_URL.")
        if "://" not in url:
            url = "https://" + url
        if "auto1.com" in url.lower():
            print("\n  Esa es una dirección de Auto1. Aquí hace falta la de TU app (PujaAuto),\n"
                  "  la que abres para ver tus subastas y Oportunidades. Inténtalo otra vez.\n")
            os.environ.pop("APP_URL", None)
            continue
        if "?" in url or len(url.split("/", 3)) > 3:
            url = "/".join(url.split("/", 3)[:3])  # solo esquema + dominio
        os.environ["APP_URL"] = url
        print(f"  Usaré: {url}")
        return


def main() -> None:
    print(__doc__.split("Los datos")[0])
    pedir_url_app()
    pedir(
        "APP_TOKEN",
        "Token de la API (el de «python manage.py crear_token_api --usuario n8n»; sin la palabra Token)",
        secreto=True,
    )
    pedir("AUTO1_EMAIL", "Email de Auto1")
    pedir("AUTO1_PASSWORD", "Contraseña de Auto1", secreto=True)
    # Opcional: para que ESTE servicio también avise por Telegram (Intro = no avisar desde el PC).
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        tg = getpass.getpass("Token del bot de Telegram (opcional, Intro para omitir): ").strip()
        if tg:
            os.environ["TELEGRAM_BOT_TOKEN"] = tg
            os.environ["TELEGRAM_CHAT_ID"] = os.environ.get("TELEGRAM_CHAT_ID") or input("Chat ID de Telegram: ").strip()
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

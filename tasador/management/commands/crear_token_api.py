"""Crea (o reutiliza) un usuario dedicado y muestra su token de la API.

Pensado para automatizaciones (n8n, scripts) que no deben usar tu usuario
personal. El token se guarda en la credencial HTTP de n8n; no lo pongas en
ningún fichero del repositorio.

    python manage.py crear_token_api --usuario n8n
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Crea un usuario de servicio y muestra su token de la API (para n8n u otras automatizaciones)."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", default="n8n", help="Nombre del usuario de servicio.")

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["usuario"]
        user, creado = User.objects.get_or_create(
            username=username, defaults={"is_staff": False, "is_superuser": False}
        )
        if creado:
            user.set_unusable_password()  # no inicia sesión en la web, solo usa el token
            user.save()
        token, _ = Token.objects.get_or_create(user=user)
        self.stdout.write(
            self.style.SUCCESS(
                f"Usuario '{username}' {'creado' if creado else 'ya existía'}. "
                f"Token: {token.key}"
            )
        )
        self.stdout.write(
            "Cabecera para las peticiones: "
            f'Authorization: Token {token.key}'
        )

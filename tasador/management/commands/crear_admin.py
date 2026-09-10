"""Crea o actualiza un superusuario a partir de variables de entorno.

Idempotente: se ejecuta en cada arranque del contenedor. Si no están definidas
``DJANGO_SUPERUSER_USERNAME`` y ``DJANGO_SUPERUSER_PASSWORD`` no hace nada.

    DJANGO_SUPERUSER_USERNAME=admin
    DJANGO_SUPERUSER_PASSWORD=...
    DJANGO_SUPERUSER_EMAIL=...   (opcional)
"""
from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea/actualiza el superusuario desde DJANGO_SUPERUSER_*."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")

        if not username or not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_USERNAME/PASSWORD no definidos: no se crea admin."
            )
            return

        User = get_user_model()
        user, creado = User.objects.get_or_create(username=username)
        user.email = email or user.email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Superusuario {'creado' if creado else 'actualizado'}: {username}"
            )
        )

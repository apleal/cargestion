"""Configuración de pytest.

Los tests del motor de cálculo (``tests/test_motor.py``, ``test_tramos.py``,
``test_facturas_bca.py``) no tocan la base de datos ni Django. Los tests que sí
usan modelos deben marcarse con ``@pytest.mark.django_db``.
"""
import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


@pytest.fixture(autouse=True)
def _sin_redireccion_ssl(settings):
    """En pruebas no forzamos HTTPS (el cliente de test usa http)."""
    settings.SECURE_SSL_REDIRECT = False

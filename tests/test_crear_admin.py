"""Pruebas del comando crear_admin."""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_no_hace_nada_sin_variables(monkeypatch, capsys):
    monkeypatch.delenv("DJANGO_SUPERUSER_USERNAME", raising=False)
    monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)
    call_command("crear_admin")
    assert get_user_model().objects.count() == 0


def test_crea_y_luego_actualiza(monkeypatch):
    User = get_user_model()
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "admin")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "clave-inicial-123")
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "a@b.com")

    call_command("crear_admin")
    u = User.objects.get(username="admin")
    assert u.is_superuser and u.is_staff
    assert u.check_password("clave-inicial-123")

    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "clave-nueva-456")
    call_command("crear_admin")
    u.refresh_from_db()
    assert User.objects.filter(username="admin").count() == 1
    assert u.check_password("clave-nueva-456")

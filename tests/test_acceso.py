"""Pantalla de acceso, marca de la aplicación y admin."""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

pytestmark = pytest.mark.django_db

PASSWORD = "una-clave-larga-123"


@pytest.fixture
def usuario(client):
    call_command("seed_datos")
    return get_user_model().objects.create_user("alberto", password=PASSWORD)


def test_el_acceso_muestra_la_marca_y_el_lema(client, settings):
    html = client.get(reverse("login")).content.decode()
    assert settings.APP_NAME in html
    assert settings.APP_TAGLINE in html
    assert "<title>Acceso · " + settings.APP_NAME in html


def test_la_marca_se_cambia_con_la_configuracion(client, settings):
    settings.APP_NAME = "MarcaNueva"
    settings.APP_TAGLINE = "El lema nuevo"
    html = client.get(reverse("login")).content.decode()
    assert "MarcaNueva" in html and "El lema nuevo" in html
    assert 'property="og:title" content="MarcaNueva"' in html


def test_el_acceso_no_enseña_la_navegacion_de_la_aplicacion(client):
    html = client.get(reverse("login")).content.decode()
    for enlace in (reverse("panel"), reverse("sesion_lista"), reverse("favoritos_lista")):
        assert f'href="{enlace}"' not in html
    assert "topbar" not in html


def test_el_acceso_no_se_indexa_y_prepara_la_vista_previa_en_redes(client):
    html = client.get(reverse("login")).content.decode()
    assert 'name="robots" content="noindex, nofollow"' in html
    assert 'property="og:description"' in html


def test_los_campos_tienen_el_autocompletado_correcto(client):
    html = client.get(reverse("login")).content.decode()
    assert 'autocomplete="username"' in html
    assert 'autocomplete="current-password"' in html
    assert 'name="password"' in html and 'type="password"' in html
    assert "Mostrar la contraseña" in html  # botón de ver/ocultar


def test_clave_incorrecta_da_un_mensaje_claro_sin_decir_cual_falla(client, usuario):
    r = client.post(reverse("login"), {"username": "alberto", "password": "mala"})
    assert r.status_code == 200
    html = r.content.decode()
    assert "Usuario o contraseña incorrectos" in html
    assert 'role="alert"' in html
    r2 = client.post(reverse("login"), {"username": "noexiste", "password": "mala"})
    assert "Usuario o contraseña incorrectos" in r2.content.decode()


def test_entrar_lleva_al_panel_o_a_donde_se_iba(client, usuario):
    r = client.post(reverse("login"), {"username": "alberto", "password": PASSWORD})
    assert r.status_code == 302 and r.url == reverse("panel")
    client.logout()
    destino = reverse("seguimiento_auto1")
    r = client.post(
        reverse("login") + f"?next={destino}", {"username": "alberto", "password": PASSWORD, "next": destino}
    )
    assert r.url == destino


def test_la_pagina_de_acceso_conserva_el_next(client):
    html = client.get(reverse("login"), {"next": "/seguimiento/"}).content.decode()
    assert 'name="next" value="/seguimiento/"' in html


def test_si_ya_has_entrado_el_acceso_te_manda_al_panel(client, usuario):
    client.login(username="alberto", password=PASSWORD)
    r = client.get(reverse("login"))
    assert r.status_code == 302 and r.url == reverse("panel")


def test_toda_la_aplicacion_usa_la_marca_en_cabecera_y_titulo(client, usuario, settings):
    client.login(username="alberto", password=PASSWORD)
    html = client.get(reverse("panel")).content.decode()
    assert f'class="brand">{settings.APP_NAME}</a>' in html
    assert f"<title>Panel · {settings.APP_NAME}" in html
    assert "cargestion" not in html.split("</header>")[0]
    for nombre in ("sesion_lista", "favoritos_lista", "seguimiento_auto1", "valoracion_lista"):
        assert f"· {settings.APP_NAME}</title>" in client.get(reverse(nombre)).content.decode()


def test_el_admin_lleva_la_marca_y_enlaza_con_el_acceso_de_la_app(client, settings):
    html = client.get(reverse("admin:login")).content.decode()
    assert f"{settings.APP_NAME} · Administración" in html
    assert "Zona de administración" in html and reverse("login") in html


def test_el_admin_usa_los_colores_de_la_marca(client):
    html = client.get(reverse("admin:login")).content.decode()
    assert "--secondary: #00519e" in html and "--header-bg: #00519e" in html
    assert "--accent: #bcdcf7" in html  # el nombre de la cabecera debe leerse sobre el azul

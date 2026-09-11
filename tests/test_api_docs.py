"""La documentacion OpenAPI/Swagger carga (util para ver los campos exactos al
montar las peticiones HTTP en n8n)."""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_schema_y_swagger_cargan(client):
    call_command("seed_datos")
    User = get_user_model()
    User.objects.create_user("doc", password="doc")
    client.login(username="doc", password="doc")

    schema = client.get("/api/schema/")
    assert schema.status_code == 200

    swagger = client.get("/api/docs/")
    assert swagger.status_code == 200

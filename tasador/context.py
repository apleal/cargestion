from django.conf import settings


def marca(request):
    """Nombre y lema de la aplicación disponibles en todas las plantillas."""
    return {"app_name": settings.APP_NAME, "app_tagline": settings.APP_TAGLINE}

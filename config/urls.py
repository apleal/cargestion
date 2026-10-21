from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from tasador.forms import AccesoForm

admin.site.site_header = f"{settings.APP_NAME} · Administración"
admin.site.site_title = settings.APP_NAME
admin.site.index_title = "Configuración"
admin.site.site_url = "/"

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "acceso/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            authentication_form=AccesoForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api_docs"),
    path("api/", include("tasador.api_urls")),
    path("", include("tasador.urls")),
]

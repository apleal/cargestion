import re
from decimal import Decimal  # noqa: F401
from urllib.parse import urlparse

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone

from . import models
from .parser import parsear_linea_auto1


class VehiculoForm(forms.ModelForm):
    class Meta:
        model = models.Vehiculo
        fields = [
            "matricula", "bastidor", "marca", "modelo", "version",
            "potencia_kw", "potencia_cv", "combustible", "cambio",
            "fecha_primera_matriculacion", "anio",
        ]
        widgets = {
            "fecha_primera_matriculacion": forms.DateInput(attrs={"type": "date"}),
        }


class ValoracionForm(forms.ModelForm):
    class Meta:
        model = models.Valoracion
        fields = [
            "sesion_subasta", "proveedor", "tipo_subasta", "ubicacion",
            "lote_id", "orden_lote", "url_anuncio", "zona_origen",
            "fecha_valoracion", "fecha_subasta",
            "regimen_fiscal", "iva_anuncio", "precio_salida",
            "precio_venta_estimado", "precio_anunciado",
            "estado_carroceria", "piezas_pintura", "descuento_comision_pct",
            "coste_alberto", "coste_gasolina", "coste_pintura_por_pieza",
            "coste_garantia", "coste_mecanica", "coste_cambio_titularidad",
            "coste_transporte", "coste_itv", "coste_tapiceria", "coste_tintado",
            "coste_otros",
            "estado", "observaciones",
        ]
        widgets = {
            "fecha_valoracion": forms.DateInput(attrs={"type": "date"}),
            "fecha_subasta": forms.DateInput(attrs={"type": "date"}),
            "observaciones": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        params = models.ParametrosCoste.vigentes()
        defaults = {
            "coste_alberto": params.comision_alberto,
            "coste_gasolina": params.gasolina,
            "coste_pintura_por_pieza": params.pintura_por_pieza,
            "coste_garantia": params.garantia,
            "coste_mecanica": params.mecanica,
            "coste_cambio_titularidad": params.cambio_titularidad,
            "coste_transporte": params.transporte,
        }
        if not self.instance.pk:
            for campo, valor in defaults.items():
                self.fields[campo].initial = valor
            estado_pdte = models.EstadoValoracion.objects.filter(
                nombre="Pendiente de valorar"
            ).first()
            if estado_pdte:
                self.fields["estado"].initial = estado_pdte.pk
            tipo = models.TipoSubasta.objects.filter(es_predeterminado=True).first()
            if tipo:
                self.fields["tipo_subasta"].initial = tipo.pk
                self.fields["proveedor"].initial = tipo.proveedor_id


class SesionSubastaForm(forms.ModelForm):
    class Meta:
        model = models.SesionSubasta
        fields = ["proveedor", "ubicacion", "fecha", "hora_inicio", "hora_fin",
                  "identificador_venta", "url", "notas"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "hora_inicio": forms.TimeInput(attrs={"type": "time"}),
            "hora_fin": forms.TimeInput(attrs={"type": "time"}),
            "notas": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ubicacion"].queryset = models.Ubicacion.objects.filter(
            activa=True
        ).select_related("proveedor")
        if not self.instance.pk:
            bca = models.Proveedor.objects.filter(nombre="BCA").first()
            if bca:
                self.fields["proveedor"].initial = bca.pk
            self.fields["fecha"].initial = timezone.localdate()


class PegarLotesForm(forms.Form):
    texto = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 8,
            "placeholder": "Pega aquí las líneas del scraper (una por coche, tal cual salen del portapapeles)…",
        }),
        label="Pegar del portapapeles",
    )


class AccesoForm(AuthenticationForm):
    """Formulario de acceso con textos claros y el comportamiento del navegador
    bien configurado (autocompletado de usuario y contraseña)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Usuario o contraseña incorrectos. Revisa mayúsculas y minúsculas.",
        "inactive": "Esta cuenta está desactivada.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuario"
        self.fields["password"].label = "Contraseña"
        self.fields["username"].widget.attrs.update(
            {"autocomplete": "username", "autofocus": True, "placeholder": "Tu usuario",
             "autocapitalize": "none", "spellcheck": "false"}
        )
        self.fields["password"].widget.attrs.update(
            {"autocomplete": "current-password", "placeholder": "Tu contraseña"}
        )


class BusquedaOportunidadForm(forms.ModelForm):
    """Crear/editar una búsqueda de oportunidades. Al crear, el coche de
    referencia sale de pegar la línea del plugin; al editar se puede corregir a
    mano o pegar otra línea para cambiarlo."""

    linea_plugin = forms.CharField(
        label="Línea del plugin del coche de referencia",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Pega aquí la línea que copia el plugin desde la ficha del coche"}),
        help_text="Es la misma línea que pegas al tasar un coche de Auto1. Se leen marca, modelo, versión, año y km.",
    )

    CAMPOS_REFERENCIA = ("marca", "modelo", "version", "anio", "km_referencia", "combustible", "cambio")

    class Meta:
        model = models.BusquedaOportunidad
        fields = [
            "url_listado", "precio_venta_estimado", "tolerancia_km", "palabras_titulo",
            "potencia_cv", "tolerancia_cv", "estado_carroceria", "piezas_pintura",
            "marca", "modelo", "version", "anio", "km_referencia", "combustible", "cambio",
            "coste_alberto", "coste_gasolina", "coste_pintura_por_pieza", "coste_garantia",
            "coste_mecanica", "coste_cambio_titularidad", "coste_transporte", "coste_itv",
            "coste_tapiceria", "coste_tintado", "coste_otros", "activa",
        ]
        widgets = {"url_listado": forms.URLInput(attrs={"placeholder": "https://www.auto1.com/es/app/merchant/cars?…"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance.pk is None
        self.fields["tolerancia_cv"].required = False
        if self.creando:
            # el coche de referencia sale de la línea; los costes, de los parámetros
            ocultos = (*self.CAMPOS_REFERENCIA, "piezas_pintura", "activa") + tuple(
                f for f in self.fields if f.startswith("coste_")
            )
            for campo in ocultos:
                self.fields.pop(campo, None)
            self.fields["linea_plugin"].required = True
            normal = models.EstadoCarroceria.objects.filter(nombre="Estado normal").first()
            if normal:
                self.fields["estado_carroceria"].initial = normal.pk

    def clean_url_listado(self):
        url = self.cleaned_data["url_listado"].strip()
        partes = urlparse(url)
        host = (partes.hostname or "").lower()
        if partes.scheme != "https" or not (host == "auto1.com" or host.endswith(".auto1.com")):
            raise forms.ValidationError("Debe ser un enlace de Auto1 (https://www.auto1.com/…).")
        if re.search(r"/merchant/car/[^/]+", partes.path):
            raise forms.ValidationError(
                "Ese enlace es la ficha de un solo coche. Hace falta el de la lista de resultados: "
                "vuelve atrás hasta ver la rejilla de coches con tus filtros y copia esa dirección "
                "(empieza por …/merchant/cars?…, con «cars» en plural)."
            )
        if "/merchant/cars" not in partes.path:
            raise forms.ValidationError(
                "Eso no es un listado de coches de Auto1. Copia la dirección de la página de resultados "
                "(la que contiene /merchant/cars)."
            )
        return url

    def clean_tolerancia_cv(self):
        tol = self.cleaned_data.get("tolerancia_cv")
        return 5 if tol is None else tol

    def clean_precio_venta_estimado(self):
        precio = self.cleaned_data["precio_venta_estimado"]
        if precio <= 0:
            raise forms.ValidationError("El precio de venta debe ser mayor que 0.")
        return precio

    def _aplicar(self, campo, valor):
        if campo in self.fields:
            self.cleaned_data[campo] = valor
        else:
            setattr(self.instance, campo, valor)

    def clean(self):
        datos = super().clean()
        linea = (datos.get("linea_plugin") or "").strip()
        if not linea:
            return datos
        primera = next((l for l in linea.splitlines() if l.strip()), "")
        lote = parsear_linea_auto1(primera)
        if primera.count("\t") < 5 or not (lote.marca and lote.modelo and lote.anio and lote.kilometros):
            self.add_error(
                "linea_plugin",
                "No reconozco la línea. Pégala tal cual la copia el plugin de Chrome desde la ficha "
                "del coche (campos separados por tabulador: nombre, precio, tarifa, referencia, año, km…).",
            )
            return datos
        valores = {
            "marca": lote.marca, "modelo": lote.modelo, "version": lote.version,
            "anio": lote.anio, "km_referencia": lote.kilometros,
            "combustible": lote.combustible or "", "cambio": lote.cambio or "",
        }
        for campo, valor in valores.items():
            self._aplicar(campo, valor)
        self.instance.referencia_origen = lote.referencia or ""
        return datos

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.creando:
            obj.aplicar_costes_por_defecto()
            obj.piezas_pintura = obj.estado_carroceria.piezas_estimadas if obj.estado_carroceria else 4
        elif "estado_carroceria" in self.changed_data and "piezas_pintura" not in self.changed_data:
            if obj.estado_carroceria:
                obj.piezas_pintura = obj.estado_carroceria.piezas_estimadas
        if commit:
            obj.save()
        return obj

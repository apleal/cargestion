"""Tasación IA: formulario de revisión de los datos del coche antes de crearlo."""
from __future__ import annotations

from datetime import date

from django import forms

from .models import Cambio, Combustible


class DatosCocheForm(forms.Form):
    """Los datos leídos (por IA o a mano) para que la persona los revise y corrija."""

    marca = forms.CharField(max_length=40, label="Marca")
    modelo = forms.CharField(max_length=80, label="Modelo")
    version = forms.CharField(max_length=120, required=False, label="Versión / motor")
    acabado = forms.CharField(
        max_length=40, required=False, label="Acabado",
        help_text="Solo se usan anuncios cuyo título lo lleve (p. ej. FR, VZ). Vacío = cualquiera.",
    )
    anio = forms.IntegerField(required=False, min_value=1979, max_value=date.today().year + 1, label="Año")
    fecha_matriculacion = forms.DateField(
        required=False, label="Fecha de matriculación", input_formats=["%Y-%m-%d", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    km = forms.IntegerField(min_value=1, max_value=1_500_000, label="Kilómetros")
    combustible = forms.ChoiceField(choices=[("", "—")] + list(Combustible.choices), required=False, label="Combustible")
    cambio = forms.ChoiceField(choices=[("", "—")] + list(Cambio.choices), required=False, label="Cambio")
    potencia_cv = forms.IntegerField(required=False, min_value=10, max_value=2000, label="Potencia (CV)")
    matricula = forms.CharField(max_length=10, required=False, label="Matrícula")
    vin = forms.CharField(max_length=20, required=False, label="Bastidor (VIN)")
    precio_compra = forms.IntegerField(
        required=False, min_value=100, max_value=5_000_000, label="Precio de compra / que piden (€)",
        help_text="Si lo sabes, la rejilla te dirá si compensa. Si no, déjalo vacío: saldrá la puja máxima.",
    )
    observaciones = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 5}), label="Observaciones")
    carroceria_sin_danos = forms.BooleanField(required=False, label="Carrocería sin daños declarados")
    avisos = forms.CharField(required=False, widget=forms.HiddenInput())
    origen = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean_matricula(self):
        return self.cleaned_data["matricula"].upper().replace(" ", "")

    def clean_vin(self):
        return self.cleaned_data["vin"].upper().replace(" ", "")

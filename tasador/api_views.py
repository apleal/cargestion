"""API para automatizaciones externas (p. ej. un flujo de n8n que vuelve a
escanear en Auto1 los coches que aún no se han vendido).

Autenticación: token de DRF. Cabecera ``Authorization: Token <token>``.
El token se crea para un usuario dedicado (no el tuyo de la web) con:

    python manage.py crear_token_api --usuario n8n

Toda la lógica de negocio (deduplicación, cálculo REBU/Auto1, herencia de
costes al retasar) vive en ``services``/``calculo``: esta API solo la invoca,
nunca la repite. Así un cambio en las fórmulas no se puede desincronizar entre
la web y las automatizaciones.
"""
from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Proveedor
from .parser import parsear_linea_auto1


class SeguimientoAuto1View(APIView):
    """GET: coches de Auto1 que hay que volver a comprobar (no vendidos/descartados)."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        salida = []
        for v in services.coches_auto1_en_seguimiento():
            salida.append(
                {
                    "valoracion_id": v.pk,
                    "vehiculo_id": v.vehiculo_id,
                    "referencia": v.lote_id,
                    "url": f"https://www.auto1.com/es/app/merchant/car/{v.lote_id}",
                    "marca": v.vehiculo.marca,
                    "modelo": v.vehiculo.modelo,
                    "version": v.vehiculo.version,
                    "anio": v.vehiculo.anio,
                    "km_ultimo_conocido": v.vehiculo.km_ultimo_conocido,
                    "estado": v.estado.nombre if v.estado else None,
                    "ultimo_precio_salida": str(v.precio_salida),
                    "ultima_iva_anuncio": str(v.iva_anuncio),
                    "ultima_fecha_escaneo": v.created_at.isoformat(),
                    "puja_maxima_15": (
                        str(v.r_puja_maxima_principal)
                        if v.r_puja_maxima_principal is not None
                        else None
                    ),
                }
            )
        return Response(salida)


class EscaneoAuto1InputSerializer(serializers.Serializer):
    # La misma línea de 8 campos que produce el plugin de Chrome:
    # nombre \t precio_subasta \t iva \t referencia \t año \t km \t combustible \t cambio
    texto = serializers.CharField(allow_blank=False, trim_whitespace=False)


class RegistrarEscaneoAuto1View(APIView):
    """POST: registra un nuevo escaneo de un coche de Auto1 (retasación automática).

    Body JSON: {"texto": "<la línea de 8 campos del plugin>"}

    Reutiliza exactamente el mismo camino que pegar a mano en la app: detecta
    si el coche ya existía (por marca+modelo+año+km), enlaza la retasación,
    hereda venta/costes de la anterior, y calcula la puja máxima y el "tier"
    (15/12/10 %) con el motor real.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        entrada = EscaneoAuto1InputSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        if not Proveedor.objects.filter(nombre="Auto1").exists():
            return Response(
                {"error": "El proveedor Auto1 no está configurado (ejecuta seed_datos)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lote = parsear_linea_auto1(entrada.validated_data["texto"])
        if lote.dudosos:
            return Response(
                {"error": "No se pudo interpretar la línea.", "dudosos": lote.dudosos},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sesion = services.sesion_auto1_de_hoy(usuario=request.user)
        v, es_retasacion = services.crear_valoracion_desde_lote(
            lote, sesion, usuario=request.user
        )

        return Response(
            {
                "valoracion_id": v.pk,
                "vehiculo_id": v.vehiculo_id,
                "referencia": v.lote_id,
                "es_retasacion": es_retasacion,
                "precio_salida": str(v.precio_salida),
                "precio_venta_estimado": str(v.precio_venta_estimado),
                "coste_total": str(v.r_coste_total),
                "beneficio_neto": str(v.r_beneficio_neto),
                "rentabilidad_coste": str(v.r_rentabilidad_coste),
                "puja_maxima_15": (
                    str(v.r_puja_maxima_principal)
                    if v.r_puja_maxima_principal is not None
                    else None
                ),
                "tier": services.tier_precio_salida(v),
                "en_precio": services.en_precio(v),
            },
            status=status.HTTP_201_CREATED,
        )

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

from decimal import Decimal

from rest_framework import serializers, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import PasadaAuto1, Proveedor, Valoracion
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

        nuevo_precio = Decimal(lote.precio_subasta or 0)
        nuevo_iva = Decimal(lote.iva_anuncio or 0)
        anterior = (
            Valoracion.objects.filter(
                proveedor__nombre="Auto1", lote_id=lote.referencia, vehiculo__matricula=""
            )
            .order_by("-created_at")
            .first()
        )

        # Pasada diaria sin novedades: no se acumula una tasación idéntica por
        # coche y día; solo se marca como comprobado (updated_at).
        if anterior and anterior.precio_salida == nuevo_precio and anterior.iva_anuncio == nuevo_iva:
            anterior.save(update_fields=["updated_at"])
            return Response(
                {
                    "valoracion_id": anterior.pk,
                    "vehiculo_id": anterior.vehiculo_id,
                    "referencia": anterior.lote_id,
                    "sin_cambios": True,
                    "es_retasacion": True,
                    "precio_salida": str(anterior.precio_salida),
                    "precio_anterior": str(anterior.precio_salida),
                    "variacion": "0",
                    "puja_maxima_15": (
                        str(anterior.r_puja_maxima_principal)
                        if anterior.r_puja_maxima_principal is not None
                        else None
                    ),
                    "tier": services.tier_precio_salida(anterior),
                    "en_precio": services.en_precio(anterior),
                },
                status=status.HTTP_200_OK,
            )

        sesion = services.sesion_auto1_continua(usuario=request.user)
        v, es_retasacion = services.crear_valoracion_desde_lote(
            lote, sesion, usuario=request.user
        )

        return Response(
            {
                "valoracion_id": v.pk,
                "vehiculo_id": v.vehiculo_id,
                "referencia": v.lote_id,
                "sin_cambios": False,
                "es_retasacion": es_retasacion,
                "precio_salida": str(v.precio_salida),
                "precio_anterior": str(anterior.precio_salida) if anterior else None,
                "variacion": str(v.precio_salida - anterior.precio_salida) if anterior else None,
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


class PasadaAuto1Serializer(serializers.ModelSerializer):
    class Meta:
        model = PasadaAuto1
        fields = [
            "ok", "revisados", "con_cambios", "sin_cambios",
            "sin_precio", "errores", "detalle",
        ]


class RegistrarPasadaAuto1View(APIView):
    """POST: el servicio de seguimiento deja constancia de cada pasada (también
    de las fallidas). El Panel usa estos partes para avisar si el servicio
    falla o simplemente deja de ejecutarse."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        entrada = PasadaAuto1Serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        pasada = entrada.save()
        return Response({"id": pasada.pk}, status=status.HTTP_201_CREATED)

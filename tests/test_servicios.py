"""Pruebas de integración: modelos + motor a través de ``services``."""
from decimal import Decimal

import pytest
from django.core.management import call_command

from tasador import models, services

pytestmark = pytest.mark.django_db


@pytest.fixture
def datos():
    call_command("seed_datos")


def _valoracion(tipo_nombre="BCA normal", **extra):
    tipo = models.TipoSubasta.objects.get(nombre=tipo_nombre)
    estado = models.EstadoValoracion.objects.get(nombre="Interesante")
    veh = models.Vehiculo.objects.create(matricula="1234ABC", marca="SEAT", modelo="Arona")
    campos = dict(
        vehiculo=veh,
        proveedor=tipo.proveedor,
        tipo_subasta=tipo,
        estado=estado,
        precio_venta_estimado=Decimal("15000"),
        piezas_pintura=4,
        coste_alberto=Decimal("50"),
        coste_gasolina=Decimal("40"),
        coste_pintura_por_pieza=Decimal("87"),
        coste_garantia=Decimal("225"),
        coste_mecanica=Decimal("200"),
        coste_cambio_titularidad=Decimal("72"),
        coste_transporte=Decimal("350"),
    )
    campos.update(extra)
    return models.Valoracion.objects.create(**campos)


def test_seed_crea_bca_y_tarifa(datos):
    bca = models.Proveedor.objects.get(nombre="BCA")
    tarifa = services.tarifa_vigente(bca)
    assert tarifa is not None
    assert tarifa.tramos.count() == 17
    assert tarifa.validar_tramos() == []


def test_recalcular_guarda_puja_maxima(datos):
    v = _valoracion()
    services.recalcular_y_guardar(v)
    v.refresh_from_db()
    assert v.r_puja_maxima_principal is not None
    assert Decimal("10000") < v.r_puja_maxima_principal < Decimal("11000")
    assert v.r_beneficio_neto > 0
    assert v.tarifa_comision_aplicada is not None
    assert any(k.startswith("0.15") for k in v.r_escenarios)


def test_concurso_usa_cuota_plana(datos):
    v = _valoracion(tipo_nombre="Concurso BCA")
    res = services.calcular(v, puja=Decimal("10000"))
    assert res.desglose_para_puja.coste_adquisicion == Decimal("10351.00")


def test_auto1_provider_y_calculo(datos):
    from tasador.models import EstadoValoracion, Proveedor, SesionSubasta, Vehiculo

    auto1 = Proveedor.objects.get(nombre="Auto1")
    tipo = auto1.tipos_subasta.get(nombre="Auto1")
    assert tipo.modo == "iva_anuncio"
    assert auto1.conceptos_fijos.filter(nombre__icontains="Auto1").exists()

    sesion = SesionSubasta.objects.create(
        proveedor=auto1, ubicacion=auto1.ubicaciones.first(), fecha="2026-09-20"
    )
    veh = Vehiculo.objects.create(matricula="0000XXX", marca="VW", modelo="Golf")
    v = models.Valoracion.objects.create(
        vehiculo=veh, proveedor=auto1, tipo_subasta=tipo, sesion_subasta=sesion,
        estado=EstadoValoracion.objects.get(nombre="Interesante"),
        iva_anuncio=Decimal("307.02"),
        precio_venta_estimado=Decimal("23500"),
        piezas_pintura=3,
        coste_alberto=Decimal("50"), coste_gasolina=Decimal("0"),
        coste_pintura_por_pieza=Decimal("87"), coste_garantia=Decimal("300"),
        coste_mecanica=Decimal("300"), coste_cambio_titularidad=Decimal("72"),
        coste_transporte=Decimal("250"),
    )
    res = services.calcular(v, puja=Decimal("19090"))
    d = res.desglose_para_puja
    assert d.modo == "iva_anuncio"
    assert d.comision_neta == Decimal("1462.00")     # tarifa Auto1
    assert d.compra_coche == Decimal("17320.98")     # B - tarifa - IVA
    assert d.margen_bruto == Decimal("6179.02")

    detalle = services.preparacion_detalle(v)
    conceptos = [x["concepto"] for x in detalle]
    assert any("Tarifa Auto1" in c for c in conceptos)
    assert any("Gestión documental Auto1" in c for c in conceptos)


def test_transporte_por_zona_al_pegar(datos):
    """El lote coge el transporte de su zona de origen."""
    from tasador.models import SesionSubasta, TarifaTransporte
    from tasador.parser import parsear_linea

    bca = models.Proveedor.objects.get(nombre="BCA")
    TarifaTransporte.objects.filter(proveedor=bca, origen="Barcelona").update(
        precio=Decimal("500")
    )
    sesion = SesionSubasta.objects.create(
        proveedor=bca, ubicacion=bca.ubicaciones.get(nombre="BCA Online"),
        fecha="2026-09-20",
    )
    linea = parsear_linea(
        "7\tAudi A3 A3 1.5 TFSI\t110 KW (150 CV), Gasolina, Manual, 90000 Km, 2020\t1234ABC\t01/01/2020\tBCA Barcelona"
    )
    assert linea.zona_origen == "Barcelona"
    v, _ = services.crear_valoracion_desde_lote(linea, sesion)
    assert v.zona_origen == "Barcelona"
    assert v.coste_transporte == Decimal("500")


def test_tarifa_versionada_no_afecta_valoracion_antigua(datos):
    """Cambiar la tarifa después no altera el snapshot guardado."""
    v = _valoracion()
    services.recalcular_y_guardar(v)
    puja_antes = v.r_puja_maxima_principal

    tarifa = services.tarifa_vigente(models.Proveedor.objects.get(nombre="BCA"))
    tramo = tarifa.tramos.get(importe_desde=Decimal("10000"))
    tramo.cuota_fija = Decimal("999")
    tramo.save()

    v.refresh_from_db()
    assert v.r_puja_maxima_principal == puja_antes  # no se recalcula solo

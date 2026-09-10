"""Pruebas del parser del texto de la extensión de Chrome."""
from tasador.parser import parsear_linea, parsear_texto

LINEA = "3\tCitroën C1 C1 1.0 VTI FEEL 72\t53 KW (72 CV), Gasolina, Manual, 79328 Km, 2019\t9553LDF\t17/12/2019\tBCA Madrid"


def test_linea_completa():
    r = parsear_linea(LINEA)
    assert r.lote == "3"
    assert r.marca == "Citroën"
    assert r.modelo == "C1"
    assert "VTI FEEL 72" in r.version
    assert r.potencia_kw == 53
    assert r.potencia_cv == 72
    assert r.combustible == "gasolina"
    assert r.cambio == "manual"
    assert r.kilometros == 79328
    assert r.anio == 2019
    assert r.matricula == "9553LDF"
    assert r.fecha_matriculacion == "2019-12-17"
    assert r.ubicacion == "BCA Madrid"
    assert "matricula" not in r.dudosos


def test_ficha_con_texto_extra_de_bateria():
    linea = (
        "96\tKia Sorento SORENTO 1.6 PHEV\t"
        "132 KW (180 CV), PHEV Petrol, Secuencial, 39607 Km, 2023"
        "Propiedad de la batería: Bat. en propiedad\t2665MGH\t04/01/2023\tBCA Madrid"
    )
    r = parsear_linea(linea)
    assert r.potencia_cv == 180
    assert r.anio == 2023
    assert r.combustible == "phev"
    assert r.cambio == "automatico"


def test_varias_lineas():
    out = parsear_texto(LINEA + "\n" + LINEA)
    assert len(out) == 2

# Manual básico de uso

## Conceptos

- **Vehículo**: el coche físico (matrícula, VIN, marca…). No cambia.
- **Valoración**: cada vez que tasas un coche. Un vehículo puede tener varias
  (retasaciones cuando vuelve a subasta). Nunca se borran.
- **Sesión de subasta**: un día + una sede de BCA. Contiene tu lista de lotes a
  pujar.

## Valorar un coche

1. **Nueva valoración** (o **Pegar lotes** para varios de golpe).
2. Rellena: precio de venta estimado (lo pones tú), tipo de subasta
   (BCA normal / Concurso BCA), estado de carrocería, y ajusta costes si hace
   falta.
3. A la derecha, en vivo:
   - **Puja máxima** para los objetivos 15 % / 12 % / 10 % de rentabilidad
     sobre el coste total.
   - **Desglose** completo y auditable de una puja concreta (escribe una puja o
     pulsa un escenario).
4. Marca el estado (Interesante / Descartado / …) y **Guarda**.

La valoración guarda una copia de los importes y la versión de tarifa usada:
si mañana cambias una tarifa, esta valoración no se altera.

## El día de la subasta

- **Panel → Próximas subastas → Sala de pujas**.
- Lista ordenada por lote con tu puja máxima. Sigue al subastador por número de
  lote. Imprime la lista si quieres.

## Cálculo (resumen)

```
coste_adquisición = puja + comisión_subasta(tramo, +IVA) + gestión (140,12 €)
gastos_preparación = Alberto + gasolina + pintura·piezas + garantía + mecánica
                   + cambio titularidad + transporte + ITV + tapicería + tintado
coste_total = coste_adquisición + gastos_preparación

margen_bruto = venta − coste_adquisición        (base configurable por proveedor)
IVA_REBU = 21/121 × margen_bruto
beneficio_neto = margen_bruto/1,21 − gastos_preparación

rentabilidad = beneficio_neto / coste_total      ← objetivo 15 %
margen_sobre_venta = beneficio_neto / venta
```

Concurso BCA: `coste_adquisición = puja + 351 €` y nada más.

## Configuración (menú **Configuración**, sólo administradores)

- **Proveedores**: BCA, sus ubicaciones, tipos de subasta y conceptos fijos.
- **Tarifas de comisión**: tabla por tramos, con validación de huecos/solapes y
  vigencias. Cada cambio queda en el historial.
- **Parámetros de coste**: valores por defecto de preparación.
- **Escenarios objetivo** y **estados**: configurables.

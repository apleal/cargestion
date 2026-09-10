# cargestion · Tasador de vehículos de subasta

Calcula el coste total, el beneficio neto, la rentabilidad y la **puja máxima**
de un coche de subasta (BCA, régimen REBU), con histórico de valoraciones,
tarifas versionadas y sesiones de subasta.

Estado: **Etapa 1 (MVP)** en construcción. Ver `docs/` y la propuesta funcional
(Fase 3).

## Arranque rápido en local

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements-dev.txt
copy .env.example .env            # y edita SECRET_KEY
python manage.py migrate
python manage.py seed_datos       # datos de BCA, estados, escenarios
python manage.py createsuperuser
python manage.py runserver
```

- Aplicación: http://localhost:8000/
- Configuración (proveedores, tarifas, tramos): http://localhost:8000/admin/

## Pruebas

```bash
pytest                 # motor de cálculo + modelos
pytest tests/test_motor.py tests/test_tramos.py tests/test_facturas_bca.py
```

## Estructura

| Carpeta | Qué es |
|---|---|
| `calculo/` | Motor de cálculo **puro** (sin Django). Fórmulas con `Decimal`. |
| `tasador/` | App Django: modelos, admin, vistas, plantillas, importador. |
| `config/` | Proyecto Django (settings, urls). |
| `tests/` | Pruebas (motor + modelos). |
| `docs/` | Instalación y manual. |

## Despliegue

Ver [`docs/INSTALACION.md`](docs/INSTALACION.md) (EasyPanel + PostgreSQL + auto-deploy desde GitHub).

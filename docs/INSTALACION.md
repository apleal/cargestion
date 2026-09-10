# Instalación y despliegue

## 1. Desarrollo en local (Windows)

```powershell
cd C:\claude\cargestion
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env      # edita SECRET_KEY (ver el propio fichero)
python manage.py migrate
python manage.py seed_datos
python manage.py createsuperuser
python manage.py runserver
```

Sin `DATABASE_URL`, en local usa SQLite (`db.sqlite3`). No necesitas PostgreSQL
ni Docker para desarrollar.

## 2. Despliegue en EasyPanel

### 2.1 Servicio PostgreSQL

1. En tu proyecto de EasyPanel: **+ Servicio → PostgreSQL**.
2. Nombre: `cargestion-db`. Anota la cadena de conexión interna que genera
   (algo como `postgres://postgres:xxxx@cargestion-db:5432/postgres`).

### 2.2 Servicio de la aplicación

1. **+ Servicio → App**.
2. **Fuente**: GitHub → repositorio `apleal/cargestion`, rama `main`.
3. **Build**: Dockerfile (está en la raíz del repo).
4. **Puerto**: `8000`.
5. **Entorno** (pestaña *Environment*):

   | Variable | Valor |
   |---|---|
   | `SECRET_KEY` | (genérala, 50+ caracteres) |
   | `DEBUG` | `False` |
   | `ALLOWED_HOSTS` | `tasador.tudominio.com` |
   | `CSRF_TRUSTED_ORIGINS` | `https://tasador.tudominio.com` |
   | `DATABASE_URL` | la cadena del servicio PostgreSQL |
   | `MEDIA_ROOT` | `/app/media` |
   | `SECURE_SSL_REDIRECT` | `True` |
   | `SESSION_COOKIE_SECURE` | `True` |
   | `CSRF_COOKIE_SECURE` | `True` |
   | `SECURE_HSTS_SECONDS` | `2592000` (solo con el dominio definitivo; nunca en localhost) |
   | `DJANGO_SUPERUSER_USERNAME` | `admin` |
   | `DJANGO_SUPERUSER_EMAIL` | tu email |
   | `DJANGO_SUPERUSER_PASSWORD` | una contraseña fuerte |

6. **Dominios**: añade el subdominio; EasyPanel emite el certificado SSL solo.
7. **Volúmenes**: monta un volumen persistente en `/app/media` y otro en
   `/app/backups`.

En cada arranque el contenedor ejecuta, de forma idempotente:
`migrate` → `seed_datos` (datos de BCA) → `crear_admin` (superusuario desde las
variables `DJANGO_SUPERUSER_*`). **No hace falta tocar la consola**: define esas
3 variables y, al desplegar, ya puedes entrar con ese usuario.

Para cambiar la contraseña más adelante: cambia `DJANGO_SUPERUSER_PASSWORD` y
vuelve a desplegar, o desde la consola `python manage.py changepassword admin`.

### 2.3 Auto-deploy

En el servicio App → **Deployments** → activa *Auto Deploy*. EasyPanel crea el
webhook en GitHub; a partir de ahí, cada `git push` a `main` reconstruye y
despliega. El historial de despliegues permite volver a una versión anterior
con un clic.

### 2.4 Copias de seguridad

En EasyPanel → **Scheduled Tasks**, crea una tarea diaria en el servicio App:

```bash
pg_dump "$DATABASE_URL" | gzip > /app/backups/cargestion-$(date +%F).sql.gz
find /app/backups -name '*.sql.gz' -mtime +30 -delete
```

Restauración:

```bash
gunzip -c /app/backups/cargestion-2026-09-10.sql.gz | psql "$DATABASE_URL"
```

> El rollback de código (EasyPanel / git) **no** revierte la base de datos.
> Haz una copia manual antes de cualquier migración importante.

## 3. Versionado

- Cada cambio es un commit en `main`.
- Hitos con etiqueta: `git tag v0.1.0 && git push --tags`.
- Ramas de trabajo: `git switch -c feature/lo-que-sea`, luego PR o merge a `main`.

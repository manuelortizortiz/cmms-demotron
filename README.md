# CMMS DEMOTRON ULTRA PRO - Railway PostgreSQL

Subir todo el contenido de esta carpeta a la raíz del repositorio GitHub conectado a Railway.

Variables requeridas en Railway:
- `DATABASE_URL` conexión PostgreSQL de Railway
- `SECRET_KEY` opcional

Login por defecto:
- Usuario: `admin`
- Clave: `admin123`

Tablas usadas:
- `equipos`: codigo, tipo, estado, ubicacion, horometro
- `lecturas`
- `mantenciones`
- `bodega`
- `compras`
- `pm` o `PM`

El sistema detecta columnas disponibles y no se cae si alguna tabla está vacía.

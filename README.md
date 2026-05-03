# CMMS DEMOTRON ULTRA PRO - Railway/PostgreSQL

## Subir a GitHub
1. Descomprime este ZIP.
2. Sube **todo el contenido a la raíz del repositorio**.
3. Railway hará redeploy automático.

## Variables Railway necesarias
- `DATABASE_URL` como referencia al servicio Postgres.
- Opcional: `SECRET_KEY`, `ADMIN_USER`, `ADMIN_PASS`, `GERENCIA_USER`, `GERENCIA_PASS`.

## Login por defecto
- admin / admin123
- gerencia / gerencia123

## Tablas usadas
- equipos: codigo, tipo, estado, ubicacion, horometro
- lecturas
- mantenciones
- bodega
- compras
- PM / pm

El sistema detecta columnas similares si los nombres tienen mayúsculas, acentos o variaciones.

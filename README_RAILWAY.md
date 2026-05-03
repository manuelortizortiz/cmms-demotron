# CMMS DEMOTRON ULTRA PRO - Railway

## Instalación rápida
1. Sube todos estos archivos a la raíz de tu repositorio GitHub.
2. En Railway, conecta el repositorio.
3. Agrega PostgreSQL y verifica que exista la variable `DATABASE_URL`.
4. Deploy automático.

## Login inicial
- admin / admin123
- gerencia / gerencia123
- mantencion / mantencion123
- bodega / bodega123
- lectura / lectura123

## Corrección incluida
Este paquete usa `psycopg[binary]==3.2.13` y `postgresql+psycopg://` para evitar el error de `libpq.so.5` y el problema de wheels en Python 3.13.

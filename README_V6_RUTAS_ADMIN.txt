DEMOTRON ERP CMMS V6 - RUTAS ADMIN CORREGIDAS

Este paquete corrige el error:
Not Found en /admin/diagnostico_datos

Después de subir y hacer Redeploy, prueba estas rutas:

1) Verificar versión activa:
https://web-production-75233.up.railway.app/admin/version

Debe decir:
V6 ACTIVO

2) Cargar/reconstruir base:
https://web-production-75233.up.railway.app/admin/cargar_sql_final

3) Ver diagnóstico:
https://web-production-75233.up.railway.app/admin/diagnostico_datos

Si /admin/version no existe, GitHub/Railway no recibió este app.py.

FIX SERVER-SIDE EQUIPOS + DASHBOARD

Este archivo evita el problema del frontend/JS/template.
- /equipos se renderiza directo desde PostgreSQL
- / se renderiza directo desde PostgreSQL
- /api/equipos usa SELECT * y mapeo flexible

Pasos:
1. Reemplaza app.py en GitHub.
2. Espera redeploy.
3. Ejecuta /admin/importar-cmms.
4. Abre /equipos y /

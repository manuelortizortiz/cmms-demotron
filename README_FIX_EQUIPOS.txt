FIX FINAL EQUIPOS ORDEN CORRECTO

Reemplaza estos archivos en GitHub:
- app.py
- templates/equipos.html
- static/js/equipos.js

Después:
1. Espera Railway redeploy.
2. Entra logueado.
3. Ejecuta /admin/importar-cmms nuevamente.
4. Abre /api/equipos para confirmar JSON.
5. Abre /equipos.

Este fix usa columnas reales:
codigo, tipo_equipo, familia, marca, modelo, ano, ubicacion, responsable,
lectura_actual, unidad, proxima_pm, estado.

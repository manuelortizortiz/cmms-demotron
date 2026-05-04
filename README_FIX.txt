FIX EQUIPOS + DASHBOARD

Problema:
Dashboard depende de /api/equipos. /api/equipos fallaba si faltaba una columna exacta como proxima_pm.

Solución:
Este app.py detecta columnas reales en maestro_equipos y arma el SELECT automáticamente.

Pasos:
1. Reemplaza app.py en la raíz de GitHub.
2. Espera redeploy Railway.
3. Entra a /admin/importar-cmms.
4. Revisa:
   /api/debug/maestro-columnas
   /api/equipos
   /equipos
   /

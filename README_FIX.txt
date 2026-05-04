FIX IMPORTADOR MAESTRO_EQUIPOS

Problema corregido:
El importador tomaba la fila "Maestro de Equipos" como encabezado, porque detectaba la palabra "equipo".
Ahora solo detecta encabezados cuando la fila contiene "Codigo" o "Fecha".

Pasos:
1. Sube este app.py a la raíz de GitHub reemplazando el anterior.
2. Espera el redeploy de Railway.
3. Entra logueado como admin.
4. Abre:
   https://web-production-75233.up.railway.app/admin/importar-cmms

Debe volver a importar:
maestro_equipos: 245

Luego abre:
https://web-production-75233.up.railway.app/api/equipos
https://web-production-75233.up.railway.app/equipos

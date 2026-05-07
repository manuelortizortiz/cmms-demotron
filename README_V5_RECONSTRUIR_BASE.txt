DEMOTRON ERP CMMS V5 - CARGA REAL CORREGIDA

Problema corregido:
Railway conservaba tablas antiguas sin columnas nuevas como chofer. Por eso el SQL no cargaba.

Solución V5:
La ruta /admin/cargar_sql_final ahora reconstruye las tablas ERP y luego carga el SQL real.

Pasos:
1. Sube TODO este ZIP a GitHub reemplazando archivos.
2. Redeploy en Railway.
3. Entra con admin/admin123.
4. Abre:
   https://web-production-75233.up.railway.app/admin/cargar_sql_final
5. Verifica en:
   https://web-production-75233.up.railway.app/admin/diagnostico_datos

Debe mostrar conteos mayores a cero en equipos, lecturas, compras, ot y bodega.

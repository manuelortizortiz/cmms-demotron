DEMOTRON ERP CMMS V4 - CARGA REAL POR SQL

Este paquete corrige el problema de “0 registros procesados”.
La importación por Excel no reconoció hojas/columnas en Railway, por eso ahora se incluye un SQL generado directamente desde tus Excel reales.

Datos incluidos en DATOS_REALES_DEMOTRON_FINAL_VALIDO.sql:
- 255 equipos válidos CD/MD/VD/EQP
- 5040 lecturas
- 1557 compras / OC
- 568 movimientos de bodega
- 780 OT / mantenciones

Instrucciones:
1. Sube TODO este ZIP a GitHub reemplazando los archivos.
2. Haz Redeploy en Railway.
3. Entra con admin / admin123.
4. Abre:
   /admin/cargar_sql_final
   o también sirve:
   /admin/reset_cargar_datos

Para verificar archivos y conteos:
/admin/verificar_archivos

Si carga bien, arriba debe aparecer VISUAL V4 SQL REAL.

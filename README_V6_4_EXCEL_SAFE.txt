DEMOTRON ERP CMMS V6.4

Corrige:
InvalidTextRepresentation('invalid input syntax for type double precision: ""')

Causa:
El SQL exportado desde Excel trae campos numéricos vacíos como ''.

Solución:
V6.4 crea las columnas numéricas como TEXT para aceptar datos Excel reales.
La aplicación convierte esos textos a número con safe_float() al calcular KPIs.

Rutas:
1. /admin/v64/version
2. /admin/v64/cargar_sql_final
3. /admin/v64/diagnostico_datos

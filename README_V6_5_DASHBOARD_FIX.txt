DEMOTRON ERP CMMS V6.5

Corrige Internal Server Error al abrir el dashboard después de cargar datos.

Causa:
V6.4 cargó los números como TEXT para aceptar campos vacíos de Excel.
El dashboard formateaba esos textos como float, generando error.

Solución:
V6.5 normaliza:
- lectura_actual
- ultima_pm
- proxima_pm
- margen
- costos
- compras
- lecturas
- bodega

Rutas:
1. /admin/v65/version
2. /admin/v65/dashboard_test
3. /
4. /dashboard_v65

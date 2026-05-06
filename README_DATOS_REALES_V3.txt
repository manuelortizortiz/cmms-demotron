DEMOTRON ERP CMMS - DATOS REALES V3

Problema corregido:
- La vista cambiaba, pero los datos no se actualizaban porque Railway conserva la base PostgreSQL anterior.
- Además, una planilla de ubicaciones podía pisar lecturas/costos con cero.

Corrección:
- Nuevo botón: Cargar datos reales V3.
- Nuevo endpoint: /admin/reset_cargar_datos
- Vacía equipos, lecturas, compras, OT, bodega e importaciones.
- Reimporta los Excel incluidos en data_import.
- Conserva lecturas/costos existentes cuando otro Excel trae celdas vacías.

Pasos:
1. Reemplaza todo el repo con este ZIP.
2. Commit + push.
3. Redeploy en Railway.
4. Entra al ERP.
5. Debe verse: VISUAL V3 DATOS REALES.
6. En Configuración presiona: Cargar datos reales V3.

Si no aparece esa etiqueta, Railway no está usando estos archivos.

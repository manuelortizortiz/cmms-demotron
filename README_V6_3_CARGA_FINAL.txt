DEMOTRON ERP CMMS V6.3

Corrige el error:
UndefinedTable('relation "lecturas" does not exist')

Causa:
El SQL empezaba con TRUNCATE lecturas, pero V6.2 borraba las tablas antes de ejecutar el SQL.

Solución:
V6.3 crea primero el esquema completo:
- equipos
- lecturas
- compras
- ot
- bodega
- actividad
- importaciones

Luego ejecuta el SQL real.

Rutas:
1. /admin/v63/version
2. /admin/v63/cargar_sql_final
3. /admin/v63/diagnostico_datos

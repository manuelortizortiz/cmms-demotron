FIX AGREGAR TODO

Corrige guardado en:
- Lecturas
- Mantenciones
- OT
- Compras
- Bodega
- Equipos

Causa:
Los formularios enviaban "" a columnas DATE/NUMERIC. PostgreSQL requiere NULL o número válido.

Solución:
Campos vacíos se convierten a NULL.
Números se limpian.
Códigos se normalizan a mayúscula.
OT automática si no escribes folio.
Lectura actual del equipo se actualiza al registrar lectura.

Sube todo a GitHub reemplazando archivos.

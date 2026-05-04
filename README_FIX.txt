FIX AGREGAR EQUIPO

Causa:
Al importar el Excel, pandas reemplaza la tabla maestro_equipos y se pierde la clave única de codigo.
El formulario usaba ON CONFLICT(codigo), lo que provoca error.

Solución:
El guardado de equipos ahora:
1. Valida código.
2. Borra el código si ya existe.
3. Inserta el equipo actualizado.

Subir todo a GitHub reemplazando archivos.
No borra tus datos actuales.

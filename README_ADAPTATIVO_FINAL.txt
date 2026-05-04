CMMS DEMOTRON ADAPTATIVO FINAL

Objetivo:
- Adaptarse a columnas reales de PostgreSQL/Excel.
- No depender de nombres exactos como tipo_equipo, lectura_actual, etc.
- Agregar columnas estándar si faltan.
- Mantener Equipos, Lecturas y OT funcionando.

Rutas clave:
- /api/debug/columnas  -> muestra columnas reales y mapeo automático.
- /equipos
- /lecturas
- /ot
- /ot/nueva
- /ot/<id>/pdf
- /planificacion
- /calendario
- /backlog

Después de subir:
1. Esperar deploy.
2. Entrar /login.
3. Ejecutar /admin/importar-cmms.
4. Revisar /api/debug/columnas.

CMMS DEMOTRON ULTRA PRO - PostgreSQL + Web + Login

LISTO PARA SUBIR A GITHUB / RAILWAY

Archivos principales:
- app.py: Backend Flask conectado a PostgreSQL mediante DATABASE_URL.
- templates/: Pantallas Dashboard, Equipos, OT, Lecturas, Compras, Bodega, Reportes, Configuración y Login.
- static/img/: Iconos/imagenes SVG pequeñas para excavadora, motoniveladora, cargador, tolva, camioneta y equipo genérico.
- requirements.txt: Dependencias.
- Procfile / railway.json: Configuración para Railway.

Usuarios iniciales:
- admin / admin123
- gerencia / gerencia123
- mantencion / mantencion123
- bodega / bodega123
- lectura / lectura123

VARIABLES EN RAILWAY:
- DATABASE_URL: Railway la crea automáticamente si tienes PostgreSQL agregado al proyecto.
- SECRET_KEY: recomendado crear una clave segura.

PASOS PARA ACTUALIZAR TU PÁGINA:
1. Descomprime este ZIP.
2. Copia todos los archivos dentro de tu repositorio GitHub.
3. Reemplaza los archivos anteriores.
4. Haz commit y push.
5. Railway redeployará automáticamente.
6. Entra a /health para comprobar que diga database: postgresql y status: ok.

IMPORTANTE:
- No puedo modificar directamente tu Railway o GitHub desde aquí sin acceso al repositorio.
- Esta versión queda conectada a PostgreSQL usando la variable DATABASE_URL del proyecto.
- Si la base está vacía, el sistema carga datos iniciales demo y luego puedes registrar equipos, lecturas, OT, compras y bodega desde la web.

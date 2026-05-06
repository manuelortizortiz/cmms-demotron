DEMOTRON ERP CMMS - PAQUETE FINAL ESTILO KOMATSU

Archivos principales:
- app.py: backend Flask robusto para Railway/PostgreSQL y local SQLite.
- templates/index.html: dashboard visual basado en la referencia enviada.
- templates/login.html: login DEMOTRON.
- requirements.txt: dependencias Railway.
- Procfile / railway.json: arranque Gunicorn.
- data_import/: incluye tus Excel originales para autoimportación al primer arranque.
- static/dashboard_referencia.jpeg: imagen de referencia del diseño.
- static/equipos/: imágenes placeholder DEMOTRON para equipos. Puedes reemplazarlas por fotos reales.

Usuarios iniciales:
- admin / admin123
- gerencia / gerencia123
- mantencion / mantencion123
- bodega / bodega123

Carga de datos:
1. Al primer arranque, si la tabla equipos está vacía, el sistema intenta importar automáticamente los Excel en data_import.
2. También puedes importar Excel desde el panel Configuración / Importar Excel CMMS.
3. El importador acepta hojas de equipos, lecturas, compras/OC y ubicaciones/choferes.

Deploy Railway:
1. Reemplaza los archivos de tu repositorio GitHub por los de este ZIP.
2. Commit + Push.
3. Railway hará redeploy automático o presiona Redeploy.
4. Abre /health para verificar estado.

Notas:
- El dashboard excluye equipos fuera de servicio/taller en vista rápida y controlado real.
- Las consultas son seguras si una tabla no tiene columna id.
- No depende de ORDER BY id para tablas importadas desde Excel.

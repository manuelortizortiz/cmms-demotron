CMMS DEMOTRON ERP WEB FINAL

Contenido listo para subir/reemplazar en GitHub:
- app.py
- templates/index.html
- templates/login.html
- static/equipos/*.svg
- requirements.txt
- Procfile
- runtime.txt
- railway.json

Instalación local:
1) python -m venv .venv
2) .venv\Scripts\activate   (Windows)
3) pip install -r requirements.txt
4) python app.py
5) Abrir http://127.0.0.1:5000

Usuarios iniciales:
- admin / admin123
- gerencia / gerencia123
- mantencion / mantencion123
- bodega / bodega123
- lectura / lectura123

Railway:
1) Subir estos archivos al repo manuelortizortiz/cmms-demotron
2) En Railway agregar PostgreSQL
3) Variable DATABASE_URL = ${{ Postgres.DATABASE_URL }}
4) Deploy
5) Revisar /health y /api/version

Importación Excel:
- En la pantalla ERP, ir a “Importar plantilla Excel”
- Subir Plantilla_Maestra_CMMS_ERP_DEMOTRON.xlsx
- El sistema detecta hojas Maestro/Equipos, Lecturas y Compras/OC

Qué incluye:
- Dashboard gerencial responsive
- Login multiusuario
- KPI controlado excluyendo EN TALLER y FUERA DE SERVICIO
- Equipos críticos atrasados/próximos
- Ficha rápida con imágenes y scroll horizontal
- OT, lecturas, compras y bodega
- Importador Excel a PostgreSQL o SQLite local
- Gráficos: estado flota, ubicación, taller, mantenciones y costos

CMMS DEMOTRON FINAL LISTO

1. Reemplaza estos archivos en GitHub:
   app.py
   templates/index.html
   templates/login.html
   requirements.txt
   Procfile
   railway.json

2. Railway:
   - Web > Variables:
     DATABASE_URL = ${{Postgres.DATABASE_URL}}
   - Deploy

3. Si la base está vacía:
   - Entra con admin / admin123
   - Equipos > Cargar datos demo
   - O usa DATA_POSTGRES_SEED.sql en Railway Postgres > Query

4. Importar Excel:
   - Pestaña Equipos > Importar Maestro desde Excel

Subir estos archivos a la RAÍZ del repositorio GitHub:
- app.py
- Procfile
- requirements.txt

No subir app_v12_1.py con otro nombre. Railway ejecuta: gunicorn app:app
Por eso el archivo debe llamarse exactamente app.py y estar en la raíz.

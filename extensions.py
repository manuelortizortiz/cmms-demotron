# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_apscheduler import APScheduler

# Inicializamos las extensiones sin vincularlas a la app todavía
db = SQLAlchemy()
login_manager = LoginManager()
scheduler = APScheduler()

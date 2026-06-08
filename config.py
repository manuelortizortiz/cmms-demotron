# config.py
import os
from dotenv import load_dotenv

# Cargar variables desde .env si existe (para desarrollo local)
load_dotenv()

class Config:
    # Seguridad
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'demotron_seguridad_maxima_2026'
    
    # Base de datos
    ruta_db = os.environ.get('DATABASE_URL', 'sqlite:///demotron_master.db')
    if ruta_db.startswith("postgres://"):
        ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = ruta_db
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Configuración de Correo (Se usará más adelante)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'CMMS Demotron <tu_email@gmail.com>')
    ALERTAS_DESTINATARIOS = os.environ.get('ALERTAS_DESTINATARIOS', '').split(',')

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler
from flask_migrate import Migrate
from flask_mail import Mail  # <-- NUEVO

db = SQLAlchemy()
login_manager = LoginManager()
scheduler = BackgroundScheduler()
migrate = Migrate()
mail = Mail()  # <-- NUEVO

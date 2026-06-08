import os
from flask import Flask
from config import Config
from extensions import db, login_manager, scheduler, migrate
from models.user import User

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # --- CONFIGURACIÓN DE SEGURIDAD (Login) ---
    # Le decimos a Flask qué ruta usar para hacer login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Por favor inicie sesión para acceder al sistema.'
    login_manager.login_message_category = 'danger'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Importar Blueprints
    from routes.dashboard import dashboard_bp
    from routes.equipos import equipos_bp
    from routes.api import api_bp
    from routes.admin import admin_bp
    from routes.auth import auth_bp  # <-- NUEVO Blueprint

    # Registrar Blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(equipos_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)  # <-- Registro del Login

    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))

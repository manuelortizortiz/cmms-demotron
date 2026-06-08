import os
from flask import Flask
from config import Config
from extensions import db, login_manager, scheduler, migrate
from models.user import User

def create_app():
    # Inicializa Flask y carga la configuración
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializar las herramientas
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)  # <-- VINCULAMOS MIGRATE CON LA APP

    # Le enseña a Flask-Login cómo buscar usuarios
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Mantenemos esto por ahora para que nada se rompa mientras migramos
    with app.app_context():
        db.create_all()

    # Importar y registrar los Blueprints (Rutas)
    from routes.dashboard import dashboard_bp
    from routes.equipos import equipos_bp
    from routes.api import api_bp
    from routes.admin import admin_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(equipos_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    return app

# Iniciar la aplicación
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))

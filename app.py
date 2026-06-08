import os
from flask import Flask
from sqlalchemy import text
from config import Config

# AQUÍ ESTÁ LA CORRECCIÓN: Agregamos 'mail' al final de esta línea
from extensions import db, login_manager, scheduler, migrate, mail
from models.user import User

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializar herramientas
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)  # <-- Ahora Python sí sabe qué es 'mail'

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'danger'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    with app.app_context():
        db.create_all()
        
        # --- AUTO-MIGRACIÓN DE CAMPOS ---
        try:
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS sistema_falla VARCHAR(100)"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS causa_raiz TEXT"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS fecha_cierre TIMESTAMP"))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Nota: Las columnas ya existían o hubo un error al auto-migrar: {e}")

    # Registro de Blueprints
    from routes.dashboard import dashboard_bp
    from routes.equipos import equipos_bp
    from routes.api import api_bp
    from routes.admin import admin_bp
    from routes.auth import auth_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(equipos_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)

    return app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))

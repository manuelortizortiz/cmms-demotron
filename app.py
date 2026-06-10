import os
from flask import Flask
from sqlalchemy import text
from config import Config
from extensions import db, login_manager, scheduler, migrate, mail
from models.user import User
from models.orden_trabajo import OrdenTrabajo

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'danger'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    with app.app_context():
        from models.chatter import RegistroChatter
        from models.bodega import InventarioBodega # <--- NUEVA TABLA BODEGA
        
        db.create_all()
        
        try:
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS sistema_falla VARCHAR(100)"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS causa_raiz TEXT"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS fecha_cierre TIMESTAMP"))
            db.session.execute(text("ALTER TABLE mecanico ADD COLUMN IF NOT EXISTS rut VARCHAR(20)"))
            db.session.commit()
        except Exception as e:
            db.session.rollback()

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

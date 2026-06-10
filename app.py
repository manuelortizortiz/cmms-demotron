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
        # --- SE AGREGA EL CHATTER PARA CREAR TABLA ---
        from models.chatter import RegistroChatter
        
        db.create_all()
        
        try:
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS sistema_falla VARCHAR(100)"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS causa_raiz TEXT"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN IF NOT EXISTS fecha_cierre TIMESTAMP"))
            db.session.execute(text("ALTER TABLE mecanico ADD COLUMN IF NOT EXISTS rut VARCHAR(20)"))
            db.session.commit()
        except Exception as e:
            db.session.rollback()

        try:
            ots_viejas = OrdenTrabajo.query.filter(OrdenTrabajo.tipo_ot == 'Correctiva').all()
            for ot in ots_viejas:
                if not ot.sistema_falla or ot.sistema_falla == 'Otros':
                    falla = ot.tipo_mantencion.lower() if ot.tipo_mantencion else ""
                    if any(x in falla for x in ['motor', 'aceite', 'filtro', 'refrig', 'radiador', 'correa']): ot.sistema_falla = 'Motor'
                    elif any(x in falla for x in ['hidraulic', 'hidráulic', 'manguera', 'bomba', 'cilindro', 'oring', 'fuga']): ot.sistema_falla = 'Hidráulico'
                    elif any(x in falla for x in ['freno', 'balata', 'tambor', 'pastilla']): ot.sistema_falla = 'Frenos'
                    elif any(x in falla for x in ['electri', 'eléctri', 'bateria', 'luces', 'sensor', 'cable']): ot.sistema_falla = 'Eléctrico'
                    elif any(x in falla for x in ['neumatico', 'neumático', 'rueda', 'llanta']): ot.sistema_falla = 'Neumáticos'
                    else: ot.sistema_falla = 'Estructura'
                    if not ot.causa_raiz: ot.causa_raiz = ot.tipo_mantencion
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

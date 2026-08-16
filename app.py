import os
from datetime import timedelta
from flask import Flask, jsonify, request
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_apscheduler import APScheduler
from sqlalchemy import text
from extensions import db

# Importar Modelos
from models.usuario import Usuario
from models.chatter import RegistroChatter
from datetime import datetime

# Importar Listener de Auditoría para que se active silenciosamente
import models.auditoria

# Importar Sentry (Observabilidad)
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

# Importar Módulos (Blueprints)
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.admin import admin_bp
from routes.api import api_bp
from routes.mobile import mobile_bp

# Inicializar programador de tareas
scheduler = APScheduler()

def create_app():
    # ==========================================
    # 1. INICIALIZAR SENTRY (Antes de Flask)
    # ==========================================
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0
        )

    app = Flask(__name__)

    # ==========================================
    # 2. SEGURIDAD Y VARIABLES DE ENTORNO
    # ==========================================
    app.secret_key = os.environ.get('SECRET_KEY', 'clave-de-desarrollo-segura-12345')
    is_prod = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_SECURE'] = is_prod
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)

    # ==========================================
    # 3. BASE DE DATOS Y MIGRACIONES
    # ==========================================
    db_url = os.environ.get('DATABASE_URL', 'sqlite:///cmms_demotron.db')
    
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    migrate = Migrate(app, db)

    # ==========================================
    # 4. AUTENTICACIÓN (FLASK-LOGIN)
    # ==========================================
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Acceso restringido. Por favor, inicie sesión."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        return Usuario.query.get(int(user_id))

    # ==========================================
    # 5. REGISTRO DE MÓDULOS (BLUEPRINTS)
    # ==========================================
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(mobile_bp)

    # ==========================================
    # 6. AUDITORÍA Y REGISTRO AUTOMÁTICO DE ACCESOS
    # ==========================================
    @app.before_request
    def registrar_actividad_usuario():
        # Ignorar archivos estáticos o peticiones técnicas para no saturar la BD
        if request.path.startswith('/static') or request.path.startswith('/favicon.ico') or request.path == '/health':
            return

        # Registrar accesos de navegación de usuarios autenticados
        if current_user.is_authenticated and request.method == 'GET':
            try:
                rutas_excluidas = ['/api/', '/mover_ubicacion_kanban']
                if not any(request.path.startswith(exc) for exc in rutas_excluidas):
                    usuario_nombre = getattr(current_user, 'username', getattr(current_user, 'nombre', 'Usuario'))
                    
                    log = RegistroChatter(
                        fecha=datetime.now(),
                        modelo_ref='navegacion',
                        registro_id='0',
                        autor=usuario_nombre,
                        accion='acceso_pagina',
                        mensaje=f"Accedió a: {request.path}"
                    )
                    db.session.add(log)
                    db.session.commit()
            except Exception:
                db.session.rollback()

    # ==========================================
    # 7. ENDPOINT DE OBSERVABILIDAD
    # ==========================================
    @app.route('/health')
    def health_check():
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify({"status": "ok", "database": "connected"}), 200
        except Exception as e:
            return jsonify({"status": "error", "details": str(e)}), 503

    # ==========================================
    # 8. WORKFLOW & NOTIFICACIONES (CRON JOBS)
    # ==========================================
    scheduler.init_app(app)
    scheduler.start()

    # Se ejecutará todos los días a las 08:00 AM
    @scheduler.task('cron', id='check_alertas', hour=8, minute=0)
    def job_notificaciones():
        with app.app_context():
            from models.equipo import Equipo
            # CORRECCIÓN: Filtrar por resta directa en SQL
            equipos_alerta = Equipo.query.filter((Equipo.proxima_pm - Equipo.lectura_actual) <= 150).all()
            if equipos_alerta:
                print(f"SISTEMA: {len(equipos_alerta)} equipos próximos a vencer. Hook de WhatsApp / Email preparado.")

    # ==========================================
    # 9. INICIALIZACIÓN DE TABLAS Y ADMIN
    # ==========================================
    with app.app_context():
        db.create_all()
        if not Usuario.query.first():
            from werkzeug.security import generate_password_hash
            admin_pass = os.environ.get('APP_PASSWORD', 'admin123')
            admin_user = Usuario(
                username='admin', 
                nombre='Administrador Sistema',
                password_hash=generate_password_hash(admin_pass), 
                role='admin', 
                activo=True
            )
            db.session.add(admin_user)
            db.session.commit()

    return app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

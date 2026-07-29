import os
from datetime import timedelta
from flask import Flask
from flask_login import LoginManager
from extensions import db
from models.usuario import Usuario  # Tu modelo de base de datos para usuarios

# Importar Módulos (Blueprints)
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.admin import admin_bp
from routes.api import api_bp

def create_app():
    app = Flask(__name__)

    # ==========================================
    # 1. SEGURIDAD Y VARIABLES DE ENTORNO
    # ==========================================
    # La Secret Key ahora es dinámica. (Configurar en Coolify)
    app.secret_key = os.environ.get('SECRET_KEY', 'clave-de-desarrollo-segura-12345')
    
    # Hardening de Cookies (Activa seguridad extra si está en producción con Traefik/HTTPS)
    is_prod = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_SECURE'] = is_prod
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)

    # ==========================================
    # 2. BASE DE DATOS
    # ==========================================
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///cmms_demotron.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    # ==========================================
    # 3. AUTENTICACIÓN (FLASK-LOGIN)
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
    # 4. REGISTRO DE MÓDULOS
    # ==========================================
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # ==========================================
    # 5. INICIALIZACIÓN DE TABLAS Y ADMIN DEFAULT
    # ==========================================
    with app.app_context():
        db.create_all()
        # Crea el usuario administrador basándose en la variable de entorno si la DB está vacía
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

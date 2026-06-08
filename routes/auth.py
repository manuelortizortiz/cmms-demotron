# routes/auth.py
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models.user import User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Crear usuario admin maestro automáticamente si la tabla está vacía
    if User.query.count() == 0:
        admin = User(username='admin', email='admin@demotron.cl', role='admin', nombre='Administrador Maestro')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    # Si ya está logueado, lo mandamos al dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        # Verificar credenciales
        if user and user.check_password(password):
            if not user.activo:
                flash('Usuario inactivo. Contacte a gerencia.', 'danger')
                return redirect(url_for('auth.login'))
            
            login_user(user)
            return redirect(url_for('dashboard.dashboard'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

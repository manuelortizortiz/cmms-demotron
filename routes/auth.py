import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db
from models.usuario import Usuario

# Intentamos importar Auditoria. Si no existe, evitamos que el programa explote.
try:
    from models.historial import Auditoria # Ajusta el archivo si tu modelo está en otro lado
except ImportError:
    try:
        from models.auditoria import Auditoria
    except ImportError:
        Auditoria = None

auth_bp = Blueprint('auth', __name__)

# Función maestra para registrar movimientos silenciosamente
def registrar_auditoria(usuario, accion, detalles):
    try:
        if Auditoria:
            nuevo_log = Auditoria(
                fecha=datetime.now(),
                usuario=usuario,
                accion=accion,
                detalles=detalles
            )
            db.session.add(nuevo_log)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        pass # Si la tabla no está creada, simplemente lo ignora sin botar el sistema


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Búsqueda de usuario
        user = Usuario.query.filter_by(username=username).first()
        
        # Validación de contraseña en base de datos
        if user and getattr(user, 'activo', True) and check_password_hash(user.password_hash, password):
            session.permanent = True
            login_user(user)
            
            # Dejamos registro del ingreso en auditoría
            registrar_auditoria(user.username, "INGRESO SISTEMA", "Inicio de sesión exitoso")
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.dashboard'))
            
        flash('Credenciales incorrectas o usuario inactivo.', 'error')

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    registrar_auditoria(current_user.username, "SALIDA SISTEMA", "Cierre de sesión manual")
    logout_user()
    session.clear()
    return redirect(url_for('auth.login'))

# ========================================================
# NUEVAS RUTAS DE USUARIOS Y AUDITORÍA
# ========================================================

@auth_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if request.method == 'POST':
        try:
            username = request.form.get('username').strip()
            password = request.form.get('password')
            rol = request.form.get('rol', 'Consulta') # Rol por defecto
            
            existente = Usuario.query.filter_by(username=username).first()
            if existente:
                return f"<div style='padding:50px; color:red; font-family:sans-serif;'><h2>Error:</h2><p>El usuario '{username}' ya existe en el sistema.</p><br><a href='/register' style='background:#1E3A8A; color:white; padding:10px; text-decoration:none;'>Volver</a></div>"

            # 1. Encriptación obligatoria (SHA256)
            hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
            
            # 2. Creación del objeto usuario
            nuevo_usuario = Usuario(username=username, password_hash=hashed_pw)
            
            # 3. Blindaje: Intentamos asignar el rol solo si la base de datos tiene esa columna
            if hasattr(nuevo_usuario, 'rol'):
                nuevo_usuario.rol = rol
            if hasattr(nuevo_usuario, 'activo'):
                nuevo_usuario.activo = True

            db.session.add(nuevo_usuario)
            db.session.commit()
            
            registrar_auditoria(current_user.username, "CREACIÓN USUARIO", f"Creó al usuario: {username} con atributo {rol}")
            
            return redirect(url_for('auth.register'))
        
        except Exception as e:
            db.session.rollback()
            return f"<div style='padding:50px; color:red; font-family:sans-serif;'><h2>Error de Base de Datos al crear usuario:</h2><p>{str(e)}</p><br><a href='/register' style='background:#1E3A8A; color:white; padding:10px; text-decoration:none;'>Volver</a></div>"

    # Mostrar la vista con la tabla de usuarios
    usuarios_db = Usuario.query.all()
    return render_template('register.html', usuarios=usuarios_db)

@auth_bp.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    try:
        user_to_delete = Usuario.query.get(user_id)
        if user_to_delete:
            if user_to_delete.username == current_user.username:
                return f"<div style='padding:50px; color:red; font-family:sans-serif;'><h2>Acción Denegada:</h2><p>No puedes eliminar tu propio usuario mientras estás en sesión.</p><br><a href='/register' style='background:#1E3A8A; color:white; padding:10px; text-decoration:none;'>Volver</a></div>"
            
            nombre_eliminado = user_to_delete.username
            db.session.delete(user_to_delete)
            db.session.commit()
            
            registrar_auditoria(current_user.username, "ELIMINACIÓN USUARIO", f"Eliminó permanentemente al usuario: {nombre_eliminado}")
            
        return redirect(url_for('auth.register'))
    except Exception as e:
        db.session.rollback()
        return f"<div style='padding:50px; color:red; font-family:sans-serif;'><h2>Error al eliminar usuario:</h2><p>{str(e)}</p><br><a href='/register'>Volver</a></div>"

@auth_bp.route('/auditoria', strict_slashes=False)
@login_required
def auditoria():
    try:
        # Busca los últimos 200 movimientos
        if Auditoria:
            logs = Auditoria.query.order_by(Auditoria.fecha.desc()).limit(200).all()
        else:
            logs = []
            
        return render_template('auditoria.html', logs=logs)
    except Exception as e:
        return f"<div style='padding:50px; color:red; font-family:sans-serif;'><h2>Error al cargar la Auditoría:</h2><p>Falta el modelo en la Base de Datos. Detalles: {str(e)}</p></div>"

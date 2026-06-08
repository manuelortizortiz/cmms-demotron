# utils/auth.py
from functools import wraps
from flask import abort
from flask_login import current_user

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401) # No autorizado (No ha hecho login)
            if current_user.role not in roles:
                abort(403) # Prohibido (No tiene el rol adecuado)
            return f(*args, **kwargs)
        return decorated
    return decorator

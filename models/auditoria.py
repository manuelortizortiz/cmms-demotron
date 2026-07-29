from extensions import db
from sqlalchemy import event, inspect
from flask_login import current_user
from datetime import datetime
import json

class LogCambios(db.Model):
    __tablename__ = 'log_cambios'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(100))
    tabla = db.Column(db.String(50))
    registro_id = db.Column(db.String(50))
    accion = db.Column(db.String(20)) # UPDATE, DELETE
    cambios = db.Column(db.Text)      # JSON con valor viejo/nuevo
    timestamp = db.Column(db.DateTime, default=datetime.now)

def obtener_usuario_actual():
    try:
        if current_user and current_user.is_authenticated:
            return getattr(current_user, 'username', getattr(current_user, 'nombre', 'Sistema'))
    except:
        pass
    return "Sistema"

# --- LISTENER AUTOMÁTICO DE EVENTOS ---
@event.listens_for(db.session, 'before_flush')
def audit_log_listener(session, flush_context, instances):
    # 1. Detectar Modificaciones (Updates)
    for obj in session.dirty:
        if isinstance(obj, LogCambios): 
            continue
            
        try:
            estado = inspect(obj)
            cambios_detectados = {}
            for attr in estado.attrs:
                hist = attr.history
                if hist.has_changes():
                    val_anterior = hist.deleted[0] if hist.deleted else None
                    val_nuevo = hist.added[0] if hist.added else None
                    cambios_detectados[attr.key] = {'anterior': val_anterior, 'nuevo': val_nuevo}
            
            if cambios_detectados:
                log = LogCambios(
                    usuario=obtener_usuario_actual(),
                    tabla=getattr(obj, '__tablename__', type(obj).__name__),
                    registro_id=str(getattr(obj, 'id', getattr(obj, 'codigo', 'S/I'))),
                    accion='UPDATE',
                    cambios=json.dumps(cambios_detectados, default=str)
                )
                session.add(log)
        except Exception:
            pass # Previene que un error de auditoría bote la transacción principal

    # 2. Detectar Eliminaciones (Deletes)
    for obj in session.deleted:
        if isinstance(obj, LogCambios): 
            continue
            
        try:
            log = LogCambios(
                usuario=obtener_usuario_actual(),
                tabla=getattr(obj, '__tablename__', type(obj).__name__),
                registro_id=str(getattr(obj, 'id', getattr(obj, 'codigo', 'S/I'))),
                accion='DELETE',
                cambios='{"estado": "Registro eliminado permanentemente"}'
            )
            session.add(log)
        except Exception:
            pass

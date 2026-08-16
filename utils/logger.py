from datetime import datetime
from extensions import db
from models.chatter import RegistroChatter

def registrar_auditoria(usuario, modelo_ref, registro_id, accion, mensaje):
    try:
        # Extraer nombre o username del usuario actual de manera segura
        autor = 'Sistema'
        if usuario and not usuario.is_anonymous:
            autor = getattr(usuario, 'username', getattr(usuario, 'nombre', 'Usuario'))

        log = RegistroChatter(
            fecha=datetime.now(),
            modelo_ref=str(modelo_ref),
            registro_id=str(registro_id),
            autor=str(autor),
            accion=str(accion),
            mensaje=str(mensaje)
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error al registrar auditoría: {str(e)}")

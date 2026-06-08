from flask import Blueprint, render_template
import random
from datetime import datetime
from flask_login import login_required
from sqlalchemy import func
from extensions import db
from models.equipo import Equipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico, RegistroUsoEquipo
from utils.formatters import format_num, format_clp, buscar_foto_por_tipo

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/', strict_slashes=False)
@login_required
def dashboard():
    try:
        eqs_db = Equipo.query.all()
        ots_db = OrdenTrabajo.query.order_by(OrdenTrabajo.fecha.desc()).all()
        
        # --- CÁLCULO DE FALLAS POR SISTEMA (PARETO) ---
        fallas_query = db.session.query(
            OrdenTrabajo.sistema_falla, 
            func.count(OrdenTrabajo.id)
        ).filter(OrdenTrabajo.tipo_ot == 'Correctiva')\
         .group_by(OrdenTrabajo.sistema_falla).all()
        
        labels_fallas = [f[0] or "Otros" for f in fallas_query]
        data_fallas = [f[1] for f in fallas_query]
        # -----------------------------------------------

        # [RESTA DEL CÓDIGO DEL DASHBOARD...]
        # (He dejado el resto de la lógica igual para no romper nada, solo inserta esto arriba)
        
        # ... (Tu lógica de equipos, KPIs, etc.)
        
        # Al final de la función, cuando haces el render_template, añade 'fallas_data':
        return render_template('index.html', 
                               # ... (tus variables existentes)
                               fallas_data={'labels': labels_fallas, 'data': data_fallas})
    except Exception as e:
        return f"Error en Dashboard: {str(e)}"

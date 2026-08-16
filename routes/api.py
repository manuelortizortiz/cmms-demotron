from flask import Blueprint, render_template, abort
from flask_login import login_required
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from datetime import datetime

api_bp = Blueprint('api', __name__)

@api_bp.route('/api/imprimir_registro/<codigo>', strict_slashes=False)
@login_required
def imprimir_registro(codigo):
    try:
        equipo = Equipo.query.filter_by(codigo=codigo).first()
        if not equipo: abort(404)
        
        mants_prev = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Preventiva').order_by(OrdenTrabajo.fecha.desc()).all()
        mants_corr = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Correctiva').order_by(OrdenTrabajo.fecha.desc()).all()
        lecturas = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).all()
        compras = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.fecha.desc()).all()
        
        # Busca equivalencias por código y por modelo
        todos_filtros = FiltroEquipo.query.all()
        filtros = []
        for f in todos_filtros:
            f_eq = str(f.codigo_equipo).strip().upper()
            if f_eq == str(equipo.codigo).strip().upper() or f_eq == str(equipo.modelo).strip().upper():
                filtros.append(f)
                
        return render_template('print_ficha.html', equipo=equipo, mants_prev=mants_prev, mants_corr=mants_corr, lecturas=lecturas, compras=compras, filtros=filtros, hoy=datetime.now())
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error del Servidor al generar PDF de Ficha:</b> {str(e)}</div>"

@api_bp.route('/api/imprimir_filtros/<codigo>', strict_slashes=False)
@login_required
def imprimir_filtros(codigo):
    try:
        equipo = Equipo.query.filter_by(codigo=codigo).first()
        if not equipo: abort(404)
        
        # Busca equivalencias por código y por modelo
        todos_filtros = FiltroEquipo.query.all()
        filtros = []
        for f in todos_filtros:
            f_eq = str(f.codigo_equipo).strip().upper()
            if f_eq == str(equipo.codigo).strip().upper() or f_eq == str(equipo.modelo).strip().upper():
                filtros.append(f)
                
        return render_template('print_filtros.html', equipo=equipo, filtros=filtros, hoy=datetime.now())
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error del Servidor al generar PDF de Filtros:</b> {str(e)}</div>"

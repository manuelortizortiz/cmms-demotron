from flask import Blueprint, render_template
from datetime import datetime
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura
from models.personal import Mecanico, RegistroUsoEquipo
from utils.formatters import format_num, format_clp, buscar_foto_por_tipo

equipos_bp = Blueprint('equipos', __name__)

@equipos_bp.route('/equipo/<codigo>', strict_slashes=False)
def ficha_equipo(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    foto_url = buscar_foto_por_tipo(equipo.tipo_equipo, equipo.marca)
    
    ots = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.fecha.desc()).all()
    lecturas_db = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).limit(15).all()
    filtros_db = FiltroEquipo.query.filter_by(codigo_equipo=codigo).all()
    usos_db = RegistroUsoEquipo.query.filter_by(codigo_equipo=codigo).order_by(RegistroUsoEquipo.fecha.desc()).limit(10).all()
    
    mecanicos_db = Mecanico.query.all()
    lista_mecanicos = [{'nombre': m.nombre} for m in mecanicos_db]

    mants_prev = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y'), 'tipo': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'folio': m.folio, 'lectura': format_num(m.lectura), 'mecanico': m.mecanico} for m in ots if m.tipo_ot == 'Preventiva']
    mants_corr = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y'), 'tipo': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'folio': m.folio, 'lectura': format_num(m.lectura), 'mecanico': m.mecanico} for m in ots if m.tipo_ot == 'Correctiva']

    lecturas = [{'id': l.id, 'fecha': l.fecha.strftime('%d/%m/%Y'), 'valor': format_num(max(l.horometro or 0, l.kilometraje or 0)), 'tipo': 'HR' if (l.horometro and l.horometro > 0) else 'KM', 'obs': l.observacion} for l in lecturas_db]
    filtros = [{'id': f.id, 'sistema': f.sistema, 'cant': f.cant, 'fleetguard': f.fleetguard, 'baldwind': f.baldwind, 'originales': f.originales, 'donaldson': f.donaldson, 'otra': f.otra} for f in filtros_db]
    usos = [{'id': u.id, 'fecha': u.fecha.strftime('%d/%m/%Y'), 'operador': u.operador, 'obs': u.observacion} for u in usos_db]

    return render_template('ficha_equipo.html', eq=equipo, foto_url=foto_url, mants_prev=mants_prev, mants_corr=mants_corr, lecturas=lecturas, filtros=filtros, usos=usos, mecanicos=lista_mecanicos)

@equipos_bp.route('/imprimir_ot/<int:ot_id>', strict_slashes=False)
def imprimir_ot(ot_id):
    ot = OrdenTrabajo.query.get_or_404(ot_id)
    equipo = Equipo.query.filter_by(codigo=ot.codigo_equipo).first()
    filtros = FiltroEquipo.query.filter_by(codigo_equipo=ot.codigo_equipo).all()
    
    ultima_ot = OrdenTrabajo.query.filter(
        OrdenTrabajo.codigo_equipo == ot.codigo_equipo,
        OrdenTrabajo.id < ot.id,
        OrdenTrabajo.estado == 'Finalizada'
    ).order_by(OrdenTrabajo.fecha.desc()).first()

    return render_template('ot_print.html', equipo=equipo, ot=ot, filtros=filtros, ultima_ot=ultima_ot, fecha_actual=datetime.now().strftime("%d/%m/%Y"))

@equipos_bp.route('/imprimir_pauta/<codigo>', strict_slashes=False)
def imprimir_pauta(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    filtros = FiltroEquipo.query.filter_by(codigo_equipo=codigo).all()
    return render_template('pauta_print.html', equipo=equipo, filtros=filtros, fecha_actual=datetime.now().strftime("%d/%m/%Y"))

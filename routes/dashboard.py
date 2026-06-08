from flask import Blueprint, render_template
import random
from datetime import datetime
from models.equipo import Equipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico, RegistroUsoEquipo
from utils.formatters import format_num, format_clp, buscar_foto_por_tipo

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/', strict_slashes=False)
def dashboard():
    try:
        eqs_db = Equipo.query.all()
        ots_db = OrdenTrabajo.query.order_by(OrdenTrabajo.fecha.desc()).all()
        compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
        lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).all()
        operadores_db = Personal.query.all()
        mecanicos_db = Mecanico.query.all()
        usos_db = RegistroUsoEquipo.query.order_by(RegistroUsoEquipo.fecha.desc()).all()
        
        equipos_dict, taller, criticos, proximos = [], [], [], []
        conteo_estado = {'Operativo': 0, 'Fuera de Servicio': 0, 'Taller': 0}
        
        for e in eqs_db:
            eq_data = {
                'codigo': e.codigo, 'tipo': e.tipo_equipo or 'S/E', 'marca': e.marca or 'S/E', 'modelo': e.modelo or 'S/E',
                'ubicacion': e.ubicacion or 'Sin Ubicación', 'responsable': e.responsable or 'Sin Asignar', 'ctrl': e.control_base,
                'lectura': format_num(e.lectura_actual), 'margen': e.margen, 'margen_str': format_num(e.margen), 
                'estado': e.estado_base, 'vin': e.vin, 'motor': e.n_motor, 'patente': e.patente,
                'foto_url': buscar_foto_por_tipo(e.tipo_equipo, e.marca)
            }
            equipos_dict.append(eq_data)
            estado_clean = 'Fuera de Servicio' if e.estado_base in ['Fuera de Servicio', 'No operativo'] else e.estado_base
            conteo_estado[estado_clean] = conteo_estado.get(estado_clean, 0) + 1
            if e.estado_base == 'Taller': taller.append(eq_data)
            if e.margen < 0 and e.estado_base != 'Fuera de Servicio': criticos.append(eq_data)
            if 0 <= e.margen <= 150 and e.estado_base != 'Fuera de Servicio': proximos.append(eq_data)

        proximos = sorted(proximos, key=lambda x: x['margen'])
        equipos_aleatorios = list(equipos_dict)
        random.shuffle(equipos_aleatorios)

        todas_mants_prev = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y'), 'fecha_iso': m.fecha.strftime('%Y-%m-%d'), 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'lectura_str': format_num(m.lectura), 'mecanico': m.mecanico} for m in ots_db if m.tipo_ot == 'Preventiva']
        todas_mants_corr = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y'), 'fecha_iso': m.fecha.strftime('%Y-%m-%d'), 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'lectura_str': format_num(m.lectura), 'mecanico': m.mecanico} for m in ots_db if m.tipo_ot == 'Correctiva']
        todas_compras = [{'id': c.id, 'fecha': c.fecha.strftime('%d/%m/%Y'), 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp)} for c in compras_db]
        todas_lecturas = [{'id': l.id, 'fecha': l.fecha.strftime('%d/%m/%Y'), 'codigo': l.codigo_equipo, 'valor_str': format_num(max(l.horometro or 0, l.kilometraje or 0)), 'tipo': 'HR' if (l.horometro and l.horometro > 0) else 'KM', 'obs': l.observacion, 'responsable': l.responsable} for l in lecturas_db]
        
        kanban_tareas = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Finalizada': []}
        for ot in ots_db:
            if ot.estado in kanban_tareas:
                if ot.estado == 'Finalizada' and len(kanban_tareas['Finalizada']) >= 10: continue
                kanban_tareas[ot.estado].append({'id': ot.id, 'codigo': ot.codigo_equipo, 'folio': ot.folio, 'tipo': ot.tipo_mantencion, 'fecha': ot.fecha.strftime('%d/%m/%Y'), 'clasificacion': ot.tipo_ot})

        lista_operadores = [{'id': p.id, 'nombre': p.nombre, 'cargo': p.cargo, 'estado': p.estado, 'equipo_asignado': p.equipo_asignado} for p in operadores_db]
        lista_mecanicos = [{'id': m.id, 'nombre': m.nombre, 'especialidad': m.especialidad, 'estado': m.estado} for m in mecanicos_db]
        lista_usos = [{'id': u.id, 'fecha': u.fecha.strftime('%d/%m/%Y'), 'operador': u.operador, 'codigo_equipo': u.codigo_equipo, 'observacion': u.observacion} for u in usos_db]

        mes_actual = datetime.now().month
        costos = {2:0, 3:0, 4:0, 5:0, 6:0, 7:0}
        for ot in ots_db:
            if ot.fecha and ot.fecha.year >= 2026 and ot.fecha.month in costos: costos[ot.fecha.month] += (ot.costo_mantencion_clp or 0)
        for c in compras_db:
            if c.fecha and c.fecha.year >= 2026 and c.fecha.month in costos: costos[c.fecha.month] += (c.costo_pm_clp or 0)

        kpis = {'total': len(eqs_db), 'operativos': conteo_estado.get('Operativo', 0), 'atrasados': len(criticos), 'ot_abiertas': len([o for o in ots_db if o.estado != 'Finalizada']), 'costo_mes_str': format_clp(costos.get(mes_actual, 0))}
        charts = {'estado': conteo_estado, 'costos_mensuales': {'labels': ['Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul'], 'data': list(costos.values())}}
        
        return render_template('index.html', kpis=kpis, charts=charts, eqs=equipos_dict, criticos=criticos, proximos=proximos, taller=taller,
                               equipos_aleatorios=equipos_aleatorios, mants_prev=todas_mants_prev, mants_corr=todas_mants_corr, compras=todas_compras, 
                               lecturas=todas_lecturas, kanban=kanban_tareas, operadores=lista_operadores, mecanicos=lista_mecanicos, usos=lista_usos)
    except Exception as e:
        return f"Error en Dashboard: {str(e)}"

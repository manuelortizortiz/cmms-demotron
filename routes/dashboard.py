from flask import Blueprint, render_template
from datetime import datetime
from collections import Counter
from flask_login import login_required
from sqlalchemy import func
from extensions import db
from models.equipo import Equipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico, RegistroUsoEquipo
from models.bodega import InventarioBodega
from utils.formatters import format_num, format_clp, buscar_foto_por_tipo

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/', strict_slashes=False)
@login_required
def dashboard():
    try:
        eqs_db = Equipo.query.all()
        ots_db = OrdenTrabajo.query.order_by(OrdenTrabajo.fecha.desc()).all()
        compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
        lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).all()
        operadores_db = Personal.query.all()
        mecanicos_db = Mecanico.query.all()
        usos_db = RegistroUsoEquipo.query.order_by(RegistroUsoEquipo.fecha.desc()).all()
        bodega_db = InventarioBodega.query.order_by(InventarioBodega.nombre).all()
        
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

        fallas_query = db.session.query(OrdenTrabajo.sistema_falla, func.count(OrdenTrabajo.id))\
                         .filter(OrdenTrabajo.tipo_ot == 'Correctiva').group_by(OrdenTrabajo.sistema_falla).all()
        fallas_data = {'labels': [f[0] or "Otros" for f in fallas_query], 'data': [f[1] for f in fallas_query]}

        proximos = sorted(proximos, key=lambda x: x['margen'])

        total_eq = len(eqs_db)
        operativos_count = conteo_estado.get('Operativo', 0)
        disponibilidad_pct = round((operativos_count / total_eq * 100), 1) if total_eq > 0 else 0

        # --- CORRECCIÓN: CUMPLIMIENTO PM REAL BASADO EN ALERTAS ACTIVAS ---
        atrasados_count = len(criticos)
        cumpl_pm_pct = round(((total_eq - atrasados_count) / total_eq * 100), 1) if total_eq > 0 else 100.0

        mes_actual = datetime.now().month
        anio_actual = datetime.now().year
        correctivas_mes = len([o for o in ots_db if o.tipo_ot=='Correctiva' and o.fecha and o.fecha.month==mes_actual and o.fecha.year==anio_actual])

        eq_fallas_counter = Counter(o.codigo_equipo for o in ots_db if o.tipo_ot=='Correctiva')
        top_equipos_fallas = [
            {'codigo': k, 'cantidad': v, 'foto_url': buscar_foto_por_tipo(next((e.tipo_equipo for e in eqs_db if e.codigo==k), ''), '')}
            for k, v in eq_fallas_counter.most_common(5)
        ]

        # --- NUEVO DATO: TOP 7 EQUIPOS MÁS COSTOSOS EN PREVENTIVA Y CORRECTIVA ---
        costos_prev_eq = {}
        costos_corr_eq = {}
        for o in ots_db:
            cod = o.codigo_equipo
            costo = float(o.costo_mantencion_clp or 0.0)
            if o.tipo_ot == 'Preventiva':
                costos_prev_eq[cod] = costos_prev_eq.get(cod, 0.0) + costo
            elif o.tipo_ot == 'Correctiva':
                costos_corr_eq[cod] = costos_corr_eq.get(cod, 0.0) + costo

        top_7_prev_list = sorted(costos_prev_eq.items(), key=lambda x: x[1], reverse=True)[:7]
        top_7_corr_list = sorted(costos_corr_eq.items(), key=lambda x: x[1], reverse=True)[:7]

        top_7_preventivas = [{'codigo': x[0], 'costo': x[1], 'costo_str': format_clp(x[1])} for x in top_7_prev_list]
        top_7_correctivas = [{'codigo': x[0], 'costo': x[1], 'costo_str': format_clp(x[1])} for x in top_7_corr_list]

        todas_mants_prev = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y'), 'fecha_iso': m.fecha.strftime('%Y-%m-%d'), 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'lectura_str': format_num(m.lectura), 'mecanico': m.mecanico} for m in ots_db if m.tipo_ot == 'Preventiva']
        todas_mants_corr = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y'), 'fecha_iso': m.fecha.strftime('%Y-%m-%d'), 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'sistema_falla': m.sistema_falla, 'causa_raiz': m.causa_raiz, 'lectura_str': format_num(m.lectura), 'mecanico': m.mecanico} for m in ots_db if m.tipo_ot == 'Correctiva']
        todas_compras = [{'id': c.id, 'fecha': c.fecha.strftime('%d/%m/%Y'), 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp)} for c in compras_db]
        
        todas_lecturas = []
        for l in lecturas_db:
            eq = next((e for e in eqs_db if e.codigo == l.codigo_equipo), None)
            tipo_eq = eq.tipo_equipo if eq else 'S/E'
            todas_lecturas.append({
                'id': l.id, 'fecha': l.fecha.strftime('%d/%m/%Y'), 
                'codigo': l.codigo_equipo, 'tipo_equipo': tipo_eq,
                'valor_str': format_num(max(l.horometro or 0, l.kilometraje or 0)), 
                'tipo': 'HR' if (l.horometro and l.horometro > 0) else 'KM'
            })
            
        bodega_list = [{'id': b.id, 'codigo_item': b.codigo_item, 'nombre': b.nombre, 'categoria': b.categoria, 'cantidad': b.cantidad, 'ubicacion': b.ubicacion} for b in bodega_db]
        
        kanban_tareas = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Finalizada': []}
        for ot in ots_db:
            estado_k = ot.estado if ot.estado in kanban_tareas else 'Pendiente'
            dias_abierta = (datetime.now() - ot.fecha).days if ot.fecha else 0
            kanban_tareas[estado_k].append({
                'id': ot.id, 'codigo': ot.codigo_equipo, 'folio': ot.folio,
                'tipo': ot.tipo_mantencion, 'fecha': ot.fecha.strftime('%d/%m/%Y') if ot.fecha else '',
                'clasificacion': ot.tipo_ot, 'mecanico': ot.mecanico or 'Sin Asignar',
                'sistema_falla': ot.sistema_falla or '', 'dias': dias_abierta,
                'vencida': dias_abierta > 7 and estado_k != 'Finalizada'
            })

        costos = {2:0, 3:0, 4:0, 5:0, 6:0, 7:0}
        for ot in ots_db:
            if ot.fecha and ot.fecha.year >= 2026 and ot.fecha.month in costos: costos[ot.fecha.month] += (ot.costo_mantencion_clp or 0)

        correctivas_cerradas = [ot for ot in ots_db if ot.tipo_ot == 'Correctiva' and ot.estado == 'Finalizada' and ot.fecha_cierre and ot.fecha]
        if correctivas_cerradas:
            horas_totales = sum((ot.fecha_cierre - ot.fecha).total_seconds() / 3600 for ot in correctivas_cerradas)
            mttr = round(horas_totales / len(correctivas_cerradas), 1)
            mttr_str = f"{mttr} hrs"
        else:
            mttr_str = "0 hrs"

        kpis = {
            'total': total_eq, 'operativos': operativos_count, 'atrasados': len(criticos), 
            'ot_abiertas': len([o for o in ots_db if o.estado != 'Finalizada']),
            'costo_mes_str': format_clp(costos.get(mes_actual, 0)), 'mttr': mttr_str,
            'disponibilidad_pct': disponibilidad_pct, 'cumpl_pm_pct': cumpl_pm_pct,
            'correctivas_mes': correctivas_mes
        }

        charts = {
            'estado': conteo_estado,
            'costos_mensuales': {'labels': ['Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul'], 'data': list(costos.values())},
            'costos_top7': {
                'prev_labels': [x['codigo'] for x in top_7_preventivas],
                'prev_data': [x['costo'] for x in top_7_preventivas],
                'corr_labels': [x['codigo'] for x in top_7_correctivas],
                'corr_data': [x['costo'] for x in top_7_correctivas]
            }
        }
        
        mecanicos_list = [{'id': m.id, 'rut': m.rut, 'nombre': m.nombre, 'especialidad': m.especialidad, 'estado': m.estado} for m in mecanicos_db]

        return render_template('index.html', kpis=kpis, charts=charts, fallas_data=fallas_data, 
                               eqs=equipos_dict, criticos=criticos, proximos=proximos, taller=taller, 
                               top_equipos_fallas=top_equipos_fallas, mants_prev=todas_mants_prev, 
                               mants_corr=todas_mants_corr, compras=todas_compras, lecturas=todas_lecturas, 
                               kanban=kanban_tareas, operadores=[{'id': p.id, 'nombre': p.nombre, 'cargo': p.cargo, 'estado': p.estado, 'equipo_asignado': p.equipo_asignado} for p in operadores_db], 
                               mecanicos=mecanicos_list, bodega=bodega_list,
                               top_7_preventivas=top_7_preventivas, top_7_correctivas=top_7_correctivas,
                               usos=[{'id': u.id, 'fecha': u.fecha.strftime('%d/%m/%Y'), 'operador': u.operador, 'codigo_equipo': u.codigo_equipo, 'observacion': u.observacion} for u in usos_db])
    except Exception as e:
        return f"Error en Dashboard: {str(e)}"

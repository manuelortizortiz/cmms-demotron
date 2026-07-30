from flask import Blueprint, render_template
from datetime import datetime, timedelta
from flask_login import login_required
from extensions import db
from models.equipo import Equipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico
from models.bodega import InventarioBodega
from utils.formatters import format_num, format_clp

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/', strict_slashes=False)
@login_required
def dashboard():
    try:
        hoy = datetime.now()
        
        # 1. ESTADO DE FLOTA Y DISPONIBILIDAD
        eqs_db = Equipo.query.all()
        total_eq = len(eqs_db)
        operativos = [e for e in eqs_db if e.estado_base == 'Operativo']
        en_taller = [e for e in eqs_db if e.estado_base == 'Taller']
        atrasados = [e for e in eqs_db if (e.proxima_pm or 0) - (e.lectura_actual or 0) < 0 and e.estado_base != 'Fuera de Servicio']
        
        disponibilidad_pct = round((len(operativos) / total_eq * 100), 1) if total_eq > 0 else 0
        cumplimiento_pct = round(((total_eq - len(atrasados)) / total_eq * 100), 1) if total_eq > 0 else 100.0

        # 2. ANÁLISIS DE OTs Y COSTOS
        ots_db = OrdenTrabajo.query.all()
        correctivas = [o for o in ots_db if o.tipo_ot == 'Correctiva']
        preventivas = [o for o in ots_db if o.tipo_ot == 'Preventiva']
        
        costo_corr = sum(float(o.costo_mantencion_clp or 0) for o in correctivas)
        costo_prev = sum(float(o.costo_mantencion_clp or 0) for o in preventivas)
        costo_total = costo_corr + costo_prev
        
        ratio_corr = round((costo_corr / costo_total * 100), 1) if costo_total > 0 else 0
        ratio_prev = round((costo_prev / costo_total * 100), 1) if costo_total > 0 else 0

        # MTTR y MTBF
        mttr_horas = 0
        cerradas_corr = [o for o in correctivas if o.estado == 'Finalizada' and o.fecha_cierre and o.fecha]
        if cerradas_corr:
            horas_tot = sum((o.fecha_cierre - o.fecha).total_seconds() / 3600 for o in cerradas_corr)
            mttr_horas = round(horas_tot / len(cerradas_corr), 1)

        dias_operacion_total = total_eq * 30 
        mtbf_dias = round(dias_operacion_total / len(correctivas), 1) if len(correctivas) > 0 else dias_operacion_total

        # 3. PREPARACIÓN DE DATASETS PARA EL FRONTEND
        marcas_stats = {}
        equipos_dict = []
        eventos_calendario = []
        scatter_riesgo = []
        
        for e in eqs_db:
            m = e.marca or 'S/I'
            if m not in marcas_stats: marcas_stats[m] = {'total': 0, 'operativos': 0, 'costo': 0, 'fallas': 0}
            marcas_stats[m]['total'] += 1
            if e.estado_base == 'Operativo': marcas_stats[m]['operativos'] += 1
            
            c_eq = sum(float(o.costo_mantencion_clp or 0) for o in ots_db if o.codigo_equipo == e.codigo)
            f_eq = len([o for o in correctivas if o.codigo_equipo == e.codigo])
            marcas_stats[m]['costo'] += c_eq
            marcas_stats[m]['fallas'] += f_eq

            disp_eq = 100 if e.estado_base == 'Operativo' else (50 if e.estado_base == 'Taller' else 0)
            if c_eq > 0 or f_eq > 0:
                scatter_riesgo.append({'x': c_eq, 'y': disp_eq, 'r': max(5, f_eq * 3), 'codigo': e.codigo})

            margen = (e.proxima_pm or 0) - (e.lectura_actual or 0)
            if margen >= 0 and e.estado_base != 'Fuera de Servicio':
                dias_est = int(margen / (8 if e.control_base == 'HORAS' else 100))
                fecha_iso = (hoy + timedelta(days=max(1, dias_est))).strftime('%Y-%m-%d')
                if dias_est <= 45:
                    eventos_calendario.append({
                        'title': f"PM: {e.codigo}",
                        'start': fecha_iso,
                        'backgroundColor': '#DBEAFE',
                        'textColor': '#1E3A8A',
                        'borderColor': 'transparent'
                    })

            equipos_dict.append({
                'codigo': e.codigo, 'tipo': e.tipo_equipo or 'S/E', 'marca': e.marca or 'S/E', 'modelo': e.modelo or 'S/E',
                'patente': e.patente or 'S/I', 'ubicacion': e.ubicacion or 'S/I', 'lectura': format_num(e.lectura_actual), 
                'margen': margen, 'margen_str': format_num(margen), 'estado': e.estado_base, 'ctrl': e.control_base
            })

        # RECUPERACIÓN DE TABLAS DE HISTORIALES (AQUÍ ESTABA EL ERROR)
        compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
        bodega_db = InventarioBodega.query.order_by(InventarioBodega.nombre).all()
        personal_db = Personal.query.all()
        
        mants_prev = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else '', 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'mecanico': m.mecanico} for m in preventivas]
        mants_corr = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else '', 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'sistema_falla': m.sistema_falla, 'causa_raiz': m.causa_raiz, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'mecanico': m.mecanico} for m in correctivas]
        compras_formateadas = [{'id': c.id, 'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else '', 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp)} for c in compras_db]
        
        kanban = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Finalizada': []}
        for ot in ots_db:
            k = ot.estado if ot.estado in kanban else 'Pendiente'
            kanban[k].append({'id': ot.id, 'codigo': ot.codigo_equipo, 'folio': ot.folio, 'tipo': ot.tipo_mantencion, 'clasificacion': ot.tipo_ot, 'mecanico': ot.mecanico})

        kpis = {
            'total': total_eq, 'operativos': len(operativos), 'atrasados': len(atrasados), 'en_taller': len(en_taller),
            'disp_pct': disponibilidad_pct, 'cumpl_pct': cumplimiento_pct,
            'mttr': mttr_horas, 'mtbf': mtbf_dias,
            'costo_total': format_clp(costo_total), 'ratio_corr': ratio_corr, 'ratio_prev': ratio_prev,
            'correctivas_count': len(correctivas), 'preventivas_count': len(preventivas),
            'ot_abiertas': sum(len(kanban[estado]) for estado in ['Pendiente', 'En Progreso', 'En Revisión'])
        }

        dist_marcas = [{'marca': k, 'total': v['total'], 'operativos': v['operativos'], 'costo': v['costo']} for k, v in marcas_stats.items()]
        dist_marcas = sorted(dist_marcas, key=lambda x: x['total'], reverse=True)

        return render_template('index.html', kpis=kpis, eqs=equipos_dict, mants_prev=mants_prev, 
                               mants_corr=mants_corr, compras=compras_formateadas, bodega=bodega_db, 
                               personal=personal_db, kanban=kanban, eventos_calendario=eventos_calendario,
                               dist_marcas=dist_marcas, scatter_riesgo=scatter_riesgo)
    except Exception as e:
        return f"Error en Dashboard: {str(e)}"

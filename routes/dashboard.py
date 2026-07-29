from flask import Blueprint, render_template
from datetime import datetime, timedelta
from collections import Counter
from flask_login import login_required
from sqlalchemy import func, case, extract
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
        hoy = datetime.now()
        
        # =========================================================================
        # 1. MOTOR ANALÍTICO OPTIMIZADO (SQLAlchemy Aggregations)
        # =========================================================================
        # CORRECCIÓN: Se reemplazó Equipo.margen por la resta directa en SQL
        kpis_flota = db.session.query(
            func.count(Equipo.id).label('total'),
            func.sum(case((Equipo.estado_base == 'Operativo', 1), else_=0)).label('operativos'),
            func.sum(case((Equipo.estado_base == 'Taller', 1), else_=0)).label('en_taller'),
            func.sum(case(((func.coalesce(Equipo.proxima_pm, 0) - func.coalesce(Equipo.lectura_actual, 0)) < 0, 1), else_=0)).label('atrasados')
        ).first()

        total_eq = int(kpis_flota.total or 0)
        operativos_count = int(kpis_flota.operativos or 0)
        atrasados_count = int(kpis_flota.atrasados or 0)

        disponibilidad_pct = round((operativos_count / total_eq * 100), 1) if total_eq > 0 else 0
        cumpl_pm_pct = round(((total_eq - atrasados_count) / total_eq * 100), 1) if total_eq > 0 else 100.0

        # Variación de Costos Mes a Mes (MoM)
        mes_actual_inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fin_mes_anterior = mes_actual_inicio - timedelta(days=1)
        mes_anterior_inicio = fin_mes_anterior.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        costo_actual = db.session.query(func.sum(OrdenTrabajo.costo_mantencion_clp))\
            .filter(OrdenTrabajo.fecha >= mes_actual_inicio).scalar() or 0.0
        
        costo_anterior = db.session.query(func.sum(OrdenTrabajo.costo_mantencion_clp))\
            .filter(OrdenTrabajo.fecha >= mes_anterior_inicio, OrdenTrabajo.fecha <= fin_mes_anterior).scalar() or 0.0

        variacion_costo = ((costo_actual - costo_anterior) / costo_anterior * 100) if costo_anterior > 0 else 0

        # Pareto de Fallas Optimizada
        fallas_query = db.session.query(OrdenTrabajo.sistema_falla, func.count(OrdenTrabajo.id))\
            .filter(OrdenTrabajo.tipo_ot == 'Correctiva', OrdenTrabajo.sistema_falla != 'Estructura')\
            .group_by(OrdenTrabajo.sistema_falla).all()
        fallas_data = {'labels': [f[0] or "Otros" for f in fallas_query], 'data': [f[1] for f in fallas_query]}

        # Top 5 Equipos Más Costosos
        top_costosos = db.session.query(
            OrdenTrabajo.codigo_equipo,
            func.sum(OrdenTrabajo.costo_mantencion_clp).label('costo_acumulado')
        ).group_by(OrdenTrabajo.codigo_equipo)\
         .order_by(func.sum(OrdenTrabajo.costo_mantencion_clp).desc()).limit(5).all()

        # Distribución de Marcas
        distribucion_marcas = db.session.query(
            Equipo.marca,
            func.count(Equipo.id).label('cantidad'),
            func.sum(case((Equipo.estado_base == 'Operativo', 1), else_=0)).label('operativos')
        ).group_by(Equipo.marca).order_by(func.count(Equipo.id).desc()).limit(10).all()

        # =========================================================================
        # 2. OBTENCIÓN DE DATOS PARA TABLAS Y KANBAN
        # =========================================================================
        eqs_db = Equipo.query.all()
        ots_db = OrdenTrabajo.query.order_by(OrdenTrabajo.fecha.desc()).all()
        compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
        lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).all()
        operadores_db = Personal.query.all()
        mecanicos_db = Mecanico.query.all()
        bodega_db = InventarioBodega.query.order_by(InventarioBodega.nombre).all()
        
        equipos_dict, taller, criticos, proximos, predictivo_list, finanzas_flota = [], [], [], [], [], []
        cercanos_seguro, eventos_futuros = [], []
        
        costos_mants_por_equipo = {}
        for ot in ots_db:
            costos_mants_por_equipo[ot.codigo_equipo] = costos_mants_por_equipo.get(ot.codigo_equipo, 0) + float(ot.costo_mantencion_clp or 0)
        
        costos_compras_por_equipo = {}
        for c in compras_db:
            costos_compras_por_equipo[c.codigo_equipo] = costos_compras_por_equipo.get(c.codigo_equipo, 0) + float(c.costo_pm_clp or 0)

        for e in eqs_db:
            eq_data = {
                'codigo': e.codigo, 'tipo': e.tipo_equipo or 'S/E', 'marca': e.marca or 'S/E', 'modelo': e.modelo or 'S/E',
                'ubicacion': e.ubicacion or 'Sin Ubicación', 'responsable': e.responsable or 'Sin Asignar', 'ctrl': e.control_base,
                'lectura': format_num(e.lectura_actual), 'margen': e.margen, 'margen_str': format_num(e.margen), 
                'estado': e.estado_base, 'vin': e.vin, 'motor': e.n_motor, 'patente': e.patente,
                'foto_url': buscar_foto_por_tipo(e.tipo_equipo, e.marca)
            }
            equipos_dict.append(eq_data)
            
            if e.estado_base == 'Taller': taller.append(eq_data)
            if e.margen < 0 and e.estado_base != 'Fuera de Servicio': criticos.append(eq_data)
            if 0 <= e.margen <= 150 and e.estado_base != 'Fuera de Servicio': proximos.append(eq_data)

            try:
                m_val = float(e.margen)
                if e.estado_base != 'Fuera de Servicio' and m_val >= 0:
                    dias_est = int(m_val / 8) if e.control_base == 'HORAS' else int(m_val / 100)
                    dias_est = max(1, dias_est) 
                    fecha_est = (hoy + timedelta(days=dias_est)).strftime('%d/%m/%Y')
                    fecha_iso = (hoy + timedelta(days=dias_est)).strftime('%Y-%m-%d')
                    
                    predictivo_list.append({
                        'codigo': e.codigo, 'tipo': e.tipo_equipo, 'estado': e.estado_base,
                        'lectura': format_num(e.lectura_actual), 'limite': format_num(e.proxima_pm),
                        'margen': m_val, 'margen_str': format_num(m_val), 
                        'fecha_est': fecha_est, 'dias_restantes': dias_est, 'fecha_iso': fecha_iso, 'ctrl': e.control_base
                    })

                    pct = 0.0
                    freq = float(e.frecuencia_base) if e.frecuencia_base else 250.0
                    if freq > 0:
                        consumido = freq - m_val
                        pct = max(0.0, min(100.0, (consumido / freq) * 100))
                    
                    cercanos_seguro.append({'codigo': e.codigo, 'margen': m_val, 'margen_str': format_num(m_val), 'pct': round(pct, 1)})

                    if m_val <= 150:
                        eventos_futuros.append({'title': f"{e.codigo} (PM)", 'start': fecha_iso, 'color': '#F59E0B'})
            except: pass

            c_mants = costos_mants_por_equipo.get(e.codigo, 0)
            c_compras = costos_compras_por_equipo.get(e.codigo, 0)
            c_total = c_mants + c_compras
            lectura_actual = float(e.lectura_actual) if e.lectura_actual else 0.0
            cpk_cph = (c_total / lectura_actual) if lectura_actual > 0 else 0.0

            finanzas_flota.append({
                'codigo': e.codigo, 'tipo': e.tipo_equipo, 'estado': e.estado_base,
                'costo_mants': format_clp(c_mants), 'costo_compras': format_clp(c_compras), 'costo_total': c_total,
                'costo_str': format_clp(c_total), 'lectura': e.lectura_actual, 'ctrl': e.control_base,
                'cpk_cph': round(cpk_cph, 2), 'cpk_cph_str': f"${round(cpk_cph, 2)}/{e.control_base[:2] if e.control_base else ''}"
            })

        equipos_dict = sorted(equipos_dict, key=lambda x: (1 if x['estado'] == 'Fuera de Servicio' else 0, x['codigo']))
        proximos = sorted(proximos, key=lambda x: x['margen'])
        predictivo_list = sorted(predictivo_list, key=lambda x: x['dias_restantes'])
        finanzas_flota = sorted(finanzas_flota, key=lambda x: x['costo_total'], reverse=True)
        top_7_cercanos = sorted(cercanos_seguro, key=lambda x: x['margen'])[:7]

        eq_fallas_counter = Counter(o.codigo_equipo for o in ots_db if o.tipo_ot=='Correctiva')
        top_equipos_fallas = [{'codigo': k, 'cantidad': v, 'foto_url': buscar_foto_por_tipo(next((e.tipo_equipo for e in eqs_db if e.codigo==k), ''), '')} for k, v in eq_fallas_counter.most_common(5)]
        correctivas_mes = len([o for o in ots_db if o.tipo_ot=='Correctiva' and o.fecha and o.fecha.month==hoy.month and o.fecha.year==hoy.year])

        # =========================================================================
        # 3. CONSOLIDACIÓN DE FINANZAS Y KANBAN
        # =========================================================================
        costos_mensuales = {1:0, 2:0, 3:0, 4:0, 5:0, 6:0, 7:0, 8:0, 9:0, 10:0, 11:0, 12:0}
        costos_prev_eq = {}
        costo_total_ytd = 0.0
        
        for o in ots_db:
            costo_ot = float(o.costo_mantencion_clp or 0.0)
            if o.fecha and o.fecha.year == 2026:
                costo_total_ytd += costo_ot
                if o.fecha.month in costos_mensuales: costos_mensuales[o.fecha.month] += costo_ot
                if o.tipo_ot == 'Preventiva': costos_prev_eq[o.codigo_equipo] = costos_prev_eq.get(o.codigo_equipo, 0.0) + costo_ot

        for c in compras_db:
            costo_compra = float(c.costo_pm_clp or 0.0)
            if c.fecha and c.fecha.year == 2026:
                costo_total_ytd += costo_compra
                if c.fecha.month in costos_mensuales: costos_mensuales[c.fecha.month] += costo_compra
                costos_prev_eq[c.codigo_equipo] = costos_prev_eq.get(c.codigo_equipo, 0.0) + costo_compra

        meses_activos = [costos_mensuales[m] for m in range(1, hoy.month + 1) if costos_mensuales[m] > 0]
        pronostico_mes = sum(meses_activos[-3:]) / len(meses_activos[-3:]) if len(meses_activos[-3:]) > 0 else 0.0

        top_7_prev_list = sorted(costos_prev_eq.items(), key=lambda x: x[1], reverse=True)[:7]
        top_7_preventivas = [{'codigo': x[0], 'costo': x[1], 'costo_str': format_clp(x[1])} for x in top_7_prev_list]

        todas_mants_prev = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else '', 'fecha_iso': m.fecha.strftime('%Y-%m-%d') if m.fecha else '', 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'lectura_str': format_num(m.lectura), 'mecanico': m.mecanico} for m in ots_db if m.tipo_ot == 'Preventiva']
        todas_mants_corr = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else '', 'fecha_iso': m.fecha.strftime('%Y-%m-%d') if m.fecha else '', 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'sistema_falla': m.sistema_falla, 'causa_raiz': m.causa_raiz, 'lectura_str': format_num(m.lectura), 'mecanico': m.mecanico} for m in ots_db if m.tipo_ot == 'Correctiva']
        todas_compras = [{'id': c.id, 'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else '', 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp)} for c in compras_db]
        
        todas_lecturas = []
        for l in lecturas_db:
            eq = next((e for e in eqs_db if e.codigo == l.codigo_equipo), None)
            tipo_eq = eq.tipo_equipo if eq else 'S/E'
            todas_lecturas.append({
                'id': l.id, 'fecha': l.fecha.strftime('%d/%m/%Y') if l.fecha else '', 
                'codigo': l.codigo_equipo, 'tipo_equipo': tipo_eq,
                'valor_str': format_num(max(l.horometro or 0, l.kilometraje or 0)), 
                'tipo': 'HR' if (l.horometro and l.horometro > 0) else 'KM'
            })
            
        bodega_list = [{'id': b.id, 'codigo_item': b.codigo_item, 'nombre': b.nombre, 'categoria': b.categoria, 'cantidad': b.cantidad, 'ubicacion': b.ubicacion} for b in bodega_db]
        
        kanban_tareas = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Finalizada': []}
        ot_abiertas = 0
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
            if estado_k != 'Finalizada': ot_abiertas += 1

        correctivas_cerradas = [ot for ot in ots_db if ot.tipo_ot == 'Correctiva' and ot.estado == 'Finalizada' and ot.fecha_cierre and ot.fecha]
        if correctivas_cerradas:
            horas_totales = sum((ot.fecha_cierre - ot.fecha).total_seconds() / 3600 for ot in correctivas_cerradas)
            mttr = round(horas_totales / len(correctivas_cerradas), 1)
            mttr_str = f"{mttr} hrs"
        else: mttr_str = "0 hrs"

        kpis = {
            'total': total_eq, 'operativos': operativos_count, 'atrasados': atrasados_count, 
            'ot_abiertas': ot_abiertas, 'costo_mes_str': format_clp(costo_actual), 
            'mttr': mttr_str, 'disponibilidad_pct': disponibilidad_pct, 'cumpl_pm_pct': cumpl_pm_pct,
            'correctivas_mes': correctivas_mes, 'costo_total_ytd': format_clp(costo_total_ytd),
            'pronostico_mes': format_clp(pronostico_mes), 'variacion_costo': round(variacion_costo, 1)
        }

        meses_nombres = {1:'Ene', 2:'Feb', 3:'Mar', 4:'Abr', 5:'May', 6:'Jun', 7:'Jul', 8:'Ago', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dic'}
        charts = {
            'estado': {'Operativo': operativos_count, 'Taller': int(kpis_flota.en_taller or 0), 'Fuera de Servicio': total_eq - operativos_count - int(kpis_flota.en_taller or 0)},
            'costos_mensuales': {'labels': [meses_nombres[m] for m in range(1, hoy.month + 1)], 'data': [costos_mensuales.get(m, 0) for m in range(1, hoy.month + 1)]},
            'costos_top7': {'prev_labels': [x['codigo'] for x in top_7_preventivas], 'prev_data': [x['costo'] for x in top_7_preventivas]}
        }
        
        mecanicos_list = [{'id': m.id, 'rut': m.rut, 'nombre': m.nombre, 'especialidad': m.especialidad, 'estado': m.estado} for m in mecanicos_db]

        return render_template('index.html', kpis=kpis, charts=charts, fallas_data=fallas_data, 
                            eqs=equipos_dict, criticos=criticos, proximos=proximos, taller=taller, 
                            top_equipos_fallas=top_equipos_fallas, mants_prev=todas_mants_prev, 
                            mants_corr=todas_mants_corr, compras=todas_compras, lecturas=todas_lecturas, 
                            kanban=kanban_tareas, operadores=[{'id': p.id, 'nombre': p.nombre, 'cargo': p.cargo, 'estado': p.estado, 'equipo_asignado': p.equipo_asignado} for p in operadores_db], 
                            mecanicos=mecanicos_list, bodega=bodega_list,
                            top_7_preventivas=top_7_preventivas, top_7_cercanos=top_7_cercanos,
                            predictivo_list=predictivo_list, finanzas_flota=finanzas_flota,
                            eventos_futuros=eventos_futuros, distribucion_marcas=distribucion_marcas,
                            top_costosos=top_costosos)
    except Exception as e:
        return f"Error Crítico en Motor de Dashboard: {str(e)}"

import os
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from datetime import datetime, timedelta
from collections import Counter
from flask_login import login_required, current_user
from sqlalchemy import func, case, text
from extensions import db

# ==========================================
# IMPORTACIONES
# ==========================================
from models.equipo import Equipo, DocumentoEquipo, FiltroEquipo, HistorialUbicacion
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico
from models.bodega import InventarioBodega, Repuesto, MovimientoBodega, RecetaModelo
from utils.formatters import format_num, format_clp, buscar_foto_por_tipo
from models.chatter import RegistroChatter
from models.logistica import Empresa, Conductor, Rampla, RutaMaestra, SolicitudTransporte, Viaje, CargaViaje, OperacionPortuaria, IncidenciaTransporte

try:
    import zoneinfo
    ZONA_CHILE = zoneinfo.ZoneInfo("America/Santiago")
except ImportError:
    from datetime import timezone
    ZONA_CHILE = timezone(timedelta(hours=-4))

def obtener_hora_chile():
    return datetime.now(ZONA_CHILE).replace(tzinfo=None)

dashboard_bp = Blueprint('dashboard', __name__)

# ==========================================
# MOTOR DE FILTRADO MULTI-EMPRESA ESTRICTO
# ==========================================
def base_query(model):
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    if hasattr(model, 'empresa'):
        if empresa_actual == 'DEMOTRON':
            return model.query.filter((model.empresa == 'DEMOTRON') | (model.empresa == None) | (model.empresa == ''))
        else:
            return model.query.filter(model.empresa == empresa_actual)
    return model.query

# ==========================================
# MÓDULO 1: DASHBOARD GENERAL CMMS
# ==========================================
@dashboard_bp.route('/', strict_slashes=False)
@login_required
def dashboard():
    try:
        hoy = obtener_hora_chile()
        
        # 1. Traer solo equipos de la empresa activa
        eqs_db = base_query(Equipo).all()
        codigos_validos = [e.codigo for e in eqs_db]
        
        # 2. Traer OTs de la empresa activa
        ots_db = base_query(OrdenTrabajo).all()
        
        # 3. FILTRO ESTRICTO PARA HISTORIALES (La clave para no cruzar stats)
        if codigos_validos:
            compras_db = CompraRepuesto.query.filter(CompraRepuesto.codigo_equipo.in_(codigos_validos)).all()
            lecturas_db = HistorialLectura.query.filter(HistorialLectura.codigo_equipo.in_(codigos_validos)).order_by(HistorialLectura.fecha.desc()).limit(100).all()
        else:
            compras_db = []
            lecturas_db = []

        personal_db = Personal.query.all()
        mecanicos_db = Mecanico.query.all()
        bodega_db = InventarioBodega.query.all()

        correctivas = [o for o in ots_db if o.tipo_ot == 'Correctiva']
        preventivas = [o for o in ots_db if o.tipo_ot == 'Preventiva']

        total_eq = len(eqs_db)
        operativos = [e for e in eqs_db if e.estado_base == 'Operativo']
        en_taller = [e for e in eqs_db if e.estado_base == 'Taller']
        fuera_servicio = [e for e in eqs_db if e.estado_base == 'Fuera de Servicio']
        
        eqs_margen = []
        for e in eqs_db:
            margen_bruto = (e.proxima_pm or 0) - (e.lectura_actual or 0)
            divisor = 8 if e.control_base == 'HORAS' else 100
            dias_margen = int(margen_bruto / divisor)
            eqs_margen.append({'eq': e, 'dias': dias_margen})
            
        atrasados_count = len([e for e in eqs_margen if e['dias'] < 0 and e['eq'].estado_base != 'Fuera de Servicio'])

        kpis = {
            'op_pct': round((len(operativos) / max(1, total_eq)) * 100, 1) if total_eq > 0 else 0,
            'op_count': len(operativos),
            'total_eq': total_eq,
            'cumpl_pm_pct': round(((total_eq - atrasados_count) / max(1, total_eq)) * 100, 1) if total_eq > 0 else 0,
            'backlog_count': atrasados_count,
            'taller_fuera_count': len(en_taller) + len(fuera_servicio),
            'disponibilidad_pct': round((len(operativos) / max(1, total_eq)) * 100, 1) if total_eq > 0 else 0
        }

        fecha_febrero = datetime(hoy.year, 2, 1)
        mes_actual_inicio = datetime(hoy.year, hoy.month, 1)
        mes_ant = hoy.month - 1 if hoy.month > 1 else 12
        ano_ant = hoy.year if hoy.month > 1 else hoy.year - 1
        mes_anterior_inicio = datetime(ano_ant, mes_ant, 1)
        mes_anterior_fin = mes_actual_inicio - timedelta(days=1)

        meses_nombres = ['Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        compras_por_mes = {m: 0 for m in meses_nombres}
        
        for c in compras_db:
            if c.fecha and c.fecha >= fecha_febrero:
                idx = c.fecha.month - 2
                if 0 <= idx < len(meses_nombres):
                    compras_por_mes[meses_nombres[idx]] += float(c.costo_pm_clp or 0)

        estados_counts = Counter(e.estado_base for e in eqs_db)
        
        gasto_ot_total = sum(float(o.costo_mantencion_clp or 0) for o in ots_db if o.fecha and o.fecha >= fecha_febrero)
        gasto_ot_actual = sum(float(o.costo_mantencion_clp or 0) for o in ots_db if o.fecha and o.fecha >= mes_actual_inicio)
        gasto_ot_anterior = sum(float(o.costo_mantencion_clp or 0) for o in ots_db if o.fecha and mes_anterior_inicio <= o.fecha <= mes_anterior_fin)

        gasto_rep_total = sum(float(c.costo_pm_clp or 0) for c in compras_db if c.fecha and c.fecha >= fecha_febrero)
        gasto_rep_actual = sum(float(c.costo_pm_clp or 0) for c in compras_db if c.fecha and c.fecha >= mes_actual_inicio)
        gasto_rep_anterior = sum(float(c.costo_pm_clp or 0) for c in compras_db if c.fecha and mes_anterior_inicio <= c.fecha <= mes_anterior_fin)

        gasto_total = gasto_ot_total + gasto_rep_total
        gasto_actual = gasto_ot_actual + gasto_rep_actual
        gasto_anterior = gasto_ot_anterior + gasto_rep_anterior

        cinta2 = {
            'compras_labels': list(compras_por_mes.keys()),
            'compras_data': list(compras_por_mes.values()),
            'estados_labels': list(estados_counts.keys()),
            'estados_data': list(estados_counts.values()),
            'gasto_total': format_clp(gasto_total),
            'gasto_actual': format_clp(gasto_actual),
            'gasto_anterior': format_clp(gasto_anterior)
        }

        marcas_stats = {}
        for e in eqs_db:
            m = e.marca or 'Sin Marca'
            if m not in marcas_stats: 
                marcas_stats[m] = {'count': 0, 'fallas': 0, 'costo_total': 0.0}
            marcas_stats[m]['count'] += 1

        for o in ots_db:
            eq = next((e for e in eqs_db if e.codigo == o.codigo_equipo), None)
            if eq:
                m = eq.marca or 'Sin Marca'
                marcas_stats[m]['costo_total'] += float(o.costo_mantencion_clp or 0)
                if o.tipo_ot == 'Correctiva':
                    marcas_stats[m]['fallas'] += 1

        for c in compras_db:
            eq = next((e for e in eqs_db if e.codigo == c.codigo_equipo), None)
            if eq:
                m = eq.marca or 'Sin Marca'
                marcas_stats[m]['costo_total'] += float(c.costo_pm_clp or 0)

        cinta3 = {'labels': [], 'mtbf': [], 'costo_promedio': []}
        for m, st in marcas_stats.items():
            if st['count'] > 0:
                cinta3['labels'].append(m)
                dias_op = st['count'] * 365
                cinta3['mtbf'].append(round(dias_op / max(1, st['fallas']), 1))
                cinta3['costo_promedio'].append(round(st['costo_total'] / st['count'], 0))

        atrasados_top = sorted([e for e in eqs_margen if e['dias'] < 0], key=lambda x: x['dias'])[:5]
        proximos_top = sorted([e for e in eqs_margen if e['dias'] >= 0], key=lambda x: x['dias'])[:5]
        taller_top = [e for e in eqs_db if e.estado_base == 'Taller'][:5]

        taller_list = []
        for eq in taller_top:
            ult_ot = next((o for o in sorted(correctivas, key=lambda x: x.fecha or datetime.min, reverse=True) if o.codigo_equipo == eq.codigo), None)
            fecha_in = ult_ot.fecha.strftime('%d/%m/%Y') if ult_ot and ult_ot.fecha else 'S/I'
            taller_list.append({'codigo': eq.codigo, 'tipo': eq.tipo_equipo, 'fecha_ingreso': fecha_in, 'estado': eq.estado_base})

        equipos_list = []
        finanzas_flota = []
        eventos_calendario = []
        ubicaciones_dict = {}

        eventos_deduplicados = set()
        
        for ot in preventivas:
            if ot.fecha and ot.estado not in ['Pendiente', 'En Progreso', 'En Revisión']:
                fecha_str = ot.fecha.strftime('%Y-%m-%d')
                clave = f"PREV_{ot.codigo_equipo}_{fecha_str}"
                if clave not in eventos_deduplicados:
                    eventos_calendario.append({'title': f"PREV: {ot.codigo_equipo}", 'start': fecha_str, 'backgroundColor': '#3B82F6', 'textColor': '#FFFFFF', 'borderColor': 'transparent'})
                    eventos_deduplicados.add(clave)
        
        for ot in correctivas:
            if ot.fecha and ot.estado not in ['Pendiente', 'En Progreso', 'En Revisión']:
                fecha_str = ot.fecha.strftime('%Y-%m-%d')
                clave = f"CORR_{ot.codigo_equipo}_{fecha_str}"
                if clave not in eventos_deduplicados:
                    eventos_calendario.append({'title': f"CORR: {ot.codigo_equipo}", 'start': fecha_str, 'backgroundColor': '#EF4444', 'textColor': '#FFFFFF', 'borderColor': 'transparent'})
                    eventos_deduplicados.add(clave)

        for e in eqs_db:
            op = next((p for p in personal_db if p.equipo_asignado == e.codigo), None)
            nom_op = op.nombre if op else 'Sin Asignar'
            
            margen_bruto = (e.proxima_pm or 0) - (e.lectura_actual or 0)
            divisor = 8 if e.control_base == 'HORAS' else 100
            dias_restantes = int(margen_bruto / divisor)
            
            if dias_restantes >= 0 and e.estado_base != 'Fuera de Servicio' and dias_restantes <= 45:
                fecha_proy = hoy + timedelta(days=max(1, dias_restantes))
                eventos_calendario.append({'title': f"PROY: {e.codigo}", 'start': fecha_proy.strftime('%Y-%m-%d'), 'backgroundColor': '#1E3A8A', 'textColor': '#FFFFFF', 'borderColor': 'transparent'})

            txt_margen = f"{dias_restantes} días" if dias_restantes > 0 else f"{dias_restantes} (VENCIDO)"
            
            equipos_list.append({
                'codigo': e.codigo, 'tipo': e.tipo_equipo, 'marca': e.marca, 'modelo': e.modelo,
                'patente': e.patente, 'ubicacion': e.ubicacion, 'lectura': format_num(e.lectura_actual),
                'margen': margen_bruto, 'margen_str': txt_margen, 'estado': e.estado_base, 'ctrl': e.control_base,
                'operador': nom_op
            })

            ub_original = e.ubicacion.upper().strip() if e.ubicacion and e.ubicacion != 'None' else 'SIN ASIGNAR'
            taller_ext_partial = ["KAUFFMAN", "DEL VALLE", "ROSSELOT", "MORAGA", "TALLER EXT"]
            casa_matriz_claves = ["OFICINA", "TALLER DEMOTRON", "TALLER CENTRAL", "CASA MATRIZ", "35°20'31.7", "35°20'32.5", "35°20'34.1", "35°20'35.3"]
            
            ub_final = ub_original

            if e.estado_base == 'Fuera de Servicio' or ub_original == 'SIN ASIGNAR': ub_final = 'FUERA DE SERVICIO'
            elif any(k in ub_original for k in taller_ext_partial): ub_final = 'TALLER EXTERNO'
            elif ub_original == 'TALLER' or any(k in ub_original for k in casa_matriz_claves): ub_final = 'CASA MATRIZ SAN RAFAEL'

            if ub_final not in ubicaciones_dict: ubicaciones_dict[ub_final] = []
            ubicaciones_dict[ub_final].append(e)

            c_mants = sum(float(o.costo_mantencion_clp or 0) for o in ots_db if o.codigo_equipo == e.codigo)
            c_comp = sum(float(c.costo_pm_clp or 0) for c in compras_db if c.codigo_equipo == e.codigo)
            tot_cost = c_mants + c_comp
            cpk = tot_cost / max(1, e.lectura_actual or 1)
            
            finanzas_flota.append({
                'codigo': e.codigo, 'tipo': e.tipo_equipo, 'lectura': format_num(e.lectura_actual),
                'ctrl': e.control_base, 'costo_mants': format_clp(c_mants), 'costo_compras': format_clp(c_comp),
                'costo_str': format_clp(tot_cost), 'cpk_cph_str': format_clp(cpk)
            })

        equipos_list.sort(key=lambda x: (1 if x['estado'] == 'Fuera de Servicio' else 0, x['codigo']))
        ubicaciones_dict = dict(sorted(ubicaciones_dict.items(), key=lambda item: (1 if item[0] == 'FUERA DE SERVICIO' else 0, item[0])))

        kanban = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Finalizada': []}
        for ot in ots_db:
            k = ot.estado if ot.estado in kanban else 'Pendiente'
            det = getattr(ot, 'observacion', '') or getattr(ot, 'causa_raiz', '')
            txt = f"{ot.tipo_mantencion} | {det}" if det else ot.tipo_mantencion
            kanban[k].append({'id': ot.id, 'codigo': ot.codigo_equipo, 'folio': ot.folio, 'tipo': txt, 'clasificacion': ot.tipo_ot, 'mecanico': ot.mecanico, 'fecha': ot.fecha.strftime('%d/%m %H:%M') if ot.fecha else ''})

        return render_template('index.html', kpis=kpis, cinta2=cinta2, cinta3=cinta3, atrasados_top=atrasados_top, proximos_top=proximos_top, taller_top=taller_list, eqs=equipos_list, finanzas_flota=finanzas_flota, bodega=bodega_db, lecturas=lecturas_db, operadores=personal_db, mecanicos=mecanicos_db, mants_prev=preventivas, mants_corr=correctivas, compras=compras_db, kanban=kanban, eventos_calendario=eventos_calendario, ubicaciones_dict=ubicaciones_dict)
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error Crítico en Dashboard:</b> {str(e)}</div>"

@dashboard_bp.route('/mover_ubicacion_kanban', methods=['POST'])
@login_required
def mover_ubicacion_kanban():
    try:
        data = request.get_json()
        codigo = data.get('codigo')
        nueva_ub = data.get('nueva_ubicacion').upper().strip()
        
        eq = Equipo.query.filter_by(codigo=codigo).first()
        if eq:
            ant = eq.ubicacion or 'SIN ASIGNAR'
            if ant.upper() != nueva_ub:
                eq.ubicacion = nueva_ub
                db.session.add(HistorialUbicacion(codigo_equipo=codigo, ubicacion_anterior=ant, ubicacion_nueva=nueva_ub))
                db.session.commit()
            return {"status": "success"}
        return {"status": "error"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@dashboard_bp.route('/guardar_ubicaciones_masivo', methods=['POST'])
@login_required
def guardar_ubicaciones_masivo():
    try:
        data = request.get_json()
        cambios = data.get('cambios', [])
        for c in cambios:
            eq = Equipo.query.filter_by(codigo=c['codigo']).first()
            if eq:
                ant = eq.ubicacion or 'SIN ASIGNAR'
                nue = c['ubicacion'].upper().strip()
                if ant.upper() != nue:
                    eq.ubicacion = nue
                    db.session.add(HistorialUbicacion(codigo_equipo=eq.codigo, ubicacion_anterior=ant, ubicacion_nueva=nue))
        db.session.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@dashboard_bp.route('/api/cambiar_estado_ot/<int:ot_id>', methods=['POST'])
@login_required
def cambiar_estado_ot(ot_id):
    try:
        data = request.get_json()
        nuevo_estado = data.get('estado')
        
        ot = OrdenTrabajo.query.get_or_404(ot_id)
        if ot.estado != nuevo_estado:
            ot.estado = nuevo_estado
            if nuevo_estado == 'Finalizada' and not ot.fecha_cierre:
                ot.fecha_cierre = obtener_hora_chile()
            db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@dashboard_bp.route('/equipo/<codigo>', strict_slashes=False)
@login_required
def detalle_equipo(codigo):
    try:
        equipo = Equipo.query.filter_by(codigo=codigo).first()
        if not equipo: return "Equipo no encontrado en la base de datos.", 404
        todos_equipos = base_query(Equipo).order_by(Equipo.codigo).all()
        e_cod = str(equipo.codigo).strip().upper()
        e_mod = str(equipo.modelo).strip().upper() if equipo.modelo else ""
        
        todos_filtros = FiltroEquipo.query.all()
        filtros = []
        for f in todos_filtros:
            f_eq = str(f.codigo_equipo).strip().upper()
            match = False
            if e_cod and (e_cod == f_eq or e_cod in f_eq or f_eq in e_cod): match = True
            if not match and e_mod and e_mod not in ['NONE', 'NAN', '']:
                if e_mod == f_eq or e_mod in f_eq or f_eq in e_mod: match = True
            if match: filtros.append(f)
        
        mants_prev = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Preventiva').order_by(OrdenTrabajo.fecha.desc()).all()
        mants_corr = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Correctiva').order_by(OrdenTrabajo.fecha.desc()).all()
        lecturas = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).all()
        compras = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.fecha.desc()).all()
        documentos = DocumentoEquipo.query.filter_by(codigo_equipo=codigo).order_by(DocumentoEquipo.fecha_vencimiento.asc()).all()
        historial_ub = HistorialUbicacion.query.filter_by(codigo_equipo=codigo).order_by(HistorialUbicacion.fecha.desc()).all()
        operador = Personal.query.filter_by(equipo_asignado=codigo).first()
        foto_url = buscar_foto_por_tipo(equipo.tipo_equipo, equipo.marca)
        
        return render_template('equipo.html', 
                               equipo=equipo, todos_equipos=todos_equipos, filtros=filtros, 
                               mants_prev=mants_prev, mants_corr=mants_corr, lecturas=lecturas, 
                               compras=compras, documentos=documentos, historial_ub=historial_ub, 
                               operador=operador, foto_url=foto_url, hoy=obtener_hora_chile())
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error al cargar Ficha:</b> {str(e)}</div>"

@dashboard_bp.route('/equipo/<codigo>/subir_documento', methods=['POST'])
@login_required
def subir_documento(codigo):
    try:
        tipo_documento = request.form.get('tipo_documento')
        fecha_vencimiento_str = request.form.get('fecha_vencimiento')
        archivo = request.files.get('archivo')
        if not tipo_documento or not archivo: return "Faltan datos o archivo", 400
        
        upload_folder = os.path.join('static', 'uploads', 'documentos')
        os.makedirs(upload_folder, exist_ok=True)
        ext = archivo.filename.rsplit('.', 1)[1].lower() if '.' in archivo.filename else 'pdf'
        filename = secure_filename(f"{codigo}_{tipo_documento.replace(' ', '_')}_{obtener_hora_chile().strftime('%Y%m%d%H%M%S')}.{ext}")
        filepath = os.path.join(upload_folder, filename)
        archivo.save(filepath)
        
        fecha_vencimiento = datetime.strptime(fecha_vencimiento_str, '%Y-%m-%d').date() if fecha_vencimiento_str else None
        db.session.add(DocumentoEquipo(codigo_equipo=codigo, tipo_documento=tipo_documento, fecha_vencimiento=fecha_vencimiento, archivo_url=f"/static/uploads/documentos/{filename}"))
        db.session.commit()
        return redirect(url_for('dashboard.detalle_equipo', codigo=codigo))
    except Exception as e:
        return f"Error al subir documento: {str(e)}", 500

@dashboard_bp.route('/bodega_kpi', strict_slashes=False)
@login_required
def bodega_kpi():
    try:
        hoy = obtener_hora_chile()
        eqs_db = base_query(Equipo).all()
        repuestos = Repuesto.query.all()
        recetas_db = RecetaModelo.query.all()
        movimientos = MovimientoBodega.query.order_by(MovimientoBodega.fecha.desc()).limit(150).all()
        
        rep_dict = {r.id: r for r in repuestos}
        valor_total = sum((r.stock_actual or 0) * (r.precio_promedio or 0) for r in repuestos)
        bajo_minimo = [r for r in repuestos if 0 < (r.stock_actual or 0) <= (r.stock_minimo or 2)]
        quiebre_stock = [r for r in repuestos if (r.stock_actual or 0) <= 0]
        
        cat_stats = {}
        for r in repuestos:
            cat = r.categoria or 'Otros'
            if cat not in cat_stats: cat_stats[cat] = 0
            cat_stats[cat] += (r.stock_actual or 0) * (r.precio_promedio or 0)
            
        grafico_categorias = {'labels': list(cat_stats.keys()), 'data': list(cat_stats.values())}

        repuestos_dict_sku = {r.codigo_oem: r for r in repuestos}
        recetas_por_modelo = {}
        for rec in recetas_db:
            m = str(rec.modelo_equipo).strip()
            if m not in recetas_por_modelo: recetas_por_modelo[m] = []
            recetas_por_modelo[m].append(rec)
            
        kits_por_equipo = {}
        repuesto_compatibilidad = {} 
        eqs_sorted = sorted(eqs_db, key=lambda x: str(x.codigo))
        
        for e in eqs_sorted:
            modelo_eq = str(e.modelo).strip()
            if modelo_eq in recetas_por_modelo:
                cod_eq = str(e.codigo).strip().upper()
                marca_modelo = f"{e.marca} {e.modelo}".strip()
                kits_por_equipo[cod_eq] = {'componentes': [], 'armable': True, 'marca_modelo': marca_modelo, 'modelo': modelo_eq}
                
                for rec in recetas_por_modelo[modelo_eq]:
                    sku = str(rec.sku_repuesto).strip().upper()
                    if sku not in repuesto_compatibilidad: repuesto_compatibilidad[sku] = set()
                    repuesto_compatibilidad[sku].add(cod_eq)
                    rep_obj = repuestos_dict_sku.get(sku)
                    stock_actual = rep_obj.stock_actual if rep_obj else 0
                    nombre_rep = rep_obj.nombre if rep_obj else 'Repuesto No Registrado'
                    ok = stock_actual >= rec.cantidad
                    if not ok: kits_por_equipo[cod_eq]['armable'] = False
                    kits_por_equipo[cod_eq]['componentes'].append({'sku': sku, 'nombre': nombre_rep, 'cant_req': rec.cantidad, 'stock': stock_actual, 'ok': ok})
                    
        for sku in repuesto_compatibilidad:
            repuesto_compatibilidad[sku] = ", ".join(sorted(list(repuesto_compatibilidad[sku])))

        filtros_db = FiltroEquipo.query.all()
        maestro_filtros = {}
        for f in filtros_db:
            eq = f.codigo_equipo
            if eq not in maestro_filtros: maestro_filtros[eq] = []
            marcas = [str(x).strip().upper() for x in [f.originales, f.fleetguard, f.donaldson, f.baldwind, f.otra_alternativa] if x and str(x).strip() not in ['-', 'NAN', 'NONE', '']]
            try: c = int(float(f.cant))
            except: c = 1
            maestro_filtros[eq].append({'sistema': f.sistema, 'cant': c, 'marcas': marcas})

        return render_template('bodega_kpi.html', 
                               repuestos=repuestos, rep_dict=rep_dict, kits_por_equipo=kits_por_equipo,
                               repuesto_compatibilidad=repuesto_compatibilidad, maestro_filtros=maestro_filtros,
                               movimientos=movimientos, valor_total_str=format_clp(valor_total),
                               bajo_minimo_count=len(bajo_minimo), quiebre_stock_count=len(quiebre_stock),
                               grafico_categorias=grafico_categorias, eqs_db=eqs_db, hoy=hoy)
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error Bodega WMS:</b> {str(e)}</div>"

@dashboard_bp.route('/imprimir_ot/<int:id>', strict_slashes=False)
@login_required
def imprimir_ot(id):
    try:
        ot = OrdenTrabajo.query.get_or_404(id)
        equipo = Equipo.query.filter_by(codigo=ot.codigo_equipo).first()
        filtros = FiltroEquipo.query.filter_by(codigo_equipo=equipo.codigo).all() if equipo else []
        return render_template('imprimir_ot.html', ot=ot, equipo=equipo, filtros=filtros, hoy=obtener_hora_chile())
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error al cargar OT:</b> {str(e)}</div>"

# ==========================================
# MÓDULOS TMS LOGÍSTICOS
# ==========================================
@dashboard_bp.route('/logistica/flota', strict_slashes=False)
@login_required
def logistica_flota():
    try:
        empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
        equipos_motrices = base_query(Equipo).filter((Equipo.tipo_equipo.ilike('%camion%')) | (Equipo.tipo_equipo.ilike('%tracto%')) | (Equipo.tipo_equipo.ilike('%remolcador%'))).order_by(Equipo.codigo).all()
        conductores = base_query(Conductor).order_by(Conductor.nombre_completo).all()
        ramplas = base_query(Rampla).order_by(Rampla.codigo_interno).all()
        
        kpis = {'total_tractos': len(equipos_motrices), 'tractos_operativos': len([e for e in equipos_motrices if e.estado_base == 'Operativo']), 'total_conductores': len(conductores), 'conductores_disponibles': len([c for c in conductores if c.estado == 'DISPONIBLE']), 'total_ramplas': len(ramplas), 'ramplas_disponibles': len([r for r in ramplas if r.estado == 'DISPONIBLE'])}
        return render_template('logistica_flota.html', equipos=equipos_motrices, conductores=conductores, ramplas=ramplas, kpis=kpis, empresa_actual=empresa_actual, hoy=obtener_hora_chile().date())
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error TMS Flota:</b> {str(e)}</div>"

@dashboard_bp.route('/api/tms/add_conductor', methods=['POST'])
@login_required
def add_conductor():
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    fecha_venc = request.form.get('vencimiento')
    nuevo = Conductor(rut=request.form.get('rut').strip(), nombre_completo=request.form.get('nombre').upper().strip(), clase_licencia=request.form.get('licencia').upper().strip(), vencimiento_licencia=datetime.strptime(fecha_venc, '%Y-%m-%d').date() if fecha_venc else None, estado='DISPONIBLE', empresa=empresa_actual)
    db.session.add(nuevo); db.session.commit()
    return redirect('/logistica/flota')

@dashboard_bp.route('/api/tms/add_rampla', methods=['POST'])
@login_required
def add_rampla():
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    nueva = Rampla(codigo_interno=request.form.get('codigo').upper().strip(), patente=request.form.get('patente').upper().strip(), tipo_rampla=request.form.get('tipo').upper().strip(), capacidad_kg=float(request.form.get('capacidad') or 0.0), estado='DISPONIBLE', empresa=empresa_actual)
    db.session.add(nueva); db.session.commit()
    return redirect('/logistica/flota')

@dashboard_bp.route('/logistica/operaciones', strict_slashes=False)
@login_required
def logistica_operaciones():
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    solicitudes = base_query(SolicitudTransporte).order_by(SolicitudTransporte.fecha_solicitud.desc()).all()
    viajes = base_query(Viaje).order_by(Viaje.id.desc()).all()
    kpis = {'solicitudes_pendientes': len([s for s in solicitudes if s.estado == 'SOLICITADA']), 'viajes_activos': len([v for v in viajes if v.estado in ['PROGRAMADO', 'ASIGNADA', 'EN CARGA', 'EN RUTA', 'EN PUERTO']]), 'viajes_completados': len([v for v in viajes if v.estado == 'ENTREGADO'])}
    return render_template('logistica_operaciones.html', solicitudes=solicitudes, sol_pendientes=[s for s in solicitudes if s.estado == 'SOLICITADA'], viajes=viajes, viajes_activos=[v for v in viajes if v.estado in ['PROGRAMADO', 'ASIGNADA', 'EN CARGA', 'EN RUTA', 'EN PUERTO']], kpis=kpis, empresa_actual=empresa_actual)

@dashboard_bp.route('/api/tms/add_solicitud', methods=['POST'])
@login_required
def add_solicitud():
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    fecha_req = request.form.get('fecha_requerida')
    nueva = SolicitudTransporte(cliente=request.form.get('cliente').upper().strip(), origen=request.form.get('origen').upper().strip(), destino=request.form.get('destino').upper().strip(), tipo_carga=request.form.get('tipo_carga').upper().strip(), peso_kg=float(request.form.get('peso') or 0.0), fecha_requerida=datetime.strptime(fecha_req, '%Y-%m-%d').date() if fecha_req else None, estado='SOLICITADA', empresa=empresa_actual)
    db.session.add(nueva); db.session.commit()
    return redirect('/logistica/operaciones')

@dashboard_bp.route('/api/tms/aprobar_solicitud/<int:id>', methods=['POST'])
@login_required
def aprobar_solicitud(id):
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    solicitud = SolicitudTransporte.query.get_or_404(id)
    if solicitud.estado == 'SOLICITADA':
        solicitud.estado = 'APROBADA'
        db.session.add(Viaje(folio_viaje=f"OT-{obtener_hora_chile().strftime('%Y%m%d')}-{solicitud.id}", solicitud_id=solicitud.id, fecha_programada=solicitud.fecha_requerida, estado='PROGRAMADO', empresa=empresa_actual))
        db.session.commit()
    return redirect('/logistica/operaciones')

@dashboard_bp.route('/logistica/planificador', strict_slashes=False)
@login_required
def logistica_planificador():
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    return render_template('logistica_planificador.html', viajes_pendientes=base_query(Viaje).filter_by(estado='PROGRAMADO').all(), viajes_asignados=base_query(Viaje).filter_by(estado='ASIGNADA').all(), solicitudes=base_query(SolicitudTransporte).all(), camiones_disp=base_query(Equipo).filter((Equipo.tipo_equipo.ilike('%camion%')) | (Equipo.tipo_equipo.ilike('%tracto%'))).filter_by(estado_base='Operativo').all(), conductores_disp=base_query(Conductor).filter_by(estado='DISPONIBLE').all(), ramplas_disp=base_query(Rampla).filter_by(estado='DISPONIBLE').all(), empresa_actual=empresa_actual)

@dashboard_bp.route('/api/tms/asignar_viaje/<int:id>', methods=['POST'])
@login_required
def asignar_viaje(id):
    viaje = Viaje.query.get_or_404(id)
    viaje.conductor_id = request.form.get('conductor_id')
    viaje.rampla_id = request.form.get('rampla_id')
    viaje.codigo_equipo = request.form.get('codigo_equipo')
    viaje.estado = 'ASIGNADA'
    if viaje.conductor_id: Conductor.query.get(viaje.conductor_id).estado = 'EN VIAJE'
    if viaje.rampla_id: Rampla.query.get(viaje.rampla_id).estado = 'EN VIAJE'
    db.session.commit()
    return redirect('/logistica/planificador')

@dashboard_bp.route('/logistica/viaje/<int:id>', strict_slashes=False)
@login_required
def logistica_detalle_viaje(id):
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    viaje = Viaje.query.get_or_404(id)
    upload_folder = os.path.join('static', 'uploads', 'viajes', str(viaje.id))
    return render_template('logistica_detalle_viaje.html', viaje=viaje, solicitud=SolicitudTransporte.query.get(viaje.solicitud_id) if viaje.solicitud_id else None, equipo=Equipo.query.filter_by(codigo=viaje.codigo_equipo).first() if viaje.codigo_equipo else None, conductor=Conductor.query.get(viaje.conductor_id) if viaje.conductor_id else None, rampla=Rampla.query.get(viaje.rampla_id) if viaje.rampla_id else None, documentos=os.listdir(upload_folder) if os.path.exists(upload_folder) else [], empresa_actual=empresa_actual)

@dashboard_bp.route('/api/tms/cambiar_estado_viaje/<int:id>', methods=['POST'])
@login_required
def cambiar_estado_viaje(id):
    nuevo_estado = request.form.get('estado')
    viaje = Viaje.query.get_or_404(id)
    viaje.estado = nuevo_estado
    if nuevo_estado == 'ENTREGADO':
        viaje.fecha_llegada_real = obtener_hora_chile()
        if viaje.conductor_id: Conductor.query.get(viaje.conductor_id).estado = 'DISPONIBLE'
        if viaje.rampla_id: Rampla.query.get(viaje.rampla_id).estado = 'DISPONIBLE'
    db.session.commit()
    return redirect(f'/logistica/viaje/{id}')

@dashboard_bp.route('/api/tms/subir_doc_viaje/<int:id>', methods=['POST'])
@login_required
def subir_doc_viaje(id):
    archivo = request.files.get('archivo')
    if archivo and archivo.filename:
        upload_folder = os.path.join('static', 'uploads', 'viajes', str(id))
        os.makedirs(upload_folder, exist_ok=True)
        archivo.save(os.path.join(upload_folder, secure_filename(archivo.filename)))
    return redirect(f'/logistica/viaje/{id}')

@dashboard_bp.route('/logistica/puertos', strict_slashes=False)
@login_required
def logistica_puertos():
    empresa_actual = getattr(current_user, 'empresa_activa', 'DEMOTRON').upper()
    viajes_activos = base_query(Viaje).filter(Viaje.estado.in_(['EN RUTA', 'EN PUERTO'])).all()
    for v in viajes_activos:
        if not OperacionPortuaria.query.filter_by(viaje_id=v.id).first():
            db.session.add(OperacionPortuaria(viaje_id=v.id, estado='ESPERANDO INGRESO'))
    db.session.commit()
    
    datos_puerto = []
    for op in OperacionPortuaria.query.all():
        v = Viaje.query.get(op.viaje_id)
        if v and v.estado in ['EN RUTA', 'EN PUERTO', 'ENTREGADO'] and getattr(v, 'empresa', 'DEMOTRON') == empresa_actual:
            datos_puerto.append({'op': op, 'viaje': v, 'solicitud': SolicitudTransporte.query.get(v.solicitud_id), 'equipo': Equipo.query.filter_by(codigo=v.codigo_equipo).first(), 'conductor': Conductor.query.get(v.conductor_id)})
    
    return render_template('logistica_puertos.html', esperando=[d for d in datos_puerto if d['op'].estado in ['PROGRAMADO', 'ESPERANDO INGRESO']], dentro=[d for d in datos_puerto if d['op'].estado == 'DENTRO DEL PUERTO'], despachados=[d for d in datos_puerto if d['op'].estado == 'DESPACHADO'], empresa_actual=empresa_actual, hoy=obtener_hora_chile())

@dashboard_bp.route('/api/tms/update_puerto/<int:op_id>', methods=['POST'])
@login_required
def update_puerto(op_id):
    op = OperacionPortuaria.query.get_or_404(op_id)
    viaje = Viaje.query.get(op.viaje_id)
    accion = request.form.get('accion')
    if accion == 'guardar_docs':
        op.puerto = request.form.get('puerto').upper().strip()
        op.booking_bl = request.form.get('booking_bl').upper().strip()
        op.contenedor = request.form.get('contenedor').upper().strip()
        op.estado = 'ESPERANDO INGRESO'
    elif accion == 'gate_in':
        op.hora_ingreso_gate = obtener_hora_chile()
        op.estado = 'DENTRO DEL PUERTO'
        if viaje.estado != 'EN PUERTO': viaje.estado = 'EN PUERTO'
    elif accion == 'gate_out':
        op.hora_salida_gate = obtener_hora_chile()
        op.estado = 'DESPACHADO'
        viaje.estado = 'ENTREGADO' 
        if viaje.conductor_id: Conductor.query.get(viaje.conductor_id).estado = 'DISPONIBLE'
        if viaje.rampla_id: Rampla.query.get(viaje.rampla_id).estado = 'DISPONIBLE'
    db.session.commit()
    return redirect('/logistica/puertos')

import os
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from datetime import datetime, timedelta
from collections import Counter
from flask_login import login_required, current_user
from sqlalchemy import func, case, text
from extensions import db

from models.equipo import Equipo, DocumentoEquipo, FiltroEquipo, HistorialUbicacion
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico
from models.bodega import InventarioBodega, Repuesto, MovimientoBodega, RecetaModelo
from utils.formatters import format_num, format_clp, buscar_foto_por_tipo

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/', strict_slashes=False)
@login_required
def dashboard():
    try:
        hoy = datetime.now()
        
        eqs_db = Equipo.query.all()
        ots_db = OrdenTrabajo.query.all()
        compras_db = CompraRepuesto.query.all()
        personal_db = Personal.query.all()
        mecanicos_db = Mecanico.query.all()
        bodega_db = InventarioBodega.query.all()
        lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).limit(100).all()

        correctivas = [o for o in ots_db if o.tipo_ot == 'Correctiva']
        preventivas = [o for o in ots_db if o.tipo_ot == 'Preventiva']

        total_eq = len(eqs_db)
        operativos = [e for e in eqs_db if e.estado_base == 'Operativo']
        en_taller = [e for e in eqs_db if e.estado_base == 'Taller']
        fuera_servicio = [e for e in eqs_db if e.estado_base == 'Fuera de Servicio']
        
        eqs_margen = []
        for e in eqs_db:
            margen = (e.proxima_pm or 0) - (e.lectura_actual or 0)
            divisor = 8 if e.control_base == 'HORAS' else 100
            dias_margen = int(margen / divisor)
            eqs_margen.append({'eq': e, 'dias': dias_margen})
            
        atrasados_count = len([e for e in eqs_margen if e['dias'] < 0 and e['eq'].estado_base != 'Fuera de Servicio'])

        kpis = {
            'op_pct': round((len(operativos) / max(1, total_eq)) * 100, 1),
            'op_count': len(operativos),
            'total_eq': total_eq,
            'cumpl_pm_pct': round(((total_eq - atrasados_count) / max(1, total_eq)) * 100, 1),
            'backlog_count': atrasados_count,
            'taller_fuera_count': len(en_taller) + len(fuera_servicio),
            'disponibilidad_pct': round((len(operativos) / max(1, total_eq)) * 100, 1)
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
                marcas_stats[m] = {'count': 0, 'fallas': 0, 'horas_rep': 0, 'costo_total': 0.0}
            marcas_stats[m]['count'] += 1

        for o in ots_db:
            eq = next((e for e in eqs_db if e.codigo == o.codigo_equipo), None)
            if eq:
                m = eq.marca or 'Sin Marca'
                marcas_stats[m]['costo_total'] += float(o.costo_mantencion_clp or 0)
                if o.tipo_ot == 'Correctiva':
                    marcas_stats[m]['fallas'] += 1
                    if o.estado == 'Finalizada' and o.fecha_cierre and o.fecha:
                        marcas_stats[m]['horas_rep'] += (o.fecha_cierre - o.fecha).total_seconds() / 3600

        for c in compras_db:
            eq = next((e for e in eqs_db if e.codigo == c.codigo_equipo), None)
            if eq:
                m = eq.marca or 'Sin Marca'
                marcas_stats[m]['costo_total'] += float(c.costo_pm_clp or 0)

        cinta3 = {'labels': [], 'mtbf': [], 'mttr': [], 'costo_promedio': []}
        for m, st in marcas_stats.items():
            if st['count'] > 0:
                cinta3['labels'].append(m)
                dias_op = st['count'] * 365
                cinta3['mtbf'].append(round(dias_op / max(1, st['fallas']), 1))
                cinta3['mttr'].append(round(st['horas_rep'] / max(1, st['fallas']), 1))
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
            
            m = (e.proxima_pm or 0) - (e.lectura_actual or 0)
            d_est = int(m / (8 if e.control_base == 'HORAS' else 100))
            
            if m >= 0 and e.estado_base != 'Fuera de Servicio' and d_est <= 45:
                eventos_calendario.append({'title': f"PROY: {e.codigo}", 'start': (hoy + timedelta(days=max(1, d_est))).strftime('%Y-%m-%d'), 'backgroundColor': '#1E3A8A', 'textColor': '#FFFFFF', 'borderColor': 'transparent'})

            equipos_list.append({
                'codigo': e.codigo, 'tipo': e.tipo_equipo, 'marca': e.marca, 'modelo': e.modelo,
                'patente': e.patente, 'ubicacion': e.ubicacion, 'lectura': format_num(e.lectura_actual),
                'margen': m, 'margen_str': format_num(m), 'estado': e.estado_base, 'ctrl': e.control_base,
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

@dashboard_bp.route('/equipo/<codigo>', strict_slashes=False)
@login_required
def detalle_equipo(codigo):
    try:
        equipo = Equipo.query.filter_by(codigo=codigo).first()
        if not equipo: return "Equipo no encontrado en la base de datos.", 404
        
        todos_filtros = FiltroEquipo.query.all()
        filtros = []
        for f in todos_filtros:
            f_eq = str(f.codigo_equipo).strip().upper()
            if f_eq == str(equipo.codigo).strip().upper() or f_eq == str(equipo.modelo).strip().upper():
                filtros.append(f)
        
        mants_prev = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Preventiva').order_by(OrdenTrabajo.fecha.desc()).all()
        mants_corr = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Correctiva').order_by(OrdenTrabajo.fecha.desc()).all()
        lecturas = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).all()
        compras = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.fecha.desc()).all()
        documentos = DocumentoEquipo.query.filter_by(codigo_equipo=codigo).order_by(DocumentoEquipo.fecha_vencimiento.asc()).all()
        historial_ub = HistorialUbicacion.query.filter_by(codigo_equipo=codigo).order_by(HistorialUbicacion.fecha.desc()).all()
        operador = Personal.query.filter_by(equipo_asignado=codigo).first()
        foto_url = buscar_foto_por_tipo(equipo.tipo_equipo, equipo.marca)
        
        return render_template('equipo.html', 
                               equipo=equipo, 
                               filtros=filtros, 
                               mants_prev=mants_prev, 
                               mants_corr=mants_corr, 
                               lecturas=lecturas, 
                               compras=compras, 
                               documentos=documentos, 
                               historial_ub=historial_ub, 
                               operador=operador, 
                               foto_url=foto_url, 
                               hoy=datetime.now())
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error del Servidor al cargar la Ficha del Equipo:</b> {str(e)}</div>"

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
        filename = secure_filename(f"{codigo}_{tipo_documento.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
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
        from models.bodega import Repuesto, MovimientoBodega, RecetaModelo
        from utils.formatters import format_clp
        hoy = datetime.now()
        
        eqs_db = Equipo.query.all()
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
            
        grafico_categorias = {
            'labels': list(cat_stats.keys()),
            'data': list(cat_stats.values())
        }

        repuestos_dict_sku = {r.codigo_oem: r for r in repuestos}
        recetas_por_modelo = {}
        for rec in recetas_db:
            m = str(rec.modelo_equipo).strip()
            if m not in recetas_por_modelo:
                recetas_por_modelo[m] = []
            recetas_por_modelo[m].append(rec)
            
        kits_por_equipo = {}
        repuesto_compatibilidad = {} 
        
        eqs_sorted = sorted(eqs_db, key=lambda x: str(x.codigo))
        
        for e in eqs_sorted:
            modelo_eq = str(e.modelo).strip()
            if modelo_eq in recetas_por_modelo:
                cod_eq = str(e.codigo).strip().upper()
                marca_modelo = f"{e.marca} {e.modelo}".strip()
                
                kits_por_equipo[cod_eq] = {
                    'componentes': [], 
                    'armable': True, 
                    'marca_modelo': marca_modelo, 
                    'modelo': modelo_eq
                }
                
                for rec in recetas_por_modelo[modelo_eq]:
                    sku = str(rec.sku_repuesto).strip().upper()
                    
                    if sku not in repuesto_compatibilidad:
                        repuesto_compatibilidad[sku] = set()
                    repuesto_compatibilidad[sku].add(cod_eq)
                    
                    rep_obj = repuestos_dict_sku.get(sku)
                    stock_actual = rep_obj.stock_actual if rep_obj else 0
                    nombre_rep = rep_obj.nombre if rep_obj else 'Repuesto No Registrado'
                    
                    ok = stock_actual >= rec.cantidad
                    if not ok: kits_por_equipo[cod_eq]['armable'] = False
                    
                    kits_por_equipo[cod_eq]['componentes'].append({
                        'sku': sku,
                        'nombre': nombre_rep,
                        'cant_req': rec.cantidad,
                        'stock': stock_actual,
                        'ok': ok
                    })
                    
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
                               repuestos=repuestos,
                               rep_dict=rep_dict,
                               kits_por_equipo=kits_por_equipo,
                               repuesto_compatibilidad=repuesto_compatibilidad,
                               maestro_filtros=maestro_filtros,
                               movimientos=movimientos,
                               valor_total_str=format_clp(valor_total),
                               bajo_minimo_count=len(bajo_minimo),
                               quiebre_stock_count=len(quiebre_stock),
                               grafico_categorias=grafico_categorias,
                               eqs_db=eqs_db,
                               hoy=hoy)
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error Crítico en Bodega WMS:</b> {str(e)}</div>"

@dashboard_bp.route('/api/wms/descontar_kit', methods=['POST'])
@login_required
def wms_descontar_kit():
    try:
        from models.bodega import Repuesto, RecetaModelo, MovimientoBodega
        data = request.get_json()
        modelo = data.get('modelo')
        equipo = data.get('equipo')
        referencia = data.get('referencia') or 'Uso Interno'
        
        try: usuario = current_user.username
        except: 
            try: usuario = current_user.nombre
            except: usuario = 'Sistema'
            
        recetas = RecetaModelo.query.filter_by(modelo_equipo=modelo).all()
        if not recetas:
            return jsonify({"status": "error", "message": "No se encontraron componentes para este modelo."})
            
        for rec in recetas:
            rep = Repuesto.query.filter_by(codigo_oem=rec.sku_repuesto).first()
            if not rep or (rep.stock_actual or 0) < rec.cantidad:
                return jsonify({"status": "error", "message": f"Quiebre de stock en: {rec.sku_repuesto}. Despacho cancelado."})
                
        for rec in recetas:
            rep = Repuesto.query.filter_by(codigo_oem=rec.sku_repuesto).first()
            rep.stock_actual -= rec.cantidad
            
            mov = MovimientoBodega(
                fecha=datetime.now(),
                tipo_movimiento='SALIDA KIT PM',
                motivo='Mantenimiento Flota',
                repuesto_id=rep.id,
                cantidad=rec.cantidad,
                costo_unitario=rep.precio_promedio,
                documento_ref=referencia,
                codigo_equipo=equipo,
                usuario=usuario,
                observaciones=f"Despacho automatizado (Equipo: {equipo})"
            )
            db.session.add(mov)
            
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)})

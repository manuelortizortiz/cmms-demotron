import os
import json
import random
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'demotron_master_key'

ruta_db = os.getenv('DATABASE_URL', 'sqlite:///demotron_master.db')
if ruta_db.startswith("postgres://"):
    ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = ruta_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def clean_int(val, default=0):
    try:
        if val is None: return default
        s = str(val).strip()
        if s.lower() in ['', 'nan', 'none']: return default
        return int(float(s))
    except: return default

def clean_float(val, default=0.0):
    try:
        if val is None: return default
        if isinstance(val, (int, float)): return float(val)
        s = str(val).strip().replace('$', '').replace(' ', '')
        if s.lower() in ['', 'nan', 'none']: return default
        if s.count('.') == 1 and ',' not in s: return float(s)
        s = s.replace('.', '').replace(',', '.')
        return float(s)
    except: return default

def format_num(val):
    try:
        if val is None: return "0"
        s = str(val).strip()
        if s.lower() in ['', 'nan', 'none']: return "0"
        return f"{int(float(s)):,}".replace(",", ".")
    except: return "0"

def format_clp(val):
    try:
        if val is None: return "$ 0"
        s = str(val).strip()
        if s.lower() in ['', 'nan', 'none']: return "$ 0"
        return f"$ {int(float(s)):,}".replace(",", ".")
    except: return "$ 0"

def buscar_foto_por_tipo(tipo_equipo):
    if not tipo_equipo: return None
    tipo_limpio = str(tipo_equipo).strip().lower()
    
    if "tracto" in tipo_limpio or "tractocamion" in tipo_limpio:
        return "/static/equipos_real/tractocamion.png"
    elif "man" in tipo_limpio and "tolva" in tipo_limpio:
        return "/static/equipos_real/camion_man_tolva.png"
    elif "camioneta" in tipo_limpio:
        return "/static/equipos_real/maxus_t60.png"
    elif "pintura" in tipo_limpio or "slurry" in tipo_limpio or "plano" in tipo_limpio:
        return "/static/equipos_real/camion_liviano.png"

    base_dir = os.path.join(app.root_path, 'static', 'equipos_real')
    if not os.path.exists(base_dir): base_dir = "static/equipos_real"
    remplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", " ": "_", "-": "_"}
    target = "".join(remplazos.get(c, c) for c in tipo_limpio)

    if os.path.exists(base_dir):
        for root, dirs, files in os.walk(base_dir):
            for f in files:
                nombre, ext = os.path.splitext(f)
                nombre_limpio = nombre.lower().strip().replace(" ", "_").replace("-", "_")
                for k, v in remplazos.items(): nombre_limpio = nombre_limpio.replace(k, v)
                if ext.lower() in ['.jpg', '.jpeg', '.png']:
                    if target in nombre_limpio or nombre_limpio in target:
                        abs_path = os.path.join(root, f).replace("\\", "/")
                        if idx := abs_path.find('static/'): return "/" + abs_path[idx:]
    return None

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    tipo_equipo = db.Column(db.String(100))
    marca = db.Column(db.String(50))
    modelo = db.Column(db.String(100))
    ano = db.Column(db.Integer)
    ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    estado_base = db.Column(db.String(50))      
    control_base = db.Column(db.String(50))     
    frecuencia_base = db.Column(db.Integer)    
    promedio_diario = db.Column(db.Float)
    lectura_actual = db.Column(db.Integer, default=0)
    proxima_pm = db.Column(db.Integer, default=0)
    
    # Nuevos campos solicitados para Ficha Técnica
    vin = db.Column(db.String(100), default="")
    n_motor = db.Column(db.String(100), default="")
    patente = db.Column(db.String(50), default="")

    @property
    def margen(self):
        return (self.proxima_pm or 0) - (self.lectura_actual or 0)

    @property
    def semaforo(self):
        if self.estado_base in ['Fuera de Servicio', 'No operativo']: return 'red'
        if self.margen < 0: return 'red'
        if self.margen < 50: return 'yellow'
        return 'green'

class HistorialLectura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    horometro = db.Column(db.Integer, default=0)
    kilometraje = db.Column(db.Integer, default=0)
    obra_ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    observacion = db.Column(db.String(250))

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    tipo_mantencion = db.Column(db.String(100))
    lectura = db.Column(db.Integer, default=0)
    es_pm = db.Column(db.String(20)) 
    folio = db.Column(db.String(50))
    lugar = db.Column(db.String(100))
    proveedor = db.Column(db.String(100))
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(50)) 

class CompraRepuesto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    oc = db.Column(db.String(100))
    codigo_equipo = db.Column(db.String(50))
    descripcion = db.Column(db.String(250))
    proveedor = db.Column(db.String(100))
    costo_pm_clp = db.Column(db.Float, default=0.0)
    regla = db.Column(db.String(100))
    estado_oc = db.Column(db.String(100))

with app.app_context():
    db.create_all()

@app.route('/', strict_slashes=False)
@app.route('/erp', strict_slashes=False)
def dashboard():
    try:
        equipos_db = Equipo.query.all()
        mantenciones_db = OrdenTrabajo.query.order_by(OrdenTrabajo.id.asc()).all()
        compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
        lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).all()

        equipos, taller, criticos, reportes_prox = [], [], [], []
        conteo_estado = {'Operativo': 0, 'Fuera de Servicio': 0, 'Taller': 0}
        conteo_ubicacion = {}
        conteo_tipos = {}
        proximos_count = 0

        # Lógica para Proveedores y Compras
        proveedores_dict = {}
        costos_por_equipo = {}
        compras_mensuales = {"Feb": 0.0, "Mar": 0.0, "Abr": 0.0, "May": 0.0}
        
        for c in compras_db:
            costo = c.costo_pm_clp or 0.0
            eq_code = c.codigo_equipo
            costos_por_equipo[eq_code] = costos_por_equipo.get(eq_code, 0.0) + costo
            
            prov = c.proveedor or "Desconocido"
            if prov not in proveedores_dict: proveedores_dict[prov] = {'cantidad': 0, 'monto': 0.0}
            proveedores_dict[prov]['cantidad'] += 1
            proveedores_dict[prov]['monto'] += costo
            
            if c.fecha and c.fecha.year == 2026:
                if c.fecha.month == 2: compras_mensuales["Feb"] += costo
                elif c.fecha.month == 3: compras_mensuales["Mar"] += costo
                elif c.fecha.month == 4: compras_mensuales["Abr"] += costo
                elif c.fecha.month == 5: compras_mensuales["May"] += costo

        proveedores_list = sorted([{'nombre': k, 'cantidad': v['cantidad'], 'monto_str': format_clp(v['monto']), 'monto_raw': v['monto']} for k, v in proveedores_dict.items()], key=lambda x: x['monto_raw'], reverse=True)

        busqueda_map = {}
        for e in equipos_db:
            foto_url = buscar_foto_por_tipo(e.tipo_equipo)
            eq_data = {
                'codigo': e.codigo, 'tipo_equipo': e.tipo_equipo, 'marca': e.marca, 'modelo': e.modelo,
                'ubicacion': e.ubicacion or 'Sin Ubicación', 'responsable': e.responsable or 'No Asignado',
                'control_base': e.control_base, 'frecuencia_base': e.frecuencia_base, 'lectura_actual_str': format_num(e.lectura_actual),
                'proxima_pm_str': format_num(e.proxima_pm), 'margen': e.margen, 'margen_str': format_num(e.margen),
                'estado_base': e.estado_base, 'semaforo': e.semaforo, 'foto_url': foto_url,
                'vin': e.vin, 'n_motor': e.n_motor, 'patente': e.patente
            }
            equipos.append(eq_data)
            busqueda_map[e.codigo] = { 'info': eq_data, 'mantenciones': [] }
            
            # Tipos para Gráfico
            t_equipo = e.tipo_equipo or "Otros"
            conteo_tipos[t_equipo] = conteo_tipos.get(t_equipo, 0) + 1
            
            status_limpio = 'Fuera de Servicio' if e.estado_base in ['Fuera de Servicio', 'No operativo'] else e.estado_base
            conteo_estado[status_limpio] = conteo_estado.get(status_limpio, 0) + 1
            if e.ubicacion: conteo_ubicacion[e.ubicacion] = conteo_ubicacion.get(e.ubicacion, 0) + 1
            if e.estado_base == 'Taller' and e.estado_base not in ['Fuera de Servicio', 'No operativo']: taller.append(eq_data)
            if e.margen < 0 and e.estado_base not in ['Fuera de Servicio', 'No operativo']: criticos.append(eq_data)
            if e.semaforo == 'yellow': proximos_count += 1
            if e.margen < 200 and e.estado_base not in ['Fuera de Servicio', 'No operativo']: reportes_prox.append(eq_data)

        reporte_costos = sorted([{'codigo': c, 'tipo': next((e['tipo_equipo'] for e in equipos if e['codigo'] == c), ''), 'costo_str': format_clp(v), 'costo_raw': v} for c, v in costos_por_equipo.items() if v > 0], key=lambda x: x['costo_raw'], reverse=True)

        kanban_tareas = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Completado': []}
        for c in criticos:
            kanban_tareas['Pendiente'].append({'id': f"TASK-{c['codigo']}", 'codigo': c['codigo'], 'tipo': c['tipo_equipo'], 'margen': c['margen_str'], 'ubicacion': c['ubicacion'], 'estado': 'Pendiente'})

        todas_mantenciones = []
        contador_ot = 1821
        for m in mantenciones_db:
            folio_mostrar = m.folio if m.folio and str(m.folio).lower() != 'none' else ""
            costo_ot_clp = m.costo_mantencion_clp
            if costo_ot_clp == 0.0 and m.codigo_equipo in costos_por_equipo: costo_ot_clp = costos_por_equipo[m.codigo_equipo]

            folio_gen = f"OT-DMT-0{contador_ot}"
            contador_ot += 1

            mant_data = {
                'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'fecha_iso': m.fecha.strftime('%Y-%m-%d') if m.fecha else '',
                'codigo': m.codigo_equipo, 'ot_generada': m.folio or folio_gen, 'lectura_str': format_num(m.lectura), 'es_pm': m.es_pm, 'folio_original': folio_mostrar,
                'lugar': m.lugar, 'costo_str': format_clp(costo_ot_clp), 'estado': m.estado
            }
            todas_mantenciones.append(mant_data)
            if m.codigo_equipo in busqueda_map: busqueda_map[m.codigo_equipo]['mantenciones'].append(mant_data)
            if m.estado != 'Finalizada':
                estado_k = 'En Progreso' if m.estado == 'Abierta' else m.estado
                if estado_k in kanban_tareas: kanban_tareas[estado_k].append({'id': f"OT-{m.codigo_equipo}", 'codigo': m.codigo_equipo, 'tipo': m.folio, 'margen': mant_data['fecha'], 'ubicacion': m.lugar, 'estado': estado_k})
        todas_mantenciones.reverse()

        costo_compras = db.session.query(db.func.sum(CompraRepuesto.costo_pm_clp)).scalar() or 0.0
        total_equipos = len(equipos_db)

        kpis = {
            'atrasados': len(criticos), 'total': total_equipos, 'proximos': proximos_count,
            'ot_abiertas': OrdenTrabajo.query.filter(OrdenTrabajo.estado.in_(['Abierta', 'En Proceso', 'En Revisión'])).count(),
            'ot_proceso': OrdenTrabajo.query.filter_by(estado='En Proceso').count(),
            'ot_programar': OrdenTrabajo.query.filter_by(estado='Por Programar').count(),
            'ot_finalizadas': OrdenTrabajo.query.filter_by(estado='Finalizada').count(),
            'controlados': total_equipos - conteo_estado.get('Fuera de Servicio', 0),
            'controlado_pct': round(((total_equipos - conteo_estado.get('Fuera de Servicio', 0)) / total_equipos * 100)) if total_equipos > 0 else 0,
            'costo_mes_str': format_clp(costo_compras)
        }
        
        charts = { 'estado': conteo_estado, 'ubicacion': {k: v for k, v in conteo_ubicacion.items() if v >= 5}, 'compras_mensuales': compras_mensuales, 'tipos': dict(sorted(conteo_tipos.items(), key=lambda item: item[1], reverse=True)[:5]) }

        todas_compras = [{'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else 'S/F', 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'proveedor': c.proveedor, 'costo_str': format_clp(c.costo_pm_clp), 'estado': c.estado_oc or 'Aprobada'} for c in compras_db]
        todas_lecturas = [{'fecha': l.fecha.strftime('%d/%m/%Y %H:%M') if l.fecha else 'S/F', 'codigo': l.codigo_equipo, 'valor_str': format_num(l.horometro if l.horometro > 0 else l.kilometraje), 'tipo': 'HORAS' if l.horometro > 0 else 'KM', 'ubicacion': l.obra_ubicacion, 'responsable': l.responsable, 'obs': l.observacion} for l in lecturas_db]
        
        equipos_aleatorios = list(equipos)
        random.shuffle(equipos_aleatorios)

        return render_template('index.html', kpis=kpis, charts=json.dumps(charts), equipos=equipos, 
                               criticos=criticos, taller=taller, mantenciones=todas_mantenciones, proveedores=proveedores_list,
                               compras=todas_compras, lecturas=todas_lecturas, equipos_aleatorios=equipos_aleatorios,
                               busqueda_json=json.dumps(busqueda_map), kanban=kanban_tareas, 
                               reporte_costos=reporte_costos, reportes_prox=reportes_prox, rol="Admin")
    except Exception as e:
        return f"<h1 style='color:red;'>Error crítico:</h1><p>{str(e)}</p>"

@app.route('/imprimir_ot/<codigo>', strict_slashes=False)
def imprimir_ot(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    ot = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).first()
    ot_data = {
        'folio': ot.folio if (ot and ot.folio and ot.folio != 'None') else f"OT-DMT-0{random.randint(2000, 9000)}",
        'tipo_mantencion': ot.tipo_mantencion if ot else "MANTENIMIENTO PREVENTIVO GENERAL"
    }
    fecha_actual = datetime.now().strftime("%d/%m/%Y")
    return render_template('ot_print.html', equipo=equipo, ot=ot_data, fecha_actual=fecha_actual)

@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    archivo_excel = "CMMS DEMOTRON MANU ORTIZ.xlsx"
    if not os.path.exists(archivo_excel): return "Error: No se encuentra el archivo maestro."
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("DROP TABLE IF EXISTS compra_repuesto CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS orden_trabajo CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS historial_lectura CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS equipo CASCADE;"))
            conn.commit()
        db.create_all()

        df_eq = pd.read_excel(archivo_excel, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            
            # Intentamos leer VIN, Motor, Patente si existen en Excel, sino quedan vacíos listos para editar
            vin_val = str(row.get('VIN', '')) if 'VIN' in df_eq.columns else ""
            motor_val = str(row.get('Motor', '')) if 'Motor' in df_eq.columns else ""
            pat_val = str(row.get('Patente', '')) if 'Patente' in df_eq.columns else ""

            eq = Equipo(codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], marca=row.iloc[2], modelo=str(row.iloc[3]).strip() if row.iloc[3] else None, ano=clean_int(row.iloc[4], None), ubicacion=row.iloc[5], responsable=row.iloc[6], estado_base=str(row.iloc[7]).strip() if row.iloc[7] else 'Operativo', control_base=str(row.iloc[8]).strip().upper() if row.iloc[8] else 'HORAS', frecuencia_base=clean_int(row.iloc[9], 250), promedio_diario=clean_float(row.iloc[10], 0.0), vin=vin_val, n_motor=motor_val, patente=pat_val)
            db.session.add(eq)
            db.session.commit()

        df_lec = pd.read_excel(archivo_excel, sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for _, row in df_lec.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            lec = HistorialLectura(fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), horometro=clean_int(row.iloc[2], 0), kilometraje=clean_int(row.iloc[3], 0), obra_ubicacion=row.iloc[4], responsable=row.iloc[5], observacion=row.iloc[6])
            db.session.add(lec)
            db.session.commit()

        df_man = pd.read_excel(archivo_excel, sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        for _, row in df_man.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            
            ot = OrdenTrabajo(fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), tipo_mantencion=row.iloc[2], lectura=clean_int(row.iloc[3], 0), es_pm=row.iloc[4], folio=str(row.iloc[5]), lugar=row.iloc[6], proveedor=row.iloc[7], costo_mantencion_clp=clean_float(row.iloc[8], 0.0), estado=row.iloc[9] if row.iloc[9] else 'Finalizada')
            db.session.add(ot)
            db.session.commit()

        df_com = pd.read_excel(archivo_excel, sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
        for _, row in df_com.iterrows():
            if not row.iloc[2]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            comp = CompraRepuesto(fecha=fecha_dt, oc=str(row.iloc[1]), codigo_equipo=str(row.iloc[2]).strip(), descripcion=row.iloc[3], proveedor=row.iloc[4], costo_pm_clp=clean_float(row.iloc[5], 0.0), regla=row.iloc[6], estado_oc=row.iloc[7])
            db.session.add(comp)
            db.session.commit()

        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            else: eq.lectura_actual = 0
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, es_pm='Sí', estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = eq.lectura_actual + eq.frecuencia_base
        db.session.commit()
        return redirect(url_for('dashboard'))
    except Exception as e:
        db.session.rollback()
        return f"<h1 style='color:red;'>Error técnico al inyectar:</h1><p>{str(e)}</p>"

if __name__ == '__main__':
    puerto = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=puerto, debug=True)

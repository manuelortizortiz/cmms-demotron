import os
from datetime import datetime, date
from decimal import Decimal
from functools import wraps
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'demotron-cmms-ultra-pro-secret')

DATABASE_URL = os.getenv('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True) if DATABASE_URL else None

USERS = {
    'admin': {'password': 'admin123', 'role': 'Administrador'},
    'gerencia': {'password': 'gerencia123', 'role': 'Gerencia'},
    'mantencion': {'password': 'mantencion123', 'role': 'Mantención'},
}

KNOWN_TABLES = ['equipos','lecturas','mantenciones','bodega','compras','pm','PM']

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper

def _json(v):
    if isinstance(v, (datetime, date)): return v.isoformat()
    if isinstance(v, Decimal): return float(v)
    return v

def rows(sql, params=None):
    if not engine: return []
    try:
        with engine.connect() as conn:
            res = conn.execute(text(sql), params or {})
            return [{k: _json(v) for k, v in r._mapping.items()} for r in res]
    except Exception:
        return []

def scalar(sql, default=0, params=None):
    if not engine: return default
    try:
        with engine.connect() as conn:
            v = conn.execute(text(sql), params or {}).scalar()
            return v if v is not None else default
    except Exception:
        return default

def table_exists(name):
    return bool(scalar("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:t)", False, {'t': name.lower()}))

def get_cols(table):
    return [r['column_name'] for r in rows("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=:t", {'t': table.lower()})]

def first_col(cols, candidates):
    for c in candidates:
        if c in cols: return c
    return None

def equipos_base(limit=500):
    cols = get_cols('equipos')
    if not cols: return []
    select = []
    mapping = {
        'id': first_col(cols, ['id']),
        'codigo': first_col(cols, ['codigo','code','equipo','unidad']),
        'tipo_equipo': first_col(cols, ['tipo_equipo','tipo','categoria']),
        'familia': first_col(cols, ['familia','familia_equipo','clase']),
        'marca': first_col(cols, ['marca','brand']),
        'modelo': first_col(cols, ['modelo','model']),
        'descripcion': first_col(cols, ['descripcion','description','nombre']),
        'estado': first_col(cols, ['estado','estado_servicio','estado_operacional','status']),
        'ubicacion': first_col(cols, ['ubicacion','obra','faena','location']),
        'horometro': first_col(cols, ['horometro','lectura','lectura_actual','km','kilometraje','odometro'])
    }
    for alias, col in mapping.items():
        if col:
            select.append(f'"{col}" AS {alias}')
        else:
            select.append(f"NULL AS {alias}")
    sql = f"SELECT {', '.join(select)} FROM equipos ORDER BY codigo NULLS LAST LIMIT :limit"
    data = rows(sql, {'limit': limit})
    for e in data:
        txt = ' '.join(str(e.get(x) or '') for x in ['codigo','tipo_equipo','familia','marca','modelo','descripcion']).lower()
        e['imagen'] = image_for(txt)
        e['estado_calc'] = calc_estado(e)
        e['tipo_visual'] = e.get('familia') or e.get('tipo_equipo') or 'Equipo'
        e['ubicacion'] = e.get('ubicacion') or 'Sin ubicación'
        e['horometro'] = e.get('horometro') or 0
    return data

def calc_estado(e):
    est = str(e.get('estado') or '').lower()
    if 'atras' in est or 'venc' in est: return 'ATRASADA'
    if 'prox' in est: return 'PROXIMA'
    if 'taller' in est or 'fuera' in est: return 'FUERA'
    cod = str(e.get('codigo') or '')
    if cod.startswith('CD-'): return 'CONTROLADO'
    if cod.startswith('MD-'): return 'CONTROLADO'
    return 'CONTROLADO'

def image_for(txt):
    if 'motoniveladora' in txt or 'grader' in txt: return '/static/img/equipos/motoniveladora.svg'
    if 'cargador' in txt or 'loader' in txt: return '/static/img/equipos/cargador.svg'
    if 'tolva' in txt or 'camión' in txt or 'camion' in txt or 'actros' in txt or 'man' in txt: return '/static/img/equipos/tolva.svg'
    if 'camioneta' in txt or 'vehículo' in txt or 'vehiculo' in txt or 'maxus' in txt: return '/static/img/equipos/camioneta.svg'
    return '/static/img/equipos/excavadora.svg'

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('usuario','').strip()
        p = request.form.get('password','')
        if u in USERS and USERS[u]['password'] == p:
            session['user'] = u; session['role'] = USERS[u]['role']
            return redirect(url_for('dashboard'))
        error = 'Usuario o contraseña incorrectos'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard(): return render_template('dashboard.html', page='dashboard')
@app.route('/equipos')
@login_required
def equipos(): return render_template('equipos.html', page='equipos')
@app.route('/lecturas')
@login_required
def lecturas(): return render_template('lecturas.html', page='lecturas')
@app.route('/mantenciones')
@login_required
def mantenciones(): return render_template('tabla.html', page='mantenciones', title='Mantenciones', endpoint='/api/mantenciones')
@app.route('/compras')
@login_required
def compras(): return render_template('tabla.html', page='compras', title='Compras', endpoint='/api/compras')
@app.route('/bodega')
@login_required
def bodega(): return render_template('tabla.html', page='bodega', title='Bodega', endpoint='/api/bodega')

@app.route('/api/health')
def health(): return jsonify({'database': 'ok' if engine else 'missing', 'tables': {t: table_exists(t) for t in KNOWN_TABLES}})

@app.route('/api/equipos')
@login_required
def api_equipos(): return jsonify(equipos_base())

@app.route('/api/dashboard')
@login_required
def api_dashboard():
    equipos = equipos_base(1000)
    total = len(equipos)
    atrasados = sum(1 for e in equipos if e['estado_calc']=='ATRASADA')
    proximos = sum(1 for e in equipos if e['estado_calc']=='PROXIMA')
    fuera = sum(1 for e in equipos if e['estado_calc']=='FUERA')
    controlado = total - atrasados - proximos - fuera
    ubic = {}
    for e in equipos:
        if e['estado_calc'] == 'ATRASADA': ubic[e['ubicacion']] = ubic.get(e['ubicacion'],0)+1
    criticos = [e for e in equipos if e['estado_calc']=='ATRASADA'][:8]
    if not criticos: criticos = equipos[:8]
    compras_count = scalar('SELECT COUNT(*) FROM compras', 0) if table_exists('compras') else 0
    bodega_count = scalar('SELECT COUNT(*) FROM bodega', 0) if table_exists('bodega') else 0
    mant_count = scalar('SELECT COUNT(*) FROM mantenciones', 0) if table_exists('mantenciones') else 0
    lect_count = scalar('SELECT COUNT(*) FROM lecturas', 0) if table_exists('lecturas') else 0
    return jsonify({
        'kpis': {'total': total, 'atrasados': atrasados, 'proximos': proximos, 'controlado': controlado, 'fuera': fuera,
                 'controlado_pct': round((controlado/total*100),1) if total else 0, 'ot_abiertas': mant_count, 'compras': compras_count, 'costo_mensual': 0},
        'estado': {'labels':['Controlado','Próximos','Atrasados','Fuera de servicio'], 'values':[controlado,proximos,atrasados,fuera]},
        'ubicaciones': {'labels': list(ubic.keys())[:8], 'values': list(ubic.values())[:8]},
        'gestion': {'labels':['Lecturas','Mantenciones','Compras','Bodega'], 'ot':[lect_count,mant_count,0,bodega_count], 'compras':[0,0,compras_count,0]},
        'criticos': criticos,
        'quick': equipos[:16],
        'actividad': [
            {'tipo':'Lectura','titulo':f'{lect_count} lecturas registradas','detalle':'Base PostgreSQL Railway'},
            {'tipo':'Mantención','titulo':f'{mant_count} mantenciones cargadas','detalle':'Historial CMMS'},
            {'tipo':'Compra','titulo':f'{compras_count} compras registradas','detalle':'Órdenes y compras'},
            {'tipo':'Bodega','titulo':f'{bodega_count} registros de bodega','detalle':'Stock y repuestos'},
        ]
    })

@app.route('/api/lecturas')
@login_required
def api_lecturas(): return jsonify(rows('SELECT * FROM lecturas ORDER BY 1 DESC LIMIT 300') if table_exists('lecturas') else [])
@app.route('/api/mantenciones')
@login_required
def api_mantenciones(): return jsonify(rows('SELECT * FROM mantenciones ORDER BY 1 DESC LIMIT 300') if table_exists('mantenciones') else [])
@app.route('/api/compras')
@login_required
def api_compras(): return jsonify(rows('SELECT * FROM compras ORDER BY 1 DESC LIMIT 300') if table_exists('compras') else [])
@app.route('/api/bodega')
@login_required
def api_bodega(): return jsonify(rows('SELECT * FROM bodega ORDER BY 1 DESC LIMIT 300') if table_exists('bodega') else [])

@app.route('/api/ot', methods=['POST'])
@login_required
def crear_ot():
    data = request.get_json() or {}
    codigo = data.get('codigo')
    if not table_exists('mantenciones'):
        return jsonify({'ok': False, 'error': 'No existe tabla mantenciones'}), 400
    cols = get_cols('mantenciones')
    try:
        with engine.begin() as conn:
            if 'codigo' in cols:
                conn.execute(text('INSERT INTO mantenciones (codigo, descripcion) VALUES (:c, :d)'), {'c': codigo, 'd': 'OT creada desde dashboard CMMS'})
            else:
                return jsonify({'ok': False, 'error': 'La tabla mantenciones no tiene columna codigo'}), 400
        return jsonify({'ok': True})
    except SQLAlchemyError as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 400

if __name__ == '__main__':
    app.run(debug=True)

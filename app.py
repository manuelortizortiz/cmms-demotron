import os, re, json
from datetime import datetime, date
from functools import wraps
from decimal import Decimal
from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from sqlalchemy import create_engine, text

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'demotron-ultra-pro-secret')

DATABASE_URL = os.getenv('DATABASE_URL') or os.getenv('DATABASE_PUBLIC_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql+psycopg://', 1)
elif DATABASE_URL and DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True) if DATABASE_URL else None

TABLES = {
    'equipos': ['equipos', 'Equipo', 'EQUIPOS'],
    'lecturas': ['lecturas', 'Lecturas', 'LECTURAS'],
    'mantenciones': ['mantenciones', 'Mantenciones', 'MANTENCIONES'],
    'bodega': ['bodega', 'Bodega', 'BODEGA'],
    'compras': ['compras', 'Compras', 'COMPRAS'],
    'pm': ['PM', 'pm', 'Plan_Mantenciones', 'plan_mantenciones']
}

def clean_value(v):
    if isinstance(v, (datetime, date)): return v.isoformat()
    if isinstance(v, Decimal): return float(v)
    return v

def logged_in():
    return session.get('user') is not None

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not logged_in(): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def qident(name):
    return '"' + name.replace('"', '""') + '"'

def resolve_table(key):
    if not engine: return None
    with engine.connect() as conn:
        for n in TABLES.get(key, [key]):
            try:
                r = conn.execute(text("select to_regclass(:n)"), {'n': n}).scalar()
                if r: return n
            except Exception:
                pass
    return TABLES.get(key, [key])[0]

def get_columns(table):
    if not engine or not table: return []
    with engine.connect() as conn:
        rows = conn.execute(text("""
            select column_name from information_schema.columns
            where table_schema='public' and lower(table_name)=lower(:t)
            order by ordinal_position
        """), {'t': table}).fetchall()
    return [r[0] for r in rows]

def first_col(cols, names):
    low = {c.lower(): c for c in cols}
    for n in names:
        if n.lower() in low: return low[n.lower()]
    for c in cols:
        cl = c.lower()
        if any(n.lower() in cl for n in names): return c
    return None

def rows(table_key, limit=500, order_col=None):
    if not engine: return []
    table = resolve_table(table_key)
    cols = get_columns(table)
    if not cols: return []
    order = f" order by {qident(order_col)} desc" if order_col and order_col in cols else ''
    sql = f"select * from {qident(table)}{order} limit :lim"
    with engine.connect() as conn:
        data = conn.execute(text(sql), {'lim': limit}).mappings().all()
    return [{k: clean_value(v) for k, v in dict(r).items()} for r in data]

def equipo_norm(r):
    cols=list(r.keys())
    codigo = r.get(first_col(cols, ['codigo','equipo','cod_equipo','Código','Codigo']))
    tipo = r.get(first_col(cols, ['tipo','descripcion','descripción','modelo','familia','clase']))
    estado = r.get(first_col(cols, ['estado','estado_servicio','status','condicion','condición']))
    ubicacion = r.get(first_col(cols, ['ubicacion','ubicación','faena','obra','centro']))
    horometro = r.get(first_col(cols, ['horometro','horómetro','lectura','ultima_lectura','km','kilometro','odometro']))
    proxima = r.get(first_col(cols, ['proxima','próxima','pm','proxima_pm','prox_pm','umbral']))
    return {
        'codigo': str(codigo or '').strip(), 'tipo': str(tipo or '').strip(),
        'estado': str(estado or '').strip(), 'ubicacion': str(ubicacion or '').strip(),
        'horometro': horometro or 0, 'proxima_pm': proxima or '',
        'raw': r
    }

def is_atrasado(e):
    s=(e.get('estado') or '').lower()
    if any(x in s for x in ['atras','venc','crit']): return True
    try:
        if e.get('proxima_pm') not in ('', None): return float(e.get('horometro') or 0) > float(e.get('proxima_pm') or 0)
    except Exception: pass
    return False

def is_proximo(e):
    s=(e.get('estado') or '').lower()
    return any(x in s for x in ['prox','próx'])

def money(n):
    try: return int(float(n or 0))
    except Exception: return 0

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u=request.form.get('username','').strip(); p=request.form.get('password','').strip()
        users = {
            os.getenv('ADMIN_USER','admin'): os.getenv('ADMIN_PASS','admin123'),
            os.getenv('GERENCIA_USER','gerencia'): os.getenv('GERENCIA_PASS','gerencia123')
        }
        if users.get(u)==p:
            session['user']={'name':u, 'role':'Administrador' if u=='admin' else 'Gerencia'}
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Usuario o contraseña incorrecta')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard(): return render_template('dashboard.html', user=session.get('user'))
@app.route('/equipos')
@login_required
def equipos_page(): return render_template('equipos.html', user=session.get('user'))
@app.route('/lecturas')
@login_required
def lecturas_page(): return render_template('lecturas.html', user=session.get('user'))
@app.route('/ot')
@login_required
def ot_page(): return render_template('simple.html', title='OT', endpoint='mantenciones', user=session.get('user'))
@app.route('/compras')
@login_required
def compras_page(): return render_template('simple.html', title='Compras', endpoint='compras', user=session.get('user'))
@app.route('/bodega')
@login_required
def bodega_page(): return render_template('simple.html', title='Bodega', endpoint='bodega', user=session.get('user'))
@app.route('/reportes')
@login_required
def reportes_page(): return render_template('reportes.html', user=session.get('user'))

@app.route('/api/health')
def health(): return jsonify({'ok': True, 'db': bool(engine)})

@app.route('/api/equipos')
def api_equipos():
    data=[equipo_norm(r) for r in rows('equipos', 1000)]
    data=[d for d in data if d['codigo']]
    return jsonify(data)

@app.route('/api/<name>')
def api_table(name):
    if name not in ['lecturas','mantenciones','bodega','compras','pm']:
        return jsonify({'error':'endpoint no existe'}), 404
    return jsonify(rows(name, 1000))

@app.route('/api/dashboard')
def api_dashboard():
    eq=[equipo_norm(r) for r in rows('equipos', 2000)]
    eq=[e for e in eq if e['codigo']]
    total=len(eq)
    atrasados=[e for e in eq if is_atrasado(e)]
    proximos=[e for e in eq if is_proximo(e)]
    fuera=[e for e in eq if any(x in (e['estado'] or '').lower() for x in ['fuera','taller','no operativo'])]
    control=max(total-len(atrasados)-len(proximos)-len(fuera), 0)
    mant=rows('mantenciones', 2000); comp=rows('compras', 2000)
    # costos compras
    cost_cols=[]
    if comp:
        cost_cols=[c for c in comp[0].keys() if any(x in c.lower() for x in ['costo','total','monto','valor'])]
    costo=sum(money(r.get(cost_cols[0])) for r in comp) if cost_cols else 0
    por_ubic={}
    for e in atrasados:
        u=e['ubicacion'] or 'Sin ubicación'; por_ubic[u]=por_ubic.get(u,0)+1
    recent=[]
    for source,label,icon in [('mantenciones','OT','fa-clipboard-list'),('lecturas','Lectura','fa-gauge-high'),('compras','Compra','fa-cart-shopping'),('bodega','Bodega','fa-box')]:
        for r in rows(source, 5):
            textv=' · '.join(str(v) for v in list(r.values())[:3] if v not in (None,''))
            recent.append({'tipo':label, 'texto': textv[:120], 'icon':icon})
    return jsonify({
        'total': total, 'atrasados': len(atrasados), 'proximos': len(proximos),
        'controlados': control, 'fuera': len(fuera),
        'control_pct': round((control/total*100) if total else 0, 1),
        'ot_abiertas': len(mant), 'compras_proceso': len(comp), 'costo_mensual': costo,
        'estado_flota': {'Controlado': control, 'Próximos': len(proximos), 'Atrasados': len(atrasados), 'Fuera de servicio': len(fuera)},
        'atrasados_ubicacion': por_ubic,
        'gestion': {'labels':['Esta semana','Semana anterior','Este mes','Mes anterior'], 'ot':[min(len(mant),18), max(len(mant)//2,0), len(mant), max(len(mant)-5,0)], 'compras':[min(len(comp),9), max(len(comp)//2,0), len(comp), max(len(comp)-3,0)]},
        'equipos_atrasados': atrasados[:10], 'equipos_rapidos': eq[:18], 'actividad': recent[:8]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)), debug=True)

from __future__ import annotations
import os, re, json
from pathlib import Path
from datetime import datetime
from functools import wraps

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

APP_VERSION = "DEMOTRON ERP CMMS KOMATSU STYLE FINAL 2026"
BASE = Path(__file__).resolve().parent
UPLOAD = BASE / "static" / "uploads"; UPLOAD.mkdir(parents=True, exist_ok=True)
DATA_IMPORT = BASE / "data_import"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "demotron-cmms-erp-final")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL if DATABASE_URL else f"sqlite:///{BASE/'cmms.db'}", pool_pre_ping=True, future=True)

def is_pg(): return bool(DATABASE_URL)
def pk(): return "BIGSERIAL PRIMARY KEY" if is_pg() else "INTEGER PRIMARY KEY AUTOINCREMENT"
def num(): return "DOUBLE PRECISION" if is_pg() else "REAL"

def q(sql, params=None):
    with engine.begin() as c: c.execute(text(sql), params or {})
def rows(sql, params=None):
    with engine.begin() as c: return [dict(r._mapping) for r in c.execute(text(sql), params or {})]
def one(sql, params=None):
    with engine.begin() as c: return c.execute(text(sql), params or {}).mappings().first()

def clean(v, default=""):
    if v is None: return default
    s = str(v).strip()
    return default if s.lower() in ("nan","none","null","nat") else s

def norm(s):
    s = clean(s).lower()
    for a,b in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ñ":"n"}.items(): s=s.replace(a,b)
    return re.sub(r"[^a-z0-9]+", "", s)

def fnum(v, default=0.0):
    try:
        if v is None: return default
        if isinstance(v, str):
            v = v.strip().replace("$","").replace(" ","")
            if not v or v.lower() in ("nan","none","null"): return default
            if "," in v and "." in v: v = v.replace(".","").replace(",",".")
            elif "," in v: v = v.replace(",",".")
        return float(v)
    except Exception: return default

def table_cols(t):
    try:
        if is_pg():
            return {r['column_name'] for r in rows("SELECT column_name FROM information_schema.columns WHERE lower(table_name)=lower(:t)", {"t":t})}
        return {r['name'] for r in rows(f"PRAGMA table_info({t})")}
    except Exception: return set()

def table_exists(t):
    try:
        if is_pg(): return bool(one("SELECT to_regclass(:t) name", {"t":t})['name'])
        return bool(one("SELECT name FROM sqlite_master WHERE type='table' AND name=:t", {"t":t}))
    except Exception: return False

def safe_select(t, limit=200):
    if not table_exists(t): return []
    cols = table_cols(t)
    for c in ["id","fecha","codigo","codigo_equipo","numero","oc"]:
        if c in cols: return rows(f"SELECT * FROM {t} ORDER BY {c} DESC LIMIT {int(limit)}")
    return rows(f"SELECT * FROM {t} LIMIT {int(limit)}")

def pick(row, *names, default=""):
    mp = {norm(c): c for c in row.index}
    for n in names:
        if norm(n) in mp: return row.get(mp[norm(n)])
    for key,col in mp.items():
        if any(norm(n) in key or key in norm(n) for n in names): return row.get(col)
    return default

def estado_calc(freq, lectura, ultima, estado_op):
    op = clean(estado_op, "OPERATIVO").upper()
    if "FUERA" in op: return "FUERA DE SERVICIO", "gray", 0, 0
    if "TALLER" in op: return "EN TALLER", "gray", 0, 0
    freq, lectura, ultima = fnum(freq), fnum(lectura), fnum(ultima)
    proxima = ultima + freq if ultima>0 and freq>0 else 0
    margen = proxima - lectura if proxima and lectura else 0
    if lectura <= 0: return "SIN LECTURA", "orange", proxima, margen
    if ultima <= 0 or freq <= 0: return "SIN HISTORIAL PM", "orange", proxima, margen
    if margen < 0: return "ATRASADA", "red", proxima, margen
    if margen <= max(15, freq*0.10): return "PRÓXIMA", "orange", proxima, margen
    return "CONTROLADO", "green", proxima, margen

def img_for(familia, codigo):
    f = norm(familia)
    if "excav" in f: return "/static/equipos/excavadora.svg"
    if "camioneta" in f or codigo.startswith("VD"): return "/static/equipos/camioneta.svg"
    if "camion" in f or codigo.startswith("CD"): return "/static/equipos/camion.svg"
    if "cargador" in f: return "/static/equipos/cargador.svg"
    return "/static/equipos/equipo.svg"

def init_db():
    q(f"CREATE TABLE IF NOT EXISTS usuarios(id {pk()}, username TEXT UNIQUE, password_hash TEXT, rol TEXT, activo INTEGER DEFAULT 1)")
    q(f"""CREATE TABLE IF NOT EXISTS equipos(
        id {pk()}, codigo TEXT UNIQUE, tipo_equipo TEXT, familia TEXT, marca TEXT, modelo TEXT, descripcion TEXT,
        ano TEXT, patente TEXT, vin TEXT, motor TEXT, chofer TEXT, ubicacion TEXT, responsable TEXT,
        control_base TEXT, frecuencia_base {num()} DEFAULT 0, lectura_actual {num()} DEFAULT 0, ultima_pm {num()} DEFAULT 0,
        proxima_pm {num()} DEFAULT 0, margen {num()} DEFAULT 0, costo_total_pm {num()} DEFAULT 0,
        estado_operacional TEXT DEFAULT 'OPERATIVO', estado_calculado TEXT, semaforo TEXT, imagen_url TEXT, fecha_actualizacion TEXT)
    """)
    q(f"CREATE TABLE IF NOT EXISTS lecturas(id {pk()}, fecha TEXT, codigo TEXT, tipo_lectura TEXT, valor {num()}, ubicacion TEXT, responsable TEXT, observacion TEXT)")
    q(f"CREATE TABLE IF NOT EXISTS compras(id {pk()}, fecha TEXT, codigo_equipo TEXT, oc TEXT, proveedor TEXT, item TEXT, cantidad {num()}, costo_total {num()}, estado TEXT, observacion TEXT)")
    q(f"CREATE TABLE IF NOT EXISTS ot(id {pk()}, numero TEXT UNIQUE, codigo TEXT, tipo TEXT, prioridad TEXT, estado TEXT, fecha_creacion TEXT, fecha_cierre TEXT, lectura {num()}, descripcion TEXT, responsable TEXT, costo_estimado {num()})")
    q(f"CREATE TABLE IF NOT EXISTS bodega(id {pk()}, fecha TEXT, codigo_equipo TEXT, ot_numero TEXT, repuesto TEXT, cantidad {num()}, costo_unitario {num()}, movimiento TEXT, observacion TEXT)")
    q(f"CREATE TABLE IF NOT EXISTS actividad(id {pk()}, fecha TEXT, tipo TEXT, titulo TEXT, detalle TEXT, usuario TEXT)")
    q(f"CREATE TABLE IF NOT EXISTS importaciones(id {pk()}, fecha TEXT, archivo TEXT, hoja TEXT, registros INTEGER, detalle TEXT)")
    if one("SELECT COUNT(*) n FROM usuarios")['n'] == 0:
        for u,p,r in [("admin","admin123","Administrador"),("gerencia","gerencia123","Gerencia"),("mantencion","mantencion123","Mantención"),("bodega","bodega123","Bodega")]:
            q("INSERT INTO usuarios(username,password_hash,rol,activo) VALUES(:u,:p,:r,1)", {"u":u,"p":generate_password_hash(p),"r":r})

def save_equipo(d):
    codigo = clean(d.get('codigo')).upper()
    if not codigo: return 0
    estado,semaforo,prox,margen = estado_calc(d.get('frecuencia_base'), d.get('lectura_actual'), d.get('ultima_pm'), d.get('estado_operacional'))
    params = {"codigo":codigo, "tipo_equipo":clean(d.get('tipo_equipo')), "familia":clean(d.get('familia')), "marca":clean(d.get('marca')), "modelo":clean(d.get('modelo')), "descripcion":clean(d.get('descripcion')), "ano":clean(d.get('ano')), "patente":clean(d.get('patente')), "vin":clean(d.get('vin')), "motor":clean(d.get('motor')), "chofer":clean(d.get('chofer')), "ubicacion":clean(d.get('ubicacion')), "responsable":clean(d.get('responsable')), "control_base":clean(d.get('control_base'),'HORAS'), "frecuencia_base":fnum(d.get('frecuencia_base')), "lectura_actual":fnum(d.get('lectura_actual')), "ultima_pm":fnum(d.get('ultima_pm')), "proxima_pm":prox, "margen":margen, "costo_total_pm":fnum(d.get('costo_total_pm')), "estado_operacional":clean(d.get('estado_operacional'),'OPERATIVO'), "estado_calculado":estado, "semaforo":semaforo, "imagen_url":clean(d.get('imagen_url')) or img_for(d.get('familia'), codigo), "fecha_actualizacion":datetime.now().strftime('%Y-%m-%d %H:%M')}
    if not params['descripcion']:
        params['descripcion'] = " ".join(x for x in [params['familia'], params['marca'], params['modelo']] if x)
    if is_pg():
        q("""INSERT INTO equipos(codigo,tipo_equipo,familia,marca,modelo,descripcion,ano,patente,vin,motor,chofer,ubicacion,responsable,control_base,frecuencia_base,lectura_actual,ultima_pm,proxima_pm,margen,costo_total_pm,estado_operacional,estado_calculado,semaforo,imagen_url,fecha_actualizacion)
        VALUES(:codigo,:tipo_equipo,:familia,:marca,:modelo,:descripcion,:ano,:patente,:vin,:motor,:chofer,:ubicacion,:responsable,:control_base,:frecuencia_base,:lectura_actual,:ultima_pm,:proxima_pm,:margen,:costo_total_pm,:estado_operacional,:estado_calculado,:semaforo,:imagen_url,:fecha_actualizacion)
        ON CONFLICT(codigo) DO UPDATE SET tipo_equipo=EXCLUDED.tipo_equipo,familia=EXCLUDED.familia,marca=EXCLUDED.marca,modelo=EXCLUDED.modelo,descripcion=EXCLUDED.descripcion,ano=EXCLUDED.ano,patente=EXCLUDED.patente,vin=EXCLUDED.vin,motor=EXCLUDED.motor,chofer=EXCLUDED.chofer,ubicacion=EXCLUDED.ubicacion,responsable=EXCLUDED.responsable,control_base=EXCLUDED.control_base,frecuencia_base=EXCLUDED.frecuencia_base,lectura_actual=EXCLUDED.lectura_actual,ultima_pm=EXCLUDED.ultima_pm,proxima_pm=EXCLUDED.proxima_pm,margen=EXCLUDED.margen,costo_total_pm=EXCLUDED.costo_total_pm,estado_operacional=EXCLUDED.estado_operacional,estado_calculado=EXCLUDED.estado_calculado,semaforo=EXCLUDED.semaforo,imagen_url=EXCLUDED.imagen_url,fecha_actualizacion=EXCLUDED.fecha_actualizacion""", params)
    else:
        q("""INSERT INTO equipos(codigo,tipo_equipo,familia,marca,modelo,descripcion,ano,patente,vin,motor,chofer,ubicacion,responsable,control_base,frecuencia_base,lectura_actual,ultima_pm,proxima_pm,margen,costo_total_pm,estado_operacional,estado_calculado,semaforo,imagen_url,fecha_actualizacion)
        VALUES(:codigo,:tipo_equipo,:familia,:marca,:modelo,:descripcion,:ano,:patente,:vin,:motor,:chofer,:ubicacion,:responsable,:control_base,:frecuencia_base,:lectura_actual,:ultima_pm,:proxima_pm,:margen,:costo_total_pm,:estado_operacional,:estado_calculado,:semaforo,:imagen_url,:fecha_actualizacion)
        ON CONFLICT(codigo) DO UPDATE SET tipo_equipo=excluded.tipo_equipo,familia=excluded.familia,marca=excluded.marca,modelo=excluded.modelo,descripcion=excluded.descripcion,ano=excluded.ano,patente=excluded.patente,vin=excluded.vin,motor=excluded.motor,chofer=excluded.chofer,ubicacion=excluded.ubicacion,responsable=excluded.responsable,control_base=excluded.control_base,frecuencia_base=excluded.frecuencia_base,lectura_actual=excluded.lectura_actual,ultima_pm=excluded.ultima_pm,proxima_pm=excluded.proxima_pm,margen=excluded.margen,costo_total_pm=excluded.costo_total_pm,estado_operacional=excluded.estado_operacional,estado_calculado=excluded.estado_calculado,semaforo=excluded.semaforo,imagen_url=excluded.imagen_url,fecha_actualizacion=excluded.fecha_actualizacion""", params)
    return 1

def import_excel_file(path: Path):
    total = 0
    try:
        xl = pd.ExcelFile(path)
        for sheet in xl.sheet_names:
            df0 = pd.read_excel(path, sheet_name=sheet, header=None, nrows=10)
            header = 0
            for i in range(len(df0)):
                tokens = [norm(x) for x in df0.iloc[i].tolist()]
                if any(t in tokens for t in ['codigo','equipo','codigoequipo']) or any('codigo' in t or 'equipo' in t for t in tokens):
                    header = i; break
            df = pd.read_excel(path, sheet_name=sheet, header=header).dropna(how='all')
            if df.empty: continue
            kind_hint = norm(sheet) + ' ' + ' '.join(norm(c) for c in df.columns)
            count = 0
            if any(x in kind_hint for x in ['maestroequipos','equipos','ubicaciones','choferes']):
                for _,r in df.iterrows():
                    codigo = clean(pick(r,'Codigo','Código','Cod Equipo','Equipo','Patente')).upper()
                    if not codigo or codigo in ('CODIGO','CÓDIGO','EQUIPO'): continue
                    count += save_equipo({
                        'codigo': codigo, 'tipo_equipo': pick(r,'Tipo Equipo','Tipo','Categoría'), 'familia': pick(r,'Familia','Descripción Equipo','Descripcion','Equipo'),
                        'marca': pick(r,'Marca'), 'modelo': pick(r,'Modelo'), 'descripcion': pick(r,'Descripcion','Descripción','Equipo'), 'ano': pick(r,'Año','Ano'),
                        'patente': pick(r,'Patente'), 'vin': pick(r,'VIN','Chasis'), 'motor': pick(r,'Motor','Numero Motor','Número Motor'), 'chofer': pick(r,'Chofer','Conductor','Operador'),
                        'ubicacion': pick(r,'Ubicacion','Ubicación','Faena','Lugar'), 'responsable': pick(r,'Responsable','Jefe'), 'control_base': pick(r,'Control Base','Unidad','Tipo Control', default='HORAS'),
                        'frecuencia_base': pick(r,'Frecuencia Base','Frecuencia','Intervalo'), 'lectura_actual': pick(r,'Lectura Actual','Horometro','Horómetro','Kilometraje','Kilometro','Odometro'),
                        'ultima_pm': pick(r,'Ultima PM','Última PM','Ultima Mantencion','Última Mantención'), 'costo_total_pm': pick(r,'Costo Total','Costo Total PM CLP','Monto'),
                        'estado_operacional': pick(r,'Estado Operacional','Estado', default='OPERATIVO')})
            if any(x in kind_hint for x in ['lecturas','horometro','kilometraje']):
                for _,r in df.iterrows():
                    codigo = clean(pick(r,'Codigo','Código','Cod Equipo','Equipo')).upper(); valor=fnum(pick(r,'Valor','Lectura','Horometro','Horómetro','Kilometraje','Kilometro','Odometro'))
                    if codigo and valor:
                        q("INSERT INTO lecturas(fecha,codigo,tipo_lectura,valor,ubicacion,responsable,observacion) VALUES(:f,:c,:t,:v,:u,:r,:o)", {"f":clean(pick(r,'Fecha'),datetime.now().strftime('%Y-%m-%d')), "c":codigo, "t":clean(pick(r,'Tipo','Unidad'),'LECTURA'), "v":valor, "u":clean(pick(r,'Ubicacion','Ubicación')), "r":clean(pick(r,'Responsable','Chofer')), "o":clean(pick(r,'Observacion','Observación'))})
                        eq=one("SELECT * FROM equipos WHERE codigo=:c", {"c":codigo})
                        if eq:
                            d=dict(eq); d['lectura_actual']=valor; ub=clean(pick(r,'Ubicacion','Ubicación'))
                            if ub: d['ubicacion']=ub
                            save_equipo(d)
                        count += 1
            if any(x in kind_hint for x in ['compras','oc','ordencompra','proveedor']):
                for _,r in df.iterrows():
                    codigo=clean(pick(r,'Codigo','Código','Equipo','Codigo Equipo')).upper(); oc=clean(pick(r,'OC','Orden Compra','N OC','Orden'))
                    if codigo or oc:
                        q("INSERT INTO compras(fecha,codigo_equipo,oc,proveedor,item,cantidad,costo_total,estado,observacion) VALUES(:f,:c,:oc,:p,:i,:q,:cost,:e,:o)", {"f":clean(pick(r,'Fecha'),datetime.now().strftime('%Y-%m-%d')), "c":codigo, "oc":oc, "p":clean(pick(r,'Proveedor')), "i":clean(pick(r,'Item','Descripción','Descripcion','Detalle')), "q":fnum(pick(r,'Cantidad')), "cost":fnum(pick(r,'Costo Total','Total','Monto','Valor')), "e":clean(pick(r,'Estado'),'EN PROCESO'), "o":clean(pick(r,'Observacion','Observación'))})
                        count += 1
            if count:
                q("INSERT INTO importaciones(fecha,archivo,hoja,registros,detalle) VALUES(:f,:a,:h,:r,:d)", {"f":datetime.now().strftime('%Y-%m-%d %H:%M'),"a":path.name,"h":sheet,"r":count,"d":"auto"})
                total += count
    except Exception as e:
        print('ERROR IMPORTANDO', path, e)
    return total

def auto_import_if_empty():
    if os.environ.get('AUTO_IMPORT_DATA','1') != '1': return
    try:
        if one("SELECT COUNT(*) n FROM equipos")['n'] > 0: return
        if DATA_IMPORT.exists():
            for p in sorted(DATA_IMPORT.glob('*.xlsx')): import_excel_file(p)
    except Exception as e: print('AUTO_IMPORT_ERROR', e)

def login_required(fn):
    @wraps(fn)
    def wrap(*a, **kw):
        if 'user' not in session: return redirect(url_for('login'))
        return fn(*a, **kw)
    return wrap

def kpi_data(equipos, ots, compras, bodega):
    oper = [e for e in equipos if e.get('semaforo')!='gray']
    atras = sum(1 for e in oper if e.get('semaforo')=='red')
    prox = sum(1 for e in oper if e.get('semaforo')=='orange')
    ctrl = max(0, len(oper)-atras-prox)
    pct = round((ctrl/len(oper))*100,1) if oper else 0
    return {"total":len(equipos),"operativos":len(oper),"controlados":ctrl,"controlado_pct":pct,"atrasados":atras,"proximos":prox,"taller":sum(1 for e in equipos if clean(e.get('estado_calculado')).upper()=='EN TALLER'),"ot_abiertas":sum(1 for o in ots if clean(o.get('estado')).upper() not in ('CERRADA','CERRADO')),"compras_proceso":sum(1 for c in compras if clean(c.get('estado')).upper() in ('PENDIENTE','EN PROCESO','POR RECIBIR')),"costo_mes":int(sum(fnum(c.get('costo_total')) for c in compras))}

def chart_data(equipos, compras, ots):
    by_estado={}; by_atras_ubic={}; by_costo={}; by_mant={}
    for e in equipos:
        st=e.get('estado_calculado') or 'SIN ESTADO'; by_estado[st]=by_estado.get(st,0)+1
        if e.get('semaforo')=='red':
            u=e.get('ubicacion') or 'Sin ubicación'; by_atras_ubic[u]=by_atras_ubic.get(u,0)+1
        by_costo[e.get('codigo')]=fnum(e.get('costo_total_pm'))
    for c in compras:
        cod=clean(c.get('codigo_equipo'),'SIN EQUIPO'); by_mant[cod]=by_mant.get(cod,0)+1
    return {"estado":by_estado,"ubicacion":dict(sorted(by_atras_ubic.items(), key=lambda x:x[1], reverse=True)[:8]),"costo":dict(sorted(by_costo.items(), key=lambda x:x[1], reverse=True)[:8]),"mantenciones":dict(sorted(by_mant.items(), key=lambda x:x[1], reverse=True)[:8]),"gestion":{"Esta semana":[len(ots), len(compras)],"Este mes":[len(ots), len(compras)]}}

@app.route('/login', methods=['GET','POST'])
def login():
    error=None
    if request.method=='POST':
        u=request.form.get('username','').strip(); p=request.form.get('password','')
        user=one("SELECT * FROM usuarios WHERE username=:u AND activo=1", {"u":u})
        if user and check_password_hash(user['password_hash'], p):
            session['user']=user['username']; session['rol']=user['rol']; return redirect(url_for('index'))
        error='Usuario o contraseña incorrectos'
    return render_template('login.html', error=error, version=APP_VERSION)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    equipos=safe_select('equipos', 2000); ots=safe_select('ot', 500); compras=safe_select('compras', 800); lecturas=safe_select('lecturas', 800); bodega=safe_select('bodega', 300); acts=safe_select('actividad', 20)
    if not acts:
        acts=[{'tipo':'sistema','titulo':'ERP CMMS DEMOTRON cargado','detalle':'Sistema preparado para operación','fecha':datetime.now().strftime('%Y-%m-%d %H:%M'), 'usuario':'Sistema'}]
    return render_template('index.html', equipos=equipos, ots=ots, compras=compras, lecturas=lecturas, bodega=bodega, actividad=acts, kpis=kpi_data(equipos,ots,compras,bodega), charts=json.dumps(chart_data(equipos,compras,ots), ensure_ascii=False), criticos=[e for e in equipos if e.get('semaforo')=='red'][:20], taller=[e for e in equipos if clean(e.get('estado_calculado')).upper()=='EN TALLER'][:20], user=session.get('user'), rol=session.get('rol'), version=APP_VERSION)

@app.route('/importar_excel', methods=['POST'])
@login_required
def importar_excel():
    f=request.files.get('excel')
    if not f: flash('No se recibió archivo.'); return redirect(url_for('index'))
    name=secure_filename(f.filename); path=UPLOAD/name; f.save(path)
    total=import_excel_file(path)
    flash(f'Importación completada: {total} registros procesados desde {name}.')
    return redirect(url_for('index'))

@app.route('/crear_ot', methods=['POST'])
@login_required
def crear_ot():
    n=(one("SELECT COUNT(*) n FROM ot")['n'] or 0)+1; numero=f"OT-{n:05d}"
    q("INSERT INTO ot(numero,codigo,tipo,prioridad,estado,fecha_creacion,lectura,descripcion,responsable,costo_estimado) VALUES(:n,:c,:t,:p,'ABIERTA',:f,:l,:d,:r,:cost)", {"n":numero,"c":request.form.get('codigo',''),"t":request.form.get('tipo','Preventiva'),"p":request.form.get('prioridad','Media'),"f":datetime.now().strftime('%Y-%m-%d %H:%M'),"l":fnum(request.form.get('lectura')),"d":request.form.get('descripcion',''),"r":session.get('user',''),"cost":fnum(request.form.get('costo_estimado'))})
    q("INSERT INTO actividad(fecha,tipo,titulo,detalle,usuario) VALUES(:f,'ot',:t,:d,:u)", {"f":datetime.now().strftime('%Y-%m-%d %H:%M'),"t":f'{numero} creada',"d":request.form.get('codigo',''),"u":session.get('user')})
    flash(f'OT creada: {numero}'); return redirect(url_for('index')+'#ot')

@app.route('/lecturas', methods=['POST'])
@login_required
def lecturas_post():
    cod=clean(request.form.get('codigo')).upper(); val=fnum(request.form.get('valor')); ub=clean(request.form.get('ubicacion'))
    q("INSERT INTO lecturas(fecha,codigo,tipo_lectura,valor,ubicacion,responsable,observacion) VALUES(:f,:c,:t,:v,:u,:r,:o)", {"f":datetime.now().strftime('%Y-%m-%d %H:%M'),"c":cod,"t":request.form.get('tipo_lectura','LECTURA'),"v":val,"u":ub,"r":session.get('user'),"o":request.form.get('observacion','')})
    eq=one("SELECT * FROM equipos WHERE codigo=:c", {"c":cod})
    if eq:
        d=dict(eq); d['lectura_actual']=val
        if ub: d['ubicacion']=ub
        save_equipo(d)
    flash('Lectura registrada y KPI recalculado.'); return redirect(url_for('index')+'#lecturas')

@app.route('/health')
def health(): return jsonify({'status':'ok','database':'postgresql' if is_pg() else 'sqlite','version':APP_VERSION})

try:
    init_db(); auto_import_if_empty()
except Exception as e:
    print('BOOT_ERROR', e)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)

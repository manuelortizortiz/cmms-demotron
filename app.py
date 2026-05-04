
import os,re,math,unicodedata,json
from datetime import datetime,date
from functools import wraps
import pandas as pd
from flask import Flask,request,redirect,url_for,session,render_template_string,jsonify
from sqlalchemy import create_engine,text,inspect

app=Flask(__name__)
app.secret_key=os.getenv("SECRET_KEY","demotron-secret")
DATABASE_URL=os.getenv("DATABASE_URL","").strip()
if DATABASE_URL.startswith("postgres://"): DATABASE_URL=DATABASE_URL.replace("postgres://","postgresql+psycopg://",1)
elif DATABASE_URL.startswith("postgresql://"): DATABASE_URL=DATABASE_URL.replace("postgresql://","postgresql+psycopg://",1)
engine=create_engine(DATABASE_URL,pool_pre_ping=True,future=True) if DATABASE_URL else None
USERS={"admin":"admin123","gerencia":"gerencia123","mantencion":"mantencion123"}
ESTADOS=["AL DÍA","PRÓXIMA","ATRASADA","EN PROCESO","POR RECIBIR","EN TALLER","FUERA DE SERVICIO"]

def norm_col(v):
    v="" if v is None else str(v).strip().lower()
    v="".join(c for c in unicodedata.normalize("NFKD",v) if not unicodedata.combining(c))
    return re.sub(r"_+","_",re.sub(r"[^a-z0-9]+","_",v)).strip("_") or "columna"
def norm_ubic(v):
    if v is None: return ""
    raw=str(v).strip()
    if raw.lower() in ["","nan","none","nat"]: return ""
    mapa={"palmucho":"Palmucho","q_61":"Palmucho","q61":"Palmucho","q_459":"Q-459","q459":"Q-459","quirihue":"Quirihue","cobquecura":"Cobquecura","curico":"Curicó","san_carlos":"San Carlos","oficina_central":"Oficina Central","san_nicolas":"San Nicolas","taller":"Taller","villaseca":"Villaseca","pelluhue":"Pelluhue","ninhue":"Ninhue","retiro":"Retiro","colbun":"Colbun","taltal":"Taltal","talca":"Talca","santiago":"Santiago"}
    return mapa.get(norm_col(raw),raw.title())
def safe(v):
    if v is None: return ""
    if isinstance(v,(datetime,date)): return v.strftime("%Y-%m-%d")
    s=str(v)
    return "" if s.lower() in ["nan","none","nat"] else v
def clean_text(v):
    if v is None: return None
    s=str(v).strip()
    return None if s=="" or s.lower() in ["none","nan","nat"] else s
def clean_upper(v):
    s=clean_text(v); return s.upper() if s else None
def clean_date(v): return clean_text(v)
def clean_number(v):
    s=clean_text(v)
    if not s: return None
    try: return float(s.replace("$","").replace(" ","").replace(".","").replace(",","."))
    except Exception: return None
def num(v):
    if v is None: return 0
    if isinstance(v,(int,float)):
        try:
            if isinstance(v,float) and math.isnan(v): return 0
        except Exception: pass
        return float(v)
    s=str(v).strip()
    if s=="" or s.lower() in ["nan","none","nat"]: return 0
    s=s.replace("$","").replace("CLP","").replace("clp","").replace(" ","")
    if "," in s: s=s.replace(".","").replace(",",".")
    elif s.count(".")>1: s=s.replace(".","")
    try: return float(s)
    except Exception: return 0
def clp(v): return "$ "+format(int(round(num(v))),",").replace(",",".")
def q(sql,params=None,fetch=True):
    if engine is None: return []
    with engine.begin() as conn:
        res=conn.execute(text(sql),params or {})
        return [dict(r) for r in res.mappings().all()] if fetch else []
def table_exists(name):
    try: return engine is not None and name in inspect(engine).get_table_names()
    except Exception: return False
def columns(table):
    try: return [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception: return []

def ensure_schema():
    if engine is None: return
    q("""CREATE TABLE IF NOT EXISTS maestro_equipos(codigo TEXT PRIMARY KEY,tipo_equipo TEXT,familia TEXT,marca TEXT,modelo TEXT,ano TEXT,ubicacion TEXT,responsable TEXT,lectura_actual TEXT,unidad TEXT,proxima_pm TEXT,estado TEXT)""",fetch=False)
    q("""CREATE TABLE IF NOT EXISTS lecturas(id SERIAL PRIMARY KEY,fecha DATE,codigo TEXT,horometro NUMERIC,kilometraje NUMERIC,obra_ubicacion TEXT,responsable TEXT,observacion TEXT)""",fetch=False)
    q("""CREATE TABLE IF NOT EXISTS mantenciones(id SERIAL PRIMARY KEY,fecha DATE,codigo TEXT,tipo_mantencion TEXT,lectura NUMERIC,espm TEXT,folio TEXT,lugar TEXT,proveedor TEXT,costo_mantencion_clp TEXT,estado TEXT)""",fetch=False)
    q("""CREATE TABLE IF NOT EXISTS ot(id SERIAL PRIMARY KEY,fecha DATE,ot TEXT,codigo TEXT,tipo TEXT,lectura TEXT,descripcion TEXT,responsable TEXT,estado TEXT,costo TEXT)""",fetch=False)
    q("""CREATE TABLE IF NOT EXISTS compras(id SERIAL PRIMARY KEY,fecha DATE,oc TEXT,codigo TEXT,descripcion TEXT,proveedor TEXT,costo_pm_clp TEXT,regla TEXT,estado_oc TEXT)""",fetch=False)
    q("""CREATE TABLE IF NOT EXISTS bodega(id SERIAL PRIMARY KEY,folio TEXT,fecha DATE,equipo TEXT,envio TEXT,persona_que_retiro TEXT,destino TEXT,comentario TEXT,codigo TEXT)""",fetch=False)
    q("""CREATE TABLE IF NOT EXISTS plan_mantenciones(codigo TEXT,tipo_equipo TEXT,familia TEXT,control TEXT,lectura_actual TEXT,proxima_lectura_objetivo TEXT,promedio_diario TEXT,dias_estimados TEXT,fecha_estimada TEXT,estado_operativo TEXT,costo_total_pm TEXT,prioridad TEXT,accion_sugerida TEXT)""",fetch=False)

def detect_header(fp,sheet):
    raw=pd.read_excel(fp,sheet_name=sheet,header=None)
    for i in range(min(len(raw),30)):
        vals=[str(x).strip().lower() for x in raw.iloc[i].tolist() if pd.notna(x)]
        if "codigo" in vals or "fecha" in vals or "folio" in vals: return i
    return 0
def clean_sheet(fp,sheet):
    df=pd.read_excel(fp,sheet_name=sheet,header=detect_header(fp,sheet))
    df=df.dropna(how="all").dropna(axis=1,how="all")
    df.columns=[norm_col(c) for c in df.columns]
    seen={}; cols=[]
    for c in df.columns:
        if c not in seen: seen[c]=0; cols.append(c)
        else: seen[c]+=1; cols.append(f"{c}_{seen[c]}")
    df.columns=cols
    for c in df.columns:
        if "fecha" in c: df[c]=pd.to_datetime(df[c],errors="coerce").dt.date
        if c in ["ubicacion","obra_ubicacion","destino","lugar"]: df[c]=df[c].apply(norm_ubic)
    return df
def import_excel():
    ensure_schema()
    fp=os.path.join(os.path.dirname(__file__),"data","cmms.xlsx")
    if not os.path.exists(fp): return {"ok":False,"error":"No existe data/cmms.xlsx"}
    sheets={"Maestro_Equipos":"maestro_equipos","Lecturas":"lecturas","Mantenciones":"mantenciones","Compras PM":"compras","Bodega":"bodega","Plan_Mantenciones":"plan_mantenciones"}
    out={}
    for sh,tb in sheets.items():
        try:
            df=clean_sheet(fp,sh); df.to_sql(tb,engine,if_exists="replace",index=False); out[tb]=len(df)
        except Exception as e: out[tb]=f"ERROR: {e}"
    ensure_schema(); return {"ok":True,"imported":out}
def ensure_data():
    ensure_schema()
    try:
        if table_exists("maestro_equipos") and int(q("SELECT COUNT(*) AS n FROM maestro_equipos")[0]["n"] or 0)==0: import_excel()
    except Exception: pass

def estado_from_row(r):
    for k in ["estado","estado_cmms","estado_servicio","estado_operativo","estado_base","situacion","condicion"]:
        val=r.get(k)
        if val is not None and str(val).strip() and str(val).lower() not in ["nan","none","nat"]: return safe(val)
    for k,val in r.items():
        if "estado" in str(k).lower() and "control" not in str(k).lower() and val is not None and str(val).strip(): return safe(val)
    return ""
def get_equipos():
    ensure_data()
    if not table_exists("maestro_equipos"): return []
    try: raw=q("SELECT * FROM maestro_equipos ORDER BY codigo")
    except Exception: raw=q("SELECT * FROM maestro_equipos")
    data=[]
    for r in raw:
        data.append({"codigo":safe(r.get("codigo")),"tipo_equipo":safe(r.get("tipo_equipo") or r.get("tipo_de_equipo")),"familia":safe(r.get("familia")),"marca":safe(r.get("marca")),"modelo":safe(r.get("modelo")),"ano":safe(r.get("ano") or r.get("anio")),"ubicacion":norm_ubic(r.get("ubicacion")),"responsable":safe(r.get("responsable")),"lectura_actual":safe(r.get("lectura_actual")),"unidad":safe(r.get("unidad")),"proxima_pm":safe(r.get("proxima_pm")),"estado":estado_from_row(r)})
    return data
def get_equipo(codigo):
    c=(codigo or "").strip().upper()
    return next((e for e in get_equipos() if str(e.get("codigo")).strip().upper()==c),None)
def historial_data(codigo):
    out=[]; c=(codigo or "").strip().upper()
    sources=[
        ("lecturas","Lectura","SELECT * FROM lecturas WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300"),
        ("mantenciones","Mantención","SELECT * FROM mantenciones WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300"),
        ("ot","OT","SELECT * FROM ot WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300"),
        ("compras","Compra","SELECT * FROM compras WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300"),
        ("bodega","Bodega","SELECT * FROM bodega WHERE UPPER(codigo)=:c OR UPPER(equipo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300")]
    for tb,ori,sql in sources:
        try:
            if table_exists(tb):
                for r in q(sql,{"c":c}):
                    if tb=="lecturas": out.append({"fecha":safe(r.get("fecha")),"origen":ori,"detalle":norm_ubic(r.get("obra_ubicacion")),"lectura":safe(r.get("horometro") or r.get("kilometraje")),"estado":""})
                    elif tb=="mantenciones": out.append({"fecha":safe(r.get("fecha")),"origen":ori,"detalle":safe(r.get("tipo_mantencion") or r.get("espm")),"lectura":safe(r.get("lectura")),"estado":safe(r.get("estado"))})
                    elif tb=="ot": out.append({"fecha":safe(r.get("fecha")),"origen":ori,"detalle":safe(r.get("descripcion") or r.get("tipo")),"lectura":safe(r.get("ot")),"estado":safe(r.get("estado"))})
                    elif tb=="compras": out.append({"fecha":safe(r.get("fecha")),"origen":ori,"detalle":f"{safe(r.get('oc'))} {safe(r.get('descripcion'))}","lectura":clp(r.get("costo_pm_clp")),"estado":safe(r.get("estado_oc"))})
                    else: out.append({"fecha":safe(r.get("fecha")),"origen":ori,"detalle":safe(r.get("comentario") or r.get("envio")),"lectura":safe(r.get("folio")),"estado":safe(r.get("destino"))})
        except Exception: pass
    return sorted(out,key=lambda x:str(x.get("fecha") or ""),reverse=True)

CSS='<link rel="stylesheet" href="/static/css/styles.css">'; JS='<script src="/static/js/cmms.js"></script>'
def login_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get("user"): return redirect(url_for("login"))
        return fn(*a,**k)
    return w
def topbar():
    return """<div class="topbar"><div class="brandmark">D</div><div class="logo">DEMOTRON</div><nav class="nav"><a href="/">Dashboard</a><a href="/equipos">Equipos</a><a href="/ficha">Ficha Equipo</a><a href="/historial">Historial</a><a href="/planificacion">Planificación</a><a href="/proyeccion">Proyección</a><a href="/lecturas">Lecturas</a><a href="/mantenciones">Mantenciones</a><a href="/ot">OT</a><a href="/compras">Compras</a><a href="/bodega">Bodega</a></nav><a class="btn" href="/admin/importar-cmms">Importar CMMS</a><a class="btn ghost" href="/logout">Salir</a></div>"""
def page(title,body,extra=""):
    return render_template_string(f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">{CSS}</head><body>{topbar()}{body}{JS}{extra}</body></html>""")
def badge(estado):
    s=str(estado or "").upper(); cls="badge"
    if "ATRAS" in s or "VENC" in s: cls="badge bad"
    elif "PROX" in s or "RECIBIR" in s or "PROCESO" in s: cls="badge warn"
    elif "FUERA" in s or "TALLER" in s: cls="badge off"
    return f"<span class='{cls}'>{safe(estado)}</span>"
def machine_image(e):
    txt=(str(e.get("tipo_equipo",""))+" "+str(e.get("familia",""))+" "+str(e.get("marca",""))+" "+str(e.get("modelo",""))).lower()
    if "tracto" in txt: return "/static/img/equipos/tractocamion.png"
    if "tolva" in txt or ("camion" in txt and "pluma" not in txt and "aljibe" not in txt and "liviano" not in txt): return "/static/img/equipos/camion_man_tolva.png"
    if "excav" in txt: return "/static/img/equipos/excavadora.png"
    if "cargador" in txt: return "/static/img/equipos/cargador_frontal.png"
    if "planta" in txt or "aridos" in txt or "áridos" in txt: return "/static/img/equipos/planta_aridos.png"
    if "maxus" in txt or "camioneta" in txt: return "/static/img/equipos/maxus_t60.png"
    if "pluma" in txt: return "/static/img/equipos/camion_pluma.png"
    if "aljibe" in txt: return "/static/img/equipos/camion_aljibe.png"
    if "liviano" in txt: return "/static/img/equipos/camion_liviano.png"
    if "gravilladora" in txt: return "/static/img/equipos/gravilladora.png"
    if "barredora" in txt: return "/static/img/equipos/barredora.png"
    if "rodillo" in txt and "neumatic" in txt: return "/static/img/equipos/rodillo_neumaticos.png"
    if "rodillo" in txt: return "/static/img/equipos/rodillo_compactador.png"
    if "motoniveladora" in txt or "moto" in txt: return "/static/img/equipos/motoniveladora.png"
    if "retro" in txt: return "/static/img/equipos/retroexcavadora.png"
    if "furgon" in txt or "furgón" in txt or "peugeot" in txt or "partner" in txt: return "/static/img/equipos/furgon_partner.png"
    return "/static/img/equipos/excavadora.png"
def equipo_datalist():
    return "<datalist id='equiposList'>"+"".join(f"<option value='{e['codigo']}'>{e['codigo']} - {e['tipo_equipo']} - {e['marca']} {e['modelo']}</option>" for e in get_equipos())+"</datalist>"
def estado_select(name="estado",current=""):
    return f"<select name='{name}' id='{name}'>"+"".join(f"<option value='{x}' {'selected' if x==current else ''}>{x}</option>" for x in ESTADOS)+"</select>"
def form_input(name,label,typ="text",value="",datalist=False,readonly=False):
    return f"<label>{label}</label><input name='{name}' id='{name}' type='{typ}' value='{safe(value)}' {'list=\"equiposList\" autocomplete=\"off\"' if datalist else ''} {'readonly' if readonly else ''}>"

@app.route("/login",methods=["GET","POST"])
def login():
    error=""
    if request.method=="POST":
        u=request.form.get("usuario",""); p=request.form.get("password","")
        if USERS.get(u)==p: session["user"]=u; ensure_data(); return redirect(url_for("dashboard"))
        error="Usuario o contraseña incorrectos"
    return render_template_string(f"""<!doctype html><html><head><meta charset="utf-8">{CSS}</head><body class="login-body"><form class="login-card" method="post"><h1>DEMOTRON</h1><p>CMMS ERP Pro</p><label>Usuario</label><input name="usuario" value="admin"><label>Contraseña</label><input type="password" name="password" value="admin123">{'<div class="error">'+error+'</div>' if error else ''}<button>Entrar</button></form></body></html>""")
@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))
@app.route("/admin/importar-cmms")
@login_required
def importar(): return jsonify(import_excel())
@app.route("/api/status")
def api_status():
    try: ensure_schema(); return jsonify({"status":"ok","database":"postgresql"})
    except Exception as e: return jsonify({"status":"error","message":str(e)}),500
@app.route("/api/equipos")
def api_equipos(): return jsonify(get_equipos())
@app.route("/api/equipo/<codigo>")
def api_equipo(codigo): return jsonify(get_equipo(codigo) or {})

@app.route("/")
@login_required
def dashboard():
    equipos=get_equipos(); total=len(equipos)
    atrasados=sum(1 for e in equipos if "ATRAS" in str(e["estado"]).upper() or "VENC" in str(e["estado"]).upper())
    aldia=sum(1 for e in equipos if "AL D" in str(e["estado"]).upper())
    taller=sum(1 for e in equipos if "TALLER" in str(e["estado"]).upper())
    fuera=sum(1 for e in equipos if "FUERA" in str(e["estado"]).upper())
    recibir=sum(1 for e in equipos if "RECIBIR" in str(e["estado"]).upper())
    proceso=sum(1 for e in equipos if "PROCESO" in str(e["estado"]).upper())
    prox=sum(1 for e in equipos if "PROX" in str(e["estado"]).upper())
    mant=q("SELECT COUNT(*) AS n FROM mantenciones")[0]["n"] if table_exists("mantenciones") else 0
    lect=q("SELECT COUNT(*) AS n FROM lecturas")[0]["n"] if table_exists("lecturas") else 0
    compras=sum(num(r.get("costo_pm_clp") or r.get("monto") or r.get("total") or r.get("valor")) for r in (q("SELECT * FROM compras LIMIT 5000") if table_exists("compras") else []))
    ubic={}; tipo={}; est={}
    for e in equipos:
        ubic[e["ubicacion"] or "Sin ubicación"]=ubic.get(e["ubicacion"] or "Sin ubicación",0)+1
        tipo[e["tipo_equipo"] or "Sin tipo"]=tipo.get(e["tipo_equipo"] or "Sin tipo",0)+1
        est[e["estado"] or "Sin estado"]=est.get(e["estado"] or "Sin estado",0)+1
    def bars(d):
        m=max(d.values()) if d else 1
        return "".join(f"<div class='bar-row'><span>{k}</span><div><b style='width:{max(4,min(100,v*100/m))}%'></b></div><em>{v}</em></div>" for k,v in sorted(d.items(),key=lambda x:x[1],reverse=True)[:10])
    crit="".join(f"<tr><td><a href='/equipo/{e['codigo']}'><b>{e['codigo']}</b></a></td><td>{e['tipo_equipo']}</td><td>{e['ubicacion']}</td><td>{e['lectura_actual']} {e['unidad']}</td><td>{badge(e['estado'])}</td></tr>" for e in [x for x in equipos if str(x['estado']).upper() not in ['AL DÍA','AL DIA']][:10]) or "<tr><td colspan='5'>Sin equipos críticos.</td></tr>"
    cards="".join(f"<a class='machine-card' href='/equipo/{e['codigo']}'><h4>{e['codigo']}</h4><div class='machine-img'><img src='{machine_image(e)}'></div><p>{e['marca']} {e['modelo']}</p><p>{e['ubicacion']}</p><p>{badge(e['estado'])}</p></a>" for e in equipos[:32])
    estado_rows="".join(f"<tr><td>{badge(k)}</td><td>{v}</td></tr>" for k,v in sorted(est.items(),key=lambda x:x[1],reverse=True))
    tipo_rows="".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k,v in sorted(tipo.items(),key=lambda x:x[1],reverse=True)[:10])
    body=f"""<main class="page"><section class="hero"><div><h1>Dashboard CMMS DEMOTRON</h1><p>Datos reales desde Maestro_Equipos, compras, lecturas y mantenciones.</p></div><form action="/ficha" method="get" class="search-card"><input name="codigo" list="equiposList" placeholder="Buscar equipo..."><button>Ver ficha</button>{equipo_datalist()}</form></section><section class="grid-kpi"><div class="card kpi blueb"><small>Total equipos</small><b>{total}</b></div><div class="card kpi greenb"><small>Operativos</small><b>{max(total-fuera,0)}</b></div><div class="card kpi offb"><small>Fuera servicio</small><b>{fuera}</b></div><div class="card kpi redb"><small>Atrasados</small><b>{atrasados}</b></div><div class="card kpi yellowb"><small>Próximas</small><b>{prox}</b></div><div class="card kpi purpleb"><small>Costo total PM</small><b>{clp(compras)}</b></div></section><section class="grid-kpi"><div class="card kpi blueb"><small>Por recibir</small><b>{recibir}</b></div><div class="card kpi yellowb"><small>En proceso</small><b>{proceso}</b></div><div class="card kpi greenb"><small>Al día</small><b>{aldia}</b></div><div class="card kpi offb"><small>En taller</small><b>{taller}</b></div><div class="card kpi tealb"><small>Lecturas</small><b>{lect}</b></div><div class="card kpi purpleb"><small>Mantenciones</small><b>{mant}</b></div></section><section class="middle"><div class="card"><h3>Equipos críticos (10)</h3><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura</th><th>Estado</th></tr></thead><tbody>{crit}</tbody></table></div><div class="card"><h3>Gráfico: equipos por ubicación</h3><div class="bar-chart">{bars(ubic)}</div></div></section><section class="middle"><div class="card"><h3>Gráfico: estado de equipos</h3><div class="bar-chart">{bars(est)}</div></div><div class="card"><h3>Resumen por estado</h3><table><thead><tr><th>Estado</th><th>Total</th></tr></thead><tbody>{estado_rows}</tbody></table></div></section><section class="middle"><div class="card"><h3>Equipos por tipo</h3><table><tbody>{tipo_rows}</tbody></table></div><div class="card"><h3>Accesos</h3><p><a class="btn" href="/planificacion">Planificación Gantt</a> <a class="btn" href="/proyeccion">Proyección tabla</a></p></div></section><section class="card"><h3>Vista rápida de equipos</h3><div class="cards-row">{cards}</div></section></main>"""
    return page("Dashboard ERP",body)

@app.route("/equipos",methods=["GET","POST"])
@login_required
def equipos():
    if request.method=="POST":
        data={k:clean_text(request.form.get(k)) for k in ["tipo_equipo","familia","marca","modelo","ano","responsable","lectura_actual","unidad","proxima_pm","estado"]}
        data["codigo"]=clean_upper(request.form.get("codigo")); data["ubicacion"]=norm_ubic(request.form.get("ubicacion"))
        if not data["codigo"]: return page("Error","<main class='data-page'><div class='card'>Código obligatorio</div></main>")
        q("DELETE FROM maestro_equipos WHERE UPPER(codigo)=UPPER(:codigo)",{"codigo":data["codigo"]},fetch=False)
        q("""INSERT INTO maestro_equipos(codigo,tipo_equipo,familia,marca,modelo,ano,ubicacion,responsable,lectura_actual,unidad,proxima_pm,estado) VALUES(:codigo,:tipo_equipo,:familia,:marca,:modelo,:ano,:ubicacion,:responsable,:lectura_actual,:unidad,:proxima_pm,:estado)""",data,fetch=False)
        return redirect(url_for("equipos"))
    eq=get_equipos()
    rows="".join(f"<tr><td><a href='/equipo/{e['codigo']}'><b>{e['codigo']}</b></a></td><td>{e['tipo_equipo']}</td><td>{e['familia']}</td><td>{e['marca']}</td><td>{e['modelo']}</td><td>{e['ano']}</td><td>{e['ubicacion']}</td><td>{e['responsable']}</td><td>{e['lectura_actual']}</td><td>{e['unidad']}</td><td>{e['proxima_pm']}</td><td>{badge(e['estado'])}</td></tr>" for e in eq)
    form=f"""<form class="form-card" method="post">{equipo_datalist()}{form_input("codigo","Código / Equipo",datalist=True)}{form_input("tipo_equipo","Tipo de Equipo")}{form_input("familia","Familia")}{form_input("marca","Marca")}{form_input("modelo","Modelo")}{form_input("ano","Año")}{form_input("ubicacion","Ubicación")}{form_input("responsable","Responsable")}{form_input("lectura_actual","Lectura Actual")}<label>Unidad</label><select name="unidad"><option>HORAS</option><option>KM</option></select>{form_input("proxima_pm","Próxima PM")}<label>Estado</label>{estado_select()}<button>Guardar / Actualizar Equipo</button></form>"""
    extra=f"<script>window.EQUIPOS={json.dumps(eq,ensure_ascii=False)};</script>"
    return page("Equipos",f"<main class='data-page'><div class='data-head'><h2>Equipos ({len(eq)})</h2><a class='btn' href='/admin/importar-cmms'>Importar CMMS</a></div><p class='hint'>Al escribir un código precargado, se completan los datos automáticamente.</p>{form}<div class='table-card'><table><thead><tr><th>Código</th><th>Tipo</th><th>Familia</th><th>Marca</th><th>Modelo</th><th>Año</th><th>Ubicación</th><th>Responsable</th><th>Lectura</th><th>Unidad</th><th>Próx PM</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>",extra)

@app.route("/ficha")
@login_required
def ficha_redirect():
    c=request.args.get("codigo","").strip()
    return redirect(url_for("equipo_ficha",codigo=c)) if c else redirect(url_for("dashboard"))
@app.route("/equipo/<codigo>")
@login_required
def equipo_ficha(codigo):
    e=get_equipo(codigo)
    if not e: return page("Equipo no encontrado",f"<main class='data-page'><div class='card'><h2>Equipo no encontrado</h2><p>{codigo}</p></div></main>")
    rows="".join(f"<tr><td>{h['fecha']}</td><td>{h['origen']}</td><td>{h['detalle']}</td><td>{h['lectura']}</td><td>{h['estado']}</td></tr>" for h in historial_data(codigo)[:100])
    body=f"""<main class="data-page"><div class="equipment-hero"><div class="photo-ref"><img src="{machine_image(e)}"></div><div><h1>{e['codigo']} · {e['tipo_equipo']}</h1><p>{e['marca']} {e['modelo']} · Año {e['ano']}</p>{badge(e['estado'])}</div></div><section class="grid-2"><div class="card"><h3>Ficha técnica</h3><table><tbody><tr><td>Código</td><td>{e['codigo']}</td></tr><tr><td>Tipo</td><td>{e['tipo_equipo']}</td></tr><tr><td>Familia</td><td>{e['familia']}</td></tr><tr><td>Marca / Modelo</td><td>{e['marca']} {e['modelo']}</td></tr><tr><td>Ubicación</td><td>{e['ubicacion']}</td></tr><tr><td>Responsable</td><td>{e['responsable']}</td></tr><tr><td>Lectura actual</td><td>{e['lectura_actual']} {e['unidad']}</td></tr><tr><td>Próxima PM</td><td>{e['proxima_pm']}</td></tr></tbody></table></div><div class="card"><h3>Acciones rápidas</h3><p><a class="btn" href="/lecturas?codigo={e['codigo']}">Agregar lectura</a></p><p><a class="btn" href="/mantenciones?codigo={e['codigo']}">Agregar mantención</a></p><p><a class="btn" href="/ot?codigo={e['codigo']}">Crear OT</a></p><p><a class="btn" href="/historial?codigo={e['codigo']}">Ver historial</a></p></div></section><section class="card"><h3>Historial técnico</h3><table><thead><tr><th>Fecha</th><th>Origen</th><th>Detalle</th><th>Lectura/Costo/Folio</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></section></main>"""
    return page(f"Ficha {codigo}",body)
@app.route("/historial")
@login_required
def historial():
    c=request.args.get("codigo","").strip()
    rows="".join(f"<tr><td>{h['fecha']}</td><td>{h['origen']}</td><td>{h['detalle']}</td><td>{h['lectura']}</td><td>{h['estado']}</td></tr>" for h in (historial_data(c) if c else []))
    return page("Historial",f"<main class='data-page'><h2>Historial de Equipo</h2><form class='search-card'><input name='codigo' list='equiposList' value='{c}' placeholder='Buscar equipo...'><button>Buscar</button>{equipo_datalist()}</form><div class='table-card'><table><thead><tr><th>Fecha</th><th>Origen</th><th>Detalle</th><th>Lectura/Costo/Folio</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/planificacion")
@login_required
def planificacion():
    data=q("SELECT * FROM plan_mantenciones LIMIT 1000") if table_exists("plan_mantenciones") else []
    lanes=""
    for r in data:
        dias=num(r.get("dias_estimados")); width=95 if dias<=0 else 90 if dias<=7 else 70 if dias<=30 else 45 if dias<=60 else 25
        c=safe(r.get("codigo")); est=safe(r.get("estado_operativo") or r.get("estado") or r.get("prioridad"))
        lanes+=f"""<a class="gantt-row" href="/equipo/{c}"><div class="gantt-code">{c}</div><div class="gantt-meta">{safe(r.get('tipo_equipo'))}<br><small>{safe(r.get('familia'))}</small></div><div class="gantt-info"><strong>Lectura:</strong> {safe(r.get('lectura_actual'))}<br><strong>Próxima:</strong> {safe(r.get('proxima_lectura_objetivo'))}<br><strong>Acción:</strong> {safe(r.get('accion_sugerida'))}</div><div class="gantt-track"><span style="width:{width}%"></span></div><div class="gantt-date">{safe(r.get('fecha_estimada'))}<br><small>{safe(r.get('dias_estimados'))} días</small></div><div>{badge(est)}</div></a>"""
    return page("Planificación",f"<main class='data-page'><div class='data-head'><h2>Planificación PM tipo Gantt</h2><a class='btn' href='/proyeccion'>Ver tabla de proyección</a></div><p class='hint'>Carta clickeable por equipo.</p><section class='gantt'>{lanes or '<div class=\"card\">No hay datos de planificación.</div>'}</section></main>")
@app.route("/proyeccion")
@login_required
def proyeccion():
    data=q("SELECT * FROM plan_mantenciones LIMIT 1000") if table_exists("plan_mantenciones") else []
    rows="".join(f"<tr><td><a href='/equipo/{safe(r.get('codigo'))}'><b>{safe(r.get('codigo'))}</b></a></td><td>{safe(r.get('tipo_equipo'))}</td><td>{safe(r.get('familia'))}</td><td>{safe(r.get('control'))}</td><td>{safe(r.get('lectura_actual'))}</td><td>{safe(r.get('proxima_lectura_objetivo'))}</td><td>{safe(r.get('promedio_diario'))}</td><td>{safe(r.get('dias_estimados'))}</td><td>{safe(r.get('fecha_estimada'))}</td><td>{badge(r.get('estado_operativo'))}</td><td>{safe(r.get('prioridad'))}</td><td>{safe(r.get('accion_sugerida'))}</td></tr>" for r in data)
    return page("Proyección",f"<main class='data-page'><div class='data-head'><h2>Proyección de Mantenciones</h2><a class='btn' href='/planificacion'>Ver Gantt</a></div><div class='table-card'><table><thead><tr><th>Código</th><th>Tipo</th><th>Familia</th><th>Control</th><th>Lectura</th><th>Próxima</th><th>Promedio</th><th>Días</th><th>Fecha</th><th>Estado</th><th>Prioridad</th><th>Acción</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

def crud_form(route, fields, button):
    return f"<form class='form-card' method='post' action='/{route}'>"+"".join(fields)+f"<button>{button}</button></form>"
@app.route("/lecturas",methods=["GET","POST"])
@login_required
def lecturas():
    if request.method=="POST":
        d={"fecha":clean_date(request.form.get("fecha")),"codigo":clean_upper(request.form.get("codigo")),"horometro":clean_number(request.form.get("horometro")),"kilometraje":clean_number(request.form.get("kilometraje")),"obra_ubicacion":norm_ubic(request.form.get("obra_ubicacion")),"responsable":clean_text(request.form.get("responsable")),"observacion":clean_text(request.form.get("observacion"))}
        if d["codigo"]: q("INSERT INTO lecturas(fecha,codigo,horometro,kilometraje,obra_ubicacion,responsable,observacion) VALUES(:fecha,:codigo,:horometro,:kilometraje,:obra_ubicacion,:responsable,:observacion)",d,fetch=False)
        val=d["horometro"] if d["horometro"] is not None else d["kilometraje"]; unidad="HORAS" if d["horometro"] is not None else "KM"
        if d["codigo"] and val is not None: q("UPDATE maestro_equipos SET lectura_actual=:v,unidad=:u,ubicacion=COALESCE(:ub,ubicacion) WHERE UPPER(codigo)=UPPER(:c)",{"v":str(val),"u":unidad,"ub":d["obra_ubicacion"],"c":d["codigo"]},fetch=False)
        return redirect(url_for("lecturas"))
    data=q("SELECT * FROM lecturas ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("lecturas") else []
    rows="".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'><b>{safe(r.get('codigo'))}</b></a></td><td>{safe(r.get('horometro'))}</td><td>{safe(r.get('kilometraje'))}</td><td>{norm_ubic(r.get('obra_ubicacion'))}</td><td>{safe(r.get('responsable'))}</td><td>{safe(r.get('observacion'))}</td></tr>" for r in data)
    c=request.args.get("codigo","")
    form=crud_form("lecturas",[f"<input name='codigo' list='equiposList' placeholder='Código' value='{c}'>{equipo_datalist()}","<input type='date' name='fecha'>","<input type='number' step='any' name='horometro' placeholder='Horómetro'>","<input type='number' step='any' name='kilometraje' placeholder='Kilometraje'>","<input name='obra_ubicacion' placeholder='Ubicación'>","<input name='responsable' placeholder='Responsable'>","<input name='observacion' placeholder='Observación'>"],"Guardar lectura")
    return page("Lecturas",f"<main class='data-page'><h2>Lecturas</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Horómetro</th><th>Kilometraje</th><th>Ubicación</th><th>Responsable</th><th>Obs</th></tr></thead><tbody>{rows}</tbody></table></div></main>")
@app.route("/mantenciones",methods=["GET","POST"])
@login_required
def mantenciones():
    if request.method=="POST":
        d={"fecha":clean_date(request.form.get("fecha")),"codigo":clean_upper(request.form.get("codigo")),"tipo_mantencion":clean_text(request.form.get("tipo_mantencion")),"lectura":clean_number(request.form.get("lectura")),"espm":clean_text(request.form.get("espm")),"folio":clean_text(request.form.get("folio")) or f"OT-WEB-{datetime.now().strftime('%Y%m%d%H%M%S')}","lugar":norm_ubic(request.form.get("lugar")),"proveedor":clean_text(request.form.get("proveedor")),"costo_mantencion_clp":clean_text(request.form.get("costo_mantencion_clp")),"estado":clean_text(request.form.get("estado"))}
        if d["codigo"]:
            q("INSERT INTO mantenciones(fecha,codigo,tipo_mantencion,lectura,espm,folio,lugar,proveedor,costo_mantencion_clp,estado) VALUES(:fecha,:codigo,:tipo_mantencion,:lectura,:espm,:folio,:lugar,:proveedor,:costo_mantencion_clp,:estado)",d,fetch=False)
            q("INSERT INTO ot(fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo) VALUES(:fecha,:folio,:codigo,:tipo_mantencion,:lectura,:espm,:proveedor,:estado,:costo_mantencion_clp)",d,fetch=False)
        return redirect(url_for("mantenciones"))
    data=q("SELECT * FROM mantenciones ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("mantenciones") else []
    rows="".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'><b>{safe(r.get('codigo'))}</b></a></td><td>{safe(r.get('tipo_mantencion'))}</td><td>{safe(r.get('lectura'))}</td><td>{safe(r.get('folio'))}</td><td>{safe(r.get('proveedor'))}</td><td>{clp(r.get('costo_mantencion_clp'))}</td><td>{badge(r.get('estado'))}</td></tr>" for r in data)
    c=request.args.get("codigo","")
    form=f"<form class='form-card' method='post'><input name='codigo' list='equiposList' value='{c}' placeholder='Código'>{equipo_datalist()}<input type='date' name='fecha'><input name='tipo_mantencion' placeholder='Tipo mantención'><input type='number' step='any' name='lectura' placeholder='Lectura'><input name='espm' placeholder='Descripción/ESPM'><input name='folio' placeholder='Folio/OT'><input name='lugar' placeholder='Lugar'><input name='proveedor' placeholder='Proveedor'><input name='costo_mantencion_clp' placeholder='Costo'><select name='estado'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><button>Guardar mantención y generar OT</button></form>"
    return page("Mantenciones",f"<main class='data-page'><h2>Mantenciones</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Tipo</th><th>Lectura</th><th>Folio/OT</th><th>Proveedor</th><th>Costo</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>")
@app.route("/ot",methods=["GET","POST"])
@login_required
def ot():
    if request.method=="POST":
        d={k:clean_text(request.form.get(k)) for k in ["ot","tipo","lectura","descripcion","responsable","estado","costo"]}; d["fecha"]=clean_date(request.form.get("fecha")); d["codigo"]=clean_upper(request.form.get("codigo")); d["ot"]=d["ot"] or f"OT-WEB-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        if d["codigo"]: q("INSERT INTO ot(fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo) VALUES(:fecha,:ot,:codigo,:tipo,:lectura,:descripcion,:responsable,:estado,:costo)",d,fetch=False)
        return redirect(url_for("ot"))
    data=q("SELECT * FROM ot ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("ot") else []
    rows="".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('ot'))}</b></td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td><td>{safe(r.get('tipo'))}</td><td>{safe(r.get('descripcion'))}</td><td>{safe(r.get('responsable'))}</td><td>{badge(r.get('estado'))}</td><td>{clp(r.get('costo'))}</td></tr>" for r in data)
    c=request.args.get("codigo","")
    form=f"<form class='form-card' method='post'><input type='date' name='fecha'><input name='ot' placeholder='OT/Folio (opcional)'><input name='codigo' list='equiposList' value='{c}' placeholder='Código'>{equipo_datalist()}<input name='tipo' placeholder='Tipo'><input name='lectura' placeholder='Lectura'><input name='descripcion' placeholder='Descripción'><input name='responsable' placeholder='Responsable'><select name='estado'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><input name='costo' placeholder='Costo'><button>Guardar OT</button></form>"
    return page("OT",f"<main class='data-page'><h2>Órdenes de Trabajo</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>OT</th><th>Código</th><th>Tipo</th><th>Descripción</th><th>Responsable</th><th>Estado</th><th>Costo</th></tr></thead><tbody>{rows}</tbody></table></div></main>")
@app.route("/compras",methods=["GET","POST"])
@login_required
def compras():
    if request.method=="POST":
        d={k:clean_text(request.form.get(k)) for k in ["oc","descripcion","proveedor","costo_pm_clp","regla","estado_oc"]}; d["fecha"]=clean_date(request.form.get("fecha")); d["codigo"]=clean_upper(request.form.get("codigo"))
        if d["codigo"]: q("INSERT INTO compras(fecha,oc,codigo,descripcion,proveedor,costo_pm_clp,regla,estado_oc) VALUES(:fecha,:oc,:codigo,:descripcion,:proveedor,:costo_pm_clp,:regla,:estado_oc)",d,fetch=False)
        return redirect(url_for("compras"))
    data=q("SELECT * FROM compras ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("compras") else []
    rows="".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('oc'))}</b></td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td><td>{safe(r.get('descripcion'))}</td><td>{safe(r.get('proveedor'))}</td><td>{clp(r.get('costo_pm_clp'))}</td><td>{badge(r.get('estado_oc'))}</td></tr>" for r in data)
    form=f"<form class='form-card' method='post'><input type='date' name='fecha'><input name='oc' placeholder='OC'><input name='codigo' list='equiposList' placeholder='Código'>{equipo_datalist()}<input name='descripcion' placeholder='Descripción'><input name='proveedor' placeholder='Proveedor'><input name='costo_pm_clp' placeholder='Monto'><input name='regla' placeholder='Regla'><select name='estado_oc'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><button>Guardar compra</button></form>"
    return page("Compras",f"<main class='data-page'><h2>Compras PM</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>OC</th><th>Código</th><th>Descripción</th><th>Proveedor</th><th>Monto</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>")
@app.route("/bodega",methods=["GET","POST"])
@login_required
def bodega():
    if request.method=="POST":
        d={k:clean_text(request.form.get(k)) for k in ["folio","equipo","envio","persona_que_retiro","comentario"]}; d["fecha"]=clean_date(request.form.get("fecha")); d["destino"]=norm_ubic(request.form.get("destino")); d["codigo"]=clean_upper(request.form.get("codigo"))
        q("INSERT INTO bodega(folio,fecha,equipo,envio,persona_que_retiro,destino,comentario,codigo) VALUES(:folio,:fecha,:equipo,:envio,:persona_que_retiro,:destino,:comentario,:codigo)",d,fetch=False)
        return redirect(url_for("bodega"))
    data=q("SELECT * FROM bodega ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("bodega") else []
    rows="".join(f"<tr><td><b>{safe(r.get('folio'))}</b></td><td>{safe(r.get('fecha'))}</td><td>{safe(r.get('equipo'))}</td><td>{safe(r.get('envio'))}</td><td>{safe(r.get('persona_que_retiro'))}</td><td>{safe(r.get('destino'))}</td><td>{safe(r.get('comentario'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td></tr>" for r in data)
    form=f"<form class='form-card' method='post'><input name='folio' placeholder='Folio'><input type='date' name='fecha'><input name='equipo' placeholder='Equipo'><input name='envio' placeholder='Envío'><input name='persona_que_retiro' placeholder='Persona que retiró'><input name='destino' placeholder='Destino'><input name='comentario' placeholder='Comentario'><input name='codigo' list='equiposList' placeholder='Código'>{equipo_datalist()}<button>Guardar bodega</button></form>"
    return page("Bodega",f"<main class='data-page'><h2>Bodega</h2>{form}<div class='table-card'><table><thead><tr><th>Folio</th><th>Fecha</th><th>Equipo</th><th>Envío</th><th>Retira</th><th>Destino</th><th>Comentario</th><th>Código</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",8080)))

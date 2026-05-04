
import os, re, unicodedata
from datetime import date, datetime
from functools import wraps

import pandas as pd
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from sqlalchemy import create_engine, text, inspect

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "demotron-secret")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True) if DATABASE_URL else None
USERS = {"admin":"admin123","gerencia":"gerencia123","mantencion":"mantencion123"}

def norm_col(v):
    v = "" if v is None else str(v)
    v = v.strip().lower()
    v = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    v = re.sub(r"[^a-z0-9]+","_",v)
    return re.sub(r"_+","_",v).strip("_") or "columna"

def key(v):
    if v is None: return ""
    v = str(v).strip().lower()
    v = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+","_",v).strip("_")

def norm_ubic(v):
    if v is None: return ""
    raw = str(v).strip()
    if raw == "" or raw.lower() in ["nan","none","nat"]: return ""
    m = {
        "palmucho":"Palmucho","q_61":"Palmucho","q61":"Palmucho",
        "q_459":"Q-459","q459":"Q-459","quirihue":"Quirihue",
        "cobquecura":"Cobquecura","curico":"Curicó","san_carlos":"San Carlos",
        "oficina_central":"Oficina Central","san_nicolas":"San Nicolas",
        "taller":"Taller","villaseca":"Villaseca","pelluhue":"Pelluhue",
        "ninhue":"Ninhue","retiro":"Retiro","colbun":"Colbun",
        "taltal":"Taltal","talca":"Talca","santiago":"Santiago"
    }
    return m.get(key(raw), raw.title())

def safe(v):
    if v is None: return ""
    if isinstance(v,(datetime,date)): return v.strftime("%Y-%m-%d")
    s = str(v)
    if s.lower() in ["nan","none","nat"]: return ""
    return v

def num(v):
    try:
        if v is None or str(v).strip()=="": return 0
        return float(str(v).replace("$","").replace(" ","").replace(".","").replace(",","."))
    except Exception:
        try: return float(v)
        except Exception: return 0

def detect_header(file_path, sheet):
    raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
    for i in range(min(len(raw), 30)):
        vals = [str(x).strip().lower() for x in raw.iloc[i].tolist() if pd.notna(x)]
        if "codigo" in vals or "fecha" in vals or "folio" in vals:
            return i
    return 0

def clean_sheet(file_path, sheet):
    hr = detect_header(file_path, sheet)
    df = pd.read_excel(file_path, sheet_name=sheet, header=hr)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [norm_col(c) for c in df.columns]
    seen, cols = {}, []
    for c in df.columns:
        if c not in seen:
            seen[c]=0; cols.append(c)
        else:
            seen[c]+=1; cols.append(f"{c}_{seen[c]}")
    df.columns = cols
    for c in df.columns:
        if "fecha" in c:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        if c in ["ubicacion","obra_ubicacion","destino","lugar"]:
            df[c] = df[c].apply(norm_ubic)
    return df

def import_excel():
    if engine is None:
        return {"ok":False,"error":"DATABASE_URL no configurada"}
    fp = os.path.join(os.path.dirname(__file__), "data", "cmms.xlsx")
    if not os.path.exists(fp):
        return {"ok":False,"error":"No existe data/cmms.xlsx"}

    sheets = {
        "Maestro_Equipos":"maestro_equipos",
        "Equipos":"equipos",
        "Lecturas":"lecturas",
        "Mantenciones":"mantenciones",
        "Compras PM":"compras",
        "Bodega":"bodega",
        "Plan_Mantenciones":"plan_mantenciones",
        "Plan_90_Dias":"plan_90_dias",
        "Planner_Semanal":"planner_semanal",
        "Dashboard":"dashboard_excel"
    }
    out={}
    for sh,tb in sheets.items():
        try:
            df = clean_sheet(fp, sh)
            df.to_sql(tb, engine, if_exists="replace", index=False)
            out[tb]=len(df)
        except Exception as e:
            out[tb]=f"ERROR: {e}"
    return {"ok":True,"imported":out}

def ensure_data():
    if engine is None: return
    try:
        insp = inspect(engine)
        if "maestro_equipos" not in insp.get_table_names():
            import_excel()
    except Exception:
        pass

def rows(sql, params=None):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params or {}).mappings().all()]

def login_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*a,**k)
    return w


def find_key(d, *names):
    keys = list(d.keys())
    for n in names:
        for k in keys:
            if k.lower() == n.lower():
                return k
    for n in names:
        for k in keys:
            if n.lower() in k.lower():
                return k
    return None

def val_from(d, *names):
    k = find_key(d, *names)
    if not k:
        return ""
    return safe(d.get(k))

def get_equipos_data():
    ensure_data()
    try:
        raw = rows("SELECT * FROM maestro_equipos")
    except Exception:
        raw = rows("SELECT * FROM equipos")

    data = []
    for r in raw:
        codigo = val_from(r, "codigo")
        tipo = val_from(r, "tipo_equipo", "tipo_de_equipo", "tipo")
        familia = val_from(r, "familia")
        marca = val_from(r, "marca")
        modelo = val_from(r, "modelo")
        anio = val_from(r, "ano", "anio", "a_o")
        ubicacion = norm_ubic(val_from(r, "ubicacion", "obra_ubicacion", "faena", "destino"))
        responsable = val_from(r, "responsable")
        lectura = val_from(r, "lectura_actual", "ultimo_horometro", "ultimo_kilometraje", "horometro", "kilometraje", "valor")
        unidad = val_from(r, "unidad", "control", "control_base")
        proxima = val_from(r, "proxima_pm", "proxima_lectura_objetivo", "fecha_estimada", "proxima_mantencion")
        estado = val_from(r, "estado", "estado_operativo", "estado_base", "control_base")

        data.append({
            "codigo": codigo,
            "tipo_equipo": tipo,
            "familia": familia,
            "marca": marca,
            "modelo": modelo,
            "anio": anio,
            "ubicacion": ubicacion,
            "responsable": responsable,
            "lectura_actual": lectura,
            "unidad": unidad,
            "proxima_pm": proxima,
            "estado": estado,
            "descripcion": f"{marca} {modelo}".strip()
        })

    return sorted(data, key=lambda x: str(x.get("codigo") or ""))

def estado_badge(estado):
    s = str(estado or "").upper()
    cls = "badge"
    if "ATRAS" in s or "VENC" in s:
        cls = "badge bad"
    elif "PROX" in s or "RECIBIR" in s or "PROCESO" in s:
        cls = "badge warn"
    return f"<span class='{cls}'>{estado or ''}</span>"

def html_topbar(user="admin"):
    return f"""
    <div class="topbar">
      <div class="logo">DEMOTRON</div>
      <nav class="nav">
        <a href="/">▦ Dashboard</a>
        <a href="/equipos">⚙ Equipos</a>
        <a href="/ot">🛠 OT</a>
        <a href="/lecturas">▤ Lecturas</a>
        <a href="/mantenciones">🧰 Mantenciones</a>
        <a href="/compras">🛒 Compras</a>
        <a href="/bodega">▣ Bodega</a>
        <a href="/proyeccion">📈 Proyección</a>
      </nav>
      <input class="search" placeholder="Buscar...">
      <div>{user}</div>
      <a class="btn" href="/logout">Salir</a>
    </div>
    """

def base_html(title, body, user="admin"):
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/static/css/styles.css">
<style>
.table-card {{ overflow:auto; }}
table {{ min-width:1200px; }}
</style>
</head>
<body>
{html_topbar(user)}
{body}
</body>
</html>"""

def render_equipos_server():
    equipos = get_equipos_data()
    trs = ""
    for e in equipos:
        trs += f"""
        <tr>
          <td><b>{e.get('codigo','')}</b></td>
          <td>{e.get('tipo_equipo','')}</td>
          <td>{e.get('familia','')}</td>
          <td>{e.get('marca','')}</td>
          <td>{e.get('modelo','')}</td>
          <td>{e.get('anio','')}</td>
          <td>{e.get('ubicacion','')}</td>
          <td>{e.get('responsable','')}</td>
          <td>{e.get('lectura_actual','')}</td>
          <td>{e.get('unidad','')}</td>
          <td>{e.get('proxima_pm','')}</td>
          <td>{estado_badge(e.get('estado'))}</td>
        </tr>
        """

    body = f"""
    <main class="data-page">
      <div class="data-head">
        <h2>Maestro de Equipos ({len(equipos)})</h2>
        <a class="btn" href="/admin/importar-cmms">Reimportar CMMS</a>
      </div>
      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th>Código</th>
              <th>Tipo de Equipo</th>
              <th>Familia</th>
              <th>Marca</th>
              <th>Modelo</th>
              <th>Año</th>
              <th>Ubicación</th>
              <th>Responsable</th>
              <th>Lectura Actual</th>
              <th>Unidad</th>
              <th>Próxima PM</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>{trs}</tbody>
        </table>
      </div>
    </main>
    """
    return base_html("Equipos DEMOTRON", body, session.get("user", "admin"))

def render_dashboard_server():
    equipos = get_equipos_data()
    total = len(equipos)
    atrasados = sum(1 for e in equipos if "ATRAS" in str(e.get("estado","")).upper() or "VENC" in str(e.get("estado","")).upper())
    al_dia = sum(1 for e in equipos if "AL D" in str(e.get("estado","")).upper())
    proximos = sum(1 for e in equipos if any(x in str(e.get("estado","")).upper() for x in ["PROX", "RECIBIR", "PROCESO"]))
    fuera = sum(1 for e in equipos if "FUERA" in str(e.get("estado","")).upper())

    ubic = {}
    tipo = {}
    for e in equipos:
        ubic[e.get("ubicacion") or "Sin ubicación"] = ubic.get(e.get("ubicacion") or "Sin ubicación", 0) + 1
        tipo[e.get("tipo_equipo") or "Sin tipo"] = tipo.get(e.get("tipo_equipo") or "Sin tipo", 0) + 1

    top_ubic = "".join([f"<tr><td>{k}</td><td>{v}</td></tr>" for k,v in sorted(ubic.items(), key=lambda x:x[1], reverse=True)[:10]])
    top_tipo = "".join([f"<tr><td>{k}</td><td>{v}</td></tr>" for k,v in sorted(tipo.items(), key=lambda x:x[1], reverse=True)[:10]])

    criticos = ""
    for e in equipos:
        if any(x in str(e.get("estado","")).upper() for x in ["ATRAS", "RECIBIR", "PROCESO", "FUERA"]):
            criticos += f"<tr><td><b>{e.get('codigo','')}</b></td><td>{e.get('tipo_equipo','')}</td><td>{e.get('ubicacion','')}</td><td>{e.get('lectura_actual','')}</td><td>{estado_badge(e.get('estado'))}</td></tr>"
        if criticos.count("<tr>") >= 12:
            break

    cards = ""
    for e in equipos[:30]:
        t = (str(e.get("tipo_equipo","")) + " " + str(e.get("familia","")) + " " + str(e.get("marca",""))).lower()
        icon = "⚙️"
        if "camion" in t or "camión" in t or "tolva" in t or "man" in t: icon = "🚚"
        elif "excav" in t: icon = "🚜"
        elif "moto" in t: icon = "🏗️"
        elif "veh" in t or "camioneta" in t or "maxus" in t: icon = "🚙"
        cards += f"<div class='machine-card'><h4>{e.get('codigo','')}</h4><div class='machine-img'>{icon}</div><p>{e.get('marca','')} {e.get('modelo','')}</p><p>{e.get('ubicacion','')}</p><p>{estado_badge(e.get('estado'))}</p></div>"

    body = f"""
    <main class="page">
      <section class="grid-kpi">
        <div class="card kpi"><div class="ico red">!</div><div><div class="kpi-title">Atrasados</div><div class="kpi-value">{atrasados}</div><div class="kpi-sub">PM vencida</div></div></div>
        <div class="card kpi"><div class="ico yellow">◷</div><div><div class="kpi-title">Próximos/Proceso</div><div class="kpi-value">{proximos}</div><div class="kpi-sub">Por recibir / proceso</div></div></div>
        <div class="card kpi"><div class="ico green">✓</div><div><div class="kpi-title">Al día</div><div class="kpi-value">{al_dia}</div><div class="kpi-sub">{total} equipos</div></div></div>
        <div class="card kpi"><div class="ico blue">▣</div><div><div class="kpi-title">Fuera servicio</div><div class="kpi-value">{fuera}</div><div class="kpi-sub">No operativos</div></div></div>
      </section>

      <section class="middle">
        <div class="card table-panel">
          <h3>Equipos críticos</h3>
          <table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura</th><th>Estado</th></tr></thead><tbody>{criticos}</tbody></table>
        </div>
        <div class="card table-panel">
          <h3>Equipos por ubicación</h3>
          <table><thead><tr><th>Ubicación</th><th>Total</th></tr></thead><tbody>{top_ubic}</tbody></table>
        </div>
      </section>

      <section class="middle">
        <div class="card table-panel">
          <h3>Equipos por tipo</h3>
          <table><thead><tr><th>Tipo</th><th>Total</th></tr></thead><tbody>{top_tipo}</tbody></table>
        </div>
        <div class="card table-panel">
          <h3>Resumen</h3>
          <table><tbody>
            <tr><td>Total equipos</td><td>{total}</td></tr>
            <tr><td>Al día</td><td>{al_dia}</td></tr>
            <tr><td>Próximos / proceso / por recibir</td><td>{proximos}</td></tr>
            <tr><td>Atrasados</td><td>{atrasados}</td></tr>
            <tr><td>Fuera de servicio</td><td>{fuera}</td></tr>
          </tbody></table>
        </div>
      </section>

      <section class="card" style="margin-top:12px">
        <h3>Equipos vista rápida</h3>
        <div class="cards-row">{cards}</div>
      </section>
    </main>
    <footer class="footer"><b>DEMOTRON CMMS</b><span>Dashboard servidor</span></footer>
    """
    return base_html("Dashboard DEMOTRON", body, session.get("user", "admin"))

@app.route("/login", methods=["GET","POST"])
def login():
    err=None
    if request.method=="POST":
        u=request.form.get("usuario","")
        p=request.form.get("password","")
        if USERS.get(u)==p:
            session["user"]=u
            return redirect(url_for("index"))
        err="Usuario o contraseña incorrectos"
    return render_template("login.html", error=err)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    ensure_data()
    return render_dashboard_server()

@app.route("/equipos")
@login_required
def equipos_page():
    ensure_data()
    return render_equipos_server()

@app.route("/lecturas")
@login_required
def lecturas_page():
    ensure_data()
    return render_template("lecturas.html", user=session.get("user"))

@app.route("/mantenciones")
@login_required
def mantenciones_page():
    ensure_data()
    return render_template("mantenciones.html", user=session.get("user"))

@app.route("/ot")
@login_required
def ot_page():
    ensure_data()
    return render_template("ot.html", user=session.get("user"))

@app.route("/compras")
@login_required
def compras_page():
    ensure_data()
    return render_template("compras.html", user=session.get("user"))

@app.route("/bodega")
@login_required
def bodega_page():
    ensure_data()
    return render_template("bodega.html", user=session.get("user"))

@app.route("/proyeccion")
@login_required
def proyeccion_page():
    ensure_data()
    return render_template("proyeccion.html", user=session.get("user"))

@app.route("/admin/importar-cmms")
@login_required
def importar():
    return jsonify(import_excel())

@app.route("/api/status")
def api_status():
    try:
        if not engine: return jsonify({"status":"error","message":"DATABASE_URL no configurada"}),500
        with engine.connect() as conn: conn.execute(text("SELECT 1"))
        return jsonify({"status":"ok","database":"postgresql"})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}),500

@app.route("/api/equipos")
def api_equipos():
    try:
        return jsonify(get_equipos_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/lecturas")
def api_lecturas():
    ensure_data()
    try:
        q = """
        SELECT fecha,codigo,horometro,kilometraje,obra_ubicacion,responsable,observacion
        FROM lecturas
        ORDER BY fecha DESC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            hor=safe(r.get("horometro"))
            km=safe(r.get("kilometraje"))
            data.append({
                "fecha":safe(r.get("fecha")),
                "codigo":safe(r.get("codigo")),
                "horometro":hor,
                "kilometraje":km,
                "tipo_lectura":"HORAS" if hor not in ["",None] else "KM",
                "valor": hor if hor not in ["",None] else km,
                "ubicacion":norm_ubic(r.get("obra_ubicacion")),
                "responsable":safe(r.get("responsable")),
                "observacion":safe(r.get("observacion"))
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/mantenciones")
def api_mantenciones():
    ensure_data()
    try:
        q = """
        SELECT fecha,codigo,tipo_mantencion,lectura,espm,folio,lugar,proveedor,
               costo_mantencion_clp,estado
        FROM mantenciones
        ORDER BY fecha DESC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            data.append({
                "fecha":safe(r.get("fecha")),
                "codigo":safe(r.get("codigo")),
                "tipo":safe(r.get("tipo_mantencion")),
                "lectura":safe(r.get("lectura")),
                "espm":safe(r.get("espm")),
                "folio":safe(r.get("folio")),
                "lugar":norm_ubic(r.get("lugar")),
                "proveedor":safe(r.get("proveedor")),
                "costo":safe(r.get("costo_mantencion_clp")),
                "estado":safe(r.get("estado")),
                "descripcion":safe(r.get("tipo_mantencion"))
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/ot")
def api_ot():
    # OT se arma desde mantenciones reales: folio = OT/folio
    ensure_data()
    try:
        mant = api_mantenciones().get_json()
        if not isinstance(mant,list): return jsonify([])
        data=[]
        for i,m in enumerate(mant):
            data.append({
                "ot": m.get("folio") or f"OT-AUTO-{i+1:04d}",
                "fecha": m.get("fecha"),
                "codigo": m.get("codigo"),
                "tipo": m.get("tipo"),
                "lectura": m.get("lectura"),
                "estado": m.get("estado"),
                "costo": m.get("costo"),
                "proveedor": m.get("proveedor")
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/compras")
def api_compras():
    ensure_data()
    try:
        q = """
        SELECT fecha,oc,codigo,descripcion,proveedor,costo_pm_clp,regla,estado_oc
        FROM compras
        ORDER BY fecha DESC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            data.append({
                "fecha":safe(r.get("fecha")),
                "oc":safe(r.get("oc")),
                "codigo":safe(r.get("codigo")),
                "descripcion":safe(r.get("descripcion")),
                "proveedor":safe(r.get("proveedor")),
                "monto":safe(r.get("costo_pm_clp")),
                "regla":safe(r.get("regla")),
                "estado":safe(r.get("estado_oc"))
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/bodega")
def api_bodega():
    ensure_data()
    try:
        q = """
        SELECT folio,fecha,equipo,envio,persona_que_retiro,destino,comentario,codigo
        FROM bodega
        ORDER BY fecha DESC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            data.append({
                "folio":safe(r.get("folio")),
                "fecha":safe(r.get("fecha")),
                "equipo":safe(r.get("equipo")),
                "envio":safe(r.get("envio")),
                "persona":safe(r.get("persona_que_retiro")),
                "destino":norm_ubic(r.get("destino")),
                "comentario":safe(r.get("comentario")),
                "codigo":safe(r.get("codigo")),
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/proyeccion")
def api_proyeccion():
    ensure_data()
    try:
        q = """
        SELECT codigo,tipo_equipo,familia,control,lectura_actual,proxima_lectura_objetivo,
               promedio_diario,dias_estimados,fecha_estimada,estado_operativo,
               costo_total_pm,prioridad,accion_sugerida
        FROM plan_mantenciones
        ORDER BY prioridad ASC NULLS LAST, dias_estimados ASC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            data.append({
                "codigo":safe(r.get("codigo")),
                "tipo_equipo":safe(r.get("tipo_equipo")),
                "familia":safe(r.get("familia")),
                "control":safe(r.get("control")),
                "lectura_actual":safe(r.get("lectura_actual")),
                "proxima_pm":safe(r.get("proxima_lectura_objetivo")),
                "promedio_diario":safe(r.get("promedio_diario")),
                "dias_estimados":safe(r.get("dias_estimados")),
                "fecha_estimada":safe(r.get("fecha_estimada")),
                "estado":safe(r.get("estado_operativo")),
                "costo_total_pm":safe(r.get("costo_total_pm")),
                "prioridad":safe(r.get("prioridad")),
                "accion":safe(r.get("accion_sugerida")),
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/dashboard")
def api_dashboard():
    ensure_data()
    equipos = api_equipos().get_json()
    lecturas = api_lecturas().get_json()
    mant = api_mantenciones().get_json()
    compras = api_compras().get_json()
    bodega = api_bodega().get_json()
    proy = api_proyeccion().get_json()
    if not isinstance(equipos,list): return jsonify(equipos),500

    atrasados=sum(1 for e in equipos if "ATRAS" in str(e.get("estado","")).upper())
    al_dia=sum(1 for e in equipos if "AL D" in str(e.get("estado","")).upper())
    prox=sum(1 for e in equipos if any(x in str(e.get("estado","")).upper() for x in ["PROX","RECIBIR","PROCESO"]))
    fuera=sum(1 for e in equipos if "FUERA" in str(e.get("estado","")).upper())

    ubic,tipo,marca={}, {}, {}
    for e in equipos:
        for dic,val in [(ubic,e.get("ubicacion") or "Sin ubicación"),(tipo,e.get("tipo_equipo") or "Sin tipo"),(marca,e.get("marca") or "Sin marca")]:
            dic[val]=dic.get(val,0)+1

    use={}
    by={}
    if isinstance(lecturas,list):
        for r in lecturas:
            code=str(r.get("codigo") or "")
            val=num(r.get("valor"))
            if code and val: by.setdefault(code,[]).append(val)
        for c,vals in by.items():
            if len(vals)>=2: use[c]=max(vals)-min(vals)

    costs={}
    total_compras=0
    if isinstance(compras,list):
        for c in compras:
            m=num(c.get("monto")); total_compras+=m
            code=str(c.get("codigo") or "Sin código")
            costs[code]=costs.get(code,0)+m
    if isinstance(mant,list):
        for m in mant:
            cost=num(m.get("costo"))
            code=str(m.get("codigo") or "Sin código")
            costs[code]=costs.get(code,0)+cost

    def top(d,n=10): return [{"label":k,"total":v} for k,v in sorted(d.items(),key=lambda x:x[1],reverse=True)[:n]]

    return jsonify({
        "total_equipos":len(equipos),
        "total_lecturas":len(lecturas) if isinstance(lecturas,list) else 0,
        "total_mantenciones":len(mant) if isinstance(mant,list) else 0,
        "total_compras":total_compras,
        "total_bodega":len(bodega) if isinstance(bodega,list) else 0,
        "atrasados":atrasados,
        "proximos":prox,
        "controlados":al_dia,
        "fuera_servicio":fuera,
        "por_estado":[{"label":"Al día","total":al_dia},{"label":"Próx/Proceso/Recibir","total":prox},{"label":"Atrasados","total":atrasados},{"label":"Fuera de servicio","total":fuera}],
        "por_ubicacion":top(ubic),
        "por_tipo":top(tipo),
        "por_marca":top(marca),
        "uso_mensual":top(use),
        "costos_altos":top(costs),
        "compras_recientes":compras[:10] if isinstance(compras,list) else [],
        "mantenciones":mant[:10] if isinstance(mant,list) else [],
        "equipos":equipos[:120],
        "proyeccion":proy[:120] if isinstance(proy,list) else []
    })

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",8080)))

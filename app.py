
import os, re, unicodedata
from datetime import datetime, date
from functools import wraps

import pandas as pd
from flask import Flask, request, redirect, url_for, session, render_template_string, jsonify
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
USERS = {"admin": "admin123", "gerencia": "gerencia123", "mantencion": "mantencion123"}

def norm_col(v):
    v = "" if v is None else str(v)
    v = v.strip().lower()
    v = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    v = re.sub(r"[^a-z0-9]+", "_", v)
    return re.sub(r"_+", "_", v).strip("_") or "columna"

def norm_ubic(v):
    if v is None: return ""
    raw = str(v).strip()
    if raw.lower() in ["", "nan", "none", "nat"]: return ""
    mapa = {
        "palmucho":"Palmucho","q_61":"Palmucho","q61":"Palmucho","q_459":"Q-459","q459":"Q-459",
        "quirihue":"Quirihue","cobquecura":"Cobquecura","curico":"Curicó","san_carlos":"San Carlos",
        "oficina_central":"Oficina Central","san_nicolas":"San Nicolas","taller":"Taller","villaseca":"Villaseca",
        "pelluhue":"Pelluhue","ninhue":"Ninhue","retiro":"Retiro","colbun":"Colbun"
    }
    return mapa.get(norm_col(raw), raw.title())

def safe(v):
    if v is None: return ""
    if isinstance(v, (datetime, date)): return v.strftime("%Y-%m-%d")
    s = str(v)
    if s.lower() in ["nan","none","nat"]: return ""
    return v

def num(v):
    try:
        if v is None or str(v).strip() == "": return 0
        s = str(v).replace("$","").replace(" ","").replace(".","").replace(",",".")
        return float(s)
    except Exception:
        return 0

def q(sql, params=None, fetch=True):
    if engine is None:
        return []
    with engine.begin() as conn:
        res = conn.execute(text(sql), params or {})
        if fetch:
            return [dict(r) for r in res.mappings().all()]
        return []

def table_exists(name):
    try:
        return engine is not None and name in inspect(engine).get_table_names()
    except Exception:
        return False

def col_exists(table, col):
    try:
        return col in [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception:
        return False

def columns(table):
    try:
        return [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception:
        return []

def ensure_schema():
    if engine is None: return
    q("""CREATE TABLE IF NOT EXISTS maestro_equipos (
        codigo TEXT PRIMARY KEY,
        tipo_equipo TEXT, familia TEXT, marca TEXT, modelo TEXT, ano TEXT,
        ubicacion TEXT, responsable TEXT, lectura_actual TEXT, unidad TEXT,
        proxima_pm TEXT, estado TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS lecturas (
        id SERIAL PRIMARY KEY, fecha DATE, codigo TEXT, horometro NUMERIC,
        kilometraje NUMERIC, obra_ubicacion TEXT, responsable TEXT, observacion TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS mantenciones (
        id SERIAL PRIMARY KEY, fecha DATE, codigo TEXT, tipo_mantencion TEXT,
        lectura NUMERIC, espm TEXT, folio TEXT, lugar TEXT, proveedor TEXT,
        costo_mantencion_clp TEXT, estado TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS compras (
        id SERIAL PRIMARY KEY, fecha DATE, oc TEXT, codigo TEXT, descripcion TEXT,
        proveedor TEXT, costo_pm_clp TEXT, regla TEXT, estado_oc TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS bodega (
        id SERIAL PRIMARY KEY, folio TEXT, fecha DATE, equipo TEXT, envio TEXT,
        persona_que_retiro TEXT, destino TEXT, comentario TEXT, codigo TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS ot (
        id SERIAL PRIMARY KEY, fecha DATE, ot TEXT, codigo TEXT, tipo TEXT,
        lectura NUMERIC, descripcion TEXT, responsable TEXT, estado TEXT, costo TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS plan_mantenciones (
        codigo TEXT, tipo_equipo TEXT, familia TEXT, control TEXT,
        lectura_actual TEXT, proxima_lectura_objetivo TEXT, promedio_diario TEXT,
        dias_estimados TEXT, fecha_estimada TEXT, estado_operativo TEXT,
        costo_total_pm TEXT, prioridad TEXT, accion_sugerida TEXT
    )""", fetch=False)

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
    seen, final_cols = {}, []
    for c in df.columns:
        if c not in seen:
            seen[c]=0; final_cols.append(c)
        else:
            seen[c]+=1; final_cols.append(f"{c}_{seen[c]}")
    df.columns = final_cols
    for c in df.columns:
        if "fecha" in c:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        if c in ["ubicacion","obra_ubicacion","destino","lugar"]:
            df[c] = df[c].apply(norm_ubic)
    return df

def import_excel():
    ensure_schema()
    fp = os.path.join(os.path.dirname(__file__), "data", "cmms.xlsx")
    if not os.path.exists(fp):
        return {"ok": False, "error": "No existe data/cmms.xlsx"}
    sheets = {
        "Maestro_Equipos":"maestro_equipos",
        "Lecturas":"lecturas",
        "Mantenciones":"mantenciones",
        "Compras PM":"compras",
        "Bodega":"bodega",
        "Plan_Mantenciones":"plan_mantenciones",
    }
    out = {}
    for sh, tb in sheets.items():
        try:
            df = clean_sheet(fp, sh)
            df.to_sql(tb, engine, if_exists="replace", index=False)
            out[tb] = len(df)
        except Exception as e:
            out[tb] = f"ERROR: {e}"
    ensure_schema()
    return {"ok": True, "imported": out}

def ensure_data():
    ensure_schema()
    try:
        if table_exists("maestro_equipos"):
            total = q("SELECT COUNT(*) AS n FROM maestro_equipos")[0]["n"]
            if int(total or 0) == 0:
                import_excel()
    except Exception:
        pass

def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*a, **k)
    return w

CSS = '<link rel="stylesheet" href="/static/css/styles.css">'

def topbar():
    return """
    <div class="topbar">
      <div class="logo">DEMOTRON</div>
      <nav class="nav">
        <a href="/">Dashboard</a><a href="/equipos">Equipos</a><a href="/lecturas">Lecturas</a>
        <a href="/mantenciones">Mantenciones</a><a href="/ot">OT</a><a href="/compras">Compras</a>
        <a href="/bodega">Bodega</a><a href="/proyeccion">Proyección</a>
      </nav>
      <a class="btn" href="/admin/importar-cmms">Importar CMMS</a>
      <a class="btn ghost" href="/logout">Salir</a>
    </div>
    """

def page(title, body):
    return render_template_string(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{CSS}</head>
    <body>{topbar()}{body}</body></html>""")

def badge(estado):
    s = str(estado or "").upper()
    cls = "badge"
    if "ATRAS" in s or "VENC" in s: cls = "badge bad"
    elif "PROX" in s or "RECIBIR" in s or "PROCESO" in s: cls = "badge warn"
    return f"<span class='{cls}'>{safe(estado)}</span>"

def get_equipos():
    ensure_data()
    if not table_exists("maestro_equipos"):
        return []
    try:
        raw = q("SELECT * FROM maestro_equipos ORDER BY codigo")
    except Exception:
        raw = q("SELECT * FROM maestro_equipos")
    data = []
    for r in raw:
        data.append({
            "codigo": safe(r.get("codigo")),
            "tipo_equipo": safe(r.get("tipo_equipo") or r.get("tipo_de_equipo")),
            "familia": safe(r.get("familia")),
            "marca": safe(r.get("marca")),
            "modelo": safe(r.get("modelo")),
            "ano": safe(r.get("ano") or r.get("anio")),
            "ubicacion": norm_ubic(r.get("ubicacion")),
            "responsable": safe(r.get("responsable")),
            "lectura_actual": safe(r.get("lectura_actual")),
            "unidad": safe(r.get("unidad")),
            "proxima_pm": safe(r.get("proxima_pm")),
            "estado": safe(r.get("estado") or r.get("control_base") or r.get("estado_operativo")),
        })
    return data

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        u = request.form.get("usuario","")
        p = request.form.get("password","")
        if USERS.get(u) == p:
            session["user"] = u
            ensure_data()
            return redirect(url_for("dashboard"))
        error = "Usuario o contraseña incorrectos"
    return render_template_string("""<!doctype html><html><head><meta charset="utf-8">{{css|safe}}</head>
    <body class="login-body"><form class="login-card" method="post">
    <h1>DEMOTRON</h1><p>CMMS Operativo</p><label>Usuario</label><input name="usuario" value="admin">
    <label>Contraseña</label><input type="password" name="password" value="admin123">
    {% if error %}<div class="error">{{error}}</div>{% endif %}<button>Entrar</button></form></body></html>""", css=CSS, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    ensure_data()

    equipos = []
    try:
        equipos = get_equipos()
    except Exception:
        equipos = []

    total = len(equipos)
    atrasados = 0
    aldia = 0
    proceso = 0
    fuera = 0

    for e in equipos:
        estado = str(e.get("estado") or "").upper()
        if "ATRAS" in estado or "VENC" in estado:
            atrasados += 1
        elif "FUERA" in estado:
            fuera += 1
        elif "AL D" in estado:
            aldia += 1
        elif "PROCESO" in estado or "RECIBIR" in estado or "PROX" in estado:
            proceso += 1

    lecturas_count = 0
    mantenciones_count = 0
    compras_total = 0
    bodega_count = 0
    ot_count = 0

    try:
        if table_exists("lecturas"):
            lecturas_count = q("SELECT COUNT(*) AS n FROM lecturas")[0].get("n", 0)
    except Exception:
        lecturas_count = 0

    try:
        if table_exists("mantenciones"):
            mantenciones_count = q("SELECT COUNT(*) AS n FROM mantenciones")[0].get("n", 0)
    except Exception:
        mantenciones_count = 0

    try:
        if table_exists("bodega"):
            bodega_count = q("SELECT COUNT(*) AS n FROM bodega")[0].get("n", 0)
    except Exception:
        bodega_count = 0

    try:
        if table_exists("ot"):
            ot_count = q("SELECT COUNT(*) AS n FROM ot")[0].get("n", 0)
    except Exception:
        ot_count = 0

    try:
        if table_exists("compras"):
            compras_rows = q("SELECT * FROM compras LIMIT 5000")
            for r in compras_rows:
                compras_total += num(r.get("costo_pm_clp") or r.get("monto") or r.get("total") or r.get("valor"))
    except Exception:
        compras_total = 0

    ubic = {}
    tipo = {}
    for e in equipos:
        u = e.get("ubicacion") or "Sin ubicación"
        t = e.get("tipo_equipo") or "Sin tipo"
        ubic[u] = ubic.get(u, 0) + 1
        tipo[t] = tipo.get(t, 0) + 1

    ubic_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>"
        for k, v in sorted(ubic.items(), key=lambda x: x[1], reverse=True)[:10]
    )

    tipo_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>"
        for k, v in sorted(tipo.items(), key=lambda x: x[1], reverse=True)[:10]
    )

    crit_rows = ""
    for e in equipos:
        estado = str(e.get("estado") or "").upper()
        if estado and not ("AL D" in estado):
            crit_rows += (
                f"<tr><td><b>{e.get('codigo','')}</b></td>"
                f"<td>{e.get('tipo_equipo','')}</td>"
                f"<td>{e.get('ubicacion','')}</td>"
                f"<td>{e.get('lectura_actual','')} {e.get('unidad','')}</td>"
                f"<td>{badge(e.get('estado'))}</td></tr>"
            )
        if crit_rows.count("<tr>") >= 12:
            break

    if not crit_rows:
        crit_rows = "<tr><td colspan='5'>Sin equipos críticos registrados.</td></tr>"

    cards = ""
    for e in equipos[:24]:
        txt = (str(e.get("tipo_equipo","")) + " " + str(e.get("familia","")) + " " + str(e.get("marca",""))).lower()
        icon = "⚙️"
        if "camion" in txt or "camión" in txt or "tolva" in txt or "man" in txt:
            icon = "🚚"
        elif "excav" in txt:
            icon = "🚜"
        elif "moto" in txt:
            icon = "🏗️"
        elif "veh" in txt or "camioneta" in txt or "maxus" in txt:
            icon = "🚙"
        cards += (
            f"<div class='machine-card'><h4>{e.get('codigo','')}</h4>"
            f"<div class='machine-img'>{icon}</div>"
            f"<p>{e.get('marca','')} {e.get('modelo','')}</p>"
            f"<p>{e.get('ubicacion','')}</p><p>{badge(e.get('estado'))}</p></div>"
        )

    body = f"""
    <main class="page">
      <section class="grid-kpi">
        <div class="card kpi redb"><small>Atrasados</small><b>{atrasados}</b></div>
        <div class="card kpi yellowb"><small>Proceso / Próx.</small><b>{proceso}</b></div>
        <div class="card kpi greenb"><small>Al día</small><b>{aldia}</b></div>
        <div class="card kpi blueb"><small>Total equipos</small><b>{total}</b></div>
        <div class="card kpi purpleb"><small>Mantenciones</small><b>{mantenciones_count}</b></div>
        <div class="card kpi tealb"><small>Compras PM</small><b>${int(compras_total):,}</b></div>
      </section>

      <section class="grid-kpi" style="margin-top:10px">
        <div class="card kpi blueb"><small>Lecturas</small><b>{lecturas_count}</b></div>
        <div class="card kpi purpleb"><small>OT</small><b>{ot_count}</b></div>
        <div class="card kpi tealb"><small>Bodega</small><b>{bodega_count}</b></div>
        <div class="card kpi yellowb"><small>Fuera Servicio</small><b>{fuera}</b></div>
      </section>

      <section class="middle">
        <div class="card"><h3>Equipos críticos</h3>
          <table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura</th><th>Estado</th></tr></thead>
          <tbody>{crit_rows}</tbody></table>
        </div>
        <div class="card"><h3>Equipos por ubicación</h3>
          <table><thead><tr><th>Ubicación</th><th>Total</th></tr></thead><tbody>{ubic_rows}</tbody></table>
        </div>
      </section>

      <section class="middle">
        <div class="card"><h3>Equipos por tipo</h3>
          <table><thead><tr><th>Tipo</th><th>Total</th></tr></thead><tbody>{tipo_rows}</tbody></table>
        </div>
        <div class="card"><h3>Accesos rápidos</h3>
          <p><a class="btn" href="/equipos">Equipos</a> <a class="btn" href="/lecturas">Lecturas</a> <a class="btn" href="/mantenciones">Mantenciones</a></p>
          <p><a class="btn" href="/ot">OT</a> <a class="btn" href="/compras">Compras</a> <a class="btn" href="/bodega">Bodega</a></p>
        </div>
      </section>

      <section class="card">
        <h3>Equipos vista rápida</h3>
        <div class="cards-row">{cards}</div>
      </section>
    </main>
    """
    return page("Dashboard", body)

@app.route("/admin/importar-cmms")
@login_required
def importar():
    return jsonify(import_excel())

@app.route("/api/equipos")
def api_equipos():
    return jsonify(get_equipos())

def form_input(name, label, typ="text"):
    return f"<label>{label}</label><input name='{name}' type='{typ}'>"

def build_form(action, fields):
    return f"<form class='form-card' method='post' action='{action}'>" + "".join(form_input(*f) for f in fields) + "<button>Guardar</button></form>"

@app.route("/equipos", methods=["GET","POST"])
@login_required
def equipos():
    ensure_data()
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["codigo","tipo_equipo","familia","marca","modelo","ano","ubicacion","responsable","lectura_actual","unidad","proxima_pm","estado"]}
        data["ubicacion"] = norm_ubic(data.get("ubicacion"))
        q("""INSERT INTO maestro_equipos (codigo,tipo_equipo,familia,marca,modelo,ano,ubicacion,responsable,lectura_actual,unidad,proxima_pm,estado)
             VALUES (:codigo,:tipo_equipo,:familia,:marca,:modelo,:ano,:ubicacion,:responsable,:lectura_actual,:unidad,:proxima_pm,:estado)
             ON CONFLICT (codigo) DO UPDATE SET tipo_equipo=EXCLUDED.tipo_equipo,familia=EXCLUDED.familia,marca=EXCLUDED.marca,modelo=EXCLUDED.modelo,
             ano=EXCLUDED.ano,ubicacion=EXCLUDED.ubicacion,responsable=EXCLUDED.responsable,lectura_actual=EXCLUDED.lectura_actual,
             unidad=EXCLUDED.unidad,proxima_pm=EXCLUDED.proxima_pm,estado=EXCLUDED.estado""", data, fetch=False)
        return redirect(url_for("equipos"))
    equipos_data = get_equipos()
    rows_html = "".join(f"<tr><td><b>{e['codigo']}</b></td><td>{e['tipo_equipo']}</td><td>{e['familia']}</td><td>{e['marca']}</td><td>{e['modelo']}</td><td>{e['ano']}</td><td>{e['ubicacion']}</td><td>{e['responsable']}</td><td>{e['lectura_actual']}</td><td>{e['unidad']}</td><td>{e['proxima_pm']}</td><td>{badge(e['estado'])}</td></tr>" for e in equipos_data)
    form = build_form("/equipos", [("codigo","Código"),("tipo_equipo","Tipo de Equipo"),("familia","Familia"),("marca","Marca"),("modelo","Modelo"),("ano","Año"),("ubicacion","Ubicación"),("responsable","Responsable"),("lectura_actual","Lectura Actual"),("unidad","Unidad"),("proxima_pm","Próxima PM"),("estado","Estado")])
    body = f"<main class='data-page'><div class='data-head'><h2>Equipos ({len(equipos_data)})</h2><a class='btn' href='/admin/importar-cmms'>Importar CMMS</a></div>{form}<div class='table-card'><table><thead><tr><th>Código</th><th>Tipo</th><th>Familia</th><th>Marca</th><th>Modelo</th><th>Año</th><th>Ubicación</th><th>Responsable</th><th>Lectura</th><th>Unidad</th><th>Próx PM</th><th>Estado</th></tr></thead><tbody>{rows_html}</tbody></table></div></main>"
    return page("Equipos", body)

@app.route("/lecturas", methods=["GET","POST"])
@login_required
def lecturas():
    ensure_data()
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["fecha","codigo","horometro","kilometraje","obra_ubicacion","responsable","observacion"]}
        data["obra_ubicacion"] = norm_ubic(data.get("obra_ubicacion"))
        q("""INSERT INTO lecturas (fecha,codigo,horometro,kilometraje,obra_ubicacion,responsable,observacion)
             VALUES (:fecha,:codigo,:horometro,:kilometraje,:obra_ubicacion,:responsable,:observacion)""", data, fetch=False)
        return redirect(url_for("lecturas"))
    data = q("SELECT * FROM lecturas ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("lecturas") else []
    rows_html = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('codigo'))}</b></td><td>{safe(r.get('horometro'))}</td><td>{safe(r.get('kilometraje'))}</td><td>{norm_ubic(r.get('obra_ubicacion'))}</td><td>{safe(r.get('responsable'))}</td><td>{safe(r.get('observacion'))}</td></tr>" for r in data)
    form = build_form("/lecturas", [("fecha","Fecha","date"),("codigo","Código"),("horometro","Horómetro","number"),("kilometraje","Kilometraje","number"),("obra_ubicacion","Ubicación"),("responsable","Responsable"),("observacion","Observación")])
    return page("Lecturas", f"<main class='data-page'><h2>Lecturas</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Horómetro</th><th>Kilometraje</th><th>Ubicación</th><th>Responsable</th><th>Obs</th></tr></thead><tbody>{rows_html}</tbody></table></div></main>")

@app.route("/mantenciones", methods=["GET","POST"])
@login_required
def mantenciones():
    ensure_data()
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["fecha","codigo","tipo_mantencion","lectura","espm","folio","lugar","proveedor","costo_mantencion_clp","estado"]}
        data["lugar"] = norm_ubic(data.get("lugar"))
        q("""INSERT INTO mantenciones (fecha,codigo,tipo_mantencion,lectura,espm,folio,lugar,proveedor,costo_mantencion_clp,estado)
             VALUES (:fecha,:codigo,:tipo_mantencion,:lectura,:espm,:folio,:lugar,:proveedor,:costo_mantencion_clp,:estado)""", data, fetch=False)
        return redirect(url_for("mantenciones"))
    data = q("SELECT * FROM mantenciones ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("mantenciones") else []
    rows_html = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('codigo'))}</b></td><td>{safe(r.get('tipo_mantencion'))}</td><td>{safe(r.get('lectura'))}</td><td>{safe(r.get('folio'))}</td><td>{safe(r.get('proveedor'))}</td><td>{safe(r.get('costo_mantencion_clp'))}</td><td>{badge(r.get('estado'))}</td></tr>" for r in data)
    form = build_form("/mantenciones", [("fecha","Fecha","date"),("codigo","Código"),("tipo_mantencion","Tipo Mantención"),("lectura","Lectura","number"),("espm","Descripción/ESPM"),("folio","Folio/OT"),("lugar","Lugar"),("proveedor","Proveedor"),("costo_mantencion_clp","Costo"),("estado","Estado")])
    return page("Mantenciones", f"<main class='data-page'><h2>Mantenciones</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Tipo</th><th>Lectura</th><th>Folio/OT</th><th>Proveedor</th><th>Costo</th><th>Estado</th></tr></thead><tbody>{rows_html}</tbody></table></div></main>")


@app.route("/ot", methods=["GET","POST"])
@login_required
def ot():
    ensure_data()
    ensure_schema()

    if request.method == "POST":
        data = {
            "fecha": request.form.get("fecha") or None,
            "ot": request.form.get("ot") or "",
            "codigo": request.form.get("codigo") or "",
            "tipo": request.form.get("tipo") or "",
            "lectura": request.form.get("lectura") or None,
            "descripcion": request.form.get("descripcion") or "",
            "responsable": request.form.get("responsable") or "",
            "estado": request.form.get("estado") or "",
            "costo": request.form.get("costo") or "",
        }
        try:
            q("""INSERT INTO ot (fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo)
                 VALUES (:fecha,:ot,:codigo,:tipo,:lectura,:descripcion,:responsable,:estado,:costo)""", data, fetch=False)
        except Exception:
            # Si la tabla OT no acepta algún tipo, la recreamos segura y reintentamos.
            q("DROP TABLE IF EXISTS ot", fetch=False)
            q("""CREATE TABLE IF NOT EXISTS ot (
                id SERIAL PRIMARY KEY,
                fecha DATE,
                ot TEXT,
                codigo TEXT,
                tipo TEXT,
                lectura TEXT,
                descripcion TEXT,
                responsable TEXT,
                estado TEXT,
                costo TEXT
            )""", fetch=False)
            q("""INSERT INTO ot (fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo)
                 VALUES (:fecha,:ot,:codigo,:tipo,:lectura,:descripcion,:responsable,:estado,:costo)""", data, fetch=False)
        return redirect(url_for("ot"))

    ot_rows = []
    try:
        if table_exists("ot"):
            ot_rows = q("SELECT * FROM ot ORDER BY fecha DESC NULLS LAST, id DESC LIMIT 1000")
    except Exception:
        ot_rows = []

    # Si OT está vacía, muestra OT virtuales desde mantenciones.
    if not ot_rows:
        try:
            if table_exists("mantenciones"):
                mant = q("SELECT * FROM mantenciones ORDER BY fecha DESC NULLS LAST LIMIT 500")
                for i, r in enumerate(mant):
                    ot_rows.append({
                        "fecha": r.get("fecha"),
                        "ot": r.get("folio") or f"OT-AUTO-{i+1:04d}",
                        "codigo": r.get("codigo"),
                        "tipo": r.get("tipo_mantencion"),
                        "lectura": r.get("lectura"),
                        "descripcion": r.get("espm") or r.get("tipo_mantencion"),
                        "responsable": r.get("proveedor") or "",
                        "estado": r.get("estado"),
                        "costo": r.get("costo_mantencion_clp"),
                    })
        except Exception:
            ot_rows = []

    rows_html = ""
    for r in ot_rows:
        rows_html += (
            f"<tr><td>{safe(r.get('fecha'))}</td>"
            f"<td><b>{safe(r.get('ot'))}</b></td>"
            f"<td>{safe(r.get('codigo'))}</td>"
            f"<td>{safe(r.get('tipo'))}</td>"
            f"<td>{safe(r.get('lectura'))}</td>"
            f"<td>{safe(r.get('descripcion'))}</td>"
            f"<td>{safe(r.get('responsable'))}</td>"
            f"<td>{badge(r.get('estado'))}</td>"
            f"<td>{safe(r.get('costo'))}</td></tr>"
        )

    if not rows_html:
        rows_html = "<tr><td colspan='9'>Sin OT registradas.</td></tr>"

    form = build_form("/ot", [
        ("fecha","Fecha","date"),
        ("ot","OT/Folio"),
        ("codigo","Código"),
        ("tipo","Tipo"),
        ("lectura","Lectura"),
        ("descripcion","Descripción"),
        ("responsable","Responsable"),
        ("estado","Estado"),
        ("costo","Costo")
    ])

    body = (
        "<main class='data-page'><h2>Órdenes de Trabajo</h2>"
        + form +
        "<div class='table-card'><table><thead><tr>"
        "<th>Fecha</th><th>OT</th><th>Código</th><th>Tipo</th><th>Lectura</th>"
        "<th>Descripción</th><th>Responsable</th><th>Estado</th><th>Costo</th>"
        "</tr></thead><tbody>" + rows_html + "</tbody></table></div></main>"
    )
    return page("OT", body)

@app.route("/compras", methods=["GET","POST"])
@login_required
def compras():
    ensure_data()
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["fecha","oc","codigo","descripcion","proveedor","costo_pm_clp","regla","estado_oc"]}
        q("""INSERT INTO compras (fecha,oc,codigo,descripcion,proveedor,costo_pm_clp,regla,estado_oc)
             VALUES (:fecha,:oc,:codigo,:descripcion,:proveedor,:costo_pm_clp,:regla,:estado_oc)""", data, fetch=False)
        return redirect(url_for("compras"))
    data = q("SELECT * FROM compras ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("compras") else []
    rows_html = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('oc'))}</b></td><td>{safe(r.get('codigo'))}</td><td>{safe(r.get('descripcion'))}</td><td>{safe(r.get('proveedor'))}</td><td>{safe(r.get('costo_pm_clp'))}</td><td>{safe(r.get('regla'))}</td><td>{badge(r.get('estado_oc'))}</td></tr>" for r in data)
    form = build_form("/compras", [("fecha","Fecha","date"),("oc","OC"),("codigo","Código"),("descripcion","Descripción"),("proveedor","Proveedor"),("costo_pm_clp","Monto"),("regla","Regla"),("estado_oc","Estado OC")])
    return page("Compras", f"<main class='data-page'><h2>Compras PM</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>OC</th><th>Código</th><th>Descripción</th><th>Proveedor</th><th>Monto</th><th>Regla</th><th>Estado</th></tr></thead><tbody>{rows_html}</tbody></table></div></main>")

@app.route("/bodega", methods=["GET","POST"])
@login_required
def bodega():
    ensure_data()
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["folio","fecha","equipo","envio","persona_que_retiro","destino","comentario","codigo"]}
        data["destino"] = norm_ubic(data.get("destino"))
        q("""INSERT INTO bodega (folio,fecha,equipo,envio,persona_que_retiro,destino,comentario,codigo)
             VALUES (:folio,:fecha,:equipo,:envio,:persona_que_retiro,:destino,:comentario,:codigo)""", data, fetch=False)
        return redirect(url_for("bodega"))
    data = q("SELECT * FROM bodega ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("bodega") else []
    rows_html = "".join(f"<tr><td><b>{safe(r.get('folio'))}</b></td><td>{safe(r.get('fecha'))}</td><td>{safe(r.get('equipo'))}</td><td>{safe(r.get('envio'))}</td><td>{safe(r.get('persona_que_retiro'))}</td><td>{safe(r.get('destino'))}</td><td>{safe(r.get('comentario'))}</td><td>{safe(r.get('codigo'))}</td></tr>" for r in data)
    form = build_form("/bodega", [("folio","Folio"),("fecha","Fecha","date"),("equipo","Equipo"),("envio","Envío"),("persona_que_retiro","Persona que retiró"),("destino","Destino"),("comentario","Comentario"),("codigo","Código")])
    return page("Bodega", f"<main class='data-page'><h2>Bodega</h2>{form}<div class='table-card'><table><thead><tr><th>Folio</th><th>Fecha</th><th>Equipo</th><th>Envío</th><th>Retira</th><th>Destino</th><th>Comentario</th><th>Código</th></tr></thead><tbody>{rows_html}</tbody></table></div></main>")

@app.route("/proyeccion")
@login_required
def proyeccion():
    ensure_data()
    data = q("SELECT * FROM plan_mantenciones LIMIT 1000") if table_exists("plan_mantenciones") else []
    rows_html = "".join(f"<tr><td><b>{safe(r.get('codigo'))}</b></td><td>{safe(r.get('tipo_equipo'))}</td><td>{safe(r.get('control'))}</td><td>{safe(r.get('lectura_actual'))}</td><td>{safe(r.get('proxima_lectura_objetivo'))}</td><td>{safe(r.get('promedio_diario'))}</td><td>{safe(r.get('dias_estimados'))}</td><td>{safe(r.get('fecha_estimada'))}</td><td>{badge(r.get('estado_operativo'))}</td><td>{safe(r.get('prioridad'))}</td><td>{safe(r.get('accion_sugerida'))}</td></tr>" for r in data)
    return page("Proyección", f"<main class='data-page'><h2>Proyección PM</h2><div class='table-card'><table><thead><tr><th>Código</th><th>Tipo</th><th>Control</th><th>Lectura</th><th>Próxima</th><th>Promedio</th><th>Días</th><th>Fecha</th><th>Estado</th><th>Prioridad</th><th>Acción</th></tr></thead><tbody>{rows_html}</tbody></table></div></main>")

@app.route("/api/status")
def api_status():
    try:
        ensure_schema()
        return jsonify({"status": "ok", "database": "postgresql"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

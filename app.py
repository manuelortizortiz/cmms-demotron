
import os, re, unicodedata, json
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

ESTADOS = ["AL DÍA", "PRÓXIMA", "ATRASADA", "EN PROCESO", "POR RECIBIR", "EN TALLER", "FUERA DE SERVICIO"]
UNIDADES = ["HORAS", "KM"]

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
        "pelluhue":"Pelluhue","ninhue":"Ninhue","retiro":"Retiro","colbun":"Colbun","taltal":"Taltal","talca":"Talca","santiago":"Santiago"
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
        if v is None or str(v).strip()=="": return 0
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
        lectura TEXT, descripcion TEXT, responsable TEXT, estado TEXT, costo TEXT
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
JS = '<script src="/static/js/cmms.js"></script>'

def topbar():
    return """
    <div class="topbar">
      <div class="logo">DEMOTRON</div>
      <nav class="nav">
        <a href="/">Dashboard</a>
        <a href="/equipos">Equipos</a>
        <a href="/ficha">Ficha Equipo</a>
        <a href="/historial">Historial</a>
        <a href="/planificacion">Planificación</a>
        <a href="/lecturas">Lecturas</a>
        <a href="/mantenciones">Mantenciones</a>
        <a href="/ot">OT</a>
        <a href="/compras">Compras</a>
        <a href="/bodega">Bodega</a>
      </nav>
      <a class="btn" href="/admin/importar-cmms">Importar CMMS</a>
      <a class="btn ghost" href="/logout">Salir</a>
    </div>
    """

def page(title, body, extra=""):
    return render_template_string(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{CSS}</head>
    <body>{topbar()}{body}{JS}{extra}</body></html>""")

def badge(estado):
    s = str(estado or "").upper()
    cls = "badge"
    if "ATRAS" in s or "VENC" in s: cls = "badge bad"
    elif "PROX" in s or "RECIBIR" in s or "PROCESO" in s: cls = "badge warn"
    elif "FUERA" in s or "TALLER" in s: cls = "badge off"
    return f"<span class='{cls}'>{safe(estado)}</span>"

def machine_icon(e):
    txt = (str(e.get("tipo_equipo","")) + " " + str(e.get("familia","")) + " " + str(e.get("marca","")) + " " + str(e.get("modelo",""))).lower()
    if "tolva" in txt or "camion" in txt or "camión" in txt or "man" in txt: return "🚚"
    if "excav" in txt or "komatsu" in txt or "sany" in txt or "doosan" in txt: return "🚜"
    if "moto" in txt: return "🏗️"
    if "cargador" in txt: return "🚜"
    if "camioneta" in txt or "maxus" in txt or "veh" in txt: return "🚙"
    if "rodillo" in txt: return "🛞"
    return "⚙️"

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

def get_equipo(codigo):
    codigo = (codigo or "").strip()
    for e in get_equipos():
        if str(e.get("codigo")).strip().upper() == codigo.upper():
            return e
    return None

def equipo_datalist():
    opts = "".join(f"<option value='{e['codigo']}'>{e['codigo']} - {e['tipo_equipo']} - {e['marca']} {e['modelo']}</option>" for e in get_equipos())
    return f"<datalist id='equiposList'>{opts}</datalist>"

def estado_select(name="estado", current=""):
    opts = "".join(f"<option value='{x}' {'selected' if x==current else ''}>{x}</option>" for x in ESTADOS)
    return f"<select name='{name}' id='{name}'>{opts}</select>"

def form_input(name, label, typ="text", value="", datalist=False, readonly=False):
    list_attr = " list='equiposList' autocomplete='off'" if datalist else ""
    ro = " readonly" if readonly else ""
    return f"<label>{label}</label><input name='{name}' id='{name}' type='{typ}' value='{safe(value)}'{list_attr}{ro}>"

def build_form(action, fields, with_status=False):
    html = f"<form class='form-card' method='post' action='{action}'>"
    for f in fields:
        html += form_input(*f)
    if with_status:
        html += "<label>Estado</label>" + estado_select()
    html += "<button>Guardar</button></form>"
    return html

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
    <h1>DEMOTRON</h1><p>CMMS ERP Pro</p><label>Usuario</label><input name="usuario" value="admin">
    <label>Contraseña</label><input type="password" name="password" value="admin123">
    {% if error %}<div class="error">{{error}}</div>{% endif %}<button>Entrar</button></form></body></html>""", css=CSS, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin/importar-cmms")
@login_required
def importar():
    return jsonify(import_excel())

@app.route("/api/equipos")
def api_equipos():
    return jsonify(get_equipos())

@app.route("/api/equipo/<codigo>")
def api_equipo(codigo):
    return jsonify(get_equipo(codigo) or {})

@app.route("/")
@login_required
def dashboard():
    equipos = get_equipos()
    total = len(equipos)
    atrasados = sum(1 for e in equipos if "ATRAS" in str(e["estado"]).upper())
    aldia = sum(1 for e in equipos if "AL D" in str(e["estado"]).upper())
    proceso = sum(1 for e in equipos if any(x in str(e["estado"]).upper() for x in ["PROCESO","RECIBIR","PROX"]))
    fuera = sum(1 for e in equipos if any(x in str(e["estado"]).upper() for x in ["FUERA","TALLER"]))
    mantenciones = q("SELECT COUNT(*) AS n FROM mantenciones")[0]["n"] if table_exists("mantenciones") else 0
    lecturas = q("SELECT COUNT(*) AS n FROM lecturas")[0]["n"] if table_exists("lecturas") else 0
    compras_rows = q("SELECT * FROM compras LIMIT 5000") if table_exists("compras") else []
    compras_total = sum(num(r.get("costo_pm_clp") or r.get("monto") or r.get("total")) for r in compras_rows)

    ubic, tipo = {}, {}
    for e in equipos:
        ubic[e["ubicacion"] or "Sin ubicación"] = ubic.get(e["ubicacion"] or "Sin ubicación",0)+1
        tipo[e["tipo_equipo"] or "Sin tipo"] = tipo.get(e["tipo_equipo"] or "Sin tipo",0)+1

    ubic_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k,v in sorted(ubic.items(), key=lambda x:x[1], reverse=True)[:10])
    tipo_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k,v in sorted(tipo.items(), key=lambda x:x[1], reverse=True)[:10])
    crit = "".join(f"<tr><td><a href='/equipo/{e['codigo']}'><b>{e['codigo']}</b></a></td><td>{e['tipo_equipo']}</td><td>{e['ubicacion']}</td><td>{e['lectura_actual']} {e['unidad']}</td><td>{badge(e['estado'])}</td></tr>" for e in equipos if str(e["estado"]).upper() not in ["AL DÍA","AL DIA"])[:10000]
    cards = "".join(f"<a class='machine-card' href='/equipo/{e['codigo']}'><h4>{e['codigo']}</h4><div class='machine-img'>{machine_icon(e)}</div><p>{e['marca']} {e['modelo']}</p><p>{e['ubicacion']}</p><p>{badge(e['estado'])}</p></a>" for e in equipos[:32])

    body = f"""
    <main class="page">
      <section class="hero">
        <div><h1>Dashboard CMMS DEMOTRON</h1><p>Gestión de flota, PM, OT, compras, bodega e historial técnico.</p></div>
        <form action="/ficha" method="get" class="search-card">
          <input name="codigo" list="equiposList" placeholder="Buscar equipo, ej: MD-100, CD-102...">
          <button>Ver ficha</button>{equipo_datalist()}
        </form>
      </section>
      <section class="grid-kpi">
        <div class="card kpi redb"><small>Atrasados</small><b>{atrasados}</b></div>
        <div class="card kpi yellowb"><small>Proceso / Próx.</small><b>{proceso}</b></div>
        <div class="card kpi greenb"><small>Al día</small><b>{aldia}</b></div>
        <div class="card kpi blueb"><small>Total equipos</small><b>{total}</b></div>
        <div class="card kpi purpleb"><small>Mantenciones</small><b>{mantenciones}</b></div>
        <div class="card kpi tealb"><small>Compras PM</small><b>${int(compras_total):,}</b></div>
      </section>
      <section class="middle">
        <div class="card"><h3>Equipos críticos</h3><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura</th><th>Estado</th></tr></thead><tbody>{crit}</tbody></table></div>
        <div class="card"><h3>Equipos por ubicación</h3><table><thead><tr><th>Ubicación</th><th>Total</th></tr></thead><tbody>{ubic_rows}</tbody></table></div>
      </section>
      <section class="middle">
        <div class="card"><h3>Equipos por tipo</h3><table><thead><tr><th>Tipo</th><th>Total</th></tr></thead><tbody>{tipo_rows}</tbody></table></div>
        <div class="card"><h3>Indicadores operacionales</h3><table><tbody><tr><td>Lecturas registradas</td><td>{lecturas}</td></tr><tr><td>Fuera servicio / taller</td><td>{fuera}</td></tr></tbody></table></div>
      </section>
      <section class="card"><h3>Vista rápida de equipos</h3><div class="cards-row">{cards}</div></section>
    </main>
    """
    return page("Dashboard ERP", body)

@app.route("/equipos", methods=["GET","POST"])
@login_required
def equipos():
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
    rows = "".join(f"<tr><td><a href='/equipo/{e['codigo']}'><b>{e['codigo']}</b></a></td><td>{e['tipo_equipo']}</td><td>{e['familia']}</td><td>{e['marca']}</td><td>{e['modelo']}</td><td>{e['ano']}</td><td>{e['ubicacion']}</td><td>{e['responsable']}</td><td>{e['lectura_actual']}</td><td>{e['unidad']}</td><td>{e['proxima_pm']}</td><td>{badge(e['estado'])}</td></tr>" for e in equipos_data)
    form = f"""
    <form class="form-card" method="post" action="/equipos">
      {equipo_datalist()}
      {form_input("codigo","Código / Equipo", datalist=True)}
      {form_input("tipo_equipo","Tipo de Equipo")}
      {form_input("familia","Familia")}
      {form_input("marca","Marca")}
      {form_input("modelo","Modelo")}
      {form_input("ano","Año")}
      {form_input("ubicacion","Ubicación")}
      {form_input("responsable","Responsable")}
      {form_input("lectura_actual","Lectura Actual")}
      <label>Unidad</label><select name="unidad"><option>HORAS</option><option>KM</option></select>
      {form_input("proxima_pm","Próxima PM")}
      <label>Estado</label>{estado_select()}
      <button>Guardar / Actualizar Equipo</button>
    </form>
    """
    body = f"<main class='data-page'><div class='data-head'><h2>Equipos ({len(equipos_data)})</h2><a class='btn' href='/admin/importar-cmms'>Importar CMMS</a></div><p class='hint'>Al escribir un código precargado, se completan tipo, familia, marca, modelo, año y estado automáticamente.</p>{form}<div class='table-card'><table><thead><tr><th>Código</th><th>Tipo</th><th>Familia</th><th>Marca</th><th>Modelo</th><th>Año</th><th>Ubicación</th><th>Responsable</th><th>Lectura</th><th>Unidad</th><th>Próx PM</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>"
    extra = f"<script>window.EQUIPOS={json.dumps(equipos_data, ensure_ascii=False)};</script>"
    return page("Equipos", body, extra)

@app.route("/ficha")
@login_required
def ficha_redirect():
    codigo = request.args.get("codigo","").strip()
    if codigo:
        return redirect(url_for("equipo_ficha", codigo=codigo))
    return redirect(url_for("dashboard"))

@app.route("/equipo/<codigo>")
@login_required
def equipo_ficha(codigo):
    e = get_equipo(codigo)
    if not e:
        return page("Equipo no encontrado", f"<main class='data-page'><div class='card'><h2>Equipo no encontrado</h2><p>{codigo}</p><a class='btn' href='/equipos'>Volver</a></div></main>")
    hist = historial_data(codigo)
    rows_hist = "".join(f"<tr><td>{h['fecha']}</td><td>{h['origen']}</td><td>{h['detalle']}</td><td>{h['lectura']}</td><td>{h['estado']}</td></tr>" for h in hist[:80])
    body = f"""
    <main class="data-page">
      <div class="equipment-hero">
        <div class="photo-ref">{machine_icon(e)}</div>
        <div><h1>{e['codigo']} · {e['tipo_equipo']}</h1><p>{e['marca']} {e['modelo']} · Año {e['ano']}</p>{badge(e['estado'])}</div>
      </div>
      <section class="grid-2">
        <div class="card"><h3>Ficha técnica</h3><table><tbody>
          <tr><td>Código</td><td>{e['codigo']}</td></tr><tr><td>Tipo</td><td>{e['tipo_equipo']}</td></tr>
          <tr><td>Familia</td><td>{e['familia']}</td></tr><tr><td>Marca / Modelo</td><td>{e['marca']} {e['modelo']}</td></tr>
          <tr><td>Ubicación</td><td>{e['ubicacion']}</td></tr><tr><td>Responsable</td><td>{e['responsable']}</td></tr>
          <tr><td>Lectura actual</td><td>{e['lectura_actual']} {e['unidad']}</td></tr><tr><td>Próxima PM</td><td>{e['proxima_pm']}</td></tr>
        </tbody></table></div>
        <div class="card"><h3>Acciones rápidas</h3>
          <p><a class="btn" href="/lecturas?codigo={e['codigo']}">Agregar lectura</a></p>
          <p><a class="btn" href="/mantenciones?codigo={e['codigo']}">Agregar mantención</a></p>
          <p><a class="btn" href="/ot?codigo={e['codigo']}">Crear OT</a></p>
          <p><a class="btn" href="/historial?codigo={e['codigo']}">Ver historial</a></p>
        </div>
      </section>
      <section class="card"><h3>Historial técnico del equipo</h3><table><thead><tr><th>Fecha</th><th>Origen</th><th>Detalle</th><th>Lectura</th><th>Estado</th></tr></thead><tbody>{rows_hist}</tbody></table></section>
    </main>
    """
    return page(f"Ficha {codigo}", body)

def historial_data(codigo):
    out = []
    codigo = codigo.strip().upper()
    try:
        if table_exists("lecturas"):
            for r in q("SELECT * FROM lecturas WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 200", {"c": codigo}):
                out.append({"fecha": safe(r.get("fecha")), "origen": "Lectura", "detalle": norm_ubic(r.get("obra_ubicacion")), "lectura": safe(r.get("horometro") or r.get("kilometraje")), "estado": ""})
    except Exception: pass
    try:
        if table_exists("mantenciones"):
            for r in q("SELECT * FROM mantenciones WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 200", {"c": codigo}):
                out.append({"fecha": safe(r.get("fecha")), "origen": "Mantención", "detalle": safe(r.get("tipo_mantencion") or r.get("espm")), "lectura": safe(r.get("lectura")), "estado": safe(r.get("estado"))})
    except Exception: pass
    try:
        if table_exists("compras"):
            for r in q("SELECT * FROM compras WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 200", {"c": codigo}):
                out.append({"fecha": safe(r.get("fecha")), "origen": "Compra", "detalle": f"{safe(r.get('oc'))} {safe(r.get('descripcion'))}", "lectura": safe(r.get("costo_pm_clp")), "estado": safe(r.get("estado_oc"))})
    except Exception: pass
    try:
        if table_exists("bodega"):
            for r in q("SELECT * FROM bodega WHERE UPPER(codigo)=:c OR UPPER(equipo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 200", {"c": codigo}):
                out.append({"fecha": safe(r.get("fecha")), "origen": "Bodega", "detalle": safe(r.get("comentario") or r.get("envio")), "lectura": safe(r.get("folio")), "estado": safe(r.get("destino"))})
    except Exception: pass
    return sorted(out, key=lambda x: str(x.get("fecha") or ""), reverse=True)

@app.route("/historial")
@login_required
def historial():
    codigo = request.args.get("codigo","").strip()
    select = f"<form class='search-card' action='/historial'><input name='codigo' list='equiposList' placeholder='Buscar equipo...' value='{codigo}'><button>Buscar</button>{equipo_datalist()}</form>"
    rows = ""
    if codigo:
        for h in historial_data(codigo):
            rows += f"<tr><td>{h['fecha']}</td><td>{h['origen']}</td><td>{h['detalle']}</td><td>{h['lectura']}</td><td>{h['estado']}</td></tr>"
    body = f"<main class='data-page'><h2>Historial de Equipo</h2>{select}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Origen</th><th>Detalle</th><th>Lectura/Costo/Folio</th><th>Estado/Destino</th></tr></thead><tbody>{rows}</tbody></table></div></main>"
    return page("Historial", body)

@app.route("/planificacion")
@login_required
def planificacion():
    data = q("SELECT * FROM plan_mantenciones LIMIT 1000") if table_exists("plan_mantenciones") else []
    lanes = ""
    for r in data:
        codigo = safe(r.get("codigo"))
        dias = num(r.get("dias_estimados"))
        width = max(8, min(100, 100 - dias if dias < 100 else 20))
        est = safe(r.get("estado_operativo") or r.get("estado") or r.get("prioridad"))
        lanes += f"""
        <a class="gantt-row" href="/equipo/{codigo}">
          <div class="gantt-code">{codigo}</div>
          <div class="gantt-meta">{safe(r.get('tipo_equipo'))} · {safe(r.get('familia'))}</div>
          <div class="gantt-track"><span style="width:{width}%"></span></div>
          <div class="gantt-date">{safe(r.get('fecha_estimada'))}</div>
          <div>{badge(est)}</div>
        </a>
        """
    body = f"<main class='data-page'><div class='data-head'><h2>Planificación PM tipo Gantt</h2><a class='btn' href='/proyeccion'>Ver tabla</a></div><p class='hint'>Cada carta es clickeable y abre la ficha del equipo.</p><section class='gantt'>{lanes}</section></main>"
    return page("Planificación", body)

# CRUD OPERATIVO
@app.route("/lecturas", methods=["GET","POST"])
@login_required
def lecturas():
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["fecha","codigo","horometro","kilometraje","obra_ubicacion","responsable","observacion"]}
        data["obra_ubicacion"] = norm_ubic(data.get("obra_ubicacion"))
        q("""INSERT INTO lecturas (fecha,codigo,horometro,kilometraje,obra_ubicacion,responsable,observacion)
             VALUES (:fecha,:codigo,:horometro,:kilometraje,:obra_ubicacion,:responsable,:observacion)""", data, fetch=False)
        return redirect(url_for("lecturas"))
    codigo = request.args.get("codigo","")
    data = q("SELECT * FROM lecturas ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("lecturas") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'><b>{safe(r.get('codigo'))}</b></a></td><td>{safe(r.get('horometro'))}</td><td>{safe(r.get('kilometraje'))}</td><td>{norm_ubic(r.get('obra_ubicacion'))}</td><td>{safe(r.get('responsable'))}</td><td>{safe(r.get('observacion'))}</td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input name='codigo' list='equiposList' placeholder='Código' value='{codigo}'>{equipo_datalist()}<input type='date' name='fecha'><input type='number' name='horometro' placeholder='Horómetro'><input type='number' name='kilometraje' placeholder='Kilometraje'><input name='obra_ubicacion' placeholder='Ubicación'><input name='responsable' placeholder='Responsable'><input name='observacion' placeholder='Observación'><button>Guardar lectura</button></form>"
    return page("Lecturas", f"<main class='data-page'><h2>Lecturas</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Horómetro</th><th>Kilometraje</th><th>Ubicación</th><th>Responsable</th><th>Obs</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/mantenciones", methods=["GET","POST"])
@login_required
def mantenciones():
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["fecha","codigo","tipo_mantencion","lectura","espm","folio","lugar","proveedor","costo_mantencion_clp","estado"]}
        data["lugar"] = norm_ubic(data.get("lugar"))
        q("""INSERT INTO mantenciones (fecha,codigo,tipo_mantencion,lectura,espm,folio,lugar,proveedor,costo_mantencion_clp,estado)
             VALUES (:fecha,:codigo,:tipo_mantencion,:lectura,:espm,:folio,:lugar,:proveedor,:costo_mantencion_clp,:estado)""", data, fetch=False)
        q("""INSERT INTO ot (fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo)
             VALUES (:fecha,:folio,:codigo,:tipo_mantencion,:lectura,:espm,:proveedor,:estado,:costo_mantencion_clp)""", data, fetch=False)
        return redirect(url_for("mantenciones"))
    codigo = request.args.get("codigo","")
    data = q("SELECT * FROM mantenciones ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("mantenciones") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'><b>{safe(r.get('codigo'))}</b></a></td><td>{safe(r.get('tipo_mantencion'))}</td><td>{safe(r.get('lectura'))}</td><td>{safe(r.get('folio'))}</td><td>{safe(r.get('proveedor'))}</td><td>{safe(r.get('costo_mantencion_clp'))}</td><td>{badge(r.get('estado'))}</td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input name='codigo' list='equiposList' value='{codigo}' placeholder='Código'>{equipo_datalist()}<input type='date' name='fecha'><input name='tipo_mantencion' placeholder='Tipo mantención'><input type='number' name='lectura' placeholder='Lectura'><input name='espm' placeholder='Descripción/ESPM'><input name='folio' placeholder='Folio/OT'><input name='lugar' placeholder='Lugar'><input name='proveedor' placeholder='Proveedor'><input name='costo_mantencion_clp' placeholder='Costo'><select name='estado'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><button>Guardar mantención y generar OT</button></form>"
    return page("Mantenciones", f"<main class='data-page'><h2>Mantenciones</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Tipo</th><th>Lectura</th><th>Folio/OT</th><th>Proveedor</th><th>Costo</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/ot", methods=["GET","POST"])
@login_required
def ot():
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["fecha","ot","codigo","tipo","lectura","descripcion","responsable","estado","costo"]}
        q("""INSERT INTO ot (fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo)
             VALUES (:fecha,:ot,:codigo,:tipo,:lectura,:descripcion,:responsable,:estado,:costo)""", data, fetch=False)
        return redirect(url_for("ot"))
    data = q("SELECT * FROM ot ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("ot") else []
    if not data and table_exists("mantenciones"):
        data = [{"fecha":r.get("fecha"),"ot":r.get("folio"),"codigo":r.get("codigo"),"tipo":r.get("tipo_mantencion"),"lectura":r.get("lectura"),"descripcion":r.get("espm"),"responsable":r.get("proveedor"),"estado":r.get("estado"),"costo":r.get("costo_mantencion_clp")} for r in q("SELECT * FROM mantenciones ORDER BY fecha DESC NULLS LAST LIMIT 1000")]
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('ot'))}</b></td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td><td>{safe(r.get('tipo'))}</td><td>{safe(r.get('descripcion'))}</td><td>{safe(r.get('responsable'))}</td><td>{badge(r.get('estado'))}</td><td>{safe(r.get('costo'))}</td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input type='date' name='fecha'><input name='ot' placeholder='OT/Folio'><input name='codigo' list='equiposList' placeholder='Código'>{equipo_datalist()}<input name='tipo' placeholder='Tipo'><input name='lectura' placeholder='Lectura'><input name='descripcion' placeholder='Descripción'><input name='responsable' placeholder='Responsable'><select name='estado'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><input name='costo' placeholder='Costo'><button>Guardar OT</button></form>"
    return page("OT", f"<main class='data-page'><h2>Órdenes de Trabajo</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>OT</th><th>Código</th><th>Tipo</th><th>Descripción</th><th>Responsable</th><th>Estado</th><th>Costo</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/compras", methods=["GET","POST"])
@login_required
def compras():
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["fecha","oc","codigo","descripcion","proveedor","costo_pm_clp","regla","estado_oc"]}
        q("""INSERT INTO compras (fecha,oc,codigo,descripcion,proveedor,costo_pm_clp,regla,estado_oc)
             VALUES (:fecha,:oc,:codigo,:descripcion,:proveedor,:costo_pm_clp,:regla,:estado_oc)""", data, fetch=False)
        return redirect(url_for("compras"))
    data = q("SELECT * FROM compras ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("compras") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('oc'))}</b></td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td><td>{safe(r.get('descripcion'))}</td><td>{safe(r.get('proveedor'))}</td><td>{safe(r.get('costo_pm_clp'))}</td><td>{badge(r.get('estado_oc'))}</td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input type='date' name='fecha'><input name='oc' placeholder='OC'><input name='codigo' list='equiposList' placeholder='Código'>{equipo_datalist()}<input name='descripcion' placeholder='Descripción'><input name='proveedor' placeholder='Proveedor'><input name='costo_pm_clp' placeholder='Monto'><input name='regla' placeholder='Regla'><select name='estado_oc'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><button>Guardar compra</button></form>"
    return page("Compras", f"<main class='data-page'><h2>Compras PM</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>OC</th><th>Código</th><th>Descripción</th><th>Proveedor</th><th>Monto</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/bodega", methods=["GET","POST"])
@login_required
def bodega():
    if request.method == "POST":
        data = {k: request.form.get(k) for k in ["folio","fecha","equipo","envio","persona_que_retiro","destino","comentario","codigo"]}
        data["destino"] = norm_ubic(data.get("destino"))
        q("""INSERT INTO bodega (folio,fecha,equipo,envio,persona_que_retiro,destino,comentario,codigo)
             VALUES (:folio,:fecha,:equipo,:envio,:persona_que_retiro,:destino,:comentario,:codigo)""", data, fetch=False)
        return redirect(url_for("bodega"))
    data = q("SELECT * FROM bodega ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("bodega") else []
    rows = "".join(f"<tr><td><b>{safe(r.get('folio'))}</b></td><td>{safe(r.get('fecha'))}</td><td>{safe(r.get('equipo'))}</td><td>{safe(r.get('envio'))}</td><td>{safe(r.get('persona_que_retiro'))}</td><td>{safe(r.get('destino'))}</td><td>{safe(r.get('comentario'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input name='folio' placeholder='Folio'><input type='date' name='fecha'><input name='equipo' placeholder='Equipo'><input name='envio' placeholder='Envío'><input name='persona_que_retiro' placeholder='Persona que retiró'><input name='destino' placeholder='Destino'><input name='comentario' placeholder='Comentario'><input name='codigo' list='equiposList' placeholder='Código'>{equipo_datalist()}<button>Guardar bodega</button></form>"
    return page("Bodega", f"<main class='data-page'><h2>Bodega</h2>{form}<div class='table-card'><table><thead><tr><th>Folio</th><th>Fecha</th><th>Equipo</th><th>Envío</th><th>Retira</th><th>Destino</th><th>Comentario</th><th>Código</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/proyeccion")
@login_required
def proyeccion():
    return redirect(url_for("planificacion"))

@app.route("/api/status")
def api_status():
    try:
        ensure_schema()
        return jsonify({"status": "ok", "database": "postgresql"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

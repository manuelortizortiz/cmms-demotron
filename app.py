
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


def clean_text(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ["none", "nan", "nat"]:
        return None
    return s

def clean_upper(v):
    s = clean_text(v)
    return s.upper() if s else None

def clean_date(v):
    s = clean_text(v)
    if not s:
        return None
    return s

def clean_number(v):
    s = clean_text(v)
    if not s:
        return None
    try:
        s = s.replace("$", "").replace(" ", "").replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return None

def clean_money_text(v):
    s = clean_text(v)
    if not s:
        return None
    return s.replace("$", "").strip()


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
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">{CSS}</head>
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

def machine_image(e):
    txt = (str(e.get("tipo_equipo","")) + " " + str(e.get("familia","")) + " " + str(e.get("marca","")) + " " + str(e.get("modelo",""))).lower()
    if "tolva" in txt or ("camion" in txt and "pluma" not in txt and "aljibe" not in txt and "liviano" not in txt):
        return "/static/img/equipos/camion_man_tolva.png"
    if "tracto" in txt:
        return "/static/img/equipos/tractocamion.png"
    if "excav" in txt:
        return "/static/img/equipos/excavadora.png"
    if "cargador" in txt:
        return "/static/img/equipos/cargador_frontal.png"
    if "planta" in txt or "aridos" in txt or "áridos" in txt:
        return "/static/img/equipos/planta_aridos.png"
    if "maxus" in txt or "camioneta" in txt:
        return "/static/img/equipos/maxus_t60.png"
    if "pluma" in txt:
        return "/static/img/equipos/camion_pluma.png"
    if "aljibe" in txt:
        return "/static/img/equipos/camion_aljibe.png"
    if "liviano" in txt:
        return "/static/img/equipos/camion_liviano.png"
    if "gravilladora" in txt:
        return "/static/img/equipos/gravilladora.png"
    if "barredora" in txt:
        return "/static/img/equipos/barredora.png"
    if "rodillo" in txt and "neumatic" in txt:
        return "/static/img/equipos/rodillo_neumaticos.png"
    if "rodillo" in txt:
        return "/static/img/equipos/rodillo_compactador.png"
    if "motoniveladora" in txt or "moto" in txt:
        return "/static/img/equipos/motoniveladora.png"
    if "retro" in txt:
        return "/static/img/equipos/retroexcavadora.png"
    if "furgon" in txt or "furgón" in txt or "peugeot" in txt or "partner" in txt:
        return "/static/img/equipos/furgon_partner.png"
    return "/static/img/equipos/excavadora.png"

def clp(v):
    return "$ " + format(int(round(num(v))), ",").replace(",", ".")

def dashboard_excel_metrics():
    """Lee valores desde la hoja Dashboard importada, si existe.
    Si no calza, el dashboard usa cálculos desde maestro_equipos.
    """
    metrics = {}
    if not table_exists("dashboard_excel"):
        return metrics
    try:
        rows_dash = q("SELECT * FROM dashboard_excel LIMIT 80")
        wanted = {
            "total equipos": "total_equipos",
            "operativos": "operativos",
            "fuera de servicio": "fuera_servicio",
            "atrasados": "atrasados",
            "próximas": "proximas",
            "proximas": "proximas",
            "por recibir": "por_recibir",
            "en proceso": "en_proceso",
            "al día": "al_dia",
            "al dia": "al_dia",
            "en taller": "en_taller",
            "pendiente de reporte": "pendiente_reporte",
            "costo total pm": "costo_total_pm",
            "% disponibilidad real": "disponibilidad_real",
            "% cumplimiento real": "cumplimiento_real",
            "% controlado": "controlado",
            "sin historial pm": "sin_historial_pm",
            "backlog compra": "backlog_compra",
            "tiempo de compra": "tiempo_compra",
            "actualizado": "actualizado"
        }
        prev_label = None
        for r in rows_dash:
            vals = [safe(v) for v in r.values()]
            for v in vals:
                sv = str(v).strip()
                if not sv:
                    continue
                low = sv.lower()
                # detect labels
                for label, key in wanted.items():
                    if label == low:
                        prev_label = key
                        break
                else:
                    # if previous cell/row was a label, next numeric/date value is the metric
                    if prev_label and sv not in wanted:
                        metrics[prev_label] = sv
                        prev_label = None
    except Exception:
        pass
    return metrics


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
    metrics = dashboard_excel_metrics()

    total = len(equipos)
    # Estado CMMS desde maestro_equipos[columna estado]
    atrasados = sum(1 for e in equipos if "ATRAS" in str(e["estado"]).upper())
    aldia = sum(1 for e in equipos if "AL D" in str(e["estado"]).upper())
    en_taller = sum(1 for e in equipos if "TALLER" in str(e["estado"]).upper())
    fuera = sum(1 for e in equipos if "FUERA" in str(e["estado"]).upper())
    por_recibir = sum(1 for e in equipos if "RECIBIR" in str(e["estado"]).upper())
    en_proceso = sum(1 for e in equipos if "PROCESO" in str(e["estado"]).upper())
    proximas = sum(1 for e in equipos if "PROX" in str(e["estado"]).upper())

    # Métricas del Dashboard Excel cuando existan, con fallback a cálculo real
    total_show = metrics.get("total_equipos", total)
    operativos_show = metrics.get("operativos", max(total - fuera, 0))
    fuera_show = metrics.get("fuera_servicio", fuera)
    atrasados_show = metrics.get("atrasados", atrasados)
    proximas_show = metrics.get("proximas", proximas)
    por_recibir_show = metrics.get("por_recibir", por_recibir)
    en_proceso_show = metrics.get("en_proceso", en_proceso)
    aldia_show = metrics.get("al_dia", aldia)
    taller_show = metrics.get("en_taller", en_taller)
    pendiente_show = metrics.get("pendiente_reporte", "")
    costo_pm_show = metrics.get("costo_total_pm", "")

    mantenciones = q("SELECT COUNT(*) AS n FROM mantenciones")[0]["n"] if table_exists("mantenciones") else 0
    lecturas = q("SELECT COUNT(*) AS n FROM lecturas")[0]["n"] if table_exists("lecturas") else 0
    compras_rows = q("SELECT * FROM compras LIMIT 5000") if table_exists("compras") else []
    compras_total = sum(num(r.get("costo_pm_clp") or r.get("monto") or r.get("total")) for r in compras_rows)

    ubic, tipo, estado_counts = {}, {}, {}
    for e in equipos:
        ubic[e["ubicacion"] or "Sin ubicación"] = ubic.get(e["ubicacion"] or "Sin ubicación",0)+1
        tipo[e["tipo_equipo"] or "Sin tipo"] = tipo.get(e["tipo_equipo"] or "Sin tipo",0)+1
        estado_counts[e["estado"] or "Sin estado"] = estado_counts.get(e["estado"] or "Sin estado",0)+1

    ubic_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k,v in sorted(ubic.items(), key=lambda x:x[1], reverse=True)[:10])
    tipo_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k,v in sorted(tipo.items(), key=lambda x:x[1], reverse=True)[:10])
    estado_rows = "".join(f"<tr><td>{badge(k)}</td><td>{v}</td></tr>" for k,v in sorted(estado_counts.items(), key=lambda x:x[1], reverse=True))

    crit_list = [e for e in equipos if str(e["estado"]).upper() not in ["AL DÍA","AL DIA"]][:10]
    crit = "".join(f"<tr><td><a href='/equipo/{e['codigo']}'><b>{e['codigo']}</b></a></td><td>{e['tipo_equipo']}</td><td>{e['ubicacion']}</td><td>{e['lectura_actual']} {e['unidad']}</td><td>{badge(e['estado'])}</td></tr>" for e in crit_list)
    if not crit:
        crit = "<tr><td colspan='5'>Sin equipos críticos.</td></tr>"

    cards = "".join(
        f"<a class='machine-card' href='/equipo/{e['codigo']}'><h4>{e['codigo']}</h4>"
        f"<div class='machine-img'><img src='{machine_image(e)}' alt='{e['codigo']}'></div>"
        f"<p>{e['marca']} {e['modelo']}</p><p>{e['ubicacion']}</p><p>{badge(e['estado'])}</p></a>"
        for e in equipos[:32]
    )

    # data para gráficos simples sin librerías
    ubic_bars = "".join(
        f"<div class='bar-row'><span>{k}</span><div><b style='width:{min(100, v*100/max(ubic.values() or [1]))}%'></b></div><em>{v}</em></div>"
        for k,v in sorted(ubic.items(), key=lambda x:x[1], reverse=True)[:10]
    )
    estado_bars = "".join(
        f"<div class='bar-row'><span>{k}</span><div><b style='width:{min(100, v*100/max(estado_counts.values() or [1]))}%'></b></div><em>{v}</em></div>"
        for k,v in sorted(estado_counts.items(), key=lambda x:x[1], reverse=True)
    )

    body = f"""
    <main class="page">
      <section class="hero">
        <div><h1>Dashboard CMMS DEMOTRON</h1><p>Datos desde Maestro_Equipos, Dashboard Excel, compras, lecturas y mantenciones.</p></div>
        <form action="/ficha" method="get" class="search-card">
          <input name="codigo" list="equiposList" placeholder="Buscar equipo, ej: MD-100, CD-102...">
          <button>Ver ficha</button>{equipo_datalist()}
        </form>
      </section>

      <section class="grid-kpi">
        <div class="card kpi blueb"><small>Total equipos</small><b>{total_show}</b></div>
        <div class="card kpi greenb"><small>Operativos</small><b>{operativos_show}</b></div>
        <div class="card kpi offb"><small>Fuera servicio</small><b>{fuera_show}</b></div>
        <div class="card kpi redb"><small>Atrasados</small><b>{atrasados_show}</b></div>
        <div class="card kpi yellowb"><small>Próximas</small><b>{proximas_show}</b></div>
        <div class="card kpi purpleb"><small>Costo total PM</small><b>{clp(costo_pm_show or compras_total)}</b></div>
      </section>

      <section class="grid-kpi">
        <div class="card kpi blueb"><small>Por recibir</small><b>{por_recibir_show}</b></div>
        <div class="card kpi yellowb"><small>En proceso</small><b>{en_proceso_show}</b></div>
        <div class="card kpi greenb"><small>Al día</small><b>{aldia_show}</b></div>
        <div class="card kpi offb"><small>En taller</small><b>{taller_show}</b></div>
        <div class="card kpi tealb"><small>Pendiente reporte</small><b>{pendiente_show}</b></div>
        <div class="card kpi blueb"><small>Lecturas</small><b>{lecturas}</b></div>
      </section>

      <section class="middle">
        <div class="card"><h3>Equipos críticos (10)</h3><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura</th><th>Estado</th></tr></thead><tbody>{crit}</tbody></table></div>
        <div class="card"><h3>Gráfico: equipos por ubicación</h3><div class="bar-chart">{ubic_bars}</div></div>
      </section>

      <section class="middle">
        <div class="card"><h3>Gráfico: estado de equipos</h3><div class="bar-chart">{estado_bars}</div></div>
        <div class="card"><h3>Resumen por estado</h3><table><thead><tr><th>Estado</th><th>Total</th></tr></thead><tbody>{estado_rows}</tbody></table></div>
      </section>

      <section class="middle">
        <div class="card"><h3>Equipos por tipo</h3><table><thead><tr><th>Tipo</th><th>Total</th></tr></thead><tbody>{tipo_rows}</tbody></table></div>
        <div class="card"><h3>Indicadores operacionales</h3><table><tbody><tr><td>Mantenciones</td><td>{mantenciones}</td></tr><tr><td>Compras PM calculadas</td><td>{clp(compras_total)}</td></tr></tbody></table></div>
      </section>

      <section class="card"><h3>Vista rápida de equipos</h3><div class="cards-row">{cards}</div></section>
    </main>
    """
    return page("Dashboard ERP", body)

@app.route("/equipos", methods=["GET","POST"])
@login_required
def equipos():
    ensure_schema()
    ensure_data()

    if request.method == "POST":
        data = {k: request.form.get(k) for k in [
            "codigo","tipo_equipo","familia","marca","modelo","ano",
            "ubicacion","responsable","lectura_actual","unidad","proxima_pm","estado"
        ]}

        data["codigo"] = (data.get("codigo") or "").strip().upper()
        data["ubicacion"] = norm_ubic(data.get("ubicacion"))

        if not data["codigo"]:
            return page("Error Equipo", "<main class='data-page'><div class='card'><h2>Error</h2><p>El código del equipo es obligatorio.</p><a class='btn' href='/equipos'>Volver</a></div></main>")

        # FIX: no usar ON CONFLICT porque al importar Excel con pandas/to_sql replace
        # se pierde la primary key/unique constraint de codigo.
        # Método seguro: borrar código existente e insertar de nuevo.
        try:
            q("DELETE FROM maestro_equipos WHERE UPPER(codigo)=UPPER(:codigo)", {"codigo": data["codigo"]}, fetch=False)
        except Exception:
            pass

        try:
            q("""
            INSERT INTO maestro_equipos (
                codigo,tipo_equipo,familia,marca,modelo,ano,ubicacion,
                responsable,lectura_actual,unidad,proxima_pm,estado
            )
            VALUES (
                :codigo,:tipo_equipo,:familia,:marca,:modelo,:ano,:ubicacion,
                :responsable,:lectura_actual,:unidad,:proxima_pm,:estado
            )
            """, data, fetch=False)
        except Exception as e:
            return page("Error guardando equipo", f"<main class='data-page'><div class='card'><h2>No se pudo guardar el equipo</h2><p>{safe(e)}</p><a class='btn' href='/equipos'>Volver</a></div></main>")

        return redirect(url_for("equipos"))

    equipos_data = get_equipos()
    rows = "".join(
        f"<tr>"
        f"<td><a href='/equipo/{e['codigo']}'><b>{e['codigo']}</b></a></td>"
        f"<td>{e['tipo_equipo']}</td>"
        f"<td>{e['familia']}</td>"
        f"<td>{e['marca']}</td>"
        f"<td>{e['modelo']}</td>"
        f"<td>{e['ano']}</td>"
        f"<td>{e['ubicacion']}</td>"
        f"<td>{e['responsable']}</td>"
        f"<td>{e['lectura_actual']}</td>"
        f"<td>{e['unidad']}</td>"
        f"<td>{e['proxima_pm']}</td>"
        f"<td>{badge(e['estado'])}</td>"
        f"</tr>"
        for e in equipos_data
    )

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

    body = (
        f"<main class='data-page'>"
        f"<div class='data-head'><h2>Equipos ({len(equipos_data)})</h2>"
        f"<a class='btn' href='/admin/importar-cmms'>Importar CMMS</a></div>"
        f"<p class='hint'>Al escribir un código precargado, se completan tipo, familia, marca, modelo, año y estado automáticamente.</p>"
        f"{form}"
        f"<div class='table-card'><table><thead><tr>"
        f"<th>Código</th><th>Tipo</th><th>Familia</th><th>Marca</th><th>Modelo</th><th>Año</th>"
        f"<th>Ubicación</th><th>Responsable</th><th>Lectura</th><th>Unidad</th><th>Próx PM</th><th>Estado</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div></main>"
    )

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
        if dias <= 0:
            width = 95
        elif dias <= 7:
            width = 90
        elif dias <= 30:
            width = 70
        elif dias <= 60:
            width = 45
        else:
            width = 25
        est = safe(r.get("estado_operativo") or r.get("estado") or r.get("prioridad"))
        lanes += f"""
        <a class="gantt-row" href="/equipo/{codigo}">
          <div class="gantt-code">{codigo}</div>
          <div class="gantt-meta">{safe(r.get('tipo_equipo'))}<br><small>{safe(r.get('familia'))}</small></div>
          <div class="gantt-info">
            <strong>Lectura actual:</strong> {safe(r.get('lectura_actual'))}<br>
            <strong>Próxima:</strong> {safe(r.get('proxima_lectura_objetivo'))}<br>
            <strong>Acción:</strong> {safe(r.get('accion_sugerida'))}
          </div>
          <div class="gantt-track"><span style="width:{width}%"></span></div>
          <div class="gantt-date">{safe(r.get('fecha_estimada'))}<br><small>{safe(r.get('dias_estimados'))} días</small></div>
          <div>{badge(est)}</div>
        </a>
        """
    if not lanes:
        lanes = "<div class='card'>No hay datos de planificación. Reimporta el CMMS.</div>"
    body = f"""
    <main class='data-page'>
      <div class='data-head'><h2>Planificación PM tipo Gantt</h2><a class='btn' href='/proyeccion'>Ver tabla de proyección</a></div>
      <p class='hint'>Carta clickeable por equipo. Basado en hoja Plan_Mantenciones / próximas mantenciones del Excel.</p>
      <section class='gantt'>{lanes}</section>
    </main>
    """
    return page("Planificación", body)

@app.route("/proyeccion")
@login_required
def proyeccion():
    data = q("SELECT * FROM plan_mantenciones LIMIT 1000") if table_exists("plan_mantenciones") else []
    rows = ""
    for r in data:
        rows += f"""
        <tr>
          <td><a href="/equipo/{safe(r.get('codigo'))}"><b>{safe(r.get('codigo'))}</b></a></td>
          <td>{safe(r.get('tipo_equipo'))}</td>
          <td>{safe(r.get('familia'))}</td>
          <td>{safe(r.get('control'))}</td>
          <td>{safe(r.get('lectura_actual'))}</td>
          <td>{safe(r.get('proxima_lectura_objetivo'))}</td>
          <td>{safe(r.get('promedio_diario'))}</td>
          <td>{safe(r.get('dias_estimados'))}</td>
          <td>{safe(r.get('fecha_estimada'))}</td>
          <td>{badge(r.get('estado_operativo'))}</td>
          <td>{safe(r.get('prioridad'))}</td>
          <td>{safe(r.get('accion_sugerida'))}</td>
        </tr>
        """
    body = f"""
    <main class='data-page'>
      <div class='data-head'><h2>Proyección de Mantenciones</h2><a class='btn' href='/planificacion'>Ver Gantt</a></div>
      <div class='table-card'><table>
        <thead><tr><th>Código</th><th>Tipo</th><th>Familia</th><th>Control</th><th>Lectura</th><th>Próxima</th><th>Promedio</th><th>Días</th><th>Fecha</th><th>Estado</th><th>Prioridad</th><th>Acción</th></tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    </main>
    """
    return page("Proyección", body)

# CRUD OPERATIVO
@app.route("/lecturas", methods=["GET","POST"])
@login_required
def lecturas():
    ensure_schema()
    ensure_data()

    if request.method == "POST":
        data = {
            "fecha": clean_date(request.form.get("fecha")),
            "codigo": clean_upper(request.form.get("codigo")),
            "horometro": clean_number(request.form.get("horometro")),
            "kilometraje": clean_number(request.form.get("kilometraje")),
            "obra_ubicacion": norm_ubic(request.form.get("obra_ubicacion")),
            "responsable": clean_text(request.form.get("responsable")),
            "observacion": clean_text(request.form.get("observacion")),
        }

        if not data["codigo"]:
            return page("Error lectura", "<main class='data-page'><div class='card'><h2>Error</h2><p>Debes ingresar código de equipo.</p><a class='btn' href='/lecturas'>Volver</a></div></main>")

        try:
            q("""INSERT INTO lecturas (fecha,codigo,horometro,kilometraje,obra_ubicacion,responsable,observacion)
                 VALUES (:fecha,:codigo,:horometro,:kilometraje,:obra_ubicacion,:responsable,:observacion)""", data, fetch=False)
        except Exception as e:
            return page("Error guardando lectura", f"<main class='data-page'><div class='card'><h2>No se pudo guardar la lectura</h2><p>{safe(e)}</p><a class='btn' href='/lecturas'>Volver</a></div></main>")

        # Actualiza lectura actual del equipo si existe
        try:
            valor = data["horometro"] if data["horometro"] is not None else data["kilometraje"]
            unidad = "HORAS" if data["horometro"] is not None else "KM"
            if valor is not None:
                q("""UPDATE maestro_equipos 
                     SET lectura_actual=:valor, unidad=:unidad, ubicacion=COALESCE(:ubicacion, ubicacion)
                     WHERE UPPER(codigo)=UPPER(:codigo)""",
                  {"valor": str(valor), "unidad": unidad, "ubicacion": data["obra_ubicacion"], "codigo": data["codigo"]}, fetch=False)
        except Exception:
            pass

        return redirect(url_for("lecturas"))

    codigo = request.args.get("codigo","")
    data = q("SELECT * FROM lecturas ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("lecturas") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'><b>{safe(r.get('codigo'))}</b></a></td><td>{safe(r.get('horometro'))}</td><td>{safe(r.get('kilometraje'))}</td><td>{norm_ubic(r.get('obra_ubicacion'))}</td><td>{safe(r.get('responsable'))}</td><td>{safe(r.get('observacion'))}</td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input name='codigo' list='equiposList' placeholder='Código' value='{codigo}'>{equipo_datalist()}<input type='date' name='fecha'><input type='number' step='any' name='horometro' placeholder='Horómetro'><input type='number' step='any' name='kilometraje' placeholder='Kilometraje'><input name='obra_ubicacion' placeholder='Ubicación'><input name='responsable' placeholder='Responsable'><input name='observacion' placeholder='Observación'><button>Guardar lectura</button></form>"
    return page("Lecturas", f"<main class='data-page'><h2>Lecturas</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Horómetro</th><th>Kilometraje</th><th>Ubicación</th><th>Responsable</th><th>Obs</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/mantenciones", methods=["GET","POST"])
@login_required
def mantenciones():
    ensure_schema()
    ensure_data()

    if request.method == "POST":
        data = {
            "fecha": clean_date(request.form.get("fecha")),
            "codigo": clean_upper(request.form.get("codigo")),
            "tipo_mantencion": clean_text(request.form.get("tipo_mantencion")),
            "lectura": clean_number(request.form.get("lectura")),
            "espm": clean_text(request.form.get("espm")),
            "folio": clean_text(request.form.get("folio")),
            "lugar": norm_ubic(request.form.get("lugar")),
            "proveedor": clean_text(request.form.get("proveedor")),
            "costo_mantencion_clp": clean_money_text(request.form.get("costo_mantencion_clp")),
            "estado": clean_text(request.form.get("estado")),
        }

        if not data["codigo"]:
            return page("Error mantención", "<main class='data-page'><div class='card'><h2>Error</h2><p>Debes ingresar código de equipo.</p><a class='btn' href='/mantenciones'>Volver</a></div></main>")

        try:
            q("""INSERT INTO mantenciones (fecha,codigo,tipo_mantencion,lectura,espm,folio,lugar,proveedor,costo_mantencion_clp,estado)
                 VALUES (:fecha,:codigo,:tipo_mantencion,:lectura,:espm,:folio,:lugar,:proveedor,:costo_mantencion_clp,:estado)""", data, fetch=False)
        except Exception as e:
            return page("Error guardando mantención", f"<main class='data-page'><div class='card'><h2>No se pudo guardar la mantención</h2><p>{safe(e)}</p><a class='btn' href='/mantenciones'>Volver</a></div></main>")

        try:
            q("""INSERT INTO ot (fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo)
                 VALUES (:fecha,:folio,:codigo,:tipo_mantencion,:lectura,:espm,:proveedor,:estado,:costo_mantencion_clp)""", data, fetch=False)
        except Exception:
            pass

        return redirect(url_for("mantenciones"))

    codigo = request.args.get("codigo","")
    data = q("SELECT * FROM mantenciones ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("mantenciones") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'><b>{safe(r.get('codigo'))}</b></a></td><td>{safe(r.get('tipo_mantencion'))}</td><td>{safe(r.get('lectura'))}</td><td>{safe(r.get('folio'))}</td><td>{safe(r.get('proveedor'))}</td><td>{safe(r.get('costo_mantencion_clp'))}</td><td>{badge(r.get('estado'))}</td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input name='codigo' list='equiposList' value='{codigo}' placeholder='Código'>{equipo_datalist()}<input type='date' name='fecha'><input name='tipo_mantencion' placeholder='Tipo mantención'><input type='number' step='any' name='lectura' placeholder='Lectura'><input name='espm' placeholder='Descripción/ESPM'><input name='folio' placeholder='Folio/OT'><input name='lugar' placeholder='Lugar'><input name='proveedor' placeholder='Proveedor'><input name='costo_mantencion_clp' placeholder='Costo'><select name='estado'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><button>Guardar mantención y generar OT</button></form>"
    return page("Mantenciones", f"<main class='data-page'><h2>Mantenciones</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Tipo</th><th>Lectura</th><th>Folio/OT</th><th>Proveedor</th><th>Costo</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/ot", methods=["GET","POST"])
@login_required
def ot():
    ensure_schema()
    ensure_data()

    if request.method == "POST":
        data = {
            "fecha": clean_date(request.form.get("fecha")),
            "ot": clean_text(request.form.get("ot")),
            "codigo": clean_upper(request.form.get("codigo")),
            "tipo": clean_text(request.form.get("tipo")),
            "lectura": clean_text(request.form.get("lectura")),
            "descripcion": clean_text(request.form.get("descripcion")),
            "responsable": clean_text(request.form.get("responsable")),
            "estado": clean_text(request.form.get("estado")),
            "costo": clean_money_text(request.form.get("costo")),
        }

        if not data["codigo"]:
            return page("Error OT", "<main class='data-page'><div class='card'><h2>Error</h2><p>Debes ingresar código de equipo.</p><a class='btn' href='/ot'>Volver</a></div></main>")

        if not data["ot"]:
            data["ot"] = f"OT-WEB-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        try:
            q("""INSERT INTO ot (fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo)
                 VALUES (:fecha,:ot,:codigo,:tipo,:lectura,:descripcion,:responsable,:estado,:costo)""", data, fetch=False)
        except Exception as e:
            return page("Error guardando OT", f"<main class='data-page'><div class='card'><h2>No se pudo guardar la OT</h2><p>{safe(e)}</p><a class='btn' href='/ot'>Volver</a></div></main>")

        return redirect(url_for("ot"))

    data = q("SELECT * FROM ot ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("ot") else []
    if not data and table_exists("mantenciones"):
        data = [{"fecha":r.get("fecha"),"ot":r.get("folio"),"codigo":r.get("codigo"),"tipo":r.get("tipo_mantencion"),"lectura":r.get("lectura"),"descripcion":r.get("espm"),"responsable":r.get("proveedor"),"estado":r.get("estado"),"costo":r.get("costo_mantencion_clp")} for r in q("SELECT * FROM mantenciones ORDER BY fecha DESC NULLS LAST LIMIT 1000")]
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('ot'))}</b></td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td><td>{safe(r.get('tipo'))}</td><td>{safe(r.get('descripcion'))}</td><td>{safe(r.get('responsable'))}</td><td>{badge(r.get('estado'))}</td><td>{safe(r.get('costo'))}</td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input type='date' name='fecha'><input name='ot' placeholder='OT/Folio (opcional)'><input name='codigo' list='equiposList' placeholder='Código'>{equipo_datalist()}<input name='tipo' placeholder='Tipo'><input name='lectura' placeholder='Lectura'><input name='descripcion' placeholder='Descripción'><input name='responsable' placeholder='Responsable'><select name='estado'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><input name='costo' placeholder='Costo'><button>Guardar OT</button></form>"
    return page("OT", f"<main class='data-page'><h2>Órdenes de Trabajo</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>OT</th><th>Código</th><th>Tipo</th><th>Descripción</th><th>Responsable</th><th>Estado</th><th>Costo</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/compras", methods=["GET","POST"])
@login_required
def compras():
    ensure_schema()
    ensure_data()

    if request.method == "POST":
        data = {
            "fecha": clean_date(request.form.get("fecha")),
            "oc": clean_text(request.form.get("oc")),
            "codigo": clean_upper(request.form.get("codigo")),
            "descripcion": clean_text(request.form.get("descripcion")),
            "proveedor": clean_text(request.form.get("proveedor")),
            "costo_pm_clp": clean_money_text(request.form.get("costo_pm_clp")),
            "regla": clean_text(request.form.get("regla")),
            "estado_oc": clean_text(request.form.get("estado_oc")),
        }

        if not data["codigo"]:
            return page("Error compra", "<main class='data-page'><div class='card'><h2>Error</h2><p>Debes ingresar código de equipo.</p><a class='btn' href='/compras'>Volver</a></div></main>")

        try:
            q("""INSERT INTO compras (fecha,oc,codigo,descripcion,proveedor,costo_pm_clp,regla,estado_oc)
                 VALUES (:fecha,:oc,:codigo,:descripcion,:proveedor,:costo_pm_clp,:regla,:estado_oc)""", data, fetch=False)
        except Exception as e:
            return page("Error guardando compra", f"<main class='data-page'><div class='card'><h2>No se pudo guardar la compra</h2><p>{safe(e)}</p><a class='btn' href='/compras'>Volver</a></div></main>")

        return redirect(url_for("compras"))

    data = q("SELECT * FROM compras ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("compras") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><b>{safe(r.get('oc'))}</b></td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td><td>{safe(r.get('descripcion'))}</td><td>{safe(r.get('proveedor'))}</td><td>{clp(r.get('costo_pm_clp'))}</td><td>{badge(r.get('estado_oc'))}</td></tr>" for r in data)
    form = f"<form class='form-card' method='post'><input type='date' name='fecha'><input name='oc' placeholder='OC'><input name='codigo' list='equiposList' placeholder='Código'>{equipo_datalist()}<input name='descripcion' placeholder='Descripción'><input name='proveedor' placeholder='Proveedor'><input name='costo_pm_clp' placeholder='Monto'><input name='regla' placeholder='Regla'><select name='estado_oc'>{''.join(f'<option>{x}</option>' for x in ESTADOS)}</select><button>Guardar compra</button></form>"
    return page("Compras", f"<main class='data-page'><h2>Compras PM</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>OC</th><th>Código</th><th>Descripción</th><th>Proveedor</th><th>Monto</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>")

@app.route("/bodega", methods=["GET","POST"])
@login_required
def bodega():
    ensure_schema()
    ensure_data()

    if request.method == "POST":
        data = {
            "folio": clean_text(request.form.get("folio")),
            "fecha": clean_date(request.form.get("fecha")),
            "equipo": clean_text(request.form.get("equipo")),
            "envio": clean_text(request.form.get("envio")),
            "persona_que_retiro": clean_text(request.form.get("persona_que_retiro")),
            "destino": norm_ubic(request.form.get("destino")),
            "comentario": clean_text(request.form.get("comentario")),
            "codigo": clean_upper(request.form.get("codigo")),
        }

        if not data["codigo"] and not data["equipo"]:
            return page("Error bodega", "<main class='data-page'><div class='card'><h2>Error</h2><p>Debes ingresar código o equipo.</p><a class='btn' href='/bodega'>Volver</a></div></main>")

        try:
            q("""INSERT INTO bodega (folio,fecha,equipo,envio,persona_que_retiro,destino,comentario,codigo)
                 VALUES (:folio,:fecha,:equipo,:envio,:persona_que_retiro,:destino,:comentario,:codigo)""", data, fetch=False)
        except Exception as e:
            return page("Error guardando bodega", f"<main class='data-page'><div class='card'><h2>No se pudo guardar bodega</h2><p>{safe(e)}</p><a class='btn' href='/bodega'>Volver</a></div></main>")

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

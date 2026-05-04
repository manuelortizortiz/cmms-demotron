
import os
import re
import math
import unicodedata
from datetime import datetime, date, timedelta
from functools import wraps

import pandas as pd
from flask import Flask, request, redirect, url_for, session, render_template_string, jsonify, send_file
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError

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
TIPOS_PM = ["PM1", "PM2", "PM3", "PM4", "PM5", "CORRECTIVA"]
UNIDADES = ["HORAS", "KM"]
UBICACIONES = [
    "Palmucho", "Quirihue", "Curico", "Taller Central", "Villa Seca", "Cobquecura",
    "Pelluhue", "San Carlos", "San Nicolas", "Linares", "Talca", "Taller Externo"
]


# =========================
# UTILIDADES
# =========================

def dialect():
    return engine.dialect.name if engine is not None else ""


def pk_sql():
    if dialect() == "sqlite":
        return "INTEGER PRIMARY KEY AUTOINCREMENT"
    return "SERIAL PRIMARY KEY"


def norm_col(v):
    v = "" if v is None else str(v)
    v = v.strip().lower()
    v = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    v = re.sub(r"[^a-z0-9]+", "_", v)
    return re.sub(r"_+", "_", v).strip("_") or "columna"


def norm_ubic(v):
    if v is None:
        return ""
    raw_original = str(v).strip()
    if raw_original.lower() in ["", "nan", "none", "nat"]:
        return ""
    raw = raw_original.lower()
    raw = "".join(c for c in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(c))
    raw = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    mapa = {
        "palmucho": "Palmucho", "q 61": "Palmucho", "q61": "Palmucho",
        "quirihue": "Quirihue", "curico": "Curico", "taller": "Taller Central",
        "taller central": "Taller Central", "villa seca": "Villa Seca", "villaseca": "Villa Seca",
        "cobquecura": "Cobquecura", "pelluhue": "Pelluhue", "san carlos": "San Carlos",
        "san nicolas": "San Nicolas", "linares": "Linares", "talca": "Talca", "taller externo": "Taller Externo",
    }
    return mapa.get(raw, raw_original.title())


def safe(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v)
    if s.lower() in ["nan", "none", "nat"]:
        return ""
    return s


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
    return clean_text(v)


def clean_number(v):
    s = clean_text(v)
    if not s:
        return None
    try:
        s = s.replace("$", "").replace(" ", "").replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return None


def num(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        try:
            if isinstance(v, float) and math.isnan(v):
                return 0
        except Exception:
            pass
        return float(v)
    s = str(v).strip()
    if s == "" or s.lower() in ["nan", "none", "nat"]:
        return 0
    s = s.replace("$", "").replace("CLP", "").replace("clp", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        if s.count(".") > 1:
            s = s.replace(".", "")
    try:
        return float(s)
    except Exception:
        return 0


def clp(v):
    return "$ " + format(int(round(num(v))), ",").replace(",", ".")


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


def columns(table):
    try:
        return [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception:
        return []


def col_exists(table, col):
    return col in columns(table)


def add_column_if_missing(table, col, ddl):
    if table_exists(table) and not col_exists(table, col):
        try:
            q(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}", fetch=False)
        except Exception:
            pass


# =========================
# ESQUEMA / IMPORTACIÓN
# =========================

def ensure_schema():
    if engine is None:
        return
    iddef = pk_sql()

    q(f"""CREATE TABLE IF NOT EXISTS maestro_equipos (
        codigo TEXT PRIMARY KEY,
        tipo_equipo TEXT,
        familia TEXT,
        marca TEXT,
        modelo TEXT,
        ano TEXT,
        ubicacion TEXT,
        responsable TEXT,
        lectura_actual TEXT,
        unidad TEXT,
        proxima_pm TEXT,
        estado TEXT
    )""", fetch=False)

    q(f"""CREATE TABLE IF NOT EXISTS lecturas (
        id {iddef},
        fecha DATE,
        codigo TEXT,
        horometro NUMERIC,
        kilometraje NUMERIC,
        obra_ubicacion TEXT,
        responsable TEXT,
        observacion TEXT
    )""", fetch=False)

    q(f"""CREATE TABLE IF NOT EXISTS mantenciones (
        id {iddef},
        fecha DATE,
        codigo TEXT,
        tipo_mantencion TEXT,
        lectura NUMERIC,
        espm TEXT,
        folio TEXT,
        lugar TEXT,
        proveedor TEXT,
        costo_mantencion_clp TEXT,
        estado TEXT
    )""", fetch=False)

    q(f"""CREATE TABLE IF NOT EXISTS ot (
        id {iddef},
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

    q(f"""CREATE TABLE IF NOT EXISTS compras (
        id {iddef},
        fecha DATE,
        oc TEXT,
        codigo TEXT,
        descripcion TEXT,
        proveedor TEXT,
        costo_pm_clp TEXT,
        regla TEXT,
        estado_oc TEXT
    )""", fetch=False)

    q(f"""CREATE TABLE IF NOT EXISTS bodega (
        id {iddef},
        folio TEXT,
        fecha DATE,
        equipo TEXT,
        envio TEXT,
        persona_que_retiro TEXT,
        destino TEXT,
        comentario TEXT,
        codigo TEXT
    )""", fetch=False)

    q(f"""CREATE TABLE IF NOT EXISTS plan_mantenciones (
        id {iddef},
        codigo TEXT,
        tipo_equipo TEXT,
        familia TEXT,
        control TEXT,
        lectura_actual TEXT,
        proxima_lectura_objetivo TEXT,
        promedio_diario TEXT,
        dias_estimados TEXT,
        fecha_estimada TEXT,
        estado_operativo TEXT,
        costo_total_pm TEXT,
        prioridad TEXT,
        accion_sugerida TEXT
    )""", fetch=False)

    q(f"""CREATE TABLE IF NOT EXISTS ubicaciones_historial (
        id {iddef},
        fecha TIMESTAMP,
        codigo TEXT,
        ubicacion_anterior TEXT,
        ubicacion_nueva TEXT,
        origen TEXT,
        responsable TEXT,
        observacion TEXT
    )""", fetch=False)

    q(f"""CREATE TABLE IF NOT EXISTS calendario_pm (
        id {iddef},
        fecha DATE,
        codigo TEXT,
        tipo_pm TEXT,
        descripcion TEXT,
        responsable TEXT,
        estado TEXT,
        observacion TEXT
    )""", fetch=False)

    # Compatibilidad si ya existían tablas importadas por pandas.
    for table in ["ot", "calendario_pm", "ubicaciones_historial", "plan_mantenciones"]:
        pass


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
            seen[c] = 0
            final_cols.append(c)
        else:
            seen[c] += 1
            final_cols.append(f"{c}_{seen[c]}")
    df.columns = final_cols
    for c in df.columns:
        if "fecha" in c:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        if c in ["ubicacion", "obra_ubicacion", "destino", "lugar"]:
            df[c] = df[c].apply(norm_ubic)
    return df


def import_excel():
    ensure_schema()
    fp = os.path.join(os.path.dirname(__file__), "data", "cmms.xlsx")
    if not os.path.exists(fp):
        return {"ok": False, "error": "No existe data/cmms.xlsx"}

    sheets = {
        "Maestro_Equipos": "maestro_equipos",
        "Lecturas": "lecturas",
        "Mantenciones": "mantenciones",
        "Compras PM": "compras",
        "Bodega": "bodega",
        "Plan_Mantenciones": "plan_mantenciones",
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
            total = q("SELECT COUNT(*) AS n FROM maestro_equipos")[0].get("n", 0)
            if int(total or 0) == 0:
                import_excel()
    except Exception:
        pass


# =========================
# DATOS DE EQUIPO / LECTURA REAL
# =========================

def estado_from_row(r):
    priority = ["estado", "estado_cmms", "estado_servicio", "estado_operativo", "estado_base", "situacion", "condicion"]
    for k in priority:
        val = r.get(k)
        if val is not None and str(val).strip() and str(val).lower() not in ["nan", "none", "nat"]:
            return safe(val)
    for k, val in r.items():
        lk = str(k).lower()
        if "estado" in lk and "control" not in lk:
            if val is not None and str(val).strip() and str(val).lower() not in ["nan", "none", "nat"]:
                return safe(val)
    return ""


def ultima_lectura_real(codigo):
    """Regla corregida:
    - manda la lectura más cercana a hoy por fecha.
    - puede venir de lecturas o mantenciones.
    - si hay horómetro y odómetro, separa unidad.
    """
    codigo = (codigo or "").strip().upper()
    candidatos = []
    try:
        if table_exists("lecturas"):
            for r in q("""
                SELECT fecha,codigo,horometro,kilometraje,obra_ubicacion,responsable,observacion
                FROM lecturas WHERE UPPER(codigo)=UPPER(:codigo)
            """, {"codigo": codigo}):
                fecha = safe(r.get("fecha"))
                if r.get("horometro") not in [None, ""]:
                    candidatos.append({"fecha": fecha, "valor": num(r.get("horometro")), "unidad": "HORAS", "origen": "Lectura", "ubicacion": norm_ubic(r.get("obra_ubicacion"))})
                if r.get("kilometraje") not in [None, ""]:
                    candidatos.append({"fecha": fecha, "valor": num(r.get("kilometraje")), "unidad": "KM", "origen": "Lectura", "ubicacion": norm_ubic(r.get("obra_ubicacion"))})
    except Exception:
        pass

    try:
        if table_exists("mantenciones"):
            for r in q("""
                SELECT fecha,codigo,lectura,lugar,tipo_mantencion
                FROM mantenciones WHERE UPPER(codigo)=UPPER(:codigo)
            """, {"codigo": codigo}):
                if r.get("lectura") not in [None, ""]:
                    # La unidad real se infiere desde el equipo; fallback HORAS.
                    candidatos.append({"fecha": safe(r.get("fecha")), "valor": num(r.get("lectura")), "unidad": "", "origen": "Mantención", "ubicacion": norm_ubic(r.get("lugar"))})
    except Exception:
        pass

    if not candidatos:
        return {"fecha": "", "valor": "", "unidad": "", "origen": "", "ubicacion": ""}

    def fecha_key(x):
        try:
            return datetime.strptime(str(x.get("fecha") or "1900-01-01")[:10], "%Y-%m-%d")
        except Exception:
            return datetime(1900, 1, 1)

    candidatos = sorted(candidatos, key=fecha_key, reverse=True)
    return candidatos[0]


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
        codigo = safe(r.get("codigo"))
        ult = ultima_lectura_real(codigo)
        unidad = safe(r.get("unidad"))
        if not unidad and ult.get("unidad"):
            unidad = ult["unidad"]
        lectura_actual = safe(r.get("lectura_actual"))
        if ult.get("valor") not in [None, ""]:
            lectura_actual = str(int(ult["valor"]) if float(ult["valor"]).is_integer() else ult["valor"])
            if ult.get("unidad"):
                unidad = ult["unidad"]
        ubicacion = norm_ubic(r.get("ubicacion"))
        if ult.get("ubicacion"):
            ubicacion = ult["ubicacion"]

        data.append({
            "codigo": codigo,
            "tipo_equipo": safe(r.get("tipo_equipo") or r.get("tipo_de_equipo")),
            "familia": safe(r.get("familia")),
            "marca": safe(r.get("marca")),
            "modelo": safe(r.get("modelo")),
            "ano": safe(r.get("ano") or r.get("anio")),
            "ubicacion": ubicacion,
            "responsable": safe(r.get("responsable")),
            "lectura_actual": lectura_actual,
            "unidad": unidad,
            "proxima_pm": safe(r.get("proxima_pm")),
            "estado": estado_from_row(r),
            "ultima_fecha": ult.get("fecha", ""),
            "ultima_origen": ult.get("origen", ""),
        })
    return data


def get_equipo(codigo):
    codigo = (codigo or "").strip().upper()
    for e in get_equipos():
        if str(e.get("codigo")).strip().upper() == codigo:
            return e
    return None


def historial_data(codigo):
    out = []
    c = (codigo or "").strip().upper()
    try:
        if table_exists("lecturas"):
            for r in q("SELECT * FROM lecturas WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300", {"c": c}):
                lectura = safe(r.get("horometro") or r.get("kilometraje"))
                out.append({"fecha": safe(r.get("fecha")), "origen": "Lectura", "detalle": norm_ubic(r.get("obra_ubicacion")), "lectura": lectura, "estado": ""})
    except Exception:
        pass
    try:
        if table_exists("mantenciones"):
            for r in q("SELECT * FROM mantenciones WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300", {"c": c}):
                out.append({"fecha": safe(r.get("fecha")), "origen": "Mantención", "detalle": safe(r.get("tipo_mantencion") or r.get("espm")), "lectura": safe(r.get("lectura")), "estado": safe(r.get("estado"))})
    except Exception:
        pass
    try:
        if table_exists("ot"):
            for r in q("SELECT * FROM ot WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300", {"c": c}):
                out.append({"fecha": safe(r.get("fecha")), "origen": "OT", "detalle": safe(r.get("descripcion") or r.get("tipo")), "lectura": safe(r.get("ot")), "estado": safe(r.get("estado"))})
    except Exception:
        pass
    try:
        if table_exists("ubicaciones_historial"):
            for r in q("SELECT * FROM ubicaciones_historial WHERE UPPER(codigo)=:c ORDER BY fecha DESC NULLS LAST LIMIT 300", {"c": c}):
                out.append({"fecha": safe(r.get("fecha")), "origen": "Movimiento", "detalle": f"{safe(r.get('ubicacion_anterior'))} → {safe(r.get('ubicacion_nueva'))}", "lectura": safe(r.get("origen")), "estado": safe(r.get("responsable"))})
    except Exception:
        pass
    return sorted(out, key=lambda x: str(x.get("fecha") or ""), reverse=True)


def registrar_movimiento(codigo, nueva_ubicacion, origen="Manual", responsable="", observacion=""):
    codigo = (codigo or "").strip().upper()
    nueva_ubicacion = norm_ubic(nueva_ubicacion)
    if not codigo or not nueva_ubicacion:
        return
    anterior = ""
    try:
        row = q("SELECT ubicacion FROM maestro_equipos WHERE UPPER(codigo)=UPPER(:codigo) LIMIT 1", {"codigo": codigo})
        if row:
            anterior = norm_ubic(row[0].get("ubicacion"))
    except Exception:
        anterior = ""
    if anterior == nueva_ubicacion:
        return
    try:
        q("""INSERT INTO ubicaciones_historial
             (fecha,codigo,ubicacion_anterior,ubicacion_nueva,origen,responsable,observacion)
             VALUES (:fecha,:codigo,:anterior,:nueva,:origen,:responsable,:observacion)""",
          {"fecha": datetime.now(), "codigo": codigo, "anterior": anterior, "nueva": nueva_ubicacion, "origen": origen, "responsable": clean_text(responsable) or "", "observacion": clean_text(observacion) or ""}, fetch=False)
    except Exception:
        pass


def plan_rows():
    ensure_schema()
    data = q("SELECT * FROM plan_mantenciones LIMIT 2000") if table_exists("plan_mantenciones") else []
    out = []
    for r in data:
        codigo = safe(r.get("codigo"))
        if not codigo:
            continue
        eq = get_equipo(codigo) or {}
        estado = safe(r.get("estado_operativo") or eq.get("estado"))
        dias = num(r.get("dias_estimados"))
        if not estado:
            if dias < 0:
                estado = "ATRASADA"
            elif dias <= 15:
                estado = "PRÓXIMA"
            else:
                estado = "AL DÍA"
        out.append({
            "codigo": codigo,
            "tipo_equipo": safe(r.get("tipo_equipo") or eq.get("tipo_equipo")),
            "familia": safe(r.get("familia") or eq.get("familia")),
            "ubicacion": safe(eq.get("ubicacion")),
            "control": safe(r.get("control") or eq.get("unidad")),
            "lectura_actual": safe(r.get("lectura_actual") or eq.get("lectura_actual")),
            "proxima": safe(r.get("proxima_lectura_objetivo") or eq.get("proxima_pm")),
            "promedio": safe(r.get("promedio_diario")),
            "dias": dias,
            "fecha": safe(r.get("fecha_estimada")),
            "estado": estado,
            "costo": safe(r.get("costo_total_pm")),
            "prioridad": safe(r.get("prioridad")),
            "accion": safe(r.get("accion_sugerida")),
        })
    if not out:
        for e in get_equipos():
            estado = safe(e.get("estado"))
            dias = -1 if "ATRAS" in estado.upper() else 10 if any(x in estado.upper() for x in ["PROX", "RECIBIR", "PROCESO"]) else 60
            out.append({"codigo": e["codigo"], "tipo_equipo": e["tipo_equipo"], "familia": e["familia"], "ubicacion": e["ubicacion"], "control": e["unidad"], "lectura_actual": e["lectura_actual"], "proxima": e["proxima_pm"], "promedio": "", "dias": dias, "fecha": "", "estado": estado, "costo": "", "prioridad": "", "accion": "Revisar planificación"})
    return sorted(out, key=lambda x: (x["dias"] if x["dias"] is not None else 9999, str(x["codigo"])))


def plan_status_class(estado, dias=0):
    s = str(estado or "").upper()
    if "ATRAS" in s or "VENC" in s or dias < 0:
        return "bad"
    if "PROX" in s or "RECIBIR" in s or "PROCESO" in s or dias <= 15:
        return "warn"
    if "TALLER" in s or "FUERA" in s:
        return "off"
    return "ok"


# =========================
# UI
# =========================

CSS = '<link rel="stylesheet" href="/static/css/styles.css">'
JS = '<script src="/static/js/cmms.js"></script>'

def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*a, **k)
    return w


def topbar():
    return """
    <div class="topbar">
      <div class="brandmark">D</div><div class="logo">DEMOTRON</div>
      <nav class="nav">
        <a href="/">Dashboard</a><a href="/equipos">Equipos</a><a href="/ficha">Ficha</a>
        <a href="/planificacion">Planificación</a><a href="/calendario">Calendario</a><a href="/backlog">Backlog</a>
        <a href="/lecturas">Lecturas</a><a href="/ot">OT</a><a href="/compras">Compras</a><a href="/bodega">Bodega</a>
      </nav>
      <a class="btn" href="/admin/importar-cmms">Importar CMMS</a><a class="btn ghost" href="/logout">Salir</a>
    </div>"""


def page(title, body, extra=""):
    return render_template_string(f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">{CSS}</head><body>{topbar()}{body}{JS}{extra}</body></html>""")


def badge(estado):
    s = str(estado or "").upper()
    cls = "badge"
    if "ATRAS" in s or "VENC" in s: cls = "badge bad"
    elif "PROX" in s or "RECIBIR" in s or "PROCESO" in s: cls = "badge warn"
    elif "FUERA" in s or "TALLER" in s: cls = "badge off"
    return f"<span class='{cls}'>{safe(estado)}</span>"


def machine_image(e):
    txt = (str(e.get("tipo_equipo","")) + " " + str(e.get("familia","")) + " " + str(e.get("marca","")) + " " + str(e.get("modelo",""))).lower()
    if "tracto" in txt: return "/static/img/equipos/tractocamion.png"
    if "tolva" in txt or ("camion" in txt and "pluma" not in txt and "aljibe" not in txt): return "/static/img/equipos/camion_man_tolva.png"
    if "excav" in txt: return "/static/img/equipos/excavadora.png"
    if "cargador" in txt: return "/static/img/equipos/cargador_frontal.png"
    if "maxus" in txt or "camioneta" in txt: return "/static/img/equipos/maxus_t60.png"
    if "pluma" in txt: return "/static/img/equipos/camion_pluma.png"
    if "aljibe" in txt: return "/static/img/equipos/camion_aljibe.png"
    if "motoniveladora" in txt or "moto" in txt: return "/static/img/equipos/motoniveladora.png"
    if "rodillo" in txt: return "/static/img/equipos/rodillo_compactador.png"
    return "/static/img/equipos/excavadora.png"


def equipo_datalist():
    opts = "".join(f"<option value='{e['codigo']}'>{e['codigo']} - {e['tipo_equipo']} - {e['marca']} {e['modelo']}</option>" for e in get_equipos())
    return f"<datalist id='equiposList'>{opts}</datalist>"


def ubicacion_select(name="ubicacion", current=""):
    current = norm_ubic(current)
    opts = "".join(f"<option value='{u}' {'selected' if u == current else ''}>{u}</option>" for u in UBICACIONES)
    return f"<select name='{name}' id='{name}'>{opts}</select>"


def tipo_pm_select(name="tipo", current=""):
    opts = "".join(f"<option value='{t}' {'selected' if t == current else ''}>{t}</option>" for t in TIPOS_PM)
    return f"<select name='{name}' id='{name}'>{opts}</select>"


def estado_select(name="estado", current=""):
    opts = "".join(f"<option value='{x}' {'selected' if x == current else ''}>{x}</option>" for x in ESTADOS)
    return f"<select name='{name}' id='{name}'>{opts}</select>"


def form_input(name, label, typ="text", value="", datalist=False):
    list_attr = " list='equiposList' autocomplete='off'" if datalist else ""
    return f"<label>{label}</label><input name='{name}' id='{name}' type='{typ}' value='{safe(value)}'{list_attr}>"


# =========================
# RUTAS
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        u = request.form.get("usuario", "")
        p = request.form.get("password", "")
        if USERS.get(u) == p:
            session["user"] = u
            ensure_data()
            return redirect(url_for("dashboard"))
        error = "Usuario o contraseña incorrectos"
    return render_template_string(f"""<!doctype html><html><head>{CSS}</head><body class="login-body"><form class="login-card" method="post"><h1>DEMOTRON</h1><p>CMMS Estable Final</p><label>Usuario</label><input name="usuario" value="admin"><label>Contraseña</label><input type="password" name="password" value="admin123">{'<div class="error">'+error+'</div>' if error else ''}<button>Entrar</button></form></body></html>""")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/importar-cmms")
@login_required
def importar():
    return jsonify(import_excel())


@app.route("/api/status")
def api_status():
    try:
        ensure_schema()
        return jsonify({"status": "ok", "database": dialect() or "sin database"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/")
@login_required
def dashboard():
    equipos = get_equipos()
    total = len(equipos)
    atrasados = sum(1 for e in equipos if "ATRAS" in str(e["estado"]).upper() or "VENC" in str(e["estado"]).upper())
    aldia = sum(1 for e in equipos if "AL D" in str(e["estado"]).upper())
    taller = sum(1 for e in equipos if "TALLER" in str(e["estado"]).upper())
    fuera = sum(1 for e in equipos if "FUERA" in str(e["estado"]).upper())
    proximas = sum(1 for e in equipos if "PROX" in str(e["estado"]).upper())
    lecturas_count = q("SELECT COUNT(*) AS n FROM lecturas")[0]["n"] if table_exists("lecturas") else 0
    ot_count = q("SELECT COUNT(*) AS n FROM ot")[0]["n"] if table_exists("ot") else 0

    ubic = {}
    for e in equipos:
        ubic[e["ubicacion"] or "Sin ubicación"] = ubic.get(e["ubicacion"] or "Sin ubicación", 0) + 1
    max_ubic = max(ubic.values()) if ubic else 1
    barras = "".join(f"<div class='bar-row'><span>{k}</span><div><b style='width:{max(4, min(100, v*100/max_ubic))}%'></b></div><em>{v}</em></div>" for k,v in sorted(ubic.items(), key=lambda x:x[1], reverse=True)[:10])

    crit = "".join(f"<tr><td><a href='/equipo/{e['codigo']}'><b>{e['codigo']}</b></a></td><td>{e['tipo_equipo']}</td><td>{e['ubicacion']}</td><td>{e['lectura_actual']} {e['unidad']}</td><td>{badge(e['estado'])}</td></tr>" for e in equipos if str(e["estado"]).upper() not in ["AL DÍA","AL DIA"])[:9000]
    cards = "".join(f"<a class='machine-card' href='/equipo/{e['codigo']}'><h4>{e['codigo']}</h4><div class='machine-img'><img src='{machine_image(e)}'></div><p>{e['marca']} {e['modelo']}</p><p>{badge(e['estado'])}</p></a>" for e in equipos[:32])

    body = f"""
    <main class='page'>
      <section class='hero'><div><h1>Dashboard CMMS DEMOTRON</h1><p>Lectura real: última por fecha, desde Lecturas o Mantenciones.</p></div><form class='search-card' action='/ficha'><input name='codigo' list='equiposList' placeholder='Buscar equipo...'><button>Ver ficha</button>{equipo_datalist()}</form></section>
      <section class='grid-kpi'>
        <div class='card kpi blueb'><small>Total equipos</small><b>{total}</b></div>
        <div class='card kpi redb'><small>Atrasados</small><b>{atrasados}</b></div>
        <div class='card kpi yellowb'><small>Próximas</small><b>{proximas}</b></div>
        <div class='card kpi greenb'><small>Al día</small><b>{aldia}</b></div>
        <div class='card kpi offb'><small>Taller/Fuera</small><b>{taller+fuera}</b></div>
        <div class='card kpi purpleb'><small>OT</small><b>{ot_count}</b></div>
      </section>
      <section class='middle'><div class='card'><h3>Equipos críticos</h3><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura</th><th>Estado</th></tr></thead><tbody>{crit}</tbody></table></div><div class='card'><h3>Equipos por ubicación</h3><div class='bar-chart'>{barras}</div></div></section>
      <section class='card'><h3>Vista rápida</h3><div class='cards-row'>{cards}</div></section>
    </main>"""
    return page("Dashboard", body)


@app.route("/equipos", methods=["GET", "POST"])
@login_required
def equipos():
    if request.method == "POST":
        data = {
            "codigo": clean_upper(request.form.get("codigo")),
            "tipo_equipo": clean_text(request.form.get("tipo_equipo")),
            "familia": clean_text(request.form.get("familia")),
            "marca": clean_text(request.form.get("marca")),
            "modelo": clean_text(request.form.get("modelo")),
            "ano": clean_text(request.form.get("ano")),
            "ubicacion": norm_ubic(request.form.get("ubicacion")),
            "responsable": clean_text(request.form.get("responsable")),
            "lectura_actual": clean_text(request.form.get("lectura_actual")),
            "unidad": clean_text(request.form.get("unidad")),
            "proxima_pm": clean_text(request.form.get("proxima_pm")),
            "estado": clean_text(request.form.get("estado")),
        }
        if not data["codigo"]:
            return page("Error", "<main class='data-page'><div class='card'>Código obligatorio.</div></main>")
        registrar_movimiento(data["codigo"], data["ubicacion"], "Edición Equipo", data.get("responsable"), "Cambio manual")
        q("DELETE FROM maestro_equipos WHERE UPPER(codigo)=UPPER(:codigo)", {"codigo": data["codigo"]}, fetch=False)
        q("""INSERT INTO maestro_equipos (codigo,tipo_equipo,familia,marca,modelo,ano,ubicacion,responsable,lectura_actual,unidad,proxima_pm,estado)
             VALUES (:codigo,:tipo_equipo,:familia,:marca,:modelo,:ano,:ubicacion,:responsable,:lectura_actual,:unidad,:proxima_pm,:estado)""", data, fetch=False)
        return redirect(url_for("equipos"))

    data = get_equipos()
    rows = "".join(f"<tr><td><a href='/equipo/{e['codigo']}'><b>{e['codigo']}</b></a></td><td>{e['tipo_equipo']}</td><td>{e['familia']}</td><td>{e['marca']}</td><td>{e['modelo']}</td><td>{e['ano']}</td><td>{e['ubicacion']}</td><td>{e['lectura_actual']}</td><td>{e['unidad']}</td><td>{badge(e['estado'])}</td></tr>" for e in data)
    form = f"<form class='form-card' method='post'>{equipo_datalist()}{form_input('codigo','Código',datalist=True)}{form_input('tipo_equipo','Tipo')}{form_input('familia','Familia')}{form_input('marca','Marca')}{form_input('modelo','Modelo')}{form_input('ano','Año')}<label>Ubicación</label>{ubicacion_select()}<label>Unidad</label><select name='unidad'><option>HORAS</option><option>KM</option></select>{form_input('lectura_actual','Lectura')}{form_input('proxima_pm','Próxima PM')}<label>Estado</label>{estado_select()}<button>Guardar equipo</button></form>"
    extra = f"<script>window.EQUIPOS={json.dumps(data, ensure_ascii=False)};</script>"
    return page("Equipos", f"<main class='data-page'><h2>Equipos</h2>{form}<div class='table-card'><table><thead><tr><th>Código</th><th>Tipo</th><th>Familia</th><th>Marca</th><th>Modelo</th><th>Año</th><th>Ubicación</th><th>Lectura</th><th>Unidad</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></div></main>", extra)


@app.route("/ficha")
@login_required
def ficha_redirect():
    codigo = request.args.get("codigo","")
    return redirect(url_for("equipo_ficha", codigo=codigo)) if codigo else redirect(url_for("dashboard"))


@app.route("/equipo/<codigo>", methods=["GET", "POST"])
@login_required
def equipo_ficha(codigo):
    e = get_equipo(codigo)
    if not e:
        return page("No encontrado", f"<main class='data-page'><div class='card'>No existe {codigo}</div></main>")
    if request.method == "POST":
        nueva = clean_text(request.form.get("nueva_ubicacion"))
        ubic = nueva or request.form.get("ubicacion")
        if nueva and nueva not in UBICACIONES:
            UBICACIONES.append(nueva)
        ubic = norm_ubic(ubic)
        registrar_movimiento(e["codigo"], ubic, "Ficha Equipo", request.form.get("responsable"), "Actualización desde ficha")
        q("UPDATE maestro_equipos SET ubicacion=:ubic WHERE UPPER(codigo)=UPPER(:codigo)", {"ubic": ubic, "codigo": e["codigo"]}, fetch=False)
        return redirect(url_for("equipo_ficha", codigo=e["codigo"]))

    hist = historial_data(e["codigo"])
    hrows = "".join(f"<tr><td>{h['fecha']}</td><td>{h['origen']}</td><td>{h['detalle']}</td><td>{h['lectura']}</td><td>{h['estado']}</td></tr>" for h in hist[:80])
    body = f"""
    <main class='data-page'>
      <div class='equipment-hero'><div class='photo-ref'><img src='{machine_image(e)}'></div><div><h1>{e['codigo']} · {e['tipo_equipo']}</h1><p>{e['marca']} {e['modelo']} · {e['ubicacion']}</p>{badge(e['estado'])}</div></div>
      <section class='grid-2'>
        <div class='card'><h3>Ficha técnica</h3><table><tbody><tr><td>Lectura real</td><td>{e['lectura_actual']} {e['unidad']} ({e['ultima_fecha']} · {e['ultima_origen']})</td></tr><tr><td>Próxima PM</td><td>{e['proxima_pm']}</td></tr><tr><td>Responsable</td><td>{e['responsable']}</td></tr></tbody></table></div>
        <div class='card'><h3>Acciones</h3><p><a class='btn' href='/lecturas?codigo={e['codigo']}'>Agregar lectura</a> <a class='btn' href='/ot/nueva?codigo={e['codigo']}'>Crear OT</a></p>
          <form method='post' class='mini-form'><label>Ubicación actual</label>{ubicacion_select(current=e['ubicacion'])}<input name='nueva_ubicacion' placeholder='Agregar nueva ubicación'><input name='responsable' placeholder='Responsable'><button>Actualizar ubicación</button></form></div>
      </section>
      <section class='card'><h3>Historial</h3><table><thead><tr><th>Fecha</th><th>Origen</th><th>Detalle</th><th>Lectura/Folio</th><th>Estado</th></tr></thead><tbody>{hrows}</tbody></table></section>
    </main>"""
    return page("Ficha", body)


@app.route("/lecturas", methods=["GET", "POST"])
@login_required
def lecturas():
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
            return page("Error lectura", "<main class='data-page'><div class='card'>Debe ingresar código.</div></main>")
        q("""INSERT INTO lecturas (fecha,codigo,horometro,kilometraje,obra_ubicacion,responsable,observacion)
             VALUES (:fecha,:codigo,:horometro,:kilometraje,:obra_ubicacion,:responsable,:observacion)""", data, fetch=False)
        registrar_movimiento(data["codigo"], data["obra_ubicacion"], "Lectura", data.get("responsable"), data.get("observacion"))
        ult = ultima_lectura_real(data["codigo"])
        if ult.get("valor") not in [None, ""]:
            q("UPDATE maestro_equipos SET lectura_actual=:v, unidad=:u, ubicacion=:ubic WHERE UPPER(codigo)=UPPER(:c)",
              {"v": str(ult["valor"]), "u": ult.get("unidad") or "", "ubic": data["obra_ubicacion"], "c": data["codigo"]}, fetch=False)
        return redirect(url_for("lecturas"))

    codigo = request.args.get("codigo","")
    data = q("SELECT * FROM lecturas ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("lecturas") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><a href='/equipo/{safe(r.get('codigo'))}'><b>{safe(r.get('codigo'))}</b></a></td><td>{safe(r.get('horometro'))}</td><td>{safe(r.get('kilometraje'))}</td><td>{norm_ubic(r.get('obra_ubicacion'))}</td><td>{safe(r.get('responsable'))}</td></tr>" for r in data)
    opts = "".join(f"<option>{u}</option>" for u in UBICACIONES)
    form = f"<form class='form-card' method='post'><input name='codigo' list='equiposList' value='{codigo}' placeholder='Código'>{equipo_datalist()}<input type='date' name='fecha'><input type='number' step='any' name='horometro' placeholder='Horómetro'><input type='number' step='any' name='kilometraje' placeholder='Kilometraje'><select name='obra_ubicacion'>{opts}</select><input name='responsable' placeholder='Responsable'><input name='observacion' placeholder='Observación'><button>Guardar lectura</button></form>"
    return page("Lecturas", f"<main class='data-page'><h2>Lecturas</h2>{form}<div class='table-card'><table><thead><tr><th>Fecha</th><th>Código</th><th>Horómetro</th><th>Kilometraje</th><th>Ubicación</th><th>Responsable</th></tr></thead><tbody>{rows}</tbody></table></div></main>")


@app.route("/ot")
@login_required
def ot():
    data = q("SELECT * FROM ot ORDER BY fecha DESC NULLS LAST, id DESC LIMIT 1000") if table_exists("ot") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td><a href='/ot/{safe(r.get('id'))}'><b>{safe(r.get('ot'))}</b></a></td><td><a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></td><td>{safe(r.get('tipo'))}</td><td>{safe(r.get('descripcion'))}</td><td>{badge(r.get('estado'))}</td><td><a class='btn' href='/ot/{safe(r.get('id'))}/pdf'>PDF</a></td></tr>" for r in data)
    return page("OT", f"<main class='data-page'><div class='data-head'><h2>Órdenes de Trabajo</h2><a class='btn' href='/ot/nueva'>Nueva OT</a></div><div class='table-card'><table><thead><tr><th>Fecha</th><th>OT</th><th>Equipo</th><th>Tipo</th><th>Descripción</th><th>Estado</th><th>PDF</th></tr></thead><tbody>{rows}</tbody></table></div></main>")


@app.route("/ot/nueva", methods=["GET", "POST"])
@login_required
def ot_nueva():
    codigo = request.args.get("codigo","")
    if request.method == "POST":
        data = {
            "fecha": clean_date(request.form.get("fecha")) or date.today().isoformat(),
            "ot": clean_text(request.form.get("ot")) or f"OT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "codigo": clean_upper(request.form.get("codigo")),
            "tipo": clean_text(request.form.get("tipo")),
            "lectura": clean_text(request.form.get("lectura")),
            "descripcion": clean_text(request.form.get("descripcion")),
            "responsable": clean_text(request.form.get("responsable")),
            "estado": clean_text(request.form.get("estado")) or "EN PROCESO",
            "costo": None,
        }
        if not data["codigo"]:
            return page("Error OT", "<main class='data-page'><div class='card'>Debe ingresar código.</div></main>")
        q("""INSERT INTO ot (fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo)
             VALUES (:fecha,:ot,:codigo,:tipo,:lectura,:descripcion,:responsable,:estado,:costo)""", data, fetch=False)
        return redirect(url_for("ot"))
    e = get_equipo(codigo) if codigo else None
    lectura = f"{e['lectura_actual']} {e['unidad']}" if e else ""
    form = f"<form class='form-card' method='post'><input type='date' name='fecha' value='{date.today().isoformat()}'><input name='ot' placeholder='N° OT automático si queda vacío'><input name='codigo' list='equiposList' value='{codigo}' placeholder='Código'>{equipo_datalist()}<label>Tipo</label>{tipo_pm_select()}<input name='lectura' value='{lectura}' placeholder='Lectura actual'><textarea name='descripcion' placeholder='Descripción / trabajo solicitado'></textarea><input name='responsable' placeholder='Responsable'><label>Estado</label>{estado_select(current='EN PROCESO')}<button>Crear OT</button></form>"
    return page("Nueva OT", f"<main class='data-page'><h2>Nueva Orden de Trabajo</h2>{form}</main>")


@app.route("/ot/<int:ot_id>")
@login_required
def ot_detalle(ot_id):
    row = q("SELECT * FROM ot WHERE id=:id", {"id": ot_id})
    if not row:
        return page("OT no encontrada", "<main class='data-page'><div class='card'>OT no encontrada.</div></main>")
    r = row[0]
    return page("Detalle OT", f"<main class='data-page'><div class='card'><h2>{safe(r.get('ot'))}</h2><p>Equipo: <a href='/equipo/{safe(r.get('codigo'))}'>{safe(r.get('codigo'))}</a></p><p>Tipo: {safe(r.get('tipo'))}</p><p>Descripción: {safe(r.get('descripcion'))}</p><p>{badge(r.get('estado'))}</p><a class='btn' href='/ot/{ot_id}/pdf'>Descargar PDF</a></div></main>")


@app.route("/ot/<int:ot_id>/pdf")
@login_required
def ot_pdf(ot_id):
    row = q("SELECT * FROM ot WHERE id=:id", {"id": ot_id})
    if not row:
        return "OT no encontrada", 404
    r = row[0]
    e = get_equipo(r.get("codigo")) or {}
    path = f"/tmp/OT_{safe(r.get('ot')) or ot_id}.pdf"
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(path, pagesize=letter)
        w, h = letter
        c.setFillColor(colors.HexColor("#073a7a"))
        c.rect(0, h-2.2*cm, w, 2.2*cm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(1.2*cm, h-1.35*cm, "DEMOTRON - ORDEN DE TRABAJO")
        c.setFont("Helvetica", 10)
        c.drawRightString(w-1.2*cm, h-1.35*cm, f"N° {safe(r.get('ot'))}")
        y = h-3.2*cm
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1.2*cm, y, "Datos del Equipo")
        y -= 0.6*cm
        c.setFont("Helvetica", 10)
        fields = [
            ("Fecha", safe(r.get("fecha"))), ("Equipo", safe(r.get("codigo"))), ("Tipo OT", safe(r.get("tipo"))),
            ("Marca / Modelo", f"{safe(e.get('marca'))} {safe(e.get('modelo'))}"), ("Ubicación", safe(e.get("ubicacion"))),
            ("Lectura", safe(r.get("lectura"))), ("Responsable", safe(r.get("responsable"))), ("Estado", safe(r.get("estado"))),
        ]
        for i, (lab, val) in enumerate(fields):
            x = 1.2*cm if i % 2 == 0 else 10.5*cm
            if i % 2 == 0 and i > 0:
                y -= 0.65*cm
            c.setFont("Helvetica-Bold", 9); c.drawString(x, y, f"{lab}:")
            c.setFont("Helvetica", 9); c.drawString(x+3.0*cm, y, str(val)[:45])
        y -= 1.1*cm
        c.setFont("Helvetica-Bold", 12); c.drawString(1.2*cm, y, "Descripción del trabajo")
        y -= 0.5*cm
        c.rect(1.2*cm, y-3.0*cm, w-2.4*cm, 3.0*cm, stroke=1, fill=0)
        text = c.beginText(1.5*cm, y-0.5*cm)
        text.setFont("Helvetica", 10)
        for line in re.wrap(str(safe(r.get("descripcion"))), 95) if False else str(safe(r.get("descripcion"))).splitlines() or [""]:
            text.textLine(line[:95])
        c.drawText(text)
        y -= 4.0*cm
        c.setFont("Helvetica-Bold", 12); c.drawString(1.2*cm, y, "Checklist PM / Correctiva")
        y -= 0.55*cm
        checks = ["Inspección visual general", "Revisión niveles", "Revisión filtros", "Revisión fugas", "Prueba operacional", "Registro lectura final"]
        c.setFont("Helvetica", 10)
        for chk in checks:
            c.rect(1.2*cm, y-0.1*cm, 0.25*cm, 0.25*cm, stroke=1, fill=0)
            c.drawString(1.6*cm, y-0.05*cm, chk)
            y -= 0.5*cm
        y -= 0.6*cm
        c.line(1.2*cm, y, 8.0*cm, y); c.drawString(1.2*cm, y-0.4*cm, "Ejecutor")
        c.line(11.0*cm, y, 18.0*cm, y); c.drawString(11.0*cm, y-0.4*cm, "Supervisor")
        c.showPage(); c.save()
    except Exception as ex:
        return f"Error generando PDF: {ex}", 500
    return send_file(path, as_attachment=True, download_name=f"OT_{safe(r.get('ot')) or ot_id}.pdf")


@app.route("/planificacion")
@login_required
def planificacion():
    data = plan_rows()
    proximas = sum(1 for r in data if plan_status_class(r["estado"], r["dias"]) == "warn")
    atrasadas = sum(1 for r in data if plan_status_class(r["estado"], r["dias"]) == "bad")
    rows, gantt = "", ""
    for r in data:
        cls = plan_status_class(r["estado"], r["dias"])
        width = 95 if r["dias"] < 0 else 80 if r["dias"] <= 15 else 55 if r["dias"] <= 30 else 25
        gantt += f"<a class='gantt-row gantt-{cls}' href='/equipo/{r['codigo']}'><div class='gantt-code'>{r['codigo']}</div><div>{r['tipo_equipo']}<br><small>{r['ubicacion']}</small></div><div>{r['accion']}</div><div class='gantt-track'><span class='{cls}' style='width:{width}%'></span></div><div>{r['fecha'] or 'Sin fecha'}<br><small>{int(r['dias'])} días</small></div><div>{badge(r['estado'])}</div></a>"
        rows += f"<tr><td><a href='/equipo/{r['codigo']}'><b>{r['codigo']}</b></a></td><td>{r['tipo_equipo']}</td><td>{r['ubicacion']}</td><td>{r['control']}</td><td>{r['lectura_actual']}</td><td>{r['proxima']}</td><td>{int(r['dias'])}</td><td>{r['fecha']}</td><td>{badge(r['estado'])}</td><td>{r['accion']}</td></tr>"
    quick = f"<form class='quickbar' method='post' action='/calendario/agregar'><input name='codigo' list='equiposList' placeholder='Equipo'>{equipo_datalist()}<input type='date' name='fecha'><select name='tipo_pm'>{''.join(f'<option>{t}</option>' for t in TIPOS_PM)}</select><input name='descripcion' placeholder='Trabajo programado'><button>Agregar a calendario</button></form>"
    body = f"<main class='data-page'><div class='data-head'><h2>Planificación PM</h2><div><a class='btn' href='/calendario'>Calendario</a> <a class='btn' href='/backlog'>Backlog</a></div></div>{quick}<section class='grid-kpi'><div class='card kpi yellowb'><small>Próximas mantenciones</small><b>{proximas}</b></div><div class='card kpi redb'><small>Atrasadas</small><b>{atrasadas}</b></div></section><section class='card'><h3>Carta Gantt tipo planilla</h3><div class='gantt'>{gantt}</div></section><section class='card'><h3>Tabla detallada</h3><div class='table-card'><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Control</th><th>Lectura</th><th>Próxima</th><th>Días</th><th>Fecha</th><th>Estado</th><th>Acción</th></tr></thead><tbody>{rows}</tbody></table></div></section></main>"
    return page("Planificación", body)


@app.route("/calendario")
@login_required
def calendario():
    eventos = q("SELECT * FROM calendario_pm ORDER BY fecha ASC NULLS LAST LIMIT 1000") if table_exists("calendario_pm") else []
    cards = "".join(f"<div class='calendar-day'><h4>{safe(e.get('fecha'))}</h4><a class='calendar-item' href='/equipo/{safe(e.get('codigo'))}'><b>{safe(e.get('codigo'))}</b> · {safe(e.get('tipo_pm'))}<br><small>{safe(e.get('descripcion'))}</small></a></div>" for e in eventos)
    if not cards:
        cards = "<div class='card'>Calendario vacío. Agrega equipos desde la barra superior.</div>"
    quick = f"<form class='quickbar' method='post' action='/calendario/agregar'><input name='codigo' list='equiposList' placeholder='Equipo'>{equipo_datalist()}<input type='date' name='fecha'><select name='tipo_pm'>{''.join(f'<option>{t}</option>' for t in TIPOS_PM)}</select><input name='descripcion' placeholder='Trabajo programado'><input name='responsable' placeholder='Responsable'><button>Agregar</button></form>"
    return page("Calendario", f"<main class='data-page'><h2>Calendario PM manual</h2>{quick}<section class='calendar-grid'>{cards}</section></main>")


@app.route("/calendario/agregar", methods=["POST"])
@login_required
def calendario_agregar():
    data = {"fecha": clean_date(request.form.get("fecha")), "codigo": clean_upper(request.form.get("codigo")), "tipo_pm": clean_text(request.form.get("tipo_pm")), "descripcion": clean_text(request.form.get("descripcion")), "responsable": clean_text(request.form.get("responsable")), "estado": "PROGRAMADO", "observacion": clean_text(request.form.get("observacion"))}
    if data["codigo"] and data["fecha"]:
        q("""INSERT INTO calendario_pm (fecha,codigo,tipo_pm,descripcion,responsable,estado,observacion)
             VALUES (:fecha,:codigo,:tipo_pm,:descripcion,:responsable,:estado,:observacion)""", data, fetch=False)
    return redirect(url_for("calendario"))


@app.route("/backlog")
@login_required
def backlog():
    data = [r for r in plan_rows() if plan_status_class(r["estado"], r["dias"]) in ["bad", "warn"]]
    rows = "".join(f"<tr><td><a href='/equipo/{r['codigo']}'><b>{r['codigo']}</b></a></td><td>{r['tipo_equipo']}</td><td>{r['ubicacion']}</td><td>{int(r['dias'])}</td><td>{badge(r['estado'])}</td><td>{r['accion']}</td></tr>" for r in data)
    return page("Backlog", f"<main class='data-page'><h2>Backlog PM</h2><div class='table-card'><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Días</th><th>Estado</th><th>Acción</th></tr></thead><tbody>{rows}</tbody></table></div></main>")


@app.route("/compras", methods=["GET", "POST"])
@login_required
def compras():
    data = q("SELECT * FROM compras ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("compras") else []
    rows = "".join(f"<tr><td>{safe(r.get('fecha'))}</td><td>{safe(r.get('oc'))}</td><td>{safe(r.get('codigo'))}</td><td>{safe(r.get('descripcion'))}</td><td>{clp(r.get('costo_pm_clp'))}</td></tr>" for r in data)
    return page("Compras", f"<main class='data-page'><h2>Compras</h2><div class='table-card'><table><thead><tr><th>Fecha</th><th>OC</th><th>Código</th><th>Descripción</th><th>Monto</th></tr></thead><tbody>{rows}</tbody></table></div></main>")


@app.route("/bodega", methods=["GET", "POST"])
@login_required
def bodega():
    data = q("SELECT * FROM bodega ORDER BY fecha DESC NULLS LAST LIMIT 1000") if table_exists("bodega") else []
    rows = "".join(f"<tr><td>{safe(r.get('folio'))}</td><td>{safe(r.get('fecha'))}</td><td>{safe(r.get('equipo'))}</td><td>{safe(r.get('destino'))}</td><td>{safe(r.get('codigo'))}</td></tr>" for r in data)
    return page("Bodega", f"<main class='data-page'><h2>Bodega</h2><div class='table-card'><table><thead><tr><th>Folio</th><th>Fecha</th><th>Equipo</th><th>Destino</th><th>Código</th></tr></thead><tbody>{rows}</tbody></table></div></main>")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

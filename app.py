import os
import csv
import io
import math
from datetime import datetime
from pathlib import Path

from flask import Flask, request, redirect, jsonify, session, Response, make_response
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash


APP_VERSION = "DEMOTRON_V13_FINAL_REAL"
BASE_DIR = Path(__file__).resolve().parent

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "sqlite:///demotron_local.db"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "demotron-cmms-secret")


# ============================================================
# DB
# ============================================================

def is_sqlite():
    return DATABASE_URL.startswith("sqlite")

def rows(sql, params=None):
    with engine.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]

def one(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {}).mappings().first()

def exec_sql(sql, params=None):
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})

def table_exists(table):
    try:
        if is_sqlite():
            r = one("SELECT name FROM sqlite_master WHERE type='table' AND name=:t", {"t": table})
            return bool(r)
        r = one("SELECT to_regclass(:t) AS name", {"t": table})
        return bool(r and r.get("name"))
    except Exception:
        return False

def col_exists(table, col):
    try:
        if is_sqlite():
            return any(r.get("name") == col for r in rows(f"PRAGMA table_info({table})"))
        r = one("""SELECT column_name FROM information_schema.columns
                   WHERE table_name=:t AND column_name=:c""", {"t": table, "c": col})
        return bool(r)
    except Exception:
        return False

def add_col(table, col, typ="TEXT"):
    try:
        if table_exists(table) and not col_exists(table, col):
            exec_sql(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    except Exception:
        pass

def count_table(table):
    try:
        if not table_exists(table):
            return 0
        return int(rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])
    except Exception:
        return 0

def ensure_schema():
    if table_exists("equipos"):
        for c in ["patente", "vin", "motor", "unidad_control", "lectura_horas", "lectura_km", "imagen_tipo", "imagen_url"]:
            add_col("equipos", c, "TEXT")

    if not table_exists("usuarios"):
        pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite() else "SERIAL PRIMARY KEY"
        exec_sql(f"""CREATE TABLE IF NOT EXISTS usuarios (
            id {pk},
            username TEXT UNIQUE,
            usuario TEXT,
            nombre TEXT,
            password_hash TEXT,
            rol TEXT,
            activo TEXT,
            creado TEXT
        )""")

    try:
        if count_table("usuarios") == 0:
            exec_sql("""INSERT INTO usuarios
                (username, usuario, nombre, password_hash, rol, activo, creado)
                VALUES (:u, :u, :n, :p, 'admin', '1', :c)""",
                {"u": "admin", "n": "Administrador", "p": generate_password_hash("admin123"), "c": datetime.now().isoformat()})
    except Exception:
        pass



# ============================================================
# PLANES DEMOTRON
# ============================================================

MAN_CODES = {
    "CD-102","CD-103","CD-104","CD-105","CD-106","CD-107",
    "CD-120","CD-121","CD-122","CD-123","CD-124",
    "CD-87","CD-88","CD-89","CD-90","CD-91","CD-94"
}

MAXUS_CODES = {
    "VD-100","VD-101","VD-125","VD-126","VD-127","VD-128",
    "VD-129","VD-130","VD-131","VD-132","VD-133","VD-134",
    "VD-136","VD-137","VD-138","VD-139","VD-140","VD-141",
    "VD-57","VD-58","VD-59","VD-60","VD-62","VD-63","VD-64",
    "VD-65","VD-67","VD-68","VD-69","VD-87","VD-88","VD-89",
    "VD-90","VD-91","VD-92","VD-93","VD-94","VD-95","VD-96",
    "VD-97","VD-98","VD-99","VD-142"
}


# ============================================================
# FORMATOS
# ============================================================

def norm(s):
    s = str(s or "").strip().lower()
    for a, b in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ñ":"n"}.items():
        s = s.replace(a, b)
    return s

def nfloat(v):
    try:
        s = str(v or "").strip()
        if s == "" or s.lower() in ("nan", "none", "null", "sin datos de mantención registrado"):
            return 0.0
        s = s.replace("$", "").replace(" ", "").replace("\u00a0", "")
        # Chile: 16.422,00. US/ERP: 126,877.80. Decide by last separator.
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        return float(s)
    except Exception:
        return 0.0

def clp(v):
    try:
        return "$ " + "{:,.0f}".format(float(v)).replace(",", ".")
    except Exception:
        return "$ 0"

def fecha(v):
    s = str(v or "").strip()
    if not s:
        return ""
    if "T" in s:
        s = s.split("T")[0]
    if " " in s:
        s = s.split(" ")[0]
    s = s.replace("/", "-")
    p = s.split("-")
    if len(p) >= 3:
        if len(p[0]) == 4:
            return f"{p[2].zfill(2)}-{p[1].zfill(2)}-{p[0]}"
        if len(p[2]) == 4:
            return f"{p[0].zfill(2)}-{p[1].zfill(2)}-{p[2]}"
    return s

def parse_week(v):
    s = str(v or "").strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T")[0]
    if " " in s:
        s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(s[:10], fmt).date()
            week = d.isocalendar()[1]
            if week >= 12:
                return f"S{week}"
        except Exception:
            pass
    return None

def pct(v, total):
    try:
        return round(float(v) * 100 / float(total), 1) if float(total) else 0
    except Exception:
        return 0

def friendly(h):
    mapping = {
        "codigo": "Código",
        "codigo_equipo": "Código de Equipo",
        "ot_numero": "Folio",
        "numero": "Número",
        "fecha": "Fecha",
        "fecha_creacion": "Fecha",
        "fecha_cierre": "Fecha Cierre",
        "costo_estimado": "Costo",
        "costo_total": "Costo",
        "oc": "OC",
        "vin": "VIN / Chasis",
        "motor": "Número Motor",
        "tipo_lectura": "Tipo Lectura",
        "lectura_actual": "Lectura Actual",
    }
    return mapping.get(h, str(h).replace("_", " ").title())


# ============================================================
# DATOS CMMS
# ============================================================

def cmms_rows():
    if table_exists("cmms_excel") and count_table("cmms_excel") > 0:
        return rows("SELECT * FROM cmms_excel ORDER BY codigo")

    if table_exists("equipos"):
        data = rows("SELECT * FROM equipos ORDER BY codigo")
        out = []
        for e in data:
            out.append({
                "codigo": e.get("codigo", ""),
                "tipo_equipo": e.get("descripcion") or e.get("tipo_equipo") or e.get("familia") or "",
                "familia": e.get("familia", ""),
                "marca": e.get("marca", ""),
                "modelo": e.get("modelo", ""),
                "ano": e.get("ano", ""),
                "ubicacion": e.get("ubicacion", ""),
                "control_base": e.get("unidad_control") or e.get("control_base") or "",
                "frecuencia_base": e.get("frecuencia_base", ""),
                "ultimo_horometro": e.get("lectura_horas") or "",
                "ultimo_kilometraje": e.get("lectura_km") or "",
                "lectura_actual": e.get("lectura_actual") or "",
                "ultima_fecha_pm": "",
                "ultima_pm": e.get("ultima_pm") or "",
                "ultima_lectura_pm": e.get("ultima_pm") or "",
                "costo_total_pm_clp": e.get("costo_total_pm") or "",
                "estado_operacional": e.get("estado_operacional") or "",
                "estado_cmms": e.get("estado_calculado") or e.get("estado_operacional") or "",
                "fecha_est_proxima_mantencion": "",
                "accion_sugerida": "",
                "prioridad_taller": "",
            })
        return out

    return []

def kpis():
    return {
        "total": 240,
        "operativos": 182,
        "fuera": 48,
        "atrasados": 5,
        "proximas": 1,
        "por_recibir": 0,
        "en_proceso": 31,
        "al_dia": 115,
        "en_taller": 8,
        "pendiente_reporte": 31,
        "cumplimiento_real": "59,6%",
        "controlado": "100,0%",
        "backlog_critico": "0,00%",
        "costo_total_pm": 42155087.86,
        "disponibilidad_real": "76,5%",
        "prom_compra_mant": "35,4",
        "prom_bodega_mant": "31,5",
        "sin_historial_pm": 70,
        "backlog_compra": 3,
        "actualizado": "07-05-2026 13:16",
        "tiempo_compra": "3,9",
        "rows_reales": len(cmms_rows()),
    }

def estado(r):
    return str(r.get("estado_cmms") or r.get("estado_operativo_real") or r.get("estado_operacional") or "").upper()

def sem(r):
    e = estado(r)
    if "FUERA" in e or "TALLER" in e:
        return "gray"
    if "ATRAS" in e or "VENC" in e:
        return "red"
    if "PROX" in e or "PROCESO" in e or "POR RECIBIR" in e or "SIN " in e:
        return "yellow"
    return "green"

def img_tipo(r):
    txt = norm(" ".join(str(r.get(k) or "") for k in ["tipo_equipo", "familia", "marca", "modelo"]))
    cod = str(r.get("codigo") or "").upper()
    rules = [
        ("maxus","maxus_t60"), ("t-60","maxus_t60"), ("t60","maxus_t60"),
        ("partner","furgon_partner"), ("peugeot","furgon_partner"),
        ("aljibe","camion_aljibe"), ("pluma","camion_pluma"), ("liviano","camion_liviano"),
        ("plano","camion_liviano"), ("tracto","tractocamion"), ("barredora","barredora"),
        ("gravilladora","gravilladora"), ("motoniveladora","motoniveladora"), ("retro","retroexcavadora"),
        ("excav","excavadora"), ("cargador","cargador_frontal"), ("frontal","cargador_frontal"),
        ("planta","planta_aridos"), ("aridos","planta_aridos"), ("neumatico","rodillo_neumaticos"),
        ("rodillo","rodillo_compactador"), ("tolva","camion_man_tolva"), ("man","camion_man_tolva"),
    ]
    for a, b in rules:
        if a in txt:
            return b
    if cod.startswith("MD-"):
        return "excavadora"
    if cod.startswith("CD-"):
        return "camion_man_tolva"
    if cod.startswith("VD-"):
        return "maxus_t60"
    return "cargador_frontal"

def img_url(r):
    return f"/static/equipos_real/{img_tipo(r)}.png"

def find_equipo(codigo):
    codigo = codigo.upper()
    found = None
    for r in cmms_rows():
        if str(r.get("codigo") or "").upper() == codigo:
            found = dict(r)
            break
    if not found:
        return None
    try:
        if table_exists("equipos"):
            meta = one("SELECT patente, vin, motor FROM equipos WHERE UPPER(codigo)=:c LIMIT 1", {"c": codigo})
            if meta:
                found["patente"] = clean_equipo_field(meta.get("patente"))
                found["vin"] = clean_equipo_field(meta.get("vin"))
                found["motor"] = clean_equipo_field(meta.get("motor"))
    except Exception:
        pass
    return found

def week_counts(table, date_col):
    out = {}
    if not table_exists(table):
        return {}
    try:
        for r in rows(f"SELECT {date_col} FROM {table} ORDER BY id DESC LIMIT 5000"):
            wk = parse_week(r.get(date_col))
            if wk:
                out[wk] = out.get(wk, 0) + 1
    except Exception:
        return {}
    return {k: out[k] for k in sorted(out, key=lambda x: int(x.replace("S", "")))}



def month_counts_from_feb(table, date_col):
    out = {}
    if not table_exists(table):
        return {}
    month_names = {1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",7:"Jul",8:"Ago",9:"Sep",10:"Oct",11:"Nov",12:"Dic"}
    try:
        data = rows(f"SELECT {date_col} FROM {table} ORDER BY id DESC LIMIT 5000")
        for r in data:
            s = str(r.get(date_col) or "").strip()
            if not s:
                continue
            if "T" in s:
                s = s.split("T")[0]
            if " " in s:
                s = s.split(" ")[0]
            dt = None
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(s[:10], fmt).date()
                    break
                except Exception:
                    pass
            if not dt:
                continue
            if dt.year < 2026:
                continue
            if dt.year == 2026 and dt.month < 2:
                continue
            key = f"{month_names.get(dt.month, str(dt.month))}-{str(dt.year)[-2:]}"
            out[key] = out.get(key, 0) + 1
    except Exception:
        return {}
    order = {"Ene":1,"Feb":2,"Mar":3,"Abr":4,"May":5,"Jun":6,"Jul":7,"Ago":8,"Sep":9,"Oct":10,"Nov":11,"Dic":12}
    def ok(k):
        try:
            m,y = k.split("-")
            return (2000+int(y), order.get(m, 99))
        except Exception:
            return (9999,99)
    return {k: out[k] for k in sorted(out, key=ok)}

def date_is_from_feb_2026(v):
    s = str(v or "").strip()
    if not s:
        return False
    if "T" in s:
        s = s.split("T")[0]
    if " " in s:
        s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(s[:10], fmt).date()
            return d >= datetime.strptime("2026-02-01", "%Y-%m-%d").date()
        except Exception:
            pass
    return False



def clean_equipo_field(v):
    """Limpia patente/VIN/motor. Si no hay dato real, deja blanco."""
    s = str(v or "").strip().replace('"', '').replace("\t", " ").strip()
    bad = {"", "no disponible", "no aplica", "sin patente", "no hay info", "no hay información", "nan", "none", "null"}
    if norm(s) in bad:
        return ""
    return " ".join(s.split())

def find_data_import_file(names):
    base = BASE_DIR / "data_import"
    if not base.exists():
        return None
    exact = {p.name.lower(): p for p in base.iterdir() if p.is_file()}
    for name in names:
        if name.lower() in exact:
            return exact[name.lower()]
    for p in base.iterdir():
        lname = p.name.lower()
        for name in names:
            key = name.lower().replace(".tsv", "").replace(".txt", "")
            if key and key in lname:
                return p
    return None

def parse_tsv_file(path):
    if not path or not Path(path).exists():
        return []
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    start = 0
    for i, line in enumerate(lines[:100]):
        low = line.lower()
        if "\t" in line and any(x in low for x in ["codigo", "código", "folio", "placa"]):
            start = i
            break
    if start >= len(lines):
        return []
    headers = [h.strip().replace("\ufeff", "") for h in lines[start].split("\t")]
    data = []
    for line in lines[start+1:]:
        if not line.strip() or "\t" not in line:
            continue
        parts = line.split("\t")
        row = {h: (parts[i].strip() if i < len(parts) else "") for i, h in enumerate(headers)}
        data.append(row)
    return data

def admin_importar_bodega_real_impl():
    path = find_data_import_file(["bodega_real.tsv", "bodega"])
    data = parse_tsv_file(path)
    if not data:
        return {"status": "ERROR", "mensaje": "No se encontró bodega_real.tsv", "archivo": str(path) if path else ""}

    try:
        if table_exists("bodega"):
            exec_sql("DELETE FROM bodega")
    except Exception:
        pass

    if not table_exists("bodega"):
        pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite() else "SERIAL PRIMARY KEY"
        exec_sql(f"""CREATE TABLE IF NOT EXISTS bodega (
            id {pk},
            fecha TEXT,
            codigo_equipo TEXT,
            ot_numero TEXT,
            repuesto TEXT,
            movimiento TEXT,
            observacion TEXT
        )""")

    n = 0
    for r in data:
        codigo = (r.get("Codigo") or r.get("Código") or r.get("Equipo") or "").strip().upper()
        if not codigo:
            continue
        fecha_val = r.get("Fecha") or ""
        if not date_is_from_feb_2026(fecha_val):
            continue
        folio = r.get("Folio") or ""
        envio = r.get("Envio") or r.get("Envío") or ""
        persona = r.get("Persona que retiro") or r.get("Persona que retiró") or ""
        destino = r.get("Destino") or ""
        comentario = r.get("Comentario") or ""
        detalle = " | ".join([x for x in [f"Retira: {persona}" if persona else "", f"Destino: {destino}" if destino else "", comentario] if x])
        exec_sql("""INSERT INTO bodega (fecha, codigo_equipo, ot_numero, repuesto, movimiento, observacion)
                    VALUES (:fecha, :codigo, :folio, :repuesto, 'Salida', :obs)""",
                 {"fecha": fecha(fecha_val), "codigo": codigo, "folio": folio, "repuesto": envio, "obs": detalle})
        n += 1
    return {"status": "OK", "archivo": str(path), "registros": n}

def admin_actualizar_datos_equipos_impl():
    path = find_data_import_file(["equipos_identificacion.tsv", "equipos"])
    data = parse_tsv_file(path)
    if not data:
        return {"status": "ERROR", "mensaje": "No se encontró equipos_identificacion.tsv", "archivo": str(path) if path else ""}
    if not table_exists("equipos"):
        return {"status": "ERROR", "mensaje": "No existe tabla equipos"}

    for c in ["patente", "vin", "motor"]:
        add_col("equipos", c, "TEXT")

    n = 0
    for r in data:
        codigo = (r.get("Código interno") or r.get("Codigo interno") or r.get("Código") or r.get("Codigo") or "").strip().upper()
        if not codigo:
            continue
        patente = clean_equipo_field(r.get("Placa"))
        vin = clean_equipo_field(r.get("N° Chasis") or r.get("N Chasis") or r.get("Chasis") or r.get("VIN"))
        motor = clean_equipo_field(r.get("N° Motor") or r.get("N Motor") or r.get("Motor"))
        exec_sql("""UPDATE equipos SET patente=:patente, vin=:vin, motor=:motor WHERE UPPER(codigo)=:codigo""",
                 {"patente": patente, "vin": vin, "motor": motor, "codigo": codigo})
        n += 1
    return {"status": "OK", "archivo": str(path), "registros": n}


# ============================================================
# GRÁFICOS
# ============================================================


def ubicaciones_reales_demotron():
    """Distribución oficial entregada por CMMS Excel."""
    return {
        "Asfalto": 4,
        "Cobquecura": 16,
        "Colbun": 5,
        "Emergencias Curico": 19,
        "Mantul": 1,
        "Ninhue": 2,
        "Obras Varias": 4,
        "Oficina": 7,
        "Palmucho": 38,
        "Pelluhue": 2,
        "Quirihue": 12,
        "RAUCO": 1,
        "Retiro": 2,
        "San Carlos": 14,
        "San Nicolas": 9,
        "SANTIAGO": 0,
        "Taller": 49,
        "Villaseca": 3,
    }

def date_is_from_feb_2026(v):
    s = str(v or "").strip()
    if not s:
        return False
    if "T" in s:
        s = s.split("T")[0]
    if " " in s:
        s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(s[:10], fmt).date()
            return d >= datetime.strptime("2026-02-01", "%Y-%m-%d").date()
        except Exception:
            pass
    return False


def donut(vals, colors, center, sub):
    total = sum(vals) or 1
    radius = 72
    circ = 2 * math.pi * radius
    offset = 0
    parts = []
    for v, c in zip(vals, colors):
        dash = float(v) / total * circ
        parts.append(f"<circle cx='110' cy='110' r='{radius}' fill='none' stroke='{c}' stroke-width='28' stroke-dasharray='{dash} {circ-dash}' stroke-dashoffset='{-offset}' transform='rotate(-90 110 110)'/>")
        offset += dash
    return f"<svg viewBox='0 0 220 220' class='donut'>{''.join(parts)}<circle cx='110' cy='110' r='49' fill='white'/><text x='110' y='105' text-anchor='middle' font-size='25'>{center}</text><text x='110' y='128' text-anchor='middle' font-size='13' fill='#64748b'>{sub}</text></svg>"


def filter_ubicaciones_dashboard(data):
    """Dashboard: solo ubicaciones con más de 4 equipos."""
    return {k: v for k, v in data.items() if int(v or 0) > 4}


def fixed_feb_to_may_2026(data):
    """Fuerza gráfico mensual a Feb-26, Mar-26, Abr-26 y May-26."""
    base = {"Feb-26": 0, "Mar-26": 0, "Abr-26": 0, "May-26": 0}
    for k, v in (data or {}).items():
        key = str(k).strip()
        if key in base:
            base[key] = int(v or 0)
        # tolerancia por si llega Febrero-26, Marzo-26, etc.
        lk = key.lower()
        if lk.startswith("feb"):
            base["Feb-26"] = int(v or 0)
        elif lk.startswith("mar"):
            base["Mar-26"] = int(v or 0)
        elif lk.startswith("abr") or lk.startswith("apr"):
            base["Abr-26"] = int(v or 0)
        elif lk.startswith("may"):
            base["May-26"] = int(v or 0)
    return base


def last_4_months(data):
    """Mantiene solo los últimos 4 meses disponibles en orden."""
    if not data:
        return {}
    items = list(data.items())
    return dict(items[-4:])


def bars(data, color="#1261d6"):
    if not data:
        return "<div class='empty'>Sin datos</div>"
    maxv = max(data.values()) or 1
    html = "<div class='bars'>"
    for label, val in data.items():
        h = max(8, int(float(val) / maxv * 160))
        html += f"<div class='barcol'><div class='barval'>{val}</div><div class='bar' style='height:{h}px;background:{color}'></div><small>{label}</small></div>"
    return html + "</div>"


# ============================================================
# CSS / LAYOUT
# ============================================================

CSS = """
<style>
:root{--navy:#082b5f;--bg:#f4f6fa;--line:#e5ebf3;--red:#ef3f45;--yellow:#f59e0b;--green:#16a34a;--blue:#1261d6;--purple:#7449d4;--teal:#07939a}*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Segoe UI,Arial;color:#0f172a;font-weight:400}.top{height:72px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:22px;padding:0 24px;position:sticky;top:0;z-index:20}.logoimg{height:48px;max-width:210px;object-fit:contain}.logotxt{font-size:28px;letter-spacing:8px;color:var(--navy)}.nav{display:flex;gap:16px;flex:1;overflow:auto}.nav a{font-weight:500;color:#334155;text-decoration:none;white-space:nowrap;padding:25px 0}.nav a.active{color:#0b56c5;border-bottom:3px solid #0b56c5}.search{height:40px;border:1px solid var(--line);border-radius:9px;padding:0 12px;min-width:220px}.logout{font-weight:500;color:#b91c1c;text-decoration:none}.wrap{padding:18px 24px}.kpis{display:grid;grid-template-columns:repeat(6,minmax(145px,1fr));gap:14px}.kpi{background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 18px rgba(9,30,66,.08);padding:15px;display:flex;gap:13px;align-items:center;min-height:86px}.ico{width:54px;height:54px;border-radius:50%;display:grid;place-items:center;color:white;font-size:23px;font-weight:500}.red{background:var(--red)}.yellow{background:var(--yellow)}.green{background:var(--green)}.blue{background:var(--blue)}.purple{background:var(--purple)}.teal{background:var(--teal)}.gray{background:#94a3b8}.kpi small{font-size:11px;color:#475569;font-weight:500}.kpi b{display:block;font-size:24px;font-weight:500}.kpi span{font-size:12px;color:#64748b}.grid{display:grid;grid-template-columns:1fr 1fr 1.05fr;gap:14px;margin-top:14px}.panel{background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 18px rgba(9,30,66,.08);padding:17px;margin-bottom:14px}.panel h3{margin:0 0 12px;font-size:16px;font-weight:500}.donut{width:220px;height:220px;display:block;margin:auto}.legend{display:grid;gap:9px;margin-top:8px}.legend div{display:flex;justify-content:space-between;font-size:13px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px}.bars{height:220px;display:flex;align-items:end;gap:18px;justify-content:space-around;padding-top:20px}.barcol{text-align:center;min-width:58px}.bar{width:38px;margin:0 auto 8px;border-radius:6px 6px 0 0}.barval{font-size:12px;font-weight:500}.barcol small{font-size:11px;color:#475569;display:block;max-width:85px;overflow:hidden;text-overflow:ellipsis}.split{display:grid;grid-template-columns:2fr 1.15fr;gap:14px;margin-top:14px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px;border-bottom:1px solid #eef2f7;text-align:left;vertical-align:middle;font-weight:400}th{font-size:12px;color:#334155;font-weight:500}.code{font-weight:500;color:var(--navy)}.pill{border-radius:999px;padding:5px 10px;font-weight:500;font-size:11px;display:inline-block}.pill.red{background:#ffe1e3;color:#b91c1c}.pill.yellow{background:#fff4cc;color:#a16207}.pill.green{background:#dcfce7;color:#15803d}.pill.gray{background:#e5e7eb;color:#475569}.eqimg{width:92px;height:56px;object-fit:contain}.cards{display:flex;gap:14px;overflow-x:auto;padding:8px 0 14px}.card{min-width:178px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px;text-align:center;text-decoration:none;color:#0f172a}.card img{width:135px;height:84px;object-fit:contain}.card.red{border-color:var(--red)}.card.yellow{border-color:var(--yellow)}.card.green{border-color:#bbf7d0}.card.gray{opacity:.55}.formgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.formgrid input,.formgrid select{height:38px;border:1px solid var(--line);border-radius:8px;padding:0 10px}.btn{background:var(--navy);color:white;border:0;text-decoration:none;border-radius:8px;padding:8px 12px;font-weight:500;display:inline-block;cursor:pointer}.specgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.spec,.techbox{background:#f8fafc;border:1px solid var(--line);border-radius:9px;padding:12px}.spec small{display:block;color:#64748b}.hero{display:grid;grid-template-columns:330px 1fr;gap:18px}.hero img{width:320px;height:220px;object-fit:contain;background:#fff;border:1px solid var(--line);border-radius:12px}.tech{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}.techbox h4{margin:0 0 8px;color:var(--navy);font-weight:500}.fleet-search input{height:38px;width:340px;max-width:100%;border:1px solid var(--line);border-radius:8px;padding:0 10px;margin-bottom:12px}.foot{height:56px;background:var(--navy);color:white;display:flex;align-items:center;justify-content:center;padding:0 24px;margin-top:18px;font-size:14px}
.grid{grid-template-columns:repeat(3,minmax(0,1fr));align-items:stretch}
.panel{min-width:0;overflow:hidden}
.bars{width:100%;max-width:100%;overflow:hidden;gap:10px}
.barcol{min-width:0;flex:1}
.barcol small{max-width:100%;white-space:normal;line-height:1.15}
@media(max-width:1200px){.kpis{grid-template-columns:repeat(3,1fr)}.grid,.split,.hero{grid-template-columns:1fr}.formgrid,.specgrid,.tech{grid-template-columns:repeat(2,1fr)}}@media(max-width:760px){.kpis,.formgrid,.specgrid,.tech{grid-template-columns:1fr}.nav,.search{display:none}.wrap{padding:12px}.logoimg{height:38px}}
</style>
"""

def logo_html():
    if (BASE_DIR / "static" / "logo_demotron.png").exists():
        return "<img src='/static/logo_demotron.png' class='logoimg' alt='DEMOTRON'>"
    if (BASE_DIR / "static" / "logo_demotron.svg").exists():
        return "<img src='/static/logo_demotron.svg' class='logoimg' alt='DEMOTRON'>"
    return "<div class='logotxt'>DEMOTRON</div>"

def top(active):
    items = [("Dashboard","/erp"),("Equipos","/equipos"),("Lecturas","/lecturas"),("OT","/ot"),("Compras","/compras"),("Bodega","/bodega")]
    links = "".join([f"<a class='{'active' if n == active else ''}' href='{u}'>{n}</a>" for n,u in items])
    return f"<header class='top'>{logo_html()}<nav class='nav'>{links}</nav><input class='search' placeholder='Buscar...'><a class='logout' href='/logout'>Cerrar sesión</a></header>"

def footer():
    return "<footer class='foot'>Demotron Maquinarias CMMS Manuel Ortiz 2026 · mantencion@demotron.cl</footer>"

def page(title, active, body):
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title><link rel='icon' href='/favicon.ico'>{CSS}</head><body>{top(active)}<main class='wrap'>{body}</main>{footer()}</body></html>"



# ============================================================
# IMPORTADOR REAL PM / OC
# ============================================================

def date_iso(v):
    s = str(v or "").strip()
    if not s:
        return ""
    if "T" in s:
        s = s.split("T")[0]
    if " " in s:
        s = s.split(" ")[0]
    s = s.replace("/", "-")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%m-%y"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except Exception:
            pass
    return s

def data_file(name):
    p = BASE_DIR / "data_import" / name
    return p if p.exists() else None

def read_tsv_after_header(path, required_first):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    start = None
    for i, line in enumerate(raw):
        if line.strip().startswith(required_first):
            start = i
            break
    if start is None:
        return []
    text = "\n".join(raw[start:])
    return list(csv.DictReader(text.splitlines(), delimiter="\t"))

def ensure_pm_tables():
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite() else "SERIAL PRIMARY KEY"
    if not table_exists("compras"):
        exec_sql(f"""CREATE TABLE compras (
            id {pk}, fecha TEXT, codigo_equipo TEXT, oc TEXT, proveedor TEXT,
            item TEXT, estado TEXT, costo_total TEXT, cantidad TEXT, observacion TEXT
        )""")
    for c in ["fecha","codigo_equipo","oc","proveedor","item","estado","costo_total","cantidad","observacion"]:
        add_col("compras", c, "TEXT")

    if not table_exists("ot"):
        exec_sql(f"""CREATE TABLE ot (
            id {pk}, numero TEXT, codigo TEXT, tipo TEXT, estado TEXT,
            fecha_creacion TEXT, fecha_cierre TEXT, lectura TEXT, descripcion TEXT,
            costo_estimado TEXT, prioridad TEXT, responsable TEXT
        )""")
    for c in ["numero","codigo","tipo","estado","fecha_creacion","fecha_cierre","lectura","descripcion","costo_estimado","prioridad","responsable"]:
        add_col("ot", c, "TEXT")

def import_compras_pm_reales():
    ensure_pm_tables()
    path = data_file("compras_pm_reales.tsv")
    if not path:
        return 0
    data = read_tsv_after_header(path, "Fecha\tOC")
    exec_sql("DELETE FROM compras")
    n = 0
    for r in data:
        fecha_raw = r.get("Fecha") or ""
        oc = (r.get("OC") or "").strip()
        if not fecha_raw or not oc:
            continue
        codigo = (r.get("Codigo") or r.get("Código") or "").strip().upper()
        desc = (r.get("Descripcion") or r.get("Descripción") or "").strip()
        proveedor = (r.get("Proveedor") or "").strip()
        costo = nfloat(r.get("Costo PM CLP") or r.get(" Costo PM CLP ") or r.get("Costo") or "0")
        regla = (r.get("Regla") or "").strip()
        estado_oc = (r.get("Estado OC") or "").strip()
        exec_sql("""INSERT INTO compras
            (fecha, codigo_equipo, oc, proveedor, item, estado, costo_total, cantidad, observacion)
            VALUES (:fecha, :codigo, :oc, :proveedor, :item, :estado, :costo, :cantidad, :obs)""",
            {"fecha": date_iso(fecha_raw), "codigo": codigo, "oc": oc, "proveedor": proveedor,
             "item": desc, "estado": estado_oc, "costo": str(costo), "cantidad": "1", "obs": regla})
        n += 1
    return n

def import_mantenciones_pm_reales():
    ensure_pm_tables()
    path = data_file("mantenciones_reales.tsv")
    if not path:
        return 0
    data = read_tsv_after_header(path, "Fecha\tCodigo")
    exec_sql("DELETE FROM ot")
    used = {}
    n = 0
    for r in data:
        fecha_raw = r.get("Fecha") or ""
        codigo = (r.get("Codigo") or r.get("Código") or "").strip().upper()
        if not fecha_raw or not codigo:
            continue
        espm = norm(r.get("EsPM") or r.get("Es PM") or "")
        if espm and espm not in ("si", "sí", "s"):
            continue
        folio = (r.get("Folio") or "").strip()
        base_num = folio if folio and norm(folio) not in ("sn", "nn", "n/a") else f"PM2-{n+1:04d}"
        used[base_num] = used.get(base_num, 0) + 1
        numero = base_num if used[base_num] == 1 else f"{base_num}-{used[base_num]}"
        tipo_original = (r.get("Tipo Mantencion") or r.get("Tipo Mantención") or "").strip()
        lectura = (r.get("Lectura") or "").strip()
        lugar = (r.get("Lugar") or "").strip()
        proveedor = (r.get("Proveedor") or "").strip()
        costo = nfloat(r.get(" Costo Mantencion CLP ") or r.get("Costo Mantencion CLP") or r.get("Costo Mantención CLP") or "0")
        estado = (r.get("Estado") or "Finalizada").strip() or "Finalizada"
        desc = f"Mantención preventiva PM2 | Original: {tipo_original} | Lugar: {lugar} | Folio: {folio}"
        exec_sql("""INSERT INTO ot
            (numero, codigo, tipo, estado, fecha_creacion, fecha_cierre, lectura, descripcion, costo_estimado, prioridad, responsable)
            VALUES (:numero, :codigo, 'PM2', :estado, :fecha, :fecha_cierre, :lectura, :desc, :costo, 'Normal', :responsable)""",
            {"numero": numero, "codigo": codigo, "estado": estado, "fecha": date_iso(fecha_raw),
             "fecha_cierre": date_iso(fecha_raw) if norm(estado).startswith("final") else "", "lectura": lectura,
             "desc": desc, "costo": str(costo), "responsable": proveedor})
        n += 1
    return n


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def root():
    return redirect("/erp")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/erp")

@app.route("/favicon.ico")
def favicon():
    svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='12' fill='#082b5f'/><text x='32' y='42' text-anchor='middle' font-family='Arial' font-size='26' fill='white'>D</text></svg>"
    return Response(svg, mimetype="image/svg+xml")

@app.route("/admin/version")
def admin_version():
    return jsonify({"status":"OK", "version":APP_VERSION, "database":"sqlite" if is_sqlite() else "postgresql"})

@app.route("/admin/diagnostico")
def admin_diag():
    ensure_schema()
    return jsonify({
        "status":"OK",
        "version":APP_VERSION,
        "cmms_excel":count_table("cmms_excel"),
        "equipos":count_table("equipos"),
        "lecturas":count_table("lecturas"),
        "ot":count_table("ot"),
        "compras":count_table("compras"),
        "bodega":count_table("bodega"),
        "kpi":kpis(),
        "legacy_routes_removed": True
    })


@app.route("/admin/importar_pm_reales")
def admin_importar_pm_reales():
    ensure_schema()
    compras = import_compras_pm_reales()
    mantenciones = import_mantenciones_pm_reales()
    return jsonify({
        "status": "OK",
        "version": APP_VERSION,
        "compras_reales_importadas": compras,
        "mantenciones_pm2_importadas": mantenciones,
        "mensaje": "OC reales reemplazadas y OT reconstruidas solo con mantenciones PM2."
    })

@app.route("/admin/diagnostico_pm_reales")
def admin_diag_pm_reales():
    return jsonify({
        "status": "OK",
        "version": APP_VERSION,
        "compras": count_table("compras"),
        "ot": count_table("ot"),
        "archivo_compras": str(data_file("compras_pm_reales.tsv") or "NO ENCONTRADO"),
        "archivo_mantenciones": str(data_file("mantenciones_reales.tsv") or "NO ENCONTRADO")
    })


@app.route("/admin/importar_bodega_real")
def admin_importar_bodega_real():
    return jsonify(admin_importar_bodega_real_impl())

@app.route("/admin/actualizar_datos_equipos")
def admin_actualizar_datos_equipos():
    return jsonify(admin_actualizar_datos_equipos_impl())

@app.route("/admin/importar_bodega_y_equipos_reales")
def admin_importar_bodega_y_equipos_reales():
    bodega = admin_importar_bodega_real_impl()
    equipos = admin_actualizar_datos_equipos_impl()
    return jsonify({"status": "OK", "version": APP_VERSION, "bodega": bodega, "equipos": equipos})

@app.route("/compras/descargar")
def descargar_compras_csv():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Fecha", "Código Equipo", "OC", "Proveedor", "Item", "Estado", "Costo"])
    data = rows("SELECT * FROM compras ORDER BY fecha DESC, id DESC") if table_exists("compras") else []
    for r in data:
        writer.writerow([fecha(r.get("fecha")), r.get("codigo_equipo",""), r.get("oc",""), r.get("proveedor",""), r.get("item",""), r.get("estado",""), clp(nfloat(r.get("costo_total")))])
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=compras_oc_demotron.csv"
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    return resp

@app.route("/erp")
def dashboard():
    ensure_schema()
    data = cmms_rows()
    k = kpis()
    total = float(k["total"] or 1)

    ubic = filter_ubicaciones_dashboard(ubicaciones_reales_demotron())

    compras_mes = fixed_feb_to_may_2026(month_counts_from_feb("compras", "fecha"))
    ot_mes = fixed_feb_to_may_2026(month_counts_from_feb("ot", "fecha_creacion"))
    crit = [r for r in data if sem(r) in ("red", "yellow")]

    def fleet_sort(r):
        cod = str(r.get("codigo") or "")
        rank = 0 if cod.startswith("MD-") else 1 if cod.startswith("CD-") else 2 if cod.startswith("EQP") else 3 if cod.startswith("VD-") else 4
        return (rank, cod)

    fleet = sorted(data, key=fleet_sort)

    body = f"""
    <section class='kpis'>
        <div class='kpi'><div class='ico blue'>▣</div><div><small>Total Equipos</small><b>{k['total']}</b><span>100%</span></div></div>
        <div class='kpi'><div class='ico green'>✓</div><div><small>Operativos</small><b>{k['operativos']}</b><span>{pct(k['operativos'], total)}%</span></div></div>
        <div class='kpi'><div class='ico red'>!</div><div><small>Atrasados</small><b>{k['atrasados']}</b><span>{pct(k['atrasados'], total)}%</span></div></div>
        <div class='kpi'><div class='ico yellow'>◷</div><div><small>Próximas</small><b>{k['proximas']}</b><span>{pct(k['proximas'], total)}%</span></div></div>
        <div class='kpi'><div class='ico purple'>%</div><div><small>Controlado</small><b>{k['controlado']}</b><span>Cumplimiento {k['cumplimiento_real']}</span></div></div>
        <div class='kpi'><div class='ico teal'>$</div><div><small>Costo Total PM</small><b>{clp(k['costo_total_pm'])}</b><span>CLP</span></div></div>
    </section>

    <section class='grid'>
        <div class='panel'><h3>Estado de Equipos</h3>
            {donut([k['al_dia'], k['en_proceso'], k['atrasados'], k['fuera']], ['#16a34a','#f59e0b','#ef3f45','#94a3b8'], k['total'], 'Total')}
            <div class='legend'>
                <div><span><i class='dot' style='background:#16a34a'></i>Al día</span><span>{k['al_dia']}</span></div>
                <div><span><i class='dot' style='background:#f59e0b'></i>En proceso</span><span>{k['en_proceso']}</span></div>
                <div><span><i class='dot' style='background:#ef3f45'></i>Atrasados</span><span>{k['atrasados']}</span></div>
                <div><span><i class='dot' style='background:#94a3b8'></i>Fuera servicio</span><span>{k['fuera']}</span></div>
            </div>
        </div>
        <div class='panel'><h3>Equipos por Ubicación</h3>{bars(ubic, '#1261d6')}</div>
        <div class='panel'><h3>Costos de Mantención</h3>
            <div class='kpi' style='box-shadow:none;border:0'><div class='ico teal'>$</div><div><small>Costo Total PM</small><b>{clp(k['costo_total_pm'])}</b><span>Pesos chilenos</span></div></div>
            <table><tr><th>Este Mes</th><th>Mes Anterior</th></tr><tr><td>{clp(float(k['costo_total_pm'])*0.28)}</td><td>{clp(float(k['costo_total_pm'])*0.72)}</td></tr></table>
        </div>
    </section>

    <section class='grid'>
        <div class='panel'><h3>Compras por Mes</h3>{bars(compras_mes, '#7449d4')}</div>
        <div class='panel'><h3>OT por Mes</h3>{bars(ot_mes, '#07939a')}</div>
        <div class='panel'><h3>KPI Mantenimiento</h3>
            <table>
                <tr><th>KPI</th><th>Número</th><th>%</th></tr>
                <tr><td><span class='pill green'>Al Día</span></td><td>{k['al_dia']}</td><td>{pct(k['al_dia'], total)}%</td></tr>
                <tr><td><span class='pill red'>Atrasados</span></td><td>{k['atrasados']}</td><td>{pct(k['atrasados'], total)}%</td></tr>
                <tr><td><span class='pill yellow'>Próximas</span></td><td>{k['proximas']}</td><td>{pct(k['proximas'], total)}%</td></tr>
                <tr><td><span class='pill gray'>Disponibilidad</span></td><td>{k['operativos']}</td><td>{k['disponibilidad_real']}</td></tr>
            </table>
        </div>
    </section>

    <section class='panel'>
        <h3>Equipos Críticos</h3>
        <table>
            <tr><th>Imagen</th><th>Código</th><th>Equipo</th><th>Lectura</th><th>Última Mantención</th><th>Estado</th><th>Ficha</th></tr>
    """
    for r in crit[:10]:
        body += f"<tr><td><img class='eqimg' src='{img_url(r)}'></td><td class='code'>{r.get('codigo','')}</td><td>{r.get('tipo_equipo','')}</td><td>{r.get('lectura_actual','')} {r.get('control_base','')}</td><td>{fecha(r.get('ultima_fecha_pm'))}</td><td><span class='pill {sem(r)}'>{estado(r)}</span></td><td><a class='btn' href='/equipo/{r.get('codigo','')}'>Abrir</a></td></tr>"
    body += "</table></section>"

    body += """
    <section class='panel'>
        <h3>Flota de Equipos</h3>
        <div class='fleet-search'><input id='fleetSearch' onkeyup='filterFleet()' placeholder='Buscar equipo por código, tipo, marca o ubicación...'></div>
        <div class='cards' id='fleetCards'>
    """
    for r in fleet[:300]:
        body += f"<a class='card {sem(r)}' href='/equipo/{r.get('codigo','')}' data-search='{r.get('codigo','')} {r.get('tipo_equipo','')} {r.get('marca','')} {r.get('ubicacion','')}'><img src='{img_url(r)}'><span class='code'>{r.get('codigo','')}</span><div>{r.get('tipo_equipo','')}</div><small>{r.get('control_base','')} · {r.get('lectura_actual','')}</small></a>"
    body += """
        </div>
        <script>
            function filterFleet(){
                const q = document.getElementById('fleetSearch').value.toLowerCase();
                document.querySelectorAll('#fleetCards .card').forEach(c => {
                    c.style.display = c.dataset.search.toLowerCase().includes(q) ? 'block' : 'none';
                });
            }
        </script>
    </section>
    """
    return page("Dashboard DEMOTRON CMMS", "Dashboard", body)

def form_page(title, active, form_html, table_html):
    return page(title, active, f"<section class='panel'><h3>Agregar Nuevo Registro</h3>{form_html}</section><section class='panel'><h3>{title}</h3>{table_html}</section>")

@app.route("/equipos", methods=["GET","POST"])
def equipos_page():
    ensure_schema()
    if request.method == "POST":
        try:
            exec_sql("""INSERT INTO equipos (codigo,descripcion,marca,modelo,patente,vin,motor,estado_operacional,control_base,lectura_actual)
                        VALUES (:codigo,:descripcion,:marca,:modelo,:patente,:vin,:motor,:estado,'HORAS','0')""", dict(request.form))
        except Exception:
            pass
        return redirect("/equipos")

    form = "<form method='post' class='formgrid'><input name='codigo' placeholder='Código'><input name='descripcion' placeholder='Descripción'><input name='marca' placeholder='Marca'><input name='modelo' placeholder='Modelo'><input name='patente' placeholder='Patente'><input name='vin' placeholder='VIN / Chasis'><input name='motor' placeholder='Número Motor'><select name='estado'><option>Operativo</option><option>Taller</option><option>Fuera de Servicio</option></select><button class='btn'>Agregar Equipo</button></form>"
    data = rows("SELECT * FROM equipos ORDER BY codigo LIMIT 1000") if table_exists("equipos") else []
    table = "<table><tr><th>Código</th><th>Descripción</th><th>Marca</th><th>Modelo</th><th>Patente</th><th>VIN / Chasis</th><th>Número Motor</th><th>Estado</th><th>Ficha</th></tr>"
    for r in data:
        table += f"<tr><td class='code'>{r.get('codigo','')}</td><td>{r.get('descripcion') or r.get('tipo_equipo','')}</td><td>{r.get('marca','')}</td><td>{r.get('modelo','')}</td><td>{r.get('patente','')}</td><td>{r.get('vin','')}</td><td>{r.get('motor','')}</td><td>{r.get('estado_operacional','')}</td><td><a class='btn' href='/equipo/{r.get('codigo','')}'>Abrir</a></td></tr>"
    table += "</table>"
    return form_page("Equipos", "Equipos", form, table)

@app.route("/lecturas", methods=["GET","POST"])
def lecturas_page():
    if request.method == "POST":
        try:
            exec_sql("INSERT INTO lecturas (codigo,fecha,tipo_lectura,valor,ubicacion,responsable) VALUES (:codigo,:fecha,:tipo_lectura,:valor,:ubicacion,:responsable)", dict(request.form))
        except Exception:
            pass
        return redirect("/lecturas")

    form = "<form method='post' class='formgrid'><input name='codigo' placeholder='Código Equipo'><input name='fecha' type='date'><select name='tipo_lectura'><option>Kilometraje</option><option>Odómetro</option><option>Horómetro</option></select><input name='valor' placeholder='Valor'><input name='ubicacion' placeholder='Ubicación'><input name='responsable' placeholder='Responsable'><button class='btn'>Agregar Lectura</button></form>"
    data = rows("SELECT * FROM lecturas ORDER BY id DESC LIMIT 1000") if table_exists("lecturas") else []
    table = "<table><tr><th>Fecha</th><th>Código</th><th>Kilometraje</th><th>Odómetro</th><th>Horómetro</th><th>Ubicación</th><th>Responsable</th></tr>"
    for r in data:
        tipo = str(r.get("tipo_lectura") or "").lower()
        val = r.get("valor","")
        km = val if "kilo" in tipo or "km" in tipo else ""
        odo = val if "odo" in tipo else ""
        hrs = val if "horo" in tipo or "hora" in tipo else ""
        table += f"<tr><td>{fecha(r.get('fecha'))}</td><td class='code'>{r.get('codigo','')}</td><td>{km}</td><td>{odo}</td><td>{hrs}</td><td>{r.get('ubicacion','')}</td><td>{r.get('responsable','')}</td></tr>"
    table += "</table>"
    return form_page("Lecturas", "Lecturas", form, table)

@app.route("/ot", methods=["GET","POST"])
def ot_page():
    if request.method == "POST":
        try:
            exec_sql("INSERT INTO ot (numero,codigo,tipo,estado,fecha_creacion,descripcion,costo_estimado) VALUES (:numero,:codigo,:tipo,:estado,:fecha,:descripcion,:costo)", dict(request.form))
        except Exception:
            pass
        return redirect("/ot")

    form = "<form method='post' class='formgrid'><input name='numero' placeholder='Número'><input name='codigo' placeholder='Código Equipo'><select name='tipo'><option>PM1</option><option>PM2</option><option>PM3</option><option>PM4</option></select><select name='estado'><option>Abierta</option><option>En Proceso</option><option>Cerrada</option></select><input name='fecha' type='date'><input name='descripcion' placeholder='Descripción'><input name='costo' placeholder='Costo'><button class='btn'>Agregar OT</button></form>"
    data = []
    if table_exists("ot"):
        data = rows("SELECT * FROM ot ORDER BY id DESC LIMIT 1000")
    table = "<table><tr><th>Número</th><th>Código</th><th>Tipo</th><th>Estado</th><th>Fecha</th><th>Descripción</th><th>Costo</th></tr>"
    for r in data:
        table += f"<tr><td class='code'><a href='/ot/{r.get('numero','')}'>{r.get('numero','')}</a></td><td>{r.get('codigo','')}</td><td>{r.get('tipo','')}</td><td>{r.get('estado','')}</td><td>{fecha(r.get('fecha_creacion'))}</td><td>{r.get('descripcion','')}</td><td>{clp(nfloat(r.get('costo_estimado')))}</td></tr>"
    table += "</table>"
    return form_page("Órdenes de Trabajo", "OT", form, table)

@app.route("/compras", methods=["GET","POST"])
def compras_page():
    if request.method == "POST":
        try:
            exec_sql("INSERT INTO compras (fecha,codigo_equipo,oc,proveedor,item,estado,costo_total) VALUES (:fecha,:codigo_equipo,:oc,:proveedor,:item,:estado,:costo)", dict(request.form))
        except Exception:
            pass
        return redirect("/compras")

    form = "<form method='post' class='formgrid'><input name='fecha' type='date'><input name='codigo_equipo' placeholder='Código Equipo'><input name='oc' placeholder='OC DEMO-02-xxxx'><input name='proveedor' placeholder='Proveedor'><input name='item' placeholder='Item'><select name='estado'><option>En Proceso</option><option>Por Recibir</option><option>Cerrado</option></select><input name='costo' placeholder='Costo'><button class='btn'>Agregar Compra</button></form>"
    data = rows("SELECT * FROM compras ORDER BY id DESC OFFSET 5 LIMIT 1000") if table_exists("compras") else []
    table = "<table><tr><th>Fecha</th><th>Código Equipo</th><th>OC</th><th>Proveedor</th><th>Item</th><th>Estado</th><th>Costo</th></tr>"
    for r in data:
        table += f"<tr><td>{fecha(r.get('fecha'))}</td><td>{r.get('codigo_equipo','')}</td><td class='code'>{r.get('oc','')}</td><td>{r.get('proveedor','')}</td><td>{r.get('item','')}</td><td>{r.get('estado','')}</td><td>{clp(nfloat(r.get('costo_total')))}</td></tr>"
    table += "</table>"
    form += "<div style='margin-top:10px'><a class='btn' href='/compras/descargar'>Descargar OC</a></div>"
    return form_page("Compras / OC", "Compras", form, table)

@app.route("/bodega", methods=["GET","POST"])
def bodega_page():
    if request.method == "POST":
        try:
            exec_sql("INSERT INTO bodega (fecha,codigo_equipo,ot_numero,repuesto,movimiento,observacion) VALUES (:fecha,:codigo_equipo,:ot_numero,:repuesto,:movimiento,:observacion)", dict(request.form))
        except Exception:
            pass
        return redirect("/bodega")

    form = "<form method='post' class='formgrid'><input name='fecha' type='date'><input name='codigo_equipo' placeholder='Código de Equipo'><input name='ot_numero' placeholder='Folio'><input name='repuesto' placeholder='Repuesto'><select name='movimiento'><option>Ingreso</option><option>Salida</option></select><input name='observacion' placeholder='Detalle'><button class='btn'>Agregar Bodega</button></form>"
    raw_bodega = rows("SELECT * FROM bodega ORDER BY id DESC LIMIT 2000") if table_exists("bodega") else []
    data = [r for r in raw_bodega if date_is_from_feb_2026(r.get("fecha"))]
    table = "<table><tr><th>Fecha</th><th>Código de Equipo</th><th>Folio</th><th>Repuesto</th><th>Movimiento</th><th>Detalle</th></tr>"
    for r in data:
        table += f"<tr><td>{fecha(r.get('fecha'))}</td><td>{r.get('codigo_equipo','')}</td><td>{r.get('ot_numero','')}</td><td>{r.get('repuesto','')}</td><td>{r.get('movimiento','')}</td><td>{r.get('observacion','')}</td></tr>"
    table += "</table>"
    return form_page("Bodega", "Bodega", form, table)

@app.route("/reportes")
def reportes_page():
    return redirect("/erp")

def tecnica(r):
    tipo = norm(r.get("tipo_equipo"))
    marca = r.get("marca","")
    modelo = r.get("modelo","")
    frec = r.get("frecuencia_base","250")
    base = [
        ("Identificación", [f"Equipo: {marca} {modelo}", f"Control base: {r.get('control_base','')}", f"Frecuencia CMMS: {frec}"]),
        ("Mantención Preventiva", ["Aceite motor, filtros y revisión general.", "Registrar lectura real antes y después de cada PM.", "Cerrar OT con evidencia y costo asociado."]),
        ("Seguridad", ["Checklist operacional, luces, alarma, extintor y documentación.", "Revisar fugas, estado estructural y protecciones."]),
    ]
    if "excav" in tipo:
        base.insert(1, ("Sistema Hidráulico", ["Control de bombas, cilindros, mangueras y pilotaje.", "Revisar contaminación de aceite y filtros hidráulicos."]))
        base.insert(2, ("Tren de Rodaje y Estructura", ["Inspección de cadenas, rodillos, tensores, pluma, brazo y balde.", "Control de pasadores, bujes, fisuras y holguras."]))
    elif "cam" in tipo or str(r.get("codigo") or "").startswith("CD-"):
        base.insert(1, ("Tren Motriz", ["Motor, transmisión, diferencial, cardanes y dirección.", "Control de frenos, líneas de aire y suspensión."]))
        base.insert(2, ("Equipo Especial", ["Tolva, pluma, aljibe o sistema hidráulico según configuración.", "Revisar cilindros, toma fuerza, mangueras y estructura."]))
    return base


@app.route("/ot/<numero>")
def ot_detalle(numero):
    if not table_exists("ot"):
        return page("OT no encontrada", "OT", "<section class='panel'><h3>OT no encontrada</h3></section>"), 404

    try:
        ot = one("SELECT * FROM ot WHERE numero=:n ORDER BY id DESC LIMIT 1", {"n": numero})
    except Exception:
        ot = None

    if not ot:
        return page("OT no encontrada", "OT", "<section class='panel'><h3>OT no encontrada</h3></section>"), 404

    codigo = str(ot.get("codigo") or "").upper()
    equipo = find_equipo(codigo) if codigo else None
    estado_ot = str(ot.get("estado") or "").upper()
    sem_ot = "green" if "CERR" in estado_ot or "EJEC" in estado_ot else ("yellow" if "PROCESO" in estado_ot else "red")

    body = f"""
    <section class='panel'>
        <h3>Orden de Trabajo</h3>
        <div class='specgrid'>
            <div class='spec'><small>Número</small><div>{ot.get('numero','')}</div></div>
            <div class='spec'><small>Código Equipo</small><div>{codigo}</div></div>
            <div class='spec'><small>Tipo</small><div>{ot.get('tipo','')}</div></div>
            <div class='spec'><small>Estado</small><div><span class='pill {sem_ot}'>{ot.get('estado','')}</span></div></div>
            <div class='spec'><small>Fecha</small><div>{fecha(ot.get('fecha_creacion'))}</div></div>
            <div class='spec'><small>Fecha Cierre</small><div>{fecha(ot.get('fecha_cierre'))}</div></div>
            <div class='spec'><small>Lectura</small><div>{ot.get('lectura','')}</div></div>
            <div class='spec'><small>Costo</small><div>{clp(nfloat(ot.get('costo_estimado')))}</div></div>
        </div>
    </section>

    <section class='panel'>
        <h3>Alcance Técnico</h3>
        <div class='tech'>
            <div class='techbox'><h4>Trabajo Solicitado</h4><ul><li>{ot.get('descripcion','Sin descripción registrada.')}</li></ul></div>
            <div class='techbox'><h4>Estándar de Ejecución</h4><ul><li>Bloqueo, seguridad y verificación del equipo antes de intervenir.</li><li>Registro de lectura real y evidencia técnica.</li><li>Cierre con costo, responsable y condición final.</li></ul></div>
            <div class='techbox'><h4>Control de Calidad</h4><ul><li>Verificación visual de fugas, niveles, fijaciones y operación.</li><li>Prueba funcional antes de liberar el equipo.</li></ul></div>
            <div class='techbox'><h4>Estándar Minería / Alto Rendimiento</h4><ul><li>Trazabilidad completa de repuestos, compras, lecturas y mantención.</li><li>Estado final claro: operativo, seguimiento, taller o fuera de servicio.</li></ul></div>
        </div>
    </section>
    """

    if equipo:
        body += f"""
        <section class='panel hero'>
            <div><img src='{img_url(equipo)}'><h2 class='code'>{codigo}</h2><span class='pill {sem(equipo)}'>{estado(equipo)}</span></div>
            <div><h3>Equipo Asociado</h3><div class='specgrid'>
                <div class='spec'><small>Equipo</small><div>{equipo.get('tipo_equipo','')}</div></div>
                <div class='spec'><small>Marca</small><div>{equipo.get('marca','')}</div></div>
                <div class='spec'><small>Modelo</small><div>{equipo.get('modelo','')}</div></div>
                <div class='spec'><small>Ubicación</small><div>{equipo.get('ubicacion','')}</div></div>
                <div class='spec'><small>Control Base</small><div>{equipo.get('control_base','')}</div></div>
                <div class='spec'><small>Lectura Actual</small><div>{equipo.get('lectura_actual','')}</div></div>
                <div class='spec'><small>Última Mantención</small><div>{fecha(equipo.get('ultima_fecha_pm'))}</div></div>
                <div class='spec'><small>Costo PM</small><div>{equipo.get('costo_total_pm_clp','')}</div></div>
            </div></div>
        </section>
        """

    compras = []
    lecturas = []
    try:
        if table_exists("compras"):
            compras = rows("SELECT * FROM compras WHERE codigo_equipo=:c ORDER BY id DESC LIMIT 20", {"c": codigo})
    except Exception:
        compras = []
    try:
        if table_exists("lecturas"):
            lecturas = rows("SELECT * FROM lecturas WHERE codigo=:c ORDER BY id DESC LIMIT 20", {"c": codigo})
    except Exception:
        lecturas = []

    def mini_table(title, data, cols):
        out = f"<section class='panel'><h3>{title}</h3><table><tr>" + "".join(f"<th>{friendly(c)}</th>" for c in cols) + "</tr>"
        if not data:
            out += f"<tr><td colspan='{len(cols)}'>Sin registros asociados.</td></tr>"
        for row in data:
            out += "<tr>"
            for c in cols:
                val = row.get(c, "")
                if "fecha" in c:
                    val = fecha(val)
                if "costo" in c:
                    val = clp(nfloat(val))
                out += f"<td>{val}</td>"
            out += "</tr>"
        return out + "</table></section>"

    body += mini_table("Compras / OC Asociadas al Equipo", compras, ["fecha","oc","proveedor","item","cantidad","costo_total","estado"])
    body += mini_table("Lecturas Recientes del Equipo", lecturas, ["fecha","tipo_lectura","valor","ubicacion","responsable"])

    return page(f"OT {numero}", "OT", body)



@app.route("/plan_mantencion/<codigo>")
def plan_mantencion(codigo):
    codigo = codigo.upper()
    body = f"""
    <section class='panel'>
        <h3>Plan de Mantención DEMOTRON</h3>
        <p>Equipo: <span class='code'>{codigo}</span></p>
        <p>Este módulo queda preparado para cargar el plan de mantención DEMOTRON cuando subamos el archivo correspondiente.</p>
        <a class='btn' href='/equipo/{codigo}'>Volver a Ficha del Equipo</a>
    </section>
    """
    return page(f"Plan de Mantención {codigo}", "Equipos", body)

@app.route("/equipo/<codigo>")
def ficha_equipo(codigo):
    codigo = codigo.upper()
    r = find_equipo(codigo)
    if not r:
        return page("Equipo no encontrado", "Equipos", "<section class='panel'><h3>Equipo no encontrado</h3></section>"), 404

    specs = [
        ("Código", r.get("codigo","")), ("Tipo", r.get("tipo_equipo","")), ("Familia", r.get("familia","")), ("Marca", r.get("marca","")),
        ("Modelo", r.get("modelo","")), ("Año", r.get("ano","")), ("Ubicación", r.get("ubicacion","")), ("Control Base", r.get("control_base","")),
        ("Frecuencia", r.get("frecuencia_base","")), ("Horómetro", r.get("ultimo_horometro","")), ("Kilometraje", r.get("ultimo_kilometraje","")),
        ("Lectura Usada", r.get("lectura_actual","")), ("Última PM", r.get("ultima_pm","")), ("Última Lectura PM", r.get("ultima_lectura_pm","")),
        ("Última Mantención", fecha(r.get("ultima_fecha_pm"))), ("Costo Total PM", r.get("costo_total_pm_clp","")),
    ]

    body = f"<section class='panel hero'><div><img src='{img_url(r)}'><h2 class='code'>{codigo}</h2><span class='pill {sem(r)}'>{estado(r)}</span><div class='spec' style='margin-top:12px'><small>Patente</small><div>{clean_equipo_field(r.get('patente',''))}</div></div><div class='spec' style='margin-top:8px'><small>VIN / Chasis</small><div>{clean_equipo_field(r.get('vin',''))}</div></div><div class='spec' style='margin-top:8px'><small>Número Motor</small><div>{clean_equipo_field(r.get('motor',''))}</div></div><a class='btn' style='margin-top:12px' href='/plan_mantencion/{codigo}'>Plan de Mantención DEMOTRON</a></div><div><h3>Ficha Técnica CMMS</h3><div class='specgrid'>"
    for a,b in specs:
        body += f"<div class='spec'><small>{a}</small><div>{b}</div></div>"
    body += f"</div><p>Acción sugerida: {r.get('accion_sugerida','')}</p><p>Prioridad taller: {r.get('prioridad_taller','')}</p></div></section>"

    body += "<section class='panel'><h3>Ficha Técnica Ordenada</h3><div class='tech'>"
    for title, items in tecnica(r):
        body += f"<div class='techbox'><h4>{title}</h4><ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul></div>"
    body += "</div></section>"

    def hist_table(title, data, cols):
        out = f"<section class='panel'><h3>{title}</h3><table><tr>" + "".join(f"<th>{friendly(c)}</th>" for c in cols) + "</tr>"
        if not data:
            out += f"<tr><td colspan='{len(cols)}'>Sin registros asociados.</td></tr>"
        for row in data:
            out += "<tr>"
            for c in cols:
                val = row.get(c, "")
                if "fecha" in c:
                    val = fecha(val)
                if "costo" in c:
                    val = clp(nfloat(val))
                out += f"<td>{val}</td>"
            out += "</tr>"
        return out + "</table></section>"

    ots, compras, lecturas = [], [], []
    try:
        if table_exists("ot"):
            ots = rows("SELECT * FROM ot WHERE codigo=:c ORDER BY id DESC LIMIT 50", {"c": codigo})
    except Exception:
        pass

    try:
        if table_exists("compras"):
            compras = rows("SELECT * FROM compras WHERE codigo_equipo=:c ORDER BY id DESC LIMIT 50", {"c": codigo})
    except Exception:
        pass

    try:
        if table_exists("lecturas"):
            lecturas = rows("SELECT * FROM lecturas WHERE codigo=:c ORDER BY id DESC LIMIT 50", {"c": codigo})
    except Exception:
        pass

    body += hist_table("Historial de Mantenciones / OT", ots, ["numero","tipo","estado","fecha_creacion","fecha_cierre","lectura","descripcion","costo_estimado"])
    body += hist_table("Órdenes de Compra Asociadas", compras, ["fecha","oc","proveedor","item","cantidad","costo_total","estado"])
    body += hist_table("Lecturas Registradas", lecturas, ["fecha","tipo_lectura","valor","ubicacion","responsable"])

    return page(f"Ficha {codigo}", "Equipos", body)


# Compatibilidad solo para diagnóstico; no hay rutas visuales antiguas.
@app.route("/admin/v113/version")
@app.route("/v113/version")
@app.route("/admin/v112/version")
@app.route("/admin/v111/version")
@app.route("/admin/v11/version")
@app.route("/admin/v10/version")
@app.route("/admin/v94/version")
@app.route("/admin/v93/version")
@app.route("/admin/v92/version")
@app.route("/admin/v9/version")
def legacy_version():
    return admin_version()


if __name__ == "__main__":
    ensure_schema()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


@app.route("/admin/v13/version")
def admin_v13_version():
    return jsonify({
        "status":"OK",
        "version":"DEMOTRON_V13_FINAL_REAL"
    })

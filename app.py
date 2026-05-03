from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import pandas as pd
import os, glob
from datetime import datetime
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, text

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "demotron-cmms-final")

UPLOAD_FOLDER = "data"
MASTER_SHEET = "Maestro_Equipos"
ALLOWED = {"xlsx", "xlsm", "xls"}

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    os.makedirs("data", exist_ok=True)
    engine = create_engine("sqlite:///data/cmms_operacion.db", future=True)

POSSIBLE_PATHS = [
    r"C:\Users\Admin\OneDrive\CMMS DEMOTRON MANU ORTIZ.xlsx",
    r"C:\Users\Admin\OneDrive - Demotron\CMMS DEMOTRON MANU ORTIZ.xlsx",
    r"C:\Users\Admin\OneDrive - DEMOTRON\CMMS DEMOTRON MANU ORTIZ.xlsx",
    os.path.join("data", "CMMS DEMOTRON MANU ORTIZ.xlsx"),
]

def is_postgres():
    return DATABASE_URL is not None

def init_db():
    id_type = "SERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real_type = "DOUBLE PRECISION" if is_postgres() else "REAL"
    tables = [
        f"""CREATE TABLE IF NOT EXISTS ot (
            id {id_type}, numero TEXT UNIQUE, codigo TEXT, tipo TEXT, prioridad TEXT, estado TEXT,
            fecha_creacion TEXT, lectura {real_type} DEFAULT 0, descripcion TEXT, responsable TEXT,
            costo_estimado {real_type} DEFAULT 0, fecha_cierre TEXT, lectura_cierre {real_type} DEFAULT 0,
            comentario_cierre TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS mantenciones (
            id {id_type}, ot_numero TEXT, codigo TEXT, fecha TEXT, tipo TEXT, lectura {real_type} DEFAULT 0,
            costo {real_type} DEFAULT 0, descripcion TEXT, responsable TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS bodega (
            id {id_type}, fecha TEXT, codigo_equipo TEXT, ot_numero TEXT, repuesto TEXT,
            cantidad {real_type} DEFAULT 0, costo_unitario {real_type} DEFAULT 0, movimiento TEXT, observacion TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS lecturas (
            id {id_type}, fecha TEXT, codigo TEXT, tipo_lectura TEXT, valor {real_type} DEFAULT 0,
            ubicacion TEXT, responsable TEXT, observacion TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS compras (
            id {id_type}, fecha TEXT, codigo_equipo TEXT, oc TEXT, proveedor TEXT, item TEXT,
            cantidad {real_type} DEFAULT 0, costo_total {real_type} DEFAULT 0, estado TEXT, observacion TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS ubicaciones (
            id {id_type}, fecha TEXT, codigo TEXT, ubicacion TEXT, responsable TEXT, observacion TEXT)""",
    ]
    with engine.begin() as conn:
        for sql in tables:
            conn.execute(text(sql))

def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED

def find_excel():
    for p in POSSIBLE_PATHS:
        if os.path.exists(p):
            return p
    for pat in [r"C:\Users\Admin\OneDrive*\**\CMMS DEMOTRON MANU ORTIZ.xlsx", r"C:\Users\Admin\**\CMMS DEMOTRON MANU ORTIZ.xlsx"]:
        try:
            found = glob.glob(pat, recursive=True)
            if found:
                return found[0]
        except Exception:
            pass
    if os.path.exists(UPLOAD_FOLDER):
        files = []
        for f in os.listdir(UPLOAD_FOLDER):
            if allowed_file(f):
                p = os.path.join(UPLOAD_FOLDER, f)
                files.append((os.path.getmtime(p), p))
        if files:
            return sorted(files, reverse=True)[0][1]
    return None

def read_sheet(path, sheet_name):
    xls = pd.ExcelFile(path)
    sheet = sheet_name if sheet_name in xls.sheet_names else None
    if sheet is None:
        for s in xls.sheet_names:
            if sheet_name.lower().replace("_", " ") in s.lower().replace("_", " "):
                sheet = s
                break
    if sheet is None:
        sheet = xls.sheet_names[0]
    return pd.read_excel(path, sheet_name=sheet, header=2).dropna(how="all"), sheet

def safe_num(s):
    return pd.to_numeric(s, errors="coerce").fillna(0)

def safe_txt(s):
    return s.fillna("").astype(str).str.strip()

def sort_key(code):
    c = str(code).upper()
    order = {"MD": 1, "CD": 2, "VD": 3, "EQP": 4}
    prefix = c.split("-")[0] if "-" in c else c[:3]
    nums = "".join(ch for ch in c if ch.isdigit())
    return (order.get(prefix, 9), int(nums) if nums else 999999, c)

def load_main():
    path = find_excel()
    meta = {"archivo": path or "", "hoja": "", "filas": 0, "actualizado": datetime.now().strftime("%d-%m-%Y %H:%M"), "error": ""}
    if not path:
        meta["error"] = "No se encontró Excel maestro. Sube uno desde Conexión."
        return pd.DataFrame(), meta
    try:
        raw, sheet = read_sheet(path, MASTER_SHEET)
        raw.columns = [str(c).strip() for c in raw.columns]
        meta["hoja"] = sheet
    except Exception as e:
        meta["error"] = f"Error leyendo Excel: {e}"
        return pd.DataFrame(), meta
    if "Codigo" not in raw.columns:
        meta["error"] = "No se encontró columna Codigo."
        return pd.DataFrame(), meta

    def col(name):
        return raw[name] if name in raw.columns else pd.Series([""] * len(raw))

    df = pd.DataFrame()
    df["codigo"] = safe_txt(col("Codigo"))
    df = df[(df["codigo"] != "") & (df["codigo"].str.lower() != "nan")].copy()
    raw = raw.loc[df.index].copy()

    text_map = {
        "tipo": "Tipo Equipo", "familia": "Familia", "marca": "Marca", "modelo": "Modelo",
        "ubicacion": "Ubicacion", "responsable": "Responsable", "control_base": "Control Base",
        "estado_operacional": "Estado Operacional", "estado_cmms_excel": "Estado CMMS",
        "accion_excel": "Acción Sugerida"
    }
    for out, source in text_map.items():
        df[out] = safe_txt(raw[source]) if source in raw.columns else ""

    num_map = {
        "anio": "Año", "frecuencia_base": "Frecuencia Base", "promedio_diario": "Promedio Diario",
        "ultimo_horometro": "Ultimo Horometro", "ultimo_kilometraje": "Ultimo Kilometraje",
        "lectura_actual_excel": "Lectura Actual", "ultima_pm": "Ultima PM", "ultima_lectura_pm": "Ultima Lectura PM",
        "costo_mantenciones": "Costo Mantenciones CLP", "costo_compras_pm": "Costo Compras PM CLP",
        "costo_total_pm": "Costo Total PM CLP"
    }
    for out, source in num_map.items():
        df[out] = safe_num(raw[source]) if source in raw.columns else 0

    def choose_values(row):
        pm_candidates = []
        if row["ultima_lectura_pm"] > 0:
            pm_candidates.append(row["ultima_lectura_pm"])
        if row["ultima_pm"] > 0:
            pm_candidates.append(row["ultima_pm"])
        pm_real = max(pm_candidates) if pm_candidates else 0

        candidates = []
        if row["lectura_actual_excel"] > 0:
            candidates.append(("Lectura Actual", row["lectura_actual_excel"]))
        if row["ultimo_horometro"] > 0:
            candidates.append(("Último Horómetro", row["ultimo_horometro"]))
        if row["ultimo_kilometraje"] > 0:
            candidates.append(("Último Kilometraje", row["ultimo_kilometraje"]))

        if candidates and pm_real > 0:
            fuente, lectura = min(candidates, key=lambda x: abs(x[1] - pm_real))
        elif candidates:
            control = str(row["control_base"]).upper()
            if "KM" in control:
                km = [c for c in candidates if c[0] == "Último Kilometraje"]
                fuente, lectura = km[0] if km else candidates[0]
            elif "HORA" in control:
                hr = [c for c in candidates if c[0] == "Último Horómetro"]
                fuente, lectura = hr[0] if hr else candidates[0]
            else:
                fuente, lectura = candidates[0]
        else:
            fuente, lectura = "Sin lectura", 0

        proxima = pm_real + row["frecuencia_base"] if pm_real > 0 else 0
        margen = proxima - lectura if proxima > 0 and lectura > 0 else 0
        return pd.Series({"lectura_real": lectura, "fuente_lectura": fuente, "ultima_pm_real": pm_real, "proxima_real": proxima, "margen_real": margen})

    df = pd.concat([df, df.apply(choose_values, axis=1)], axis=1)

    def estado(row):
        op = str(row["estado_operacional"]).upper()
        excel = str(row["estado_cmms_excel"]).upper()
        if "FUERA" in op or "NO OPER" in op:
            return "FUERA DE SERVICIO"
        if "TALLER" in op:
            return "EN TALLER"
        if "PROCESO" in excel:
            return "EN PROCESO"
        if "POR RECIBIR" in excel:
            return "POR RECIBIR"
        if "PENDIENTE" in excel:
            return "PENDIENTE"
        if row["ultima_pm_real"] <= 0:
            return "SIN HISTORIAL PM"
        if row["lectura_real"] <= 0:
            return "SIN LECTURA"
        if row["margen_real"] < 0:
            return "ATRASADA"
        limite = max(15, row["frecuencia_base"] * 0.10)
        if row["margen_real"] <= limite:
            return "PRÓXIMA"
        return "AL DÍA"

    def color(e):
        e = str(e).upper()
        if "ATRAS" in e:
            return "red"
        if "SIN HISTORIAL" in e or "SIN LECTURA" in e:
            return "orange"
        if "PRÓXIMA" in e or "PROXIMA" in e:
            return "yellow"
        if "PROCESO" in e or "POR RECIBIR" in e or "PENDIENTE" in e:
            return "blue"
        if "TALLER" in e or "FUERA" in e:
            return "gray"
        return "green"

    def accion(row):
        e = row["estado_calculado"]
        if e == "ATRASADA":
            return "Crear OT preventiva inmediata y validar repuestos."
        if e == "SIN HISTORIAL PM":
            return "Regularizar historial PM."
        if e == "SIN LECTURA":
            return "Solicitar lectura real de terreno."
        if e == "PRÓXIMA":
            return "Planificar compra, bodega y ventana."
        if e in ["EN PROCESO", "POR RECIBIR", "PENDIENTE"]:
            return "Seguimiento hasta cierre técnico."
        if e in ["EN TALLER", "FUERA DE SERVICIO"]:
            return "Controlar retorno operacional."
        return "Monitorear."

    df["estado_calculado"] = df.apply(estado, axis=1)
    df["semaforo"] = df["estado_calculado"].apply(color)
    df["accion_sugerida"] = df.apply(accion, axis=1)
    df["sort_key"] = df["codigo"].apply(sort_key)
    df = df.sort_values("sort_key").drop(columns=["sort_key"])
    meta["filas"] = int(len(df))
    return df, meta

def query_rows(sql, params=None):
    with engine.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]

def get_ots():
    return query_rows("SELECT * FROM ot ORDER BY id DESC")

def get_mantenciones():
    return query_rows("SELECT * FROM mantenciones ORDER BY id DESC LIMIT 300")

def get_bodega():
    return query_rows("SELECT * FROM bodega ORDER BY id DESC LIMIT 300")

def get_lecturas():
    return query_rows("SELECT * FROM lecturas ORDER BY id DESC LIMIT 500")

def get_compras():
    return query_rows("SELECT * FROM compras ORDER BY id DESC LIMIT 500")

def get_ubicaciones():
    return query_rows("SELECT * FROM ubicaciones ORDER BY id DESC LIMIT 500")

def build_kpis(df, ots, bodega, compras, lecturas):
    out = {
        "total": 0, "controlado": 0, "atrasados": 0, "proximos": 0, "proceso": 0, "sin_historial": 0,
        "no_operativos": 0, "ot_abiertas": sum(1 for o in ots if o["estado"] != "CERRADA"),
        "ot_cerradas": sum(1 for o in ots if o["estado"] == "CERRADA"),
        "lecturas": len(lecturas), "compras_total": len(compras),
        "compras_proceso": sum(1 for c in compras if str(c.get("estado", "")).upper() == "EN PROCESO"),
        "compras_por_recibir": sum(1 for c in compras if "POR RECIBIR" in str(c.get("estado", "")).upper()),
        "compras_recibidas": sum(1 for c in compras if "RECIBIDO" in str(c.get("estado", "")).upper()),
        "bodega_movimientos": len(bodega), "costo_total": 0,
        "costo_compras_registradas": int(sum(float(c.get("costo_total") or 0) for c in compras)),
        "costo_bodega": int(sum(float(b.get("cantidad") or 0) * float(b.get("costo_unitario") or 0) for b in bodega)),
    }
    if not df.empty:
        no_oper = df["estado_calculado"].str.contains("TALLER|FUERA", case=False, na=False).sum()
        base = df[~df["estado_calculado"].str.contains("TALLER|FUERA", case=False, na=False)]
        base_count = len(base)
        al_dia = df["estado_calculado"].str.contains("AL D", case=False, na=False).sum()
        proceso = df["estado_calculado"].str.contains("PROCESO|POR RECIBIR|PENDIENTE", case=False, na=False).sum()
        proximos = df["estado_calculado"].str.contains("PRÓXIMA|PROXIMA", case=False, na=False).sum()
        atrasados = df["estado_calculado"].str.contains("ATRAS", case=False, na=False).sum()
        sin_hist = df["estado_calculado"].str.contains("SIN HISTORIAL|SIN LECTURA", case=False, na=False).sum()
        out.update({
            "total": int(len(df)),
            "controlado": round(((al_dia + proceso + proximos) / base_count * 100), 1) if base_count else 0,
            "atrasados": int(atrasados), "proximos": int(proximos), "proceso": int(proceso),
            "sin_historial": int(sin_hist), "no_operativos": int(no_oper), "costo_total": int(df["costo_total_pm"].sum()),
        })
    return out

def ubicaciones_chart(df):
    if df.empty:
        return []
    g = df[df["estado_calculado"].eq("ATRASADA")].groupby("ubicacion").size().reset_index(name="cantidad").sort_values("cantidad", ascending=False)
    return g.to_dict(orient="records")

def alertas(df):
    if df.empty:
        return []
    order = {"red": 1, "orange": 2, "yellow": 3, "blue": 4, "gray": 5, "green": 9}
    d = df[df["semaforo"].isin(["red", "orange", "yellow", "blue"])].copy()
    d["orden"] = d["semaforo"].map(order)
    return d.sort_values(["orden", "margen_real"]).head(100).to_dict(orient="records")

def top_costos(df):
    if df.empty:
        return []
    return df.sort_values("costo_total_pm", ascending=False).head(12).to_dict(orient="records")

@app.route("/")
def index():
    try:
        df, meta = load_main()
        ots, bod, compras, lecturas = get_ots(), get_bodega(), get_compras(), get_lecturas()
        return render_template(
            "index.html",
            data=df.to_dict(orient="records") if not df.empty else [],
            meta=meta, kpis=build_kpis(df, ots, bod, compras, lecturas),
            ubicaciones=ubicaciones_chart(df), alertas=alertas(df), costos=top_costos(df),
            ots=ots, mantenciones=get_mantenciones(), bodega=bod,
            lecturas=lecturas, compras=compras, ubicaciones_reg=get_ubicaciones(),
            maestro_cols=list(df.columns) if not df.empty else [],
            maestro_rows=df.to_dict(orient="records") if not df.empty else [],
        )
    except Exception as e:
        return f"<h1>Error en Dashboard</h1><pre>{str(e)}</pre>", 500

@app.route("/crear_ot", methods=["POST"])
def crear_ot():
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM ot")).scalar() + 1
        numero = f"OT-WEB-{count:05d}"
        conn.execute(text("""INSERT INTO ot(numero,codigo,tipo,prioridad,estado,fecha_creacion,lectura,descripcion,responsable,costo_estimado)
        VALUES(:numero,:codigo,:tipo,:prioridad,:estado,:fecha,:lectura,:descripcion,:responsable,:costo)"""),
        dict(numero=numero, codigo=request.form.get("codigo", "").strip(), tipo=request.form.get("tipo", "Preventiva"),
        prioridad=request.form.get("prioridad", "Media"), estado="ABIERTA", fecha=fecha, lectura=float(request.form.get("lectura") or 0),
        descripcion=request.form.get("descripcion", "").strip(), responsable=request.form.get("responsable", "").strip(),
        costo=float(request.form.get("costo_estimado") or 0)))
    flash(f"OT creada: {numero}")
    return redirect(url_for("index"))

@app.route("/cerrar_ot/<int:ot_id>", methods=["POST"])
def cerrar_ot(ot_id):
    with engine.begin() as conn:
        ot = conn.execute(text("SELECT * FROM ot WHERE id=:id"), {"id": ot_id}).mappings().first()
        if not ot:
            flash("OT no encontrada.")
            return redirect(url_for("index"))
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
        lectura = float(request.form.get("lectura_cierre") or ot["lectura"] or 0)
        costo = float(request.form.get("costo_real") or ot["costo_estimado"] or 0)
        comentario = request.form.get("comentario_cierre", "").strip()
        conn.execute(text("""UPDATE ot SET estado='CERRADA', fecha_cierre=:fecha, lectura_cierre=:lectura, comentario_cierre=:comentario WHERE id=:id"""),
                     {"fecha": fecha, "lectura": lectura, "comentario": comentario, "id": ot_id})
        conn.execute(text("""INSERT INTO mantenciones(ot_numero,codigo,fecha,tipo,lectura,costo,descripcion,responsable)
        VALUES(:ot_numero,:codigo,:fecha,:tipo,:lectura,:costo,:descripcion,:responsable)"""),
        dict(ot_numero=ot["numero"], codigo=ot["codigo"], fecha=fecha, tipo=ot["tipo"], lectura=lectura, costo=costo,
        descripcion=comentario or ot["descripcion"], responsable=ot["responsable"]))
    flash("OT cerrada correctamente.")
    return redirect(url_for("index"))

@app.route("/bodega", methods=["POST"])
def registrar_bodega():
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO bodega(fecha,codigo_equipo,ot_numero,repuesto,cantidad,costo_unitario,movimiento,observacion)
        VALUES(:fecha,:codigo,:ot,:repuesto,:cantidad,:costo,:movimiento,:observacion)"""),
        dict(fecha=datetime.now().strftime("%Y-%m-%d %H:%M"), codigo=request.form.get("codigo_equipo", ""),
        ot=request.form.get("ot_numero", ""), repuesto=request.form.get("repuesto", ""),
        cantidad=float(request.form.get("cantidad") or 0), costo=float(request.form.get("costo_unitario") or 0),
        movimiento=request.form.get("movimiento", "SALIDA"), observacion=request.form.get("observacion", "")))
    flash("Movimiento de bodega registrado.")
    return redirect(url_for("index"))

@app.route("/lecturas", methods=["POST"])
def registrar_lectura():
    fecha = request.form.get("fecha") or datetime.now().strftime("%Y-%m-%d %H:%M")
    codigo = request.form.get("codigo", "").strip()
    ubicacion = request.form.get("ubicacion", "").strip()
    responsable = request.form.get("responsable", "").strip()
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO lecturas(fecha,codigo,tipo_lectura,valor,ubicacion,responsable,observacion)
        VALUES(:fecha,:codigo,:tipo,:valor,:ubicacion,:responsable,:observacion)"""),
        dict(fecha=fecha, codigo=codigo, tipo=request.form.get("tipo_lectura", "HOROMETRO"),
        valor=float(request.form.get("valor") or 0), ubicacion=ubicacion, responsable=responsable,
        observacion=request.form.get("observacion", "").strip()))
        if ubicacion:
            conn.execute(text("""INSERT INTO ubicaciones(fecha,codigo,ubicacion,responsable,observacion)
            VALUES(:fecha,:codigo,:ubicacion,:responsable,:observacion)"""),
            dict(fecha=fecha, codigo=codigo, ubicacion=ubicacion, responsable=responsable, observacion="Ubicación registrada desde lectura"))
    flash("Lectura registrada correctamente.")
    return redirect(url_for("index"))

@app.route("/compras", methods=["POST"])
def registrar_compra():
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO compras(fecha,codigo_equipo,oc,proveedor,item,cantidad,costo_total,estado,observacion)
        VALUES(:fecha,:codigo,:oc,:proveedor,:item,:cantidad,:costo,:estado,:observacion)"""),
        dict(fecha=request.form.get("fecha") or datetime.now().strftime("%Y-%m-%d %H:%M"),
        codigo=request.form.get("codigo_equipo", "").strip(), oc=request.form.get("oc", "").strip(),
        proveedor=request.form.get("proveedor", "").strip(), item=request.form.get("item", "").strip(),
        cantidad=float(request.form.get("cantidad") or 0), costo=float(request.form.get("costo_total") or 0),
        estado=request.form.get("estado", "EN PROCESO"), observacion=request.form.get("observacion", "").strip()))
    flash("Compra registrada correctamente.")
    return redirect(url_for("index"))

@app.route("/ubicaciones", methods=["POST"])
def registrar_ubicacion():
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO ubicaciones(fecha,codigo,ubicacion,responsable,observacion)
        VALUES(:fecha,:codigo,:ubicacion,:responsable,:observacion)"""),
        dict(fecha=request.form.get("fecha") or datetime.now().strftime("%Y-%m-%d %H:%M"),
        codigo=request.form.get("codigo", "").strip(), ubicacion=request.form.get("ubicacion", "").strip(),
        responsable=request.form.get("responsable", "").strip(), observacion=request.form.get("observacion", "").strip()))
    flash("Ubicación registrada correctamente.")
    return redirect(url_for("index"))

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        flash("No se recibió archivo.")
        return redirect(url_for("index"))
    f = request.files["file"]
    if not f or f.filename == "":
        flash("No seleccionaste archivo.")
        return redirect(url_for("index"))
    if not allowed_file(f.filename):
        flash("Formato no permitido.")
        return redirect(url_for("index"))
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    f.save(os.path.join(UPLOAD_FOLDER, secure_filename(f.filename)))
    flash("Archivo cargado como respaldo.")
    return redirect(url_for("index"))

@app.route("/health")
def health():
    return jsonify({"status": "ok", "database": "postgresql" if DATABASE_URL else "sqlite"})

try:
    init_db()
    print("DB inicializada correctamente")
except Exception as e:
    print("ERROR INIT DB:", e)

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

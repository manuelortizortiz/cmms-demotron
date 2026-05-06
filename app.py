from __future__ import annotations

import os
import re
import json
from datetime import datetime
from functools import wraps
from pathlib import Path

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


APP_VERSION = "DEMOTRON_ERP_CMMS_WEB_FINAL_2026_FIX_RAILWAY"

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "demotron-erp-cmms-final")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
else:
    (BASE_DIR / "data").mkdir(exist_ok=True)
    engine = create_engine(f"sqlite:///{BASE_DIR / 'data' / 'cmms_erp.db'}", future=True)


def is_postgres() -> bool:
    return bool(DATABASE_URL)


def id_col() -> str:
    return "SERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"


def real_col() -> str:
    return "DOUBLE PRECISION" if is_postgres() else "REAL"


def exec_sql(sql: str, params: dict | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})


def rows(sql: str, params: dict | None = None) -> list[dict]:
    with engine.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]


def one(sql: str, params: dict | None = None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {}).mappings().first()


def table_exists(table: str) -> bool:
    try:
        if is_postgres():
            result = one("SELECT to_regclass(:t) AS name", {"t": table})
            return bool(result and result["name"])
        result = one("SELECT name FROM sqlite_master WHERE type='table' AND name=:t", {"t": table})
        return bool(result)
    except Exception:
        return False


def table_columns(table: str) -> set[str]:
    try:
        if is_postgres():
            data = rows(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name=:t
                """,
                {"t": table},
            )
            return {r["column_name"] for r in data}
        data = rows(f"PRAGMA table_info({table})")
        return {r["name"] for r in data}
    except Exception:
        return set()


def safe_table_rows(table: str, limit: int = 200, preferred_order: str = "id") -> list[dict]:
    """
    Evita el error de Railway:
    psycopg2.errors.UndefinedColumn: column "id" does not exist

    Si la tabla no tiene columna id, consulta sin ORDER BY.
    """
    if not table_exists(table):
        return []

    cols = table_columns(table)

    if preferred_order in cols:
        return rows(f"SELECT * FROM {table} ORDER BY {preferred_order} DESC LIMIT {int(limit)}")

    for fallback in ["fecha", "codigo", "codigo_equipo", "numero", "oc"]:
        if fallback in cols:
            return rows(f"SELECT * FROM {table} ORDER BY {fallback} DESC LIMIT {int(limit)}")

    return rows(f"SELECT * FROM {table} LIMIT {int(limit)}")


def safe_float(value, default=0.0) -> float:
    try:
        if value is None or str(value).strip().lower() in ("", "nan", "none", "null"):
            return default
        if isinstance(value, str) and "," in value:
            return float(value.replace(".", "").replace(",", "."))
        return float(value)
    except Exception:
        return default


def clean_text(value, default="") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return default if s.lower() in ("nan", "none", "null") else s


def norm(s: str) -> str:
    s = clean_text(s).lower()
    rep = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    for a, b in rep.items():
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "", s)


def pick(row: pd.Series, *names, default=""):
    lookup = {norm(c): c for c in row.index}
    for name in names:
        key = norm(name)
        if key in lookup:
            return row.get(lookup[key])
    for key, col in lookup.items():
        if any(norm(n) in key for n in names):
            return row.get(col)
    return default


def calc_estado(freq, lectura, ultima_pm, estado_operacional):
    op = clean_text(estado_operacional, "OPERATIVO").upper()

    if "FUERA" in op:
        return "FUERA DE SERVICIO", "gray", 0, 0

    if "TALLER" in op:
        return "EN TALLER", "gray", 0, 0

    freq = safe_float(freq)
    lectura = safe_float(lectura)
    ultima_pm = safe_float(ultima_pm)

    proxima = ultima_pm + freq if ultima_pm > 0 and freq > 0 else 0
    margen = proxima - lectura if proxima > 0 and lectura > 0 else 0

    if lectura <= 0 or freq <= 0:
        return "SIN LECTURA", "orange", proxima, margen

    if ultima_pm <= 0:
        return "SIN HISTORIAL PM", "orange", proxima, margen

    if margen < 0:
        return "ATRASADA", "red", proxima, margen

    if margen <= max(15, freq * 0.10):
        return "PRÓXIMA", "orange", proxima, margen

    return "AL DÍA", "green", proxima, margen


def init_db():
    idt = id_col()
    real = real_col()

    exec_sql(
        f"""
        CREATE TABLE IF NOT EXISTS usuarios (
            id {idt},
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            rol TEXT NOT NULL,
            activo INTEGER DEFAULT 1,
            creado TEXT
        )
        """
    )

    exec_sql(
        f"""
        CREATE TABLE IF NOT EXISTS equipos (
            id {idt},
            codigo TEXT UNIQUE NOT NULL,
            tipo_equipo TEXT,
            familia TEXT,
            marca TEXT,
            modelo TEXT,
            descripcion TEXT,
            ano TEXT,
            patente TEXT,
            vin TEXT,
            motor TEXT,
            ubicacion TEXT,
            responsable TEXT,
            control_base TEXT,
            frecuencia_base {real} DEFAULT 0,
            lectura_actual {real} DEFAULT 0,
            ultima_pm {real} DEFAULT 0,
            proxima_pm {real} DEFAULT 0,
            margen {real} DEFAULT 0,
            costo_total_pm {real} DEFAULT 0,
            estado_operacional TEXT DEFAULT 'OPERATIVO',
            estado_calculado TEXT,
            semaforo TEXT,
            imagen_url TEXT,
            fecha_actualizacion TEXT
        )
        """
    )

    exec_sql(
        f"""
        CREATE TABLE IF NOT EXISTS ot (
            id {idt},
            numero TEXT UNIQUE,
            codigo TEXT,
            tipo TEXT,
            prioridad TEXT,
            estado TEXT,
            fecha_creacion TEXT,
            fecha_cierre TEXT,
            lectura {real} DEFAULT 0,
            descripcion TEXT,
            responsable TEXT,
            costo_estimado {real} DEFAULT 0
        )
        """
    )

    exec_sql(
        f"""
        CREATE TABLE IF NOT EXISTS lecturas (
            id {idt},
            fecha TEXT,
            codigo TEXT,
            tipo_lectura TEXT,
            valor {real} DEFAULT 0,
            ubicacion TEXT,
            responsable TEXT,
            observacion TEXT
        )
        """
    )

    exec_sql(
        f"""
        CREATE TABLE IF NOT EXISTS compras (
            id {idt},
            fecha TEXT,
            codigo_equipo TEXT,
            oc TEXT,
            proveedor TEXT,
            item TEXT,
            cantidad {real} DEFAULT 0,
            costo_total {real} DEFAULT 0,
            estado TEXT,
            observacion TEXT
        )
        """
    )

    exec_sql(
        f"""
        CREATE TABLE IF NOT EXISTS bodega (
            id {idt},
            fecha TEXT,
            codigo_equipo TEXT,
            ot_numero TEXT,
            repuesto TEXT,
            cantidad {real} DEFAULT 0,
            costo_unitario {real} DEFAULT 0,
            movimiento TEXT,
            observacion TEXT
        )
        """
    )

    exec_sql(
        f"""
        CREATE TABLE IF NOT EXISTS importaciones (
            id {idt},
            fecha TEXT,
            archivo TEXT,
            hoja TEXT,
            registros INTEGER,
            detalle TEXT
        )
        """
    )

    result = one("SELECT COUNT(*) AS n FROM usuarios")
    if result and result["n"] == 0:
        usuarios = [
            ("admin", "admin123", "Administrador"),
            ("gerencia", "gerencia123", "Gerencia"),
            ("mantencion", "mantencion123", "Mantención"),
            ("bodega", "bodega123", "Bodega"),
            ("lectura", "lectura123", "Lecturas"),
        ]

        for username, password, rol in usuarios:
            exec_sql(
                """
                INSERT INTO usuarios(username,password_hash,rol,activo,creado)
                VALUES(:u,:p,:r,1,:c)
                """,
                {
                    "u": username,
                    "p": generate_password_hash(password),
                    "r": rol,
                    "c": datetime.now().isoformat(timespec="minutes"),
                },
            )

    result = one("SELECT COUNT(*) AS n FROM equipos")
    if result and result["n"] == 0:
        seed_demo()


def imagen_por_equipo(familia, codigo=""):
    f = norm(familia)

    if "excav" in f:
        return "/static/equipos/excavadora.svg"
    if "camioneta" in f or codigo.startswith("VD"):
        return "/static/equipos/camioneta.svg"
    if "camion" in f or codigo.startswith("CD"):
        return "/static/equipos/camion.svg"
    if "cargador" in f:
        return "/static/equipos/cargador.svg"

    return "/static/equipos/equipo.svg"


def guardar_equipo(data: dict):
    codigo = clean_text(data.get("codigo")).upper()

    if not codigo:
        return

    estado, semaforo, proxima, margen = calc_estado(
        data.get("frecuencia_base"),
        data.get("lectura_actual"),
        data.get("ultima_pm"),
        data.get("estado_operacional"),
    )

    desc = clean_text(data.get("descripcion")) or " ".join(
        x
        for x in [
            clean_text(data.get("familia")),
            clean_text(data.get("marca")),
            clean_text(data.get("modelo")),
        ]
        if x
    )

    params = {
        "codigo": codigo,
        "tipo_equipo": clean_text(data.get("tipo_equipo")),
        "familia": clean_text(data.get("familia")),
        "marca": clean_text(data.get("marca")),
        "modelo": clean_text(data.get("modelo")),
        "descripcion": desc,
        "ano": clean_text(data.get("ano")),
        "patente": clean_text(data.get("patente")),
        "vin": clean_text(data.get("vin")),
        "motor": clean_text(data.get("motor")),
        "ubicacion": clean_text(data.get("ubicacion")),
        "responsable": clean_text(data.get("responsable")),
        "control_base": clean_text(data.get("control_base"), "HORAS"),
        "frecuencia_base": safe_float(data.get("frecuencia_base")),
        "lectura_actual": safe_float(data.get("lectura_actual")),
        "ultima_pm": safe_float(data.get("ultima_pm")),
        "proxima_pm": proxima,
        "margen": margen,
        "costo_total_pm": safe_float(data.get("costo_total_pm")),
        "estado_operacional": clean_text(data.get("estado_operacional"), "OPERATIVO"),
        "estado_calculado": estado,
        "semaforo": semaforo,
        "imagen_url": clean_text(data.get("imagen_url")) or imagen_por_equipo(data.get("familia"), codigo),
        "fecha_actualizacion": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if is_postgres():
        sql = """
        INSERT INTO equipos(
            codigo,tipo_equipo,familia,marca,modelo,descripcion,ano,patente,vin,motor,
            ubicacion,responsable,control_base,frecuencia_base,lectura_actual,ultima_pm,
            proxima_pm,margen,costo_total_pm,estado_operacional,estado_calculado,semaforo,
            imagen_url,fecha_actualizacion
        )
        VALUES(
            :codigo,:tipo_equipo,:familia,:marca,:modelo,:descripcion,:ano,:patente,:vin,:motor,
            :ubicacion,:responsable,:control_base,:frecuencia_base,:lectura_actual,:ultima_pm,
            :proxima_pm,:margen,:costo_total_pm,:estado_operacional,:estado_calculado,:semaforo,
            :imagen_url,:fecha_actualizacion
        )
        ON CONFLICT (codigo) DO UPDATE SET
            tipo_equipo=EXCLUDED.tipo_equipo,
            familia=EXCLUDED.familia,
            marca=EXCLUDED.marca,
            modelo=EXCLUDED.modelo,
            descripcion=EXCLUDED.descripcion,
            ano=EXCLUDED.ano,
            patente=EXCLUDED.patente,
            vin=EXCLUDED.vin,
            motor=EXCLUDED.motor,
            ubicacion=EXCLUDED.ubicacion,
            responsable=EXCLUDED.responsable,
            control_base=EXCLUDED.control_base,
            frecuencia_base=EXCLUDED.frecuencia_base,
            lectura_actual=EXCLUDED.lectura_actual,
            ultima_pm=EXCLUDED.ultima_pm,
            proxima_pm=EXCLUDED.proxima_pm,
            margen=EXCLUDED.margen,
            costo_total_pm=EXCLUDED.costo_total_pm,
            estado_operacional=EXCLUDED.estado_operacional,
            estado_calculado=EXCLUDED.estado_calculado,
            semaforo=EXCLUDED.semaforo,
            imagen_url=EXCLUDED.imagen_url,
            fecha_actualizacion=EXCLUDED.fecha_actualizacion
        """
    else:
        sql = """
        INSERT INTO equipos(
            codigo,tipo_equipo,familia,marca,modelo,descripcion,ano,patente,vin,motor,
            ubicacion,responsable,control_base,frecuencia_base,lectura_actual,ultima_pm,
            proxima_pm,margen,costo_total_pm,estado_operacional,estado_calculado,semaforo,
            imagen_url,fecha_actualizacion
        )
        VALUES(
            :codigo,:tipo_equipo,:familia,:marca,:modelo,:descripcion,:ano,:patente,:vin,:motor,
            :ubicacion,:responsable,:control_base,:frecuencia_base,:lectura_actual,:ultima_pm,
            :proxima_pm,:margen,:costo_total_pm,:estado_operacional,:estado_calculado,:semaforo,
            :imagen_url,:fecha_actualizacion
        )
        ON CONFLICT(codigo) DO UPDATE SET
            tipo_equipo=excluded.tipo_equipo,
            familia=excluded.familia,
            marca=excluded.marca,
            modelo=excluded.modelo,
            descripcion=excluded.descripcion,
            ano=excluded.ano,
            patente=excluded.patente,
            vin=excluded.vin,
            motor=excluded.motor,
            ubicacion=excluded.ubicacion,
            responsable=excluded.responsable,
            control_base=excluded.control_base,
            frecuencia_base=excluded.frecuencia_base,
            lectura_actual=excluded.lectura_actual,
            ultima_pm=excluded.ultima_pm,
            proxima_pm=excluded.proxima_pm,
            margen=excluded.margen,
            costo_total_pm=excluded.costo_total_pm,
            estado_operacional=excluded.estado_operacional,
            estado_calculado=excluded.estado_calculado,
            semaforo=excluded.semaforo,
            imagen_url=excluded.imagen_url,
            fecha_actualizacion=excluded.fecha_actualizacion
        """

    exec_sql(sql, params)


def seed_demo():
    demo = [
        {
            "codigo": "MD-01",
            "tipo_equipo": "Maquinaria Pesada",
            "familia": "Excavadora",
            "marca": "SANY",
            "modelo": "SY215C",
            "ubicacion": "Palmucho",
            "control_base": "HORAS",
            "frecuencia_base": 250,
            "lectura_actual": 2350,
            "ultima_pm": 2250,
            "costo_total_pm": 1850000,
            "estado_operacional": "OPERATIVO",
        },
        {
            "codigo": "MD-02",
            "tipo_equipo": "Maquinaria Pesada",
            "familia": "Cargador Frontal",
            "marca": "Komatsu",
            "modelo": "WA1200",
            "ubicacion": "Planta Áridos",
            "control_base": "HORAS",
            "frecuencia_base": 250,
            "lectura_actual": 1510,
            "ultima_pm": 1250,
            "costo_total_pm": 2100000,
            "estado_operacional": "OPERATIVO",
        },
        {
            "codigo": "CD-102",
            "tipo_equipo": "Camión",
            "familia": "Camión Tolva",
            "marca": "MAN",
            "modelo": "40400",
            "ubicacion": "Cobquecura",
            "control_base": "KM",
            "frecuencia_base": 15000,
            "lectura_actual": 302500,
            "ultima_pm": 300000,
            "costo_total_pm": 980000,
            "estado_operacional": "OPERATIVO",
        },
        {
            "codigo": "VD-01",
            "tipo_equipo": "Vehículo Liviano",
            "familia": "Camioneta",
            "marca": "Maxus",
            "modelo": "T60",
            "ubicacion": "Santiago",
            "control_base": "KM",
            "frecuencia_base": 10000,
            "lectura_actual": 94800,
            "ultima_pm": 90000,
            "costo_total_pm": 350000,
            "estado_operacional": "OPERATIVO",
        },
        {
            "codigo": "EQP-01",
            "tipo_equipo": "Equipo Planta",
            "familia": "Planta Áridos Móvil",
            "marca": "Genérica",
            "modelo": "Móvil",
            "ubicacion": "Talca",
            "control_base": "HORAS",
            "frecuencia_base": 250,
            "lectura_actual": 980,
            "ultima_pm": 1000,
            "costo_total_pm": 560000,
            "estado_operacional": "EN TALLER",
        },
    ]

    for equipo in demo:
        guardar_equipo(equipo)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def equipos_list():
    if not table_exists("equipos"):
        return []

    return rows(
        """
        SELECT *
        FROM equipos
        ORDER BY
            CASE
                WHEN codigo LIKE 'MD-%' THEN 1
                WHEN codigo LIKE 'CD-%' THEN 2
                WHEN codigo LIKE 'VD-%' THEN 3
                WHEN codigo LIKE 'EQP-%' THEN 4
                ELSE 9
            END,
            codigo
        """
    )


def build_kpis(equipos, ots, compras, lecturas, bodega):
    operativos = [e for e in equipos if e.get("semaforo") != "gray"]
    atrasados = sum(1 for e in operativos if e.get("semaforo") == "red")
    proximos = sum(1 for e in operativos if e.get("semaforo") == "orange")
    taller = sum(1 for e in equipos if clean_text(e.get("estado_calculado")).upper() == "EN TALLER")
    fuera = sum(1 for e in equipos if clean_text(e.get("estado_calculado")).upper() == "FUERA DE SERVICIO")
    controlado = round(((len(operativos) - atrasados) / len(operativos) * 100), 1) if operativos else 0

    compras_proceso = sum(
        1
        for c in compras
        if clean_text(c.get("estado")).upper() in ("EN PROCESO", "POR RECIBIR", "PENDIENTE")
    )

    return {
        "total": len(equipos),
        "operativos": len(operativos),
        "atrasados": atrasados,
        "proximos": proximos,
        "taller": taller,
        "fuera": fuera,
        "controlado": controlado,
        "ot_abiertas": sum(1 for o in ots if clean_text(o.get("estado")).upper() not in ("CERRADA", "CERRADO")),
        "compras_proceso": compras_proceso,
        "compras_monto": int(sum(safe_float(c.get("costo_total")) for c in compras)),
        "lecturas": len(lecturas),
        "bodega_movimientos": len(bodega),
        "costo_total": int(sum(safe_float(e.get("costo_total_pm")) for e in equipos)),
    }


def charts(equipos, compras):
    by_estado = {}
    by_ubic = {}
    by_costo = {}
    by_mant = {}

    for e in equipos:
        estado = e.get("estado_calculado") or "SIN ESTADO"
        by_estado[estado] = by_estado.get(estado, 0) + 1

        if e.get("semaforo") != "gray":
            ubicacion = e.get("ubicacion") or "Sin ubicación"
            by_ubic[ubicacion] = by_ubic.get(ubicacion, 0) + 1

        by_costo[e.get("codigo")] = safe_float(e.get("costo_total_pm"))

    for c in compras:
        cod = clean_text(c.get("codigo_equipo"), "SIN EQUIPO")
        by_mant[cod] = by_mant.get(cod, 0) + 1

    return {
        "estado": [{"label": k, "value": v} for k, v in by_estado.items()],
        "ubicacion": [
            {"label": k, "value": v}
            for k, v in sorted(by_ubic.items(), key=lambda x: x[1], reverse=True)[:10]
        ],
        "costo": [
            {"label": k, "value": v}
            for k, v in sorted(by_costo.items(), key=lambda x: x[1], reverse=True)[:10]
        ],
        "mantenciones": [
            {"label": k, "value": v}
            for k, v in sorted(by_mant.items(), key=lambda x: x[1], reverse=True)[:10]
        ],
    }


def import_sheet(file_storage, sheet_name, kind):
    df = pd.read_excel(file_storage, sheet_name=sheet_name, header=None).dropna(how="all")
    header_idx = 0

    for i in range(min(8, len(df))):
        vals = [norm(x) for x in df.iloc[i].tolist()]
        if any("codigo" in v for v in vals) or any("equipo" in v for v in vals):
            header_idx = i
            break

    file_storage.seek(0)
    df = pd.read_excel(file_storage, sheet_name=sheet_name, header=header_idx).dropna(how="all")
    df.columns = [clean_text(c) for c in df.columns]

    count = 0

    for _, r in df.iterrows():
        if kind == "equipos":
            codigo = clean_text(pick(r, "Codigo", "Código", "Cod Equipo", "Equipo")).upper()

            if not codigo:
                continue

            guardar_equipo(
                {
                    "codigo": codigo,
                    "tipo_equipo": pick(r, "Tipo Equipo", "Tipo"),
                    "familia": pick(r, "Familia", "Descripción Equipo", "Descripcion"),
                    "marca": pick(r, "Marca"),
                    "modelo": pick(r, "Modelo"),
                    "descripcion": pick(r, "Descripcion", "Descripción", "Equipo"),
                    "ano": pick(r, "Año", "Ano"),
                    "patente": pick(r, "Patente"),
                    "vin": pick(r, "VIN", "Chasis"),
                    "motor": pick(r, "Motor", "Numero Motor"),
                    "ubicacion": pick(r, "Ubicacion", "Ubicación", "Faena"),
                    "responsable": pick(r, "Responsable"),
                    "control_base": pick(r, "Control Base", "Unidad", "Tipo Control", default="HORAS"),
                    "frecuencia_base": safe_float(pick(r, "Frecuencia Base", "Frecuencia", "Intervalo")),
                    "lectura_actual": safe_float(
                        pick(r, "Lectura Actual", "Horometro", "Horómetro", "Kilometro", "Kilómetro", "Odometro")
                    ),
                    "ultima_pm": safe_float(pick(r, "Ultima PM", "Última PM", "Ultima Mantencion", "Última Mantención")),
                    "costo_total_pm": safe_float(pick(r, "Costo Total PM CLP", "Costo", "Costo Total")),
                    "estado_operacional": pick(r, "Estado Operacional", "Estado", default="OPERATIVO"),
                }
            )
            count += 1

        elif kind == "lecturas":
            codigo = clean_text(pick(r, "Codigo", "Código", "Equipo")).upper()
            valor = safe_float(pick(r, "Valor", "Lectura", "Horometro", "Horómetro", "Kilometro", "Kilómetro", "Odometro"))

            if codigo and valor:
                exec_sql(
                    """
                    INSERT INTO lecturas(fecha,codigo,tipo_lectura,valor,ubicacion,responsable,observacion)
                    VALUES(:f,:c,:t,:v,:u,:r,:o)
                    """,
                    {
                        "f": clean_text(pick(r, "Fecha", default=datetime.now().strftime("%Y-%m-%d"))),
                        "c": codigo,
                        "t": clean_text(pick(r, "Tipo", "Unidad", default="LECTURA")),
                        "v": valor,
                        "u": clean_text(pick(r, "Ubicacion", "Ubicación")),
                        "r": clean_text(pick(r, "Responsable")),
                        "o": clean_text(pick(r, "Observacion", "Observación")),
                    },
                )

                eq = one("SELECT * FROM equipos WHERE codigo=:c", {"c": codigo})

                if eq:
                    data = dict(eq)
                    data["lectura_actual"] = valor
                    ubicacion = clean_text(pick(r, "Ubicacion", "Ubicación"))

                    if ubicacion:
                        data["ubicacion"] = ubicacion

                    guardar_equipo(data)

                count += 1

        elif kind == "compras":
            codigo = clean_text(pick(r, "Codigo", "Código", "Equipo", "Codigo Equipo")).upper()
            oc = clean_text(pick(r, "OC", "Orden Compra", "N OC"))

            if codigo or oc:
                exec_sql(
                    """
                    INSERT INTO compras(fecha,codigo_equipo,oc,proveedor,item,cantidad,costo_total,estado,observacion)
                    VALUES(:f,:c,:oc,:p,:i,:q,:cost,:e,:o)
                    """,
                    {
                        "f": clean_text(pick(r, "Fecha", default=datetime.now().strftime("%Y-%m-%d"))),
                        "c": codigo,
                        "oc": oc,
                        "p": clean_text(pick(r, "Proveedor")),
                        "i": clean_text(pick(r, "Item", "Descripción", "Descripcion")),
                        "q": safe_float(pick(r, "Cantidad")),
                        "cost": safe_float(pick(r, "Costo Total", "Total", "Monto")),
                        "e": clean_text(pick(r, "Estado", default="EN PROCESO")),
                        "o": clean_text(pick(r, "Observacion", "Observación")),
                    },
                )
                count += 1

    exec_sql(
        """
        INSERT INTO importaciones(fecha,archivo,hoja,registros,detalle)
        VALUES(:f,:a,:h,:r,:d)
        """,
        {
            "f": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "a": secure_filename(file_storage.filename),
            "h": sheet_name,
            "r": count,
            "d": kind,
        },
    )

    return count


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = one("SELECT * FROM usuarios WHERE username=:u AND activo=1", {"u": username})

        if user and check_password_hash(user["password_hash"], password):
            session["user"] = user["username"]
            session["rol"] = user["rol"]
            return redirect(url_for("index"))

        error = "Usuario o contraseña incorrectos."

    return render_template("login.html", error=error, version=APP_VERSION)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    equipos = equipos_list()

    # Consultas corregidas para Railway/PostgreSQL:
    # No todas las tablas importadas desde Excel tienen columna id.
    ots = safe_table_rows("ot", 200)
    compras = safe_table_rows("compras", 300)
    lecturas = safe_table_rows("lecturas", 300)
    bodega = safe_table_rows("bodega", 200)

    kpis = build_kpis(equipos, ots, compras, lecturas, bodega)
    criticos = [e for e in equipos if e.get("semaforo") in ("red", "orange")][:30]
    taller = [e for e in equipos if clean_text(e.get("estado_calculado")).upper() == "EN TALLER"][:30]

    return render_template(
        "index.html",
        equipos=equipos,
        ots=ots,
        compras=compras,
        lecturas=lecturas,
        bodega=bodega,
        kpis=kpis,
        criticos=criticos,
        taller=taller,
        charts=json.dumps(charts(equipos, compras), ensure_ascii=False),
        current_user=session.get("user"),
        current_role=session.get("rol"),
        anio_actual=datetime.now().year,
        version_sistema=APP_VERSION,
    )


@app.route("/equipos/nuevo", methods=["POST"])
@login_required
def nuevo_equipo():
    guardar_equipo(request.form.to_dict())
    flash("Equipo guardado/actualizado correctamente.")
    return redirect(url_for("index") + "#equipos")


@app.route("/crear_ot", methods=["POST"])
@login_required
def crear_ot():
    count = one("SELECT COUNT(*) AS n FROM ot")["n"] + 1
    numero = f"OT-WEB-{count:05d}"

    exec_sql(
        """
        INSERT INTO ot(numero,codigo,tipo,prioridad,estado,fecha_creacion,lectura,descripcion,responsable,costo_estimado)
        VALUES(:n,:c,:t,:p,'ABIERTA',:f,:l,:d,:r,:cost)
        """,
        {
            "n": numero,
            "c": request.form.get("codigo", ""),
            "t": request.form.get("tipo", "Preventiva"),
            "p": request.form.get("prioridad", "Media"),
            "f": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "l": safe_float(request.form.get("lectura")),
            "d": request.form.get("descripcion", ""),
            "r": request.form.get("responsable", ""),
            "cost": safe_float(request.form.get("costo_estimado")),
        },
    )

    flash(f"OT creada: {numero}")
    return redirect(url_for("index") + "#ot")


@app.route("/lecturas", methods=["POST"])
@login_required
def registrar_lectura():
    codigo = clean_text(request.form.get("codigo")).upper()
    valor = safe_float(request.form.get("valor"))
    ubicacion = clean_text(request.form.get("ubicacion"))

    exec_sql(
        """
        INSERT INTO lecturas(fecha,codigo,tipo_lectura,valor,ubicacion,responsable,observacion)
        VALUES(:f,:c,:t,:v,:u,:r,:o)
        """,
        {
            "f": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "c": codigo,
            "t": request.form.get("tipo_lectura", "HOROMETRO"),
            "v": valor,
            "u": ubicacion,
            "r": request.form.get("responsable", ""),
            "o": request.form.get("observacion", ""),
        },
    )

    eq = one("SELECT * FROM equipos WHERE codigo=:c", {"c": codigo}) if codigo else None

    if eq:
        data = dict(eq)
        data["lectura_actual"] = valor

        if ubicacion:
            data["ubicacion"] = ubicacion

        guardar_equipo(data)

    flash("Lectura registrada y equipo recalculado.")
    return redirect(url_for("index") + "#lecturas")


@app.route("/compras", methods=["POST"])
@login_required
def registrar_compra():
    exec_sql(
        """
        INSERT INTO compras(fecha,codigo_equipo,oc,proveedor,item,cantidad,costo_total,estado,observacion)
        VALUES(:f,:c,:oc,:p,:i,:q,:cost,:e,:o)
        """,
        {
            "f": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "c": request.form.get("codigo_equipo", ""),
            "oc": request.form.get("oc", ""),
            "p": request.form.get("proveedor", ""),
            "i": request.form.get("item", ""),
            "q": safe_float(request.form.get("cantidad")),
            "cost": safe_float(request.form.get("costo_total")),
            "e": request.form.get("estado", "EN PROCESO"),
            "o": request.form.get("observacion", ""),
        },
    )

    flash("Compra registrada.")
    return redirect(url_for("index") + "#compras")


@app.route("/bodega", methods=["POST"])
@login_required
def registrar_bodega():
    exec_sql(
        """
        INSERT INTO bodega(fecha,codigo_equipo,ot_numero,repuesto,cantidad,costo_unitario,movimiento,observacion)
        VALUES(:f,:c,:ot,:rep,:q,:cost,:m,:o)
        """,
        {
            "f": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "c": request.form.get("codigo_equipo", ""),
            "ot": request.form.get("ot_numero", ""),
            "rep": request.form.get("repuesto", ""),
            "q": safe_float(request.form.get("cantidad")),
            "cost": safe_float(request.form.get("costo_unitario")),
            "m": request.form.get("movimiento", "SALIDA"),
            "o": request.form.get("observacion", ""),
        },
    )

    flash("Movimiento de bodega registrado.")
    return redirect(url_for("index") + "#bodega")


@app.route("/importar_excel", methods=["POST"])
@login_required
def importar_excel():
    f = request.files.get("excel")

    if not f:
        flash("No se recibió archivo Excel.")
        return redirect(url_for("index") + "#admin")

    filename = secure_filename(f.filename)
    path = UPLOAD_DIR / filename
    f.save(path)

    total = 0

    try:
        xl = pd.ExcelFile(path)

        mapping = {
            "equipos": ["Maestro_Equipos", "Equipos", "Maestro"],
            "lecturas": ["Lecturas", "Combustible"],
            "compras": ["Compras", "OC", "Ordenes Compra"],
        }

        for kind, candidates in mapping.items():
            sheet = next(
                (
                    s
                    for s in xl.sheet_names
                    if norm(s) in [norm(c) for c in candidates] or any(norm(c) in norm(s) for c in candidates)
                ),
                None,
            )

            if sheet:
                with open(path, "rb") as fh:
                    class NamedFile:
                        def __init__(self, stream, name):
                            self.stream = stream
                            self.filename = name

                        def read(self, *a):
                            return self.stream.read(*a)

                        def seek(self, *a):
                            return self.stream.seek(*a)

                    total += import_sheet(NamedFile(fh, filename), sheet, kind)

        flash(f"Importación ERP completada: {total} registros procesados desde {filename}.")

    except Exception as e:
        flash(f"Error importando Excel: {e}")

    return redirect(url_for("index") + "#admin")


@app.route("/seed")
@login_required
def seed():
    seed_demo()
    flash("Datos demo DEMOTRON cargados.")
    return redirect(url_for("index"))


@app.route("/api/version")
def api_version():
    return jsonify({"version": APP_VERSION, "database": "postgresql" if DATABASE_URL else "sqlite"})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "database": "postgresql" if DATABASE_URL else "sqlite", "version": APP_VERSION})


try:
    init_db()
except Exception as exc:
    print("ERROR INIT DB:", exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)

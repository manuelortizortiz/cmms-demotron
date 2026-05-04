# CMMS DEMOTRON FINAL FIXED API EQUIPOS

import os
from flask import Flask, jsonify, session, redirect, url_for
from sqlalchemy import create_engine, text

app = Flask(__name__)
app.secret_key = "demotron-secret"

DATABASE_URL = os.getenv("DATABASE_URL").replace("postgres://", "postgresql+psycopg://")
engine = create_engine(DATABASE_URL)

def normalize_ubicacion(u):
    if not u:
        return ""
    return str(u).upper()

def ensure_data():
    pass

@app.route("/api/equipos")
def api_equipos():
    ensure_data()

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT 
                    codigo,
                    tipo_de_equipo,
                    familia,
                    marca,
                    modelo,
                    ano,
                    ubicacion,
                    responsable,
                    lectura_actual,
                    unidad,
                    proxima_pm,
                    estado
                FROM maestro_equipos
                ORDER BY codigo
            """)).mappings().all()

        data = []
        for r in rows:
            data.append({
                "codigo": r.get("codigo"),
                "tipo_equipo": r.get("tipo_de_equipo"),
                "familia": r.get("familia"),
                "marca": r.get("marca"),
                "modelo": r.get("modelo"),
                "anio": r.get("ano"),
                "ubicacion": normalize_ubicacion(r.get("ubicacion")),
                "responsable": r.get("responsable"),
                "lectura_actual": r.get("lectura_actual"),
                "unidad": r.get("unidad"),
                "proxima_pm": r.get("proxima_pm"),
                "estado": r.get("estado"),
                "descripcion": f"{r.get('marca','')} {r.get('modelo','')}"
            })

        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/")
def home():
    return "CMMS DEMOTRON OK"

if __name__ == "__main__":
    app.run()

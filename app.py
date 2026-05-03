import os
from flask import Flask, jsonify, render_template
from sqlalchemy import create_engine, text

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "demotron-secret")

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.strip()

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True
) if DATABASE_URL else None

@app.route("/")
def index():
    return "CMMS DEMOTRON RUNNING"

@app.route("/api/status")
def status():
    try:
        if engine is None:
            return jsonify({"status": "error", "message": "DATABASE_URL no configurada"}), 500

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        return jsonify({"status": "ok", "database": "postgresql"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/equipos")
def get_equipos():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    codigo,
                    tipo_equipo,
                    familia,
                    marca,
                    modelo,
                    descripcion
                FROM equipos
                ORDER BY codigo
            """))
            data = [dict(row._mapping) for row in result]

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/dashboard")
def dashboard():
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM equipos")).scalar() or 0

        return jsonify({
            "total_equipos": total,
            "atrasados": 0,
            "proximos": 0,
            "operativos": total
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

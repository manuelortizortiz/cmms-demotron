
import pandas as pd
import os
from sqlalchemy import create_engine

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")

engine = create_engine(DATABASE_URL)

def clean(df):
    df.columns = df.iloc[1]
    df = df[2:]
    df = df.dropna(how='all')
    return df

file = "data/cmms.xlsx"

# Equipos
df = pd.read_excel(file, sheet_name="Equipos")
df = clean(df)
df = df.rename(columns={
    "Codigo":"codigo",
    "Tipo Equipo":"tipo_equipo",
    "Marca":"marca",
    "Modelo":"modelo"
})
df.to_sql("equipos", engine, if_exists="replace", index=False)

# Lecturas
df = pd.read_excel(file, sheet_name="Lecturas")
df = clean(df)
df = df.rename(columns={
    "Fecha":"fecha",
    "Codigo":"codigo",
    "Tipo Lectura":"tipo_lectura",
    "Valor":"valor"
})
df.to_sql("lecturas", engine, if_exists="replace", index=False)

# Mantenciones
df = pd.read_excel(file, sheet_name="Mantenciones")
df = clean(df)
df = df.rename(columns={
    "Fecha":"fecha",
    "Codigo":"codigo",
    "Tipo":"tipo",
    "Estado":"estado"
})
df.to_sql("mantenciones", engine, if_exists="replace", index=False)

print("IMPORTACIÓN COMPLETA")

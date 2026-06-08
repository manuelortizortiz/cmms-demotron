import pandas as pd
from datetime import datetime

def clean_string(val):
    s = str(val).strip()
    return "" if s.lower() in ['nan', 'none', 'nat', ''] else s

def clean_int(val, default=0):
    try: return int(float(clean_string(val))) if clean_string(val) else default
    except: return default

def clean_float(val, default=0.0):
    try:
        if pd.isna(val) or val is None: return default
        if isinstance(val, (int, float)): return float(val)
        s = clean_string(val).replace('$', '').replace(' ', '').replace('.', '').replace(',', '.')
        return float(s) if s else default
    except: return default

def parse_date(val):
    if pd.isna(val): return datetime.now()
    try:
        if isinstance(val, datetime): return val
        return pd.to_datetime(val).to_pydatetime()
    except: return datetime.now()

def format_num(val):
    try: return f"{int(float(str(val))):,}".replace(",", ".")
    except: return "0"

def format_clp(val):
    try: return f"$ {int(float(str(val))):,}".replace(",", ".")
    except: return "$ 0"

def buscar_foto_por_tipo(tipo_equipo, marca=""):
    t = str(tipo_equipo).lower(); m = str(marca).lower()
    if "tolva" in t: return "/static/equipos_real/camion_man_tolva.png"
    if "tracto" in t: return "/static/equipos_real/tractocamion.png"
    if "camioneta" in t: return "/static/equipos_real/maxus_t60.png"
    if any(x in t for x in ["furgon", "minibus", "bus"]): return "/static/equipos_real/minibus.png"
    if any(x in t for x in ["liviano", "pintura", "slurry", "plano"]): return "/static/equipos_real/camion_liviano.png"
    return "/static/equipos_real/tractocamion.png"

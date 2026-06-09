import re
from datetime import datetime

def clean_string(val):
    if val is None or str(val).lower() in ['nan', 'nat', 'none', '']:
        return ""
    return str(val).strip()

def clean_int(val, default=0):
    try:
        if val is None or str(val).lower() in ['nan', 'nat', 'none', '']: return default
        return int(float(val))
    except:
        return default

def clean_float(val, default=0.0):
    try:
        if val is None or str(val).lower() in ['nan', 'nat', 'none', '']: return default
        return float(val)
    except:
        return default

def parse_date(val):
    if val is None or str(val).lower() in ['nan', 'nat', 'none', '']:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.strptime(str(val).split()[0], '%Y-%m-%d')
    except:
        return None

def format_num(val):
    try:
        return f"{int(val):,}".replace(",", ".")
    except:
        return "0"

def format_clp(val):
    try:
        return f"${int(val):,}".replace(",", ".")
    except:
        return "$0"

def buscar_foto_por_tipo(tipo_equipo, marca=""):
    t = str(tipo_equipo or '').lower()
    m = str(marca or '').lower()
    if "tolva" in t:                                    return "/static/equipos_real/camion_man_tolva.png"
    if "tracto" in t:                                   return "/static/equipos_real/tractocamion.png"
    if "camioneta" in t or "pick" in t:                 return "/static/equipos_real/maxus_t60.png"
    if any(x in t for x in ["furgon","minibus","bus"]): return "/static/equipos_real/minibus.png"
    if "aljibe" in t:                                   return "/static/equipos_real/camion_aljibe.png"
    if "pluma" in t or "grua" in t:                     return "/static/equipos_real/camion_pluma.png"
    if "retroexcavadora" in t or "retro" in t:          return "/static/equipos_real/retroexcavadora.png"
    if "cargador" in t:                                 return "/static/equipos_real/cargador_frontal.png"
    if "excavadora" in t:                               return "/static/equipos_real/excavadora.png"
    if "motoniveladora" in t or "niveladora" in t:      return "/static/equipos_real/motoniveladora.png"
    if "rodillo" in t and "neumatic" in t:              return "/static/equipos_real/rodillo_neumaticos.png"
    if "rodillo" in t:                                  return "/static/equipos_real/rodillo_compactador.png"
    if "gravilladora" in t:                             return "/static/equipos_real/gravilladora.png"
    if "barredora" in t:                                return "/static/equipos_real/barredora.png"
    if "planta" in t:                                   return "/static/equipos_real/planta_aridos.png"
    if any(x in t for x in ["liviano","slurry","plano","camion","truck"]): return "/static/equipos_real/camion_liviano.png"
    return "/static/equipos_real/tractocamion.png"

import json
from datetime import datetime

# --- UTILIDADES ---
def safe_int(val):
    try: return int(val)
    except: return 0

def get_draw_moment(dt):
    if dt.hour < 16: return 'DIA'
    if dt.hour < 20: return 'TARDE'
    return 'NOCHE'

# ==========================================
# 🟢 PARSER LOTO 3 (HÍBRIDO ID/NOMBRE)
# ==========================================
def parse_loto3(data):
    row = {}
    row['sorteo'] = data.get('drawNumber')
    ts = data.get('drawDate')
    if ts:
        dt = datetime.fromtimestamp(ts / 1000)
        row['fecha'] = dt.strftime('%Y-%m-%d %H:%M:%S')
        row['dia_semana'] = dt.strftime('%A')
        row['hora'] = dt.hour
        row['momento'] = get_draw_moment(dt)

    results = sorted(data.get('results', []), key=lambda x: x.get('order', 999))
    nums = []
    for i, item in enumerate(results):
        if i < 3:
            val = safe_int(item.get('number'))
            row[f'n{i+1}'] = val
            nums.append(str(val))
    row['combinacion'] = "".join(nums)

    # --- PREMIOS ---
    prizes = data.get('prizes', [])
    
    # Mapa por ID (Para JSONs antiguos)
    id_map = {
        1: 'EXACTA', 2: 'TRIO_PAR', 3: 'TRIO_AZAR',
        4: 'PAR', 5: 'TERMINACION'
    }

    for p in prizes:
        name = (p.get('name') or p.get('categoryName') or "").upper()
        cat_id = p.get('id', {}).get('categoryCd')
        
        col = None
        
        # 1. Intentar por Nombre (Prioridad)
        if 'EXACTA' in name: col = 'EXACTA'
        elif 'TRIO' in name and 'PAR' in name: col = 'TRIO_PAR'
        elif 'TRIO' in name and 'AZAR' in name: col = 'TRIO_AZAR'
        elif 'PAR' in name: col = 'PAR'
        elif 'TERMINACI' in name: col = 'TERMINACION'
        
        # 2. Intentar por ID (Fallback)
        if not col and cat_id in id_map:
            col = id_map[cat_id]
            
        if col:
            row[f'{col}_GANADORES'] = p.get('winners', 0)
            row[f'{col}_MONTO'] = p.get('winningAmount', 0)

    return row

# ==========================================
# 🔵 PARSER LOTO 4 (HÍBRIDO ID/NOMBRE)
# ==========================================
def parse_loto4(data):
    row = {}
    row['sorteo'] = data.get('drawNumber')
    ts = data.get('drawDate')
    if ts:
        dt = datetime.fromtimestamp(ts / 1000)
        row['fecha'] = dt.strftime('%Y-%m-%d %H:%M:%S')
        row['dia_semana'] = dt.strftime('%A')
        row['hora'] = dt.hour

    results = sorted(data.get('results', []), key=lambda x: x.get('order', 999))
    vals = []
    for i, item in enumerate(results):
        val = safe_int(item.get('number'))
        row[f'pos{i+1}'] = val
        vals.append(val)
    vals.sort()
    for i, val in enumerate(vals):
        row[f'n{i+1}'] = val

    prizes = data.get('prizes', [])
    id_map = { 1: '4_PUNTOS', 2: '3_PUNTOS', 3: '2_PUNTOS' }

    for p in prizes:
        name = (p.get('name') or "").upper()
        cat_id = p.get('id', {}).get('categoryCd')
        
        col = None
        if '4' in name: col = '4_PUNTOS'
        elif '3' in name: col = '3_PUNTOS'
        elif '2' in name: col = '2_PUNTOS'
        
        if not col and cat_id in id_map:
            col = id_map[cat_id]

        if col:
            row[f'{col}_GANADORES'] = p.get('winners', 0)
            row[f'{col}_MONTO'] = p.get('winningAmount', 0)
    return row

# ==========================================
# 🔴 PARSER RACHA (CORREGIDO CON MAPA DE IDs)
# ==========================================
def parse_racha(data):
    row = {}
    row['sorteo'] = data.get('drawNumber')
    ts = data.get('drawDate')
    if ts:
        dt = datetime.fromtimestamp(ts / 1000)
        row['fecha'] = dt.strftime('%Y-%m-%d %H:%M:%S')
        row['dia_semana'] = dt.strftime('%A')
        row['hora'] = dt.hour

    # --- RESULTADOS ---
    results = sorted(data.get('results', []), key=lambda x: x.get('order', 999))
    vals = []
    for i, item in enumerate(results):
        val = safe_int(item.get('number'))
        row[f'pos{i+1}'] = val
        vals.append(val)
    vals.sort()
    for i, val in enumerate(vals):
        row[f'n{i+1}'] = val

    # --- PREMIOS ---
    prizes = data.get('prizes', [])
    
    # Mapa de IDs (Solo para históricos 2016-2018 donde no hay 'name')
    legacy_id_map = {
        1: 'ACIERTO_10', 2: 'ACIERTO_0', 3: 'ACIERTO_9',
        4: 'ACIERTO_1', 5: 'ACIERTO_8', 6: 'ACIERTO_2',
        7: 'ACIERTO_7', 8: 'ACIERTO_3'
    }

    for p in prizes:
        raw_name = (p.get('name') or p.get('categoryName') or "").upper()
        cat_id = safe_int(p.get('id', {}).get('categoryCd') or p.get('categoryCd'))
        
        col_name = None

        # DETECCIÓN INTELIGENTE
        # 1. Si hay nombre, usamos el nombre (es lo más seguro para diferenciar CD)
        if raw_name:
            # Normalizar nombre para evitar errores de tildes o espacios
            name = raw_name.replace('.', '').strip() 
            
            # Categorías C.D. (Apuesta de $500)
            if 'CD' in name or 'DISTINTIVO' in name:
                if 'SIETE' in name or '7' in name: col_name = 'ACIERTO_7CD'
                elif 'TRES' in name or '3' in name: col_name = 'ACIERTO_3CD'
            
            # Categorías Normales
            elif 'DIEZ' in name or '10' in name: col_name = 'ACIERTO_10'
            elif 'NUEVE' in name or '9' in name: col_name = 'ACIERTO_9'
            elif 'OCHO' in name or '8' in name: col_name = 'ACIERTO_8'
            elif 'SIETE' in name or '7' in name: col_name = 'ACIERTO_7'
            
            elif 'CERO' in name or '0' in name: col_name = 'ACIERTO_0'
            elif 'UN' in name or '1' in name: col_name = 'ACIERTO_1'
            elif 'DOS' in name or '2' in name: col_name = 'ACIERTO_2'
            elif 'TRES' in name or '3' in name: col_name = 'ACIERTO_3'

        # 2. Si NO hay nombre, usamos el ID (Históricos viejos)
        elif cat_id in legacy_id_map:
            col_name = legacy_id_map[cat_id]

        # 3. Guardar datos
        if col_name:
            row[f'{col_name}_GANADORES'] = p.get('winners', 0)
            row[f'{col_name}_MONTO'] = p.get('winningAmount', 0)

    return row
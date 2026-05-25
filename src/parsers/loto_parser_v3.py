import json
import os
import re
import unicodedata
from datetime import datetime

def normalize_name(name):
    if not name: return "UNKNOWN"
    nfkd_form = unicodedata.normalize('NFKD', str(name))
    name_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    clean_name = re.sub(r'[^a-zA-Z0-9]', '_', name_ascii).upper()
    return re.sub(r'_+', '_', clean_name).strip('_')

def parse_loto_rich(data_source):
    data = {}
    if isinstance(data_source, dict):
        data = data_source
    elif isinstance(data_source, str) and os.path.exists(data_source):
        with open(data_source, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        return {}

    row = {}
    game = data.get('game', {})
    
    # --- 1. METADATA ---
    row['sorteo'] = game.get('drawNumber') or data.get('drawNumber')
    
    ts = data.get('drawDate')
    if ts:
        dt = datetime.fromtimestamp(ts / 1000)
        row['fecha'] = dt.strftime('%Y-%m-%d %H:%M:%S')
        row['anio'] = dt.year
        row['mes'] = dt.month
        row['dia'] = dt.day
        row['dia_semana'] = dt.strftime('%A')

    # --- 2. VENTAS ---
    ventas = data.get('sales') or game.get('sales') or 0
    precio = game.get('columnPrice') or 1000
    row['ventas_totales'] = ventas
    row['boletos_estimados'] = int(ventas / precio) if precio and ventas else 0

    # --- 3. EXTRACCIÓN DE NÚMEROS (Con orden Físico y Numérico) ---
    
    # A) LOTO PRINCIPAL (Resultados en raíz)
    results_root = data.get('results', [])
    if results_root:
        # Ordenar por salida de la tómbola (campo 'order')
        loto_ordered = sorted(results_root, key=lambda x: x.get('order', 999))
        loto_main = loto_ordered[:6]
        loto_wild = loto_ordered[6] if len(loto_ordered) > 6 else None
        
        # Guardar Posicional (Físico)
        for i, item in enumerate(loto_main):
            row[f'LOTO_pos{i+1}'] = int(item.get('number'))
            
        # Guardar Numérico (Ordenado)
        vals_num = sorted([int(x.get('number')) for x in loto_main])
        for i, val in enumerate(vals_num):
            row[f'LOTO_n{i+1}'] = val
            
        # Comodín
        if loto_wild:
            row['LOTO_comodin'] = int(loto_wild.get('number'))

    # B) OTROS JUEGOS (Resultados en additionalGameResults)
    additional = data.get('additionalGameResults', [])
    keywords = {
        'RECARGADO': 'RECARGADO', 'REVANCHA': 'REVANCHA', 'DESQUITE': 'DESQUITE',
        'AHORA': 'AHORA_SI_QUE_SI', 'JUBILAZO': 'JUBILAZO', 'MULTIPLICAR': 'MULTIPLICAR'
    }
    jubilazo_counter = 1

    for game_data in additional:
        raw_name = game_data.get('gameName', 'UNKNOWN').upper()
        prefix = "OTRO"
        for key, val in keywords.items():
            if key in raw_name:
                prefix = val
                break
        
        if prefix == 'JUBILAZO':
            prefix = f'JUBILAZO_{jubilazo_counter}'
            jubilazo_counter += 1

        for area in game_data.get('areas', []):
            winning_nums = area.get('winningNumbers', [])
            if not winning_nums: continue

            # Orden Físico
            ordered_nums = sorted(winning_nums, key=lambda x: x.get('order', 999))
            vals_pos = [int(n.get('number')) for n in ordered_nums]
            for i, val in enumerate(vals_pos):
                row[f'{prefix}_pos{i+1}'] = val

            # Orden Numérico
            vals_sort = sorted(vals_pos)
            for i, val in enumerate(vals_sort):
                row[f'{prefix}_n{i+1}'] = val
            
            # Comodín
            supp = area.get('supplementaryNumbers')
            if supp:
                row[f'{prefix}_comodin'] = int(supp[0].get('number'))

    # --- 4. PREMIOS & POZOS REALES ---
    CAT_ID_MAP = {
        1: "LOTO", 2: "SUPER_QUINA_5_ACIERTOS_COMODIN", 3: "QUINA_5_ACIERTOS",
        4: "SUPER_CUATERNA_4_ACIERTOS_COMODIN", 5: "CUATERNA_4_ACIERTOS",
        6: "SUPER_TERNA_3_ACIERTOS_COMODIN", 7: "TERNA_3_ACIERTOS",
        8: "SUPER_DUPLA_2_ACIERTOS_COMODIN", 9: "RECARGADO_6_ACIERTOS",
        11: "REVANCHA", 12: "DESQUITE"
    }

    prizes = data.get('prizes', [])
    for p in prizes:
        cat_id = p.get('id', {}).get('categoryCd')
        col_prefix = CAT_ID_MAP.get(cat_id)

        # Intento de corrección de nombre si falla el ID
        if not col_prefix:
            cat_name = p.get('name') or p.get('categoryName')
            if cat_name:
                norm = normalize_name(cat_name)
                if 'AHORA' in norm: col_prefix = 'AHORA_SI_QUE_SI'

        if col_prefix:
            row[f'{col_prefix}_GANADORES'] = p.get('winners', 0)
            row[f'{col_prefix}_MONTO'] = p.get('prizePerWinner', 0) or p.get('winningAmount', 0)
            
            # --- CORRECCIÓN FINAL: Guardar Pozo Real SIEMPRE ---
            # Quitamos el 'if pozo > 0' para que el dato '0' se escriba explícitamente
            # y el scraper detecte la columna desde el primer sorteo.
            row[f'{col_prefix}_POZO_REAL'] = p.get('jackpot', 0)

    # Pozo acumulado COMERCIAL (el que sale en la tele)
    row['LOTO_POZO_ACUMULADO'] = data.get('poolAccumulated', 0) or data.get('jackpotAmount', 0)

    return row
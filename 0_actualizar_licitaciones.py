#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
0_actualizar_licitaciones.py
Sincroniza una base local con la API de licitaciones (modo espejo 1:1).
"""
import sys
sys.dont_write_bytecode = True
import os, json, time, datetime, requests, hashlib
from pathlib import Path

# ============================================================
# CONFIGURACIÓN
# ============================================================

API_URL = "http://34.46.3.229:5000/licitaciones"
API_KEY = "2244"
MAX_DIAS_ATRAS = 10         # límite de revisión hacia atrás
PAUSA_ENTRE_DIAS = 2.0      # segundos entre descargas
PAUSA_ENTRE_LLAMADAS = 0.5  # segundos entre requests HTTP
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "base_local"
LOG_DIR = BASE_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "actualizar_licitaciones.log"
CATALOGO_LOCAL = BASE_DIR / "catalog_local.json"

# ============================================================
# UTILIDADES
# ============================================================

def log(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def leer_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def escribir_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_catalog(api_url: str, api_key: str):
    root = api_url.rsplit("/", 1)[0]
    r = requests.get(f"{root}/catalog", headers={"x-api-key": api_key}, timeout=30)
    r.raise_for_status()
    time.sleep(PAUSA_ENTRE_LLAMADAS)
    data = r.json()
    return data.get("dias", [])

def fetch_dia(api_url: str, api_key: str, fecha: str):
    r = requests.get(api_url, headers={"x-api-key": api_key}, params={"dia": fecha}, timeout=90)
    r.raise_for_status()
    time.sleep(PAUSA_ENTRE_LLAMADAS)
    data = r.json()
    if isinstance(data, dict) and "licitaciones" in data:
        return data["licitaciones"]
    elif isinstance(data, list):
        return data
    return []

def guardar_dia_local(fecha: str, data: list):
    y, m, d = fecha.split("-")
    path = DATA_DIR / y / m / f"{d}.json"
    escribir_json(path, data)

def checksum_archivo(path: Path):
    try: return hashlib.md5(path.read_bytes()).hexdigest()[:10]
    except Exception: return None

# ============================================================
# SINCRONIZACIÓN PRINCIPAL
# ============================================================

def sincronizar():
    log("===== INICIO SINCRONIZACIÓN =====")
    inicio = time.time()

    remoto = fetch_catalog(API_URL, API_KEY)
    if not remoto:
        log("❌ No se pudo obtener /catalog de la API.")
        return

    remoto = sorted(remoto, key=lambda x: x["fecha"], reverse=True)
    hoy = datetime.date.today()
    remoto = [d for d in remoto if (hoy - datetime.date.fromisoformat(d["fecha"])).days <= MAX_DIAS_ATRAS]

    local = leer_json(CATALOGO_LOCAL, {})
    cambios, nuevos, actualizados = [], [], []

    for d in remoto:
        fecha, checksum_api = d["fecha"], d.get("checksum")
        if not fecha or not checksum_api:
            continue
        if local.get(fecha) != checksum_api:
            cambios.append((fecha, checksum_api))
            if fecha not in local: nuevos.append(fecha)
            else: actualizados.append(fecha)

    total = len(cambios)
    if total == 0:
        log("Base local ya está al día ✅")
        return

    log(f"Se detectaron {total} días a sincronizar ({len(nuevos)} nuevos, {len(actualizados)} actualizados).")

    for i, (fecha, checksum_api) in enumerate(sorted(cambios), start=1):
        t_elapsed = time.time() - inicio
        t_eta = (t_elapsed / i) * (total - i) if i > 0 else 0
        log(f"({i}/{total}) Descargando {fecha} | t={int(t_elapsed)}s ETA={int(t_eta)}s")

        try:
            data = fetch_dia(API_URL, API_KEY, fecha)
            guardar_dia_local(fecha, data)
            local[fecha] = checksum_api
            escribir_json(CATALOGO_LOCAL, local)
            log(f"✅ {fecha}: {len(data)} licitaciones guardadas")
        except Exception as e:
            log(f"⚠️ Error en {fecha}: {e}")

        time.sleep(PAUSA_ENTRE_DIAS)

    dur = time.time() - inicio
    log(f"===== FIN ({total} días sincronizados en {int(dur)}s) =====")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    sincronizar()

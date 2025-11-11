#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
sys.dont_write_bytecode = True

import os, json, time, logging, datetime, random
from pathlib import Path
import requests, importlib.util

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

API_KEY = "EF2AF107-D5E2-4D89-A1BA-8EA47735905E"
BASE_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
ESTADOS_VIGENTES = [5, 6]
PAUSA_ENTRE_LIC = 2.5
REINTENTOS = 3
BACKOFF_SEG = [5, 10, 20]

BASE_DIR     = Path(__file__).resolve().parent
CLIENTES_DIR = BASE_DIR / "clientes"
HIST_DIR     = BASE_DIR / "historial"
LOG_DIR      = BASE_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=LOG_DIR / "comprobar_vigencia.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ============================================================
# UTILIDADES
# ============================================================

def safe_get(url: str, retries: int = REINTENTOS, backoff=BACKOFF_SEG, timeout=30):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
            logging.warning(f"GET {url} -> {r.status_code}")
        except Exception as e:
            logging.warning(f"Excepción GET ({url}): {e}")
        time.sleep(backoff[min(i, len(backoff)-1)] + random.uniform(0, 1))
    return None

def cargar_config_cliente(nombre_archivo: str):
    path = CLIENTES_DIR / nombre_archivo
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def url_detalle(codigo: str) -> str:
    return f"{BASE_URL}?codigo={codigo}&ticket={API_KEY}"

def obtener_mas_reciente_en(dir_path: Path, patron: str):
    archivos = list(dir_path.glob(patron))
    return max(archivos, key=os.path.getmtime) if archivos else None

def obtener_mas_reciente_global(salida_base: Path):
    """
    Busca el archivo de ejecución más reciente en todas las carpetas año/mes:
    salida_base/AAAA/MM/*_alas_*.json
    """
    carpetas_mes = sorted(salida_base.glob("*/*"), reverse=True)
    for carpeta in carpetas_mes:
        cand = obtener_mas_reciente_en(carpeta, "*_alas_*.json")
        if cand:
            return cand
    return None

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def guardar_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def path_activas(nombre_cliente: str) -> Path:
    return HIST_DIR / f"licitaciones_activas_{nombre_cliente.lower()}.json"

# ============================================================
# PROCESO PRINCIPAL POR CLIENTE
# ============================================================

def procesar_cliente(config_file: str):
    nombre_cliente = config_file.replace("_config.py", "")
    print(f"\n🧾 Procesando cliente: {nombre_cliente.upper()}")

    try:
        cfg = cargar_config_cliente(config_file)
        hoy = datetime.date.today()

        # ----- Cargar archivo de activas como fuente -----
        p_act = path_activas(nombre_cliente)
        if not p_act.exists():
            print(f"ℹ️  {nombre_cliente}: no existe {p_act.name}. Nada que verificar.")
            return

        activas_data = load_json(p_act, {})
        codigos_activas = set(activas_data.get("activas", []) or [])
        if not codigos_activas:
            print(f"ℹ️  {nombre_cliente}: lista 'activas' vacía en {p_act.name}.")
            return

        # ----- Archivo de ejecución más reciente (global) -----
        salida_base  = Path(getattr(cfg, "DIRECTORIO_SALIDA", BASE_DIR / "resultados" / nombre_cliente.lower()))
        archivo_ejecucion = obtener_mas_reciente_global(salida_base)
        data_exec = load_json(archivo_ejecucion, {}) if archivo_ejecucion else {}

        resumen_exec = data_exec.get("resumen", []) or []
        mapa_exec = {str(x.get("CodigoExterno")): x for x in resumen_exec if isinstance(x, dict) and x.get("CodigoExterno")}

        # ----- Cargar base_local del mes actual (simple y corto) -----
        base_mes_dir = BASE_DIR / "base_local" / str(hoy.year) / f"{hoy.month:02d}"
        if not base_mes_dir.exists():
            print(f"⚠️  No existe carpeta base_local del mes: {base_mes_dir}")
            # seguimos, pero sólo podremos actualizar ejecución / activas
        archivos_dia = sorted(base_mes_dir.glob("*.json")) if base_mes_dir.exists() else []

        mapa_global = {}
        for path in archivos_dia:
            data = load_json(path, [])
            if not isinstance(data, list):
                continue
            for lic in data:
                cod = str(lic.get("CodigoExterno"))
                if cod:
                    mapa_global[cod] = (path, lic)

        print(f"🔍 Comprobando vigencia de {len(codigos_activas)} licitaciones (fuente: activas) …")

        vigentes, no_vigentes, sin_detalle = 0, 0, 0
        siguen_vigentes = set()

        for idx, codigo in enumerate(sorted(codigos_activas), start=1):
            print(f"[{idx}/{len(codigos_activas)}] {nombre_cliente}: consultando {codigo} …")
            r = safe_get(url_detalle(codigo))
            if not r:
                logging.warning(f"{nombre_cliente} - sin respuesta para {codigo}")
                continue

            try:
                data_api = r.json()
                if "Listado" in data_api and isinstance(data_api["Listado"], list) and data_api["Listado"]:
                    detalle = data_api["Listado"][0]
                else:
                    detalle = data_api

                estado = int(detalle.get("CodigoEstado", 0))
                vigente = estado in ESTADOS_VIGENTES

                if vigente:
                    vigentes += 1
                    siguen_vigentes.add(codigo)
                else:
                    no_vigentes += 1

                # --- Actualizar en base_local (si está presente ahí) ---
                if codigo in mapa_global:
                    path_archivo, lic_local = mapa_global[codigo]
                    lic_local["CodigoEstado"] = estado
                    mapa_global[codigo] = (path_archivo, lic_local)
                else:
                    sin_detalle += 1

                # --- Actualizar en archivo de ejecución más reciente (si existe y contiene el código) ---
                if codigo in mapa_exec:
                    mapa_exec[codigo]["CodigoEstado"] = estado

            except Exception as e:
                logging.error(f"{nombre_cliente} - error parseando {codigo}: {e}")

            time.sleep(PAUSA_ENTRE_LIC + random.uniform(-0.5, 0.5))

        # ----- Guardar cambios en cada archivo base_local -----
        if archivos_dia:
            actualizados_por_archivo = {}
            for cod, (path, lic) in mapa_global.items():
                if not path.exists():
                    continue
                if path not in actualizados_por_archivo:
                    actualizados_por_archivo[path] = []
                actualizados_por_archivo[path].append(lic)

            for path, lic_list in actualizados_por_archivo.items():
                guardar_json(path, lic_list)

        # ----- Actualizar archivo de ejecución (si había uno) -----
        if resumen_exec and archivo_ejecucion:
            data_exec["resumen"] = list(mapa_exec.values())
            guardar_json(archivo_ejecucion, data_exec)

        # ----- Actualizar archivo de activas (mantener solo las vigentes) -----
        nuevas_activas = sorted(list(siguen_vigentes))
        guardar_json(p_act, {"activas": nuevas_activas})

        # ----- Resumen final -----
        print(f"\n✅ {nombre_cliente.upper()} - Comprobación finalizada.")
        print(f"🟢 Vigentes: {vigentes}")
        print(f"🔴 No vigentes: {no_vigentes}")
        if sin_detalle:
            print(f"⚠️  Códigos no presentes en base_local (mes actual): {sin_detalle}")
        if archivo_ejecucion:
            print(f"📁 Ejecución actualizada: {archivo_ejecucion.name}")
        else:
            print("ℹ️  No había archivo de ejecución reciente para actualizar.")
        print(f"📁 Activas actualizadas: {p_act.name}")
        if archivos_dia:
            print(f"📁 Base local actualizada: {base_mes_dir}")

    except Exception as e:
        logging.error(f"{nombre_cliente} - error general: {e}")
        print(f"❌ Error procesando cliente {nombre_cliente}: {e}")

# ============================================================
# PRINCIPAL
# ============================================================

def main():
    clientes = [f.name for f in CLIENTES_DIR.glob("*_config.py")]
    if not clientes:
        print("⚠️  No se encontraron archivos *_config.py en la carpeta clientes.")
        return

    print(f"🔍 Clientes detectados: {', '.join([c.replace('_config.py','') for c in clientes])}")
    for config_file in clientes:
        procesar_cliente(config_file)

    print("\n🏁 Comprobación completada para todos los clientes.")

if __name__ == "__main__":
    main()

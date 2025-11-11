#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
sys.dont_write_bytecode = True
import os, json, time, random, datetime, logging, hashlib
from pathlib import Path
import importlib.util
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# CONFIG GENERAL
# ============================================================

BASE_DIR     = Path(__file__).resolve().parent
CLIENTES_DIR = BASE_DIR / "clientes"
HIST_DIR     = BASE_DIR / "historial"
LOG_DIR      = BASE_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)
HIST_DIR.mkdir(exist_ok=True)

logging.basicConfig(filename=LOG_DIR / "filtro_ia.log", level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

PAUSA_ENTRE_REQ = 0.3  # pausa entre envíos (para suavizar carga)
MAX_WORKERS = 3        # número de hilos simultáneos
MODO_DEBUG = False

# ============================================================
# UTILIDADES
# ============================================================

def obtener_mas_reciente_en(dir_path: Path, patron: str):
    archivos = list(dir_path.glob(patron))
    return max(archivos, key=os.path.getmtime) if archivos else None

def cargar_config_cliente(nombre_archivo: str):
    path = CLIENTES_DIR / nombre_archivo
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def fusionar_sin_duplicar(lst_exist, lst_nueva, clave="CodigoExterno"):
    if not isinstance(lst_exist, list): lst_exist = []
    if not isinstance(lst_nueva, list): lst_nueva = []
    vistos = {x.get(clave) for x in lst_exist if isinstance(x, dict)}
    fusion = list(lst_exist)
    for it in lst_nueva:
        if isinstance(it, dict):
            k = it.get(clave)
            if k and k not in vistos:
                fusion.append(it); vistos.add(k)
    return fusion

def hash_config(path: Path) -> str:
    try: return hashlib.md5(path.read_bytes()).hexdigest()[:10]
    except Exception: return "nohash"

def path_historial_ia(nombre_cliente: str) -> Path:
    return HIST_DIR / f"ia_{nombre_cliente.lower()}.json"

def cargar_historial_ia(nombre_cliente: str) -> dict:
    p = path_historial_ia(nombre_cliente)
    if not p.exists(): return {"por_hash": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict): data = {"por_hash": {}}
        if "por_hash" not in data: data["por_hash"] = {}
        return data
    except Exception:
        return {"por_hash": {}}

def guardar_historial_ia(nombre_cliente: str, data: dict):
    p = path_historial_ia(nombre_cliente)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# NUEVO: ruta del archivo acumulado de activas por cliente
def path_activas(nombre_cliente: str) -> Path:
    return HIST_DIR / f"licitaciones_activas_{nombre_cliente.lower()}.json"

# ============================================================
# FUNCIÓN DE EVALUACIÓN IA (una licitación)
# ============================================================

def evaluar_licitacion(lic, descripcion_cliente, modelo, nombre_cliente):
    """Evalúa una licitación individual con la IA (retorna 'SI' o 'NO')."""
    codigo = lic.get("CodigoExterno")
    nombre = lic.get("Nombre", "").strip()
    desc   = lic.get("Descripcion", "").strip()

    prompt = (
        f"El cliente se dedica a: {descripcion_cliente}\n\n"
        f"Evalúa la siguiente licitación:\n"
        f"{nombre}\n{desc}\n\n"
        "¿Esta licitación corresponde al tipo de trabajo o rubro del cliente?\n"
        "Responde solo con 'SI' o 'NO'."
    )

    try:
        resp = openai.ChatCompletion.create(
            model=modelo,
            messages=[
                {"role": "system", "content": "Responde estrictamente con 'SI' o 'NO'."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3, temperature=0
        )
        decision = resp.choices[0].message["content"].strip().upper()
        if decision not in ["SI", "NO"]:
            decision = "NO"
    except Exception as e:
        logging.error(f"{nombre_cliente} - Error API ({codigo}): {e}")
        decision = "NO"

    time.sleep(PAUSA_ENTRE_REQ + random.uniform(0, 0.2))
    return codigo, decision, nombre, desc

# ============================================================
# PROCESO POR CLIENTE
# ============================================================

def procesar_cliente(config_file: str):
    nombre_cliente = config_file.replace("_config.py", "")
    print(f"\n🧾 Procesando cliente: {nombre_cliente.upper()}")

    try:
        cfg = cargar_config_cliente(config_file)
        openai.api_key = getattr(cfg, "IA_API_KEY", None)
        if not openai.api_key:
            raise ValueError("IA_API_KEY no definida en el config del cliente.")

        modelo = getattr(cfg, "IA_MODELO", "gpt-4o-mini")
        descripcion_cliente = getattr(cfg, "DESCRIPCION_CLIENTE", "")

        # --- Archivo de ejecución más reciente (sin restringir al día de hoy) ---
        salida_base = Path(getattr(cfg, "DIRECTORIO_SALIDA", BASE_DIR / "resultados" / nombre_cliente.lower()))
        carpetas_mes = sorted(salida_base.glob("*/*"), reverse=True)  # busca todas las subcarpetas año/mes
        archivo_ejecucion = None

        for carpeta in carpetas_mes:
            candidato = obtener_mas_reciente_en(carpeta, "*_alas_*.json")
            if candidato:
                archivo_ejecucion = candidato
                break

        if not archivo_ejecucion:
            print(f"⚠️  No se encontró ningún archivo de ejecución reciente para {nombre_cliente}")
            return


        data = json.loads(archivo_ejecucion.read_text(encoding="utf-8"))
        licitaciones = data.get("resumen", [])
        if not licitaciones:
            print(f"⚠️  {nombre_cliente}: no hay licitaciones en 'resumen'.")
            return

        # --- Memoria IA ---
        cfg_path  = CLIENTES_DIR / config_file
        chash     = hash_config(cfg_path)
        h_ia      = cargar_historial_ia(nombre_cliente)
        bucket    = h_ia["por_hash"].setdefault(chash, {})

        pendientes = [
            lic for lic in licitaciones
            if isinstance(lic, dict)
            and lic.get("CodigoExterno")
            and lic["CodigoExterno"] not in bucket
        ]

        if MODO_DEBUG:
            pendientes = random.sample(pendientes, min(20, len(pendientes)))
            print(f"🧩 Modo debug: IA evaluará {len(pendientes)} pendientes.")

        total = len(licitaciones)
        por_ia = len(pendientes)
        print(f"📊 {total} licitaciones ({por_ia} nuevas para IA, {total-por_ia} desde memoria)\n")

        resultados_finales = []
        codigos_si_totales = set(data.get("ia_codigos_si", []))

        # --- Evaluación en paralelo ---
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(evaluar_licitacion, lic, descripcion_cliente, modelo, nombre_cliente): lic
                for lic in pendientes
            }

            for idx, future in enumerate(as_completed(futures), start=1):
                codigo, decision, nombre, desc = future.result()
                print(f"[{idx}/{por_ia}] {codigo}: {decision}")
                bucket[codigo] = decision
                resultados_finales.append({
                    "CodigoExterno": codigo,
                    "Nombre": nombre,
                    "Descripcion": desc,
                    "decision_ia": decision
                })
                if decision == "SI":
                    codigos_si_totales.add(codigo)

        # --- Fusionar y guardar en archivo de ejecución ---
        data["ia_filtro"] = fusionar_sin_duplicar(data.get("ia_filtro", []), resultados_finales)
        data["ia_codigos_si"] = sorted(list(codigos_si_totales))
        archivo_ejecucion.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        h_ia["por_hash"][chash] = bucket
        guardar_historial_ia(nombre_cliente, h_ia)

        # --- Actualizar archivo acumulado de activas ---
        try:
            p_act = path_activas(nombre_cliente)
            existentes = set()
            if p_act.exists():
                try:
                    existentes = set(json.loads(p_act.read_text(encoding="utf-8")).get("activas", []))
                except Exception:
                    existentes = set()
            combinadas = sorted(list(existentes | set(data["ia_codigos_si"])))
            p_act.write_text(json.dumps({"activas": combinadas}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logging.error(f"{nombre_cliente} - Error guardando activas: {e}")

        print(f"\n✅ Filtro IA completado para {nombre_cliente.upper()}.")
        print(f"   • Total: {total}")
        print(f"   • Evaluadas por IA: {por_ia}")
        print(f"   • SI acumulados (día): {len(data['ia_codigos_si'])}")
        print(f"   • Activas acumuladas (global): {len(combinadas)}")
        print(f"📁 Archivo actualizado: {archivo_ejecucion.name}")

    except Exception as e:
        logging.error(f"{nombre_cliente} - Error general: {e}")
        print(f"❌ Error procesando cliente {nombre_cliente}: {e}")

# ============================================================
# MAIN
# ============================================================

def main():
    clientes = [f.name for f in CLIENTES_DIR.glob("*_config.py")]
    if not clientes:
        print("⚠️  No se encontraron archivos *_config.py.")
        return

    print(f"🔍 Clientes detectados: {', '.join([c.replace('_config.py','') for c in clientes])}")
    for config_file in clientes:
        procesar_cliente(config_file)

    print("\n🏁 Proceso completado para todos los clientes.")

if __name__ == "__main__":
    main()

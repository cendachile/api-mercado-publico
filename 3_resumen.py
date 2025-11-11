#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
sys.dont_write_bytecode = True
import os, json, datetime
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================

CLIENTES_DIR = Path("./clientes")
RESULTADOS_DIR = Path("./resultados")

if not CLIENTES_DIR.exists():
    raise FileNotFoundError("No existe la carpeta 'clientes'.")

# ============================================================
# UTILIDADES
# ============================================================

def obtener_mas_reciente_en(dir_path: Path, patron: str):
    """Devuelve el archivo más reciente que coincide con el patrón en dir_path."""
    archivos = list(dir_path.glob(patron))
    if not archivos:
        return None
    return max(archivos, key=os.path.getmtime)

def fusionar_sin_duplicar(lista_existente, lista_nueva, clave="CodigoExterno"):
    """Fusiona listas de dicts eliminando duplicados por clave."""
    if not isinstance(lista_existente, list): lista_existente = []
    if not isinstance(lista_nueva, list): lista_nueva = []
    vistos = {x.get(clave) for x in lista_existente if isinstance(x, dict)}
    fusion = list(lista_existente)
    for item in lista_nueva:
        if isinstance(item, dict):
            k = item.get(clave)
            if k and k not in vistos:
                fusion.append(item)
                vistos.add(k)
    return fusion

# ============================================================
# PROCESO POR CLIENTE
# ============================================================

def procesar_cliente(nombre_cliente: str):
    cliente_lower = nombre_cliente.lower()
    base_dir = RESULTADOS_DIR / cliente_lower
    if not base_dir.exists():
        print(f"⚠️  Saltando cliente {nombre_cliente}: no existe {base_dir}")
        return

    ahora = datetime.datetime.now()
    y, m, d = ahora.year, ahora.month, ahora.day
    hh, mm, ss = ahora.hour, ahora.minute, ahora.second

    carpeta_mes = base_dir / f"{y}" / f"{m:02d}"
    carpeta_mes.mkdir(parents=True, exist_ok=True)
    # Archivo por EJECUCIÓN: DD_alas_HH_MM.json
    archivo_ejecucion = carpeta_mes / f"{d:02d}_alas_{hh:02d}_{mm:02d}.json"

    # --- Buscar archivos base más recientes ---
    path_consol = obtener_mas_reciente_en(base_dir, "resultados_consolidados_*.json")
    path_scoring = obtener_mas_reciente_en(base_dir, "scoring_*.json")

    if not path_scoring and not path_consol:
        print(f"⚠️  Cliente {nombre_cliente}: no se encontró ni scoring_*.json ni resultados_consolidados_*.json")
        return

    print(f"\n🧾 Procesando cliente: {nombre_cliente.upper()}")
    if path_scoring:
        print(f"📊 Usando scoring: {path_scoring.name}")
    else:
        print("📊 Sin scoring disponible (continuará solo con consolidados)")
    if path_consol:
        print(f"📁 Usando consolidados: {path_consol.name}")
    else:
        print("📁 Sin consolidados disponibles (continuará solo con scoring)")

    # --- Cargar scoring ---
    lista_scoring = []
    if path_scoring:
        with open(path_scoring, "r", encoding="utf-8") as f:
            scoring_json = json.load(f)
        lista_scoring = scoring_json.get("resultados", []) if isinstance(scoring_json, dict) else []

    # --- Generar resumen a partir de scoring ---
    resumen_items = [
        {
            "CodigoExterno": lic.get("CodigoExterno"),
            "Nombre": lic.get("Nombre"),
            "Descripcion": lic.get("Descripcion"),
            "MontoEstimado": lic.get("MontoEstimado"),
            "Tipo": lic.get("Tipo"),
            "score_total": lic.get("score_total"),
        }
        for lic in lista_scoring if isinstance(lic, dict)
    ]

    # --- Cargar consolidados ---
    lista_consolidados = []
    if path_consol and path_consol.exists():
        with open(path_consol, "r", encoding="utf-8") as f:
            consol_json = json.load(f)
        if isinstance(consol_json, dict):
            if isinstance(consol_json.get("licitaciones"), list):
                lista_consolidados = consol_json["licitaciones"]
            else:
                # fallback si viniera como dict con alguna lista
                for v in consol_json.values():
                    if isinstance(v, list):
                        lista_consolidados = v
                        break
        elif isinstance(consol_json, list):
            lista_consolidados = consol_json

    # --- tokens estimados ---
    total_chars = sum(len((x.get("Nombre") or "") + (x.get("Descripcion") or "")) for x in resumen_items)
    tokens_estimados = round(total_chars / 4)

    # --- Construir salida de ESTA EJECUCIÓN (sin acumular previos) ---
    salida = {
        "cliente": nombre_cliente,
        "fecha": ahora.date().isoformat(),
        "hora": f"{hh:02d}:{mm:02d}:{ss:02d}",
        "resultados_consolidados": fusionar_sin_duplicar([], lista_consolidados),
        "scoring": fusionar_sin_duplicar([], lista_scoring),
        "resumen": fusionar_sin_duplicar([], resumen_items),
        "tokens_estimados": tokens_estimados
    }

    # --- Guardar archivo por ejecución ---
    with open(archivo_ejecucion, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print(f"✅ Datos fusionados y guardados en: {archivo_ejecucion}")
    print(f"   - Consolidados: {len(salida['resultados_consolidados'])}")
    print(f"   - Scoring: {len(salida['scoring'])}")
    print(f"   - Resumen: {len(salida['resumen'])}")
    print(f"   - Tokens estimados: {tokens_estimados}")

    # --- Limpieza de archivos base ---
    try:
        if path_consol and path_consol.exists():
            os.remove(path_consol)
            print(f"🧹 Borrado: {path_consol.name}")
        if path_scoring and path_scoring.exists():
            os.remove(path_scoring)
            print(f"🧹 Borrado: {path_scoring.name}")
    except Exception as e:
        print(f"⚠️ No se pudieron borrar archivos base: {e}")

# ============================================================
# PRINCIPAL
# ============================================================

def main():
    clientes = [
        f.stem.replace("_config", "")
        for f in CLIENTES_DIR.glob("*_config.py")
    ]

    if not clientes:
        print("⚠️ No se encontraron archivos *_config.py en la carpeta clientes.")
        return

    print(f"🔍 Clientes detectados: {', '.join(clientes)}")

    for cliente in clientes:
        procesar_cliente(cliente)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RUN.py
Ejecuta secuencialmente todos los scripts del flujo de procesamiento.
Cada script se ejecuta solo cuando el anterior termina correctamente.
"""

import subprocess
import sys
from pathlib import Path

# ============================================================
# CONFIGURACIÓN
# ============================================================

SCRIPTS = [
    "0_actualizar_licitaciones.py",
    "1_filtro_duro.py",
    "2_scoring.py",
    "3_resumen.py",
    "4_filtro_IA.py",
    "5_comprobar_vigencia.py",
    "6_presentar_resultados.py"
]

BASE_DIR = Path(__file__).resolve().parent

# ============================================================
# EJECUCIÓN
# ============================================================

def run_script(script_name: str):
    script_path = BASE_DIR / script_name
    if not script_path.exists():
        print(f"⚠️  No se encontró: {script_name}, se omite.")
        return False

    print(f"\n🚀 Ejecutando {script_name} ...")
    try:
        result = subprocess.run([sys.executable, str(script_path)], check=True)
        print(f"✅ {script_name} completado.\n")
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"❌ Error en {script_name} (código {e.returncode}). Deteniendo ejecución.")
        return False
    except Exception as e:
        print(f"❌ Error inesperado en {script_name}: {e}")
        return False

def main():
    print("=== INICIO DEL PROCESO SECUENCIAL ===")
    for script in SCRIPTS:
        ok = run_script(script)
        if not ok:
            print("🛑 Proceso detenido por error.")
            sys.exit(1)
    print("\n🏁 Todos los scripts ejecutados correctamente.")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
sys.dont_write_bytecode = True
import os, json, datetime, logging
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ============================================================
# CONFIG
# ============================================================

BASE_DIR       = Path(__file__).resolve().parent
CLIENTES_DIR   = BASE_DIR / "clientes"
RESULTADOS_DIR = BASE_DIR / "resultados"
BASE_LOCAL     = BASE_DIR / "base_local"
HIST_DIR       = BASE_DIR / "historial"
LOG_DIR        = BASE_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=LOG_DIR / "presentar_resultados.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BUSCAR_DIAS_ATRAS = 60
NOMBRE_HOJA_DATOS = "Licitaciones activas"
NOMBRE_HOJA_RESUM = "Resumen"
NOMBRE_HOJA_FALT  = "No_encontrados"

# ============================================================
# UTILIDADES
# ============================================================

def cargar_config_names() -> List[str]:
    return [f.stem.replace("_config", "") for f in CLIENTES_DIR.glob("*_config.py")]

def path_activas(cliente: str) -> Path:
    return HIST_DIR / f"licitaciones_activas_{cliente.lower()}.json"

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def buscar_licitaciones_en_base_local(codigos: List[str]) -> Tuple[List[dict], List[str]]:
    objetivos = set(map(str, codigos))
    if not objetivos:
        return [], []

    encontradas: Dict[str, dict] = {}
    hoy = date.today()
    ya_cargados: Dict[Path, Optional[List[dict]]] = {}

    for delta in range(BUSCAR_DIAS_ATRAS + 1):
        if len(encontradas) == len(objetivos):
            break
        dt = hoy - timedelta(days=delta)
        p = BASE_LOCAL / f"{dt.year}" / f"{dt.month:02d}" / f"{dt.day:02d}.json"
        if not p.exists():
            continue

        if p not in ya_cargados:
            data = load_json(p, [])
            ya_cargados[p] = data if isinstance(data, list) else []

        for lic in ya_cargados[p] or []:
            cod = str(lic.get("CodigoExterno", "")).strip()
            if cod and cod in objetivos and cod not in encontradas:
                encontradas[cod] = lic
                if len(encontradas) == len(objetivos):
                    break

    no_encontradas = sorted(list(objetivos - set(encontradas.keys())))
    return list(encontradas.values()), no_encontradas

def _get_comprador_field(lic: dict, key: str, fallback_key: Optional[str] = None) -> str:
    """
    Extrae campos desde lic['Comprador'][key] si existe; si no, intenta fallback_key en la raíz.
    """
    comp = lic.get("Comprador")
    if isinstance(comp, dict) and key in comp:
        val = comp.get(key, "")
        return "" if val is None else str(val)
    if fallback_key:
        val = lic.get(fallback_key, "")
        return "" if val is None else str(val)
    return ""

def _get_monto(lic: dict):
    """
    Obtiene el monto de la licitación.
    Prioriza MontoEstimado, luego Monto. Devuelve número o string.
    """
    val = lic.get("MontoEstimado")
    if val in (None, "", 0):
        val = lic.get("Monto")
    # si es string numérica, intenta castear
    if isinstance(val, str):
        try:
            return float(val.replace(".", "").replace(",", "."))
        except Exception:
            return val
    return val if val is not None else ""

def _get_fecha_cierre(lic: dict) -> str:
    """
    Obtiene la fecha de cierre y la formatea como: DD-MM-AAAA / HH:MM.
    Prioriza 'FechaCierre' directo y luego 'Fechas'['FechaCierre'].
    Si no se puede parsear, devuelve el valor original.
    """
    fc = lic.get("FechaCierre")
    if not fc:
        fechas = lic.get("Fechas")
        if isinstance(fechas, dict):
            fc = fechas.get("FechaCierre", "")
    if not fc:
        return ""

    fc_str = str(fc).strip()
    # Normalizamos para intentar parsear YYYY-MM-DD HH:MM:SS o YYYY-MM-DDTHH:MM:SS
    fc_clean = fc_str.replace("T", " ")

    # Intento simple por slicing si respeta el patrón YYYY-MM-DD HH:MM:SS
    try:
        if len(fc_clean) >= 16 and fc_clean[4] == "-" and fc_clean[7] == "-":
            y = fc_clean[0:4]
            m = fc_clean[5:7]
            d = fc_clean[8:10]
            h = fc_clean[11:13]
            mi = fc_clean[14:16]
            return f"{d}-{m}-{y} / {h}:{mi}"
    except Exception:
        pass

    # Fallback: si no pudimos formatear, devolvemos tal cual
    return fc_str


def armar_dataframe(licitaciones: List[dict]) -> pd.DataFrame:
    """
    Columnas (en orden):
    N°, Nombre, Descripción, Nombre Organismo, Monto, Fecha Cierre,
    Región, Comuna, CodigoExterno
    """
    rows = []
    for i, lic in enumerate(licitaciones, start=1):
        rows.append({
            "N°":               i,
            "Nombre":           lic.get("Nombre", "") or "",
            "Descripción":      lic.get("Descripcion", "") or "",
            "Nombre Organismo": _get_comprador_field(lic, "NombreOrganismo", "NombreOrganismo"),
            "Monto":            _get_monto(lic),
            "Fecha Cierre":     _get_fecha_cierre(lic),
            "Región":           _get_comprador_field(lic, "RegionUnidad", "RegionUnidad"),
            "Comuna":           _get_comprador_field(lic, "ComunaUnidad", "ComunaUnidad"),
            "CodigoExterno":    lic.get("CodigoExterno", "") or "",
        })
    cols = [
        "N°",
        "Nombre",
        "Descripción",
        "Nombre Organismo",
        "Monto",
        "Fecha Cierre",
        "Región",
        "Comuna",
        "CodigoExterno",
    ]
    return pd.DataFrame(rows, columns=cols)

def escribir_excel_formateado(archivo_salida: Path, cliente: str, df: pd.DataFrame, faltantes: List[str]):
    archivo_salida.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(archivo_salida, engine="xlsxwriter") as writer:
        # ========== Hoja Datos ==========
        df.to_excel(writer, index=False, sheet_name=NOMBRE_HOJA_DATOS)
        wb = writer.book
        ws = writer.sheets[NOMBRE_HOJA_DATOS]

        # Formatos
        fmt_header = wb.add_format({"bold": True, "bg_color": "#E6E6E6", "border": 1})
        fmt_text   = wb.add_format({"text_wrap": False, "border": 1})
        fmt_wrap   = wb.add_format({"text_wrap": True,  "border": 1})
        fmt_code   = wb.add_format({"border": 1})
        fmt_monto  = wb.add_format({"border": 1, "num_format": "#,##0"})

        # Encabezados
        for col_num, col_name in enumerate(df.columns):
            ws.write(0, col_num, col_name, fmt_header)

        # Cuerpo con formatos por columna
        nrows, ncols = df.shape
        for r in range(1, nrows+1):
            for c in range(ncols):
                colname = df.columns[c]
                val = df.iloc[r-1, c]
                if colname == "Descripción":
                    ws.write(r, c, val, fmt_wrap)
                elif colname == "CodigoExterno":
                    ws.write(r, c, val, fmt_code)
                elif colname == "Monto":
                    ws.write(r, c, val, fmt_monto)
                else:
                    ws.write(r, c, val, fmt_text)

        # Anchos de columna (ajustados al nuevo orden)
        ws.set_column("A:A", 6)    # N°
        ws.set_column("B:B", 48)   # Nombre
        ws.set_column("C:C", 90)   # Descripción
        ws.set_column("D:D", 36)   # Nombre Organismo
        ws.set_column("E:E", 16)   # Monto
        ws.set_column("F:F", 22)   # Fecha Cierre
        ws.set_column("G:G", 16)   # Región
        ws.set_column("H:H", 18)   # Comuna
        ws.set_column("I:I", 24)   # CodigoExterno

        # Congelar fila de encabezado
        ws.freeze_panes(1, 0)

        # ========== Hoja Resumen ==========
        resumen = pd.DataFrame({
            "Métrica": [
                "Cliente",
                "Fecha de generación",
                "Total licitaciones activas incluidas",
                "Códigos no encontrados (últimos 60 días)"
            ],
            "Valor": [
                cliente,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                len(df),
                len(faltantes)
            ]
        })
        resumen.to_excel(writer, index=False, sheet_name=NOMBRE_HOJA_RESUM)
        ws_r = writer.sheets[NOMBRE_HOJA_RESUM]
        ws_r.set_column("A:A", 40, wb.add_format({"bold": True}))
        ws_r.set_column("B:B", 60)

        # ========== Hoja No encontrados ==========
        if faltantes:
            pd.DataFrame({"CodigoExterno": faltantes}).to_excel(
                writer, index=False, sheet_name=NOMBRE_HOJA_FALT
            )
            ws_f = writer.sheets[NOMBRE_HOJA_FALT]
            ws_f.set_column("A:A", 30)

def generar_para_cliente(cliente: str):
    print(f"\n🧾 Presentando resultados (activas): {cliente.upper()}")

    # 1) Cargar activas
    p_act = path_activas(cliente)
    if not p_act.exists():
        msg = f"ℹ️  {cliente}: no existe {p_act.name}. Saltando."
        print(msg); logging.info(msg); return

    activas = load_json(p_act, {}).get("activas", [])
    if not activas:
        msg = f"ℹ️  {cliente}: 'activas' vacío en {p_act.name}. Nada que presentar."
        print(msg); logging.info(msg); return

    # 2) Buscar en base_local
    licitaciones, faltantes = buscar_licitaciones_en_base_local(activas)
    if not licitaciones:
        msg = f"ℹ️  {cliente}: no se encontró información en base_local para los códigos activos (últimos {BUSCAR_DIAS_ATRAS} días)."
        print(msg); logging.info(msg); return

    # 3) DataFrame con el nuevo orden/columnas
    df = armar_dataframe(licitaciones)

    # 4) Salida por cliente en resultados/cliente/AAAA/MM
    hoy = date.today()
    carpeta_salida = RESULTADOS_DIR / cliente.lower() / f"{hoy.year}" / f"{hoy.month:02d}"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archivo_excel = carpeta_salida / f"presentacion_activas_{ts}.xlsx"

    # 5) Escribir Excel con formato
    escribir_excel_formateado(archivo_excel, cliente, df, faltantes)

    print(f"✅ Archivo generado: {archivo_excel}")
    print(f"   • Registros incluidos: {len(df)}")
    if faltantes:
        print(f"   • No encontrados (últimos {BUSCAR_DIAS_ATRAS} días): {len(faltantes)}")
    logging.info(f"{cliente} -> {archivo_excel.name} ({len(df)} filas, {len(faltantes)} no encontrados)")

# ============================================================
# MAIN
# ============================================================

def main():
    clientes = cargar_config_names()
    if not clientes:
        print("⚠️  No se encontraron archivos *_config.py en 'clientes'.")
        return

    print(f"🔍 Clientes: {', '.join(clientes)}")
    for cliente in clientes:
        generar_para_cliente(cliente)

    print("\n🏁 Presentación completada.")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
filtro_duro_local.py
Lee licitaciones desde la base local (espejada por 0_actualizar_licitaciones.py),
aplica filtros del cliente y genera resultados consolidados.
"""
import sys
sys.dont_write_bytecode = True
import argparse, datetime, importlib.util, json, hashlib, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ========== paths base ==========
BASE_DIR = Path(__file__).resolve().parent

# ========== utils ==========
def slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in s).strip("_")

def leer_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def escribir_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def cargar_config(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)                # type: ignore
    oblig = ["NOMBRE_CLIENTE","MONTO_MINIMO","MONTO_MAXIMO","TIPOS_LICITACION_ACEPTABLES",
             "ESTADOS_ACEPTABLES","MONEDAS_ACEPTABLES","DIAS_MINIMOS_PREPARACION","DIRECTORIO_SALIDA"]
    faltan = [k for k in oblig if not hasattr(mod, k)]
    if faltan: raise ValueError(f"{path.name}: faltan claves en config: {faltan}")
    if not hasattr(mod, "REGIONES_PRIORITARIAS"): mod.REGIONES_PRIORITARIAS = []  # no se usa para filtrar
    if not hasattr(mod, "MAX_DIAS_ATRAS"):        mod.MAX_DIAS_ATRAS = 30
    return mod

def hash_config(path: Path) -> str:
    try: return hashlib.md5(path.read_bytes()).hexdigest()[:10]
    except Exception: return "nohash"

def parse_int_safe(v: Any) -> Optional[int]:
    try: return int(str(v)) if v is not None and str(v).strip() != "" else None
    except Exception: return None

def parse_iso(s: Optional[str]) -> Optional[datetime.datetime]:
    if not s: return None
    s = s.rstrip("Z")
    try: return datetime.datetime.fromisoformat(s.split(".")[0])
    except Exception: return None

def dias_hasta_cierre(lic: Dict[str, Any]) -> Optional[int]:
    d = parse_int_safe(lic.get("DiasCierreLicitacion"))
    if d is not None and d >= 0: return d
    fc = parse_iso(((lic.get("Fechas") or {}).get("FechaCierre")))
    return (fc - datetime.datetime.now()).days if fc else None

def fmt_dur(s: float) -> str:
    s = int(s)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h: return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

# ========== filtro duro ==========
def pasa_filtros_duros(lic: Dict[str, Any], cfg) -> Tuple[bool, str]:
    if lic.get("CodigoEstado") not in set(cfg.ESTADOS_ACEPTABLES):
        return False, f"Estado {lic.get('CodigoEstado')} no aceptable"
    tipo = (lic.get("Tipo") or "").strip().upper()
    if tipo and tipo not in {t.upper() for t in cfg.TIPOS_LICITACION_ACEPTABLES}:
        return False, f"Tipo {tipo} no aceptable"
    mon = (lic.get("Moneda") or "").strip().upper()
    if mon and mon not in {m.upper() for m in cfg.MONEDAS_ACEPTABLES}:
        return False, f"Moneda {mon} no aceptable"
    monto = lic.get("MontoEstimado")
    if isinstance(monto, (int, float)) and monto > 0:
        if monto < cfg.MONTO_MINIMO: return False, f"Monto {monto} < mínimo"
        if monto > cfg.MONTO_MAXIMO: return False, f"Monto {monto} > máximo"
    dias = dias_hasta_cierre(lic)
    if dias is not None and dias < cfg.DIAS_MINIMOS_PREPARACION: return False, f"Días {dias} < mínimos"
    if not lic.get("CodigoExterno") or not lic.get("Nombre"): return False, "Faltan campos básicos"
    return True, ""

# ========== helpers locales ==========
def cargar_catalogo_local(catalog_path: Path) -> Dict[str, str]:
    data = leer_json(catalog_path, {})
    # catalog_local.json: { "YYYY-MM-DD": "checksum", ... } (según 0_actualizar)
    if isinstance(data, dict): return data
    # Compatibilidad si viniera como {"dias":[{"fecha":...,"checksum":...}]}
    out = {}
    dias = data.get("dias", []) if isinstance(data, dict) else []
    for d in dias:
        f, cs = d.get("fecha"), d.get("checksum")
        if isinstance(f, str) and f and cs: out[f] = cs
    return out

def fechas_a_procesar(catalogo: Dict[str, str], max_dias: int) -> List[str]:
    fechas = sorted(catalogo.keys(), reverse=True)
    if max_dias is not None and max_dias > 0:
        fechas = fechas[:max_dias]
    return fechas

def cargar_dia_local(base_dir: Path, fecha: str) -> List[Dict[str, Any]]:
    try:
        y, m, d = fecha.split("-")
        path = base_dir / y / m / f"{d}.json"
        data = leer_json(path, [])
        return data if isinstance(data, list) else []
    except Exception:
        return []

# ========== proceso principal ==========
def procesar_cliente_local(cfg, cfg_path: Path, base_dir: Path, catalog_path: Path,
                           max_dias_cli: int, dry_run: bool=False):
    nombre, scli, chash = cfg.NOMBRE_CLIENTE, slug(cfg.NOMBRE_CLIENTE), hash_config(cfg_path)

    catalogo = cargar_catalogo_local(catalog_path)
    if not catalogo:
        print(f"[{nombre}] ❌ No se encontró catálogo local en {catalog_path}")
        return {
            "cliente": nombre, "config_hash": chash, "generado": datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            "rango_dias": 0, "total_consultadas": 0, "nuevas_filtradas": 0,
            "descartadas_por_filtro": 0, "detalle_por_dia": [], "licitaciones": []
        }

    dias = fechas_a_procesar(catalogo, max_dias_cli)
    total_dias = len(dias)
    if total_dias == 0:
        print(f"- {nombre} [{chash}]: no hay días que procesar (catálogo vacío).")
        return {
            "cliente": nombre, "config_hash": chash, "generado": datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            "rango_dias": 0, "total_consultadas": 0, "nuevas_filtradas": 0,
            "descartadas_por_filtro": 0, "detalle_por_dia": [], "licitaciones": []
        }

    t0 = time.time()
    nuevas_global: List[Dict[str, Any]] = []
    resumen_por_dia: List[Dict[str, Any]] = []
    total_consultadas = total_descartadas = 0

    for i, dia_str in enumerate(dias, start=1):
        elapsed = time.time() - t0
        eta = (elapsed / i) * (total_dias - i) if i > 0 else 0
        print(f"[{nombre}] Día {i}/{total_dias} → {dia_str} | t={fmt_dur(elapsed)} ETA={fmt_dur(eta)}")

        entrada = cargar_dia_local(base_dir, dia_str)
        consultadas = len(entrada)
        nuevas_dia: List[Dict[str, Any]] = []
        descartadas_dia = 0

        for lic in entrada:
            ok, _ = pasa_filtros_duros(lic, cfg)
            if ok: nuevas_dia.append(lic)
            else:  descartadas_dia += 1

        nuevas_global.extend(nuevas_dia)
        total_consultadas += consultadas
        total_descartadas += descartadas_dia

        resumen_por_dia.append({
            "dia": dia_str,
            "consultadas": consultadas,
            "nuevas": len(nuevas_dia),
            "descartadas": descartadas_dia
        })

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "cliente": nombre, "config_hash": chash, "generado": ts,
        "rango_dias": total_dias, "total_consultadas": total_consultadas,
        "nuevas_filtradas": len(nuevas_global), "descartadas_por_filtro": total_descartadas,
        "detalle_por_dia": resumen_por_dia, "licitaciones": nuevas_global,
    }

    out_dir = Path(getattr(cfg, "DIRECTORIO_SALIDA", f"./resultados/{scli}"))
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        escribir_json(out_dir / f"resultados_consolidados_{ts}.json", out)

    print(f"- {nombre} [{chash}]: nuevas={len(nuevas_global)}, descartadas={total_descartadas}, consultadas={total_consultadas}")
    return out

# ========== main ==========
def main():
    ap = argparse.ArgumentParser(description="Filtro duro local (sin API) con progreso.")
    ap.add_argument("--clientes_dir", default=str(BASE_DIR / "clientes"))
    ap.add_argument("--base-dir", default=str(BASE_DIR / "base_local"), help="Directorio raíz de la base local")
    ap.add_argument("--catalog",  default=str(BASE_DIR / "catalog_local.json"), help="Ruta a catalog_local.json")
    ap.add_argument("--max-dias", type=int, default=None, help="Límite de días hacia atrás a procesar")
    ap.add_argument("--dry-run",  action="store_true")
    args = ap.parse_args()

    cfg_paths = sorted(Path(args.clientes_dir).glob("*_config.py"))
    if not cfg_paths:
        print(f"No se encontraron configs en {args.clientes_dir}")
        return

    base_dir = Path(args.base_dir)
    catalog_path = Path(args.catalog)

    resumen_global = []
    for p in cfg_paths:
        cfg = cargar_config(p)
        max_dias_cli = args.max_dias if args.max_dias is not None else getattr(cfg, "MAX_DIAS_ATRAS", 30)
        res = procesar_cliente_local(
            cfg, p, base_dir, catalog_path, max_dias_cli, dry_run=args.dry_run
        )
        resumen_global.append({
            "cliente": res["cliente"], "hash": res.get("config_hash"),
            "nuevas": res.get("nuevas_filtradas", 0),
            "descartadas": res.get("descartadas_por_filtro", 0),
            "consultadas": res.get("total_consultadas", 0)
        })

    print("\nResumen:")
    print(json.dumps(resumen_global, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

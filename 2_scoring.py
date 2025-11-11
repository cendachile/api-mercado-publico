#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
sys.dont_write_bytecode = True
import argparse, importlib.util, json, re, datetime, random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -------- util --------

def slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in s).strip("_")

def leer_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def escribir_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def cargar_config(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)                # type: ignore
    oblig = [
        "NOMBRE_CLIENTE","DIRECTORIO_SALIDA","PONDERACIONES",
        "CATEGORIAS_UNSPSC_RELEVANTES","KEYWORDS_TEMATICAS",
        "PESO_CATEGORIA_UNSPSC","PESO_KEYWORDS","MIN_KEYWORDS_MATCH",
        "MONTO_OPTIMO_MIN","MONTO_OPTIMO_MAX",
        "DIAS_OPTIMOS_PREPARACION","DIAS_MINIMOS_PREPARACION","DIAS_MAXIMOS_BENEFICIO",
        "REGIONES_PRIORITARIAS","SCORE_MINIMO_RESULTADO"
    ]
    faltan = [k for k in oblig if not hasattr(mod, k)]
    if faltan: raise ValueError(f"{path.name}: faltan claves en config: {faltan}")
    return mod

def texto(lic: Dict[str, Any]) -> str:
    return (str(lic.get("Nombre") or "") + " " + str(lic.get("Descripcion") or "")).lower()

def dias_hasta_cierre(lic: Dict[str, Any]) -> Optional[int]:
    v = lic.get("DiasCierreLicitacion")
    if v is not None and str(v).strip() != "":
        try: return int(str(v).strip())
        except Exception: pass
    from datetime import datetime
    fc = (lic.get("Fechas") or {}).get("FechaCierre")
    if not fc: return None
    try:
        base = str(fc).rstrip("Z").split(".")[0]
        dt = datetime.fromisoformat(base)
        return (dt - datetime.now()).days
    except Exception:
        return None

def extraer_unspsc(lic: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    items = (lic.get("Items") or {}).get("Listado") or []
    for it in items:
        code = str(it.get("CodigoCategoria") or "").strip()
        if code and code.isdigit(): out.append(code)
    return out

# -------- scoring --------

def score_match_tematico(lic: Dict[str, Any], cfg) -> Tuple[float, Dict[str, Any]]:
    # UNSPSC (profundidad 2/4/6/8)
    lic_codes = extraer_unspsc(lic)
    rel_codes = [str(c) for c in cfg.CATEGORIAS_UNSPSC_RELEVANTES]
    best_unspsc = 0.0
    hits_unspsc: List[Tuple[str, str, float]] = []
    for lc in lic_codes:
        m_local = 0.0; m_with = None
        for rc in rel_codes:
            depth = 0.0
            if len(lc) >= 8 and len(rc) >= 8:
                if lc[:8] == rc[:8]: depth = 1.0
                elif lc[:6] == rc[:6]: depth = 0.8
                elif lc[:4] == rc[:4]: depth = 0.6
                elif lc[:2] == rc[:2]: depth = 0.4
            if depth > m_local:
                m_local, m_with = depth, rc
        best_unspsc = max(best_unspsc, m_local)
        if m_with and m_local > 0:
            hits_unspsc.append((lc, m_with, m_local))

    # Keywords positivas
    body = texto(lic)
    found_pos = []
    for kw in cfg.KEYWORDS_TEMATICAS:
        if re.search(r"\b" + re.escape(str(kw).lower()) + r"\b", body):
            found_pos.append(str(kw).lower())
    n_pos = len(set(found_pos))

    # Puntaje por keywords positivas (como antes)
    if cfg.MIN_KEYWORDS_MATCH <= 0:
        kw_score = 1.0 if n_pos > 0 else 0.0
    else:
        kw_score = min(n_pos / float(cfg.MIN_KEYWORDS_MATCH), 1.0)

    # Score temático base (UNSPSC + keywords positivas)
    mt_base = cfg.PESO_CATEGORIA_UNSPSC * best_unspsc + cfg.PESO_KEYWORDS * kw_score
    mt_base = max(0.0, min(mt_base, 1.0)) * 100.0

    # ---------- Balance positivo/negativo ----------
    penal_list = getattr(cfg, "KEYWORDS_PENALIZADORAS", []) or []
    found_neg = []
    for kw in penal_list:
        if re.search(r"\b" + re.escape(str(kw).lower()) + r"\b", body):
            found_neg.append(str(kw).lower())
    n_neg = len(set(found_neg))

    # Parámetros con defaults seguros
    peso_neg = float(getattr(cfg, "PESO_NEGATIVO", 1.5))         # cuánto pesa cada negativa vs una positiva
    factor_adj = float(getattr(cfg, "AJUSTE_BALANCE_FACTOR", 0.5))  # cuánto influye el balance en el score

    # BC en [-1, +1] aprox: positivo si predominan positivas, negativo si predominan negativas
    bc_num = (n_pos - (n_neg * peso_neg))
    bc_den = (n_pos + n_neg + 1)  # +1 evita división por cero
    balance_ctx = bc_num / bc_den

    # Ajuste multiplicativo del score temático base
    mt_ajustado = mt_base * (1.0 + balance_ctx * factor_adj)
    mt_ajustado = max(0.0, min(mt_ajustado, 100.0))

    meta = {
        "unspsc_best": round(best_unspsc, 3),
        "unspsc_hits": [{"licitacion": a, "relevante": b, "peso": c} for a, b, c in hits_unspsc],
        "keywords_encontradas": sorted(set(found_pos)),
        "keywords_count": n_pos,
        "keywords_score": round(kw_score, 3),
        "penalizadoras_encontradas": sorted(set(found_neg)),
        "penalizadoras_count": n_neg,
        "balance_contexto": round(balance_ctx, 3),
        "tematico_base": round(mt_base, 2),
    }
    return mt_ajustado, meta


def score_viabilidad_financiera(lic: Dict[str, Any], cfg) -> Tuple[float, Dict[str, Any]]:
    monto = lic.get("MontoEstimado"); vis = lic.get("VisibilidadMonto")
    if monto in (None,0) or (isinstance(vis,int) and vis==0 and not monto):
        return 50.0, {"monto": monto, "nota": "sin_monto=50%"}
    if not isinstance(monto,(int,float)) or monto<0: return 0.0, {"monto": monto, "nota":"monto_invalido"}
    a,b = cfg.MONTO_OPTIMO_MIN, cfg.MONTO_OPTIMO_MAX
    if a<=monto<=b: return 100.0, {"monto": monto, "rango":[a,b]}
    if monto < a:
        lo = getattr(cfg,"MONTO_MINIMO",0) or 0
        if a==lo: return 0.0, {"monto": monto, "rango":[a,b]}
        val = max(0.0, min(1.0,(monto-lo)/float(a-lo)))*100.0
        return val, {"monto": monto, "rango":[a,b]}
    hi = getattr(cfg,"MONTO_MAXIMO",b)
    if hi==b: return 0.0, {"monto": monto, "rango":[a,b]}
    val = max(0.0, min(1.0,(hi-monto)/float(hi-b)))*100.0
    return val, {"monto": monto, "rango":[a,b]}

def score_oportunidad_temporal(lic: Dict[str, Any], cfg) -> Tuple[float, Dict[str, Any]]:
    d = dias_hasta_cierre(lic)
    if d is None: return 0.0, {"dias": None, "nota":"sin_fecha_cierre"}
    if d <= cfg.DIAS_MINIMOS_PREPARACION: return 0.0, {"dias": d}
    if d >= cfg.DIAS_OPTIMOS_PREPARACION: return 100.0, {"dias": d}
    rng = cfg.DIAS_OPTIMOS_PREPARACION - cfg.DIAS_MINIMOS_PREPARACION
    val = max(0.0, min(1.0,(d-cfg.DIAS_MINIMOS_PREPARACION)/float(rng)))*100.0
    return val, {"dias": d}

def score_ventaja_geografica(lic: Dict[str, Any], cfg) -> Tuple[float, Dict[str, Any]]:
    reg = ((lic.get("Comprador") or {}).get("RegionUnidad") or "").strip()
    ok = 1.0 if reg and reg in (cfg.REGIONES_PRIORITARIAS or []) else 0.0
    return ok*100.0, {"region": reg}

def combinar_scores(sub: Dict[str, float], cfg) -> float:
    P = cfg.PONDERACIONES
    total = (P["match_tematico"]*sub["match_tematico"]
           + P["viabilidad_financiera"]*sub["viabilidad_financiera"]
           + P["oportunidad_temporal"]*sub["oportunidad_temporal"]
           + P["ventaja_geografica"]*sub["ventaja_geografica"]) / 100.0
    return round(total, 2)

# -------- IO --------

def encontrar_ultimo_resultado_consolidado(dir_salida: Path) -> Optional[Path]:
    files = sorted(dir_salida.glob("resultados_consolidados_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None

def procesar_cliente(cfg, input_path: Optional[str], min_score_override: Optional[int],
                     dump_descartadas: bool, dump_count: int, dry_run: bool=False) -> Dict[str, Any]:
    nombre = cfg.NOMBRE_CLIENTE
    out_dir = Path(cfg.DIRECTORIO_SALIDA)

    entrada = Path(input_path) if input_path else encontrar_ultimo_resultado_consolidado(out_dir)
    if not entrada or not entrada.exists():
        print(f"- {nombre}: no hay resultados_consolidados_*.json en {out_dir}")
        return {"cliente": nombre, "procesadas": 0, "guardadas": 0}

    data = leer_json(entrada)
    licits = data.get("licitaciones", []) if isinstance(data, dict) else []
    if not isinstance(licits, list):
        print(f"- {nombre}: formato inesperado en {entrada.name}")
        return {"cliente": nombre, "procesadas": 0, "guardadas": 0}

    resultados: List[Dict[str, Any]] = []
    descartadas_tmp: List[Dict[str, Any]] = []

    for lic in licits:
        s_mt, meta_mt = score_match_tematico(lic, cfg)
        s_vf, meta_vf = score_viabilidad_financiera(lic, cfg)
        s_ot, meta_ot = score_oportunidad_temporal(lic, cfg)
        s_vg, meta_vg = score_ventaja_geografica(lic, cfg)

        subs = {
            "match_tematico": round(s_mt, 2),
            "viabilidad_financiera": round(s_vf, 2),
            "oportunidad_temporal": round(s_ot, 2),
            "ventaja_geografica": round(s_vg, 2),
        }
        score_total = combinar_scores(subs, cfg)

        lic_out = {
            "CodigoExterno": lic.get("CodigoExterno"),
            "Nombre": lic.get("Nombre"),
            "Descripcion": lic.get("Descripcion"),
            "Comprador": lic.get("Comprador"),
            "Tipo": lic.get("Tipo"),
            "Moneda": lic.get("Moneda"),
            "MontoEstimado": lic.get("MontoEstimado"),
            "Fechas": lic.get("Fechas"),
            "subscores": subs,
            "score_total": score_total,
            "meta": {
                "tematico": meta_mt,
                "financiero": meta_vf,
                "temporal": meta_ot,
                "geografico": meta_vg
            }
        }
        resultados.append(lic_out)

    min_score = min_score_override if min_score_override is not None else cfg.SCORE_MINIMO_RESULTADO
    aprobadas = [r for r in resultados if r["score_total"] >= min_score]
    aprobadas.sort(key=lambda r: r["score_total"], reverse=True)

    # preparar descartadas (para muestreo aleatorio opcional)
    descartadas_tmp = [r for r in resultados if r["score_total"] < min_score]

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    salida = {
        "cliente": nombre,
        "generado": ts,
        "archivo_entrada": str(entrada),
        "procesadas": len(licits),
        "guardadas": len(aprobadas),
        "score_minimo": min_score,
        "resultados": aprobadas
    }

    if not dry_run:
        escribir_json(out_dir / f"scoring_{ts}.json", salida)

        if dump_descartadas and descartadas_tmp:
            sample = random.sample(descartadas_tmp, k=min(dump_count, len(descartadas_tmp)))
            # dejar solo lo necesario
            sample_clean = [{
                "CodigoExterno": s.get("CodigoExterno"),
                "score_total": s.get("score_total"),
                "Nombre": s.get("Nombre"),
                "Descripcion": s.get("Descripcion"),
            } for s in sample]
            escribir_json(out_dir / f"scoring_descartadas_sample_{ts}.json", {
                "cliente": nombre,
                "generado": ts,
                "score_minimo": min_score,
                "total_descartadas": len(descartadas_tmp),
                "muestra_count": len(sample_clean),
                "muestra": sample_clean
            })

    print(f"- {nombre}: procesadas={len(licits)}, guardadas={len(aprobadas)} (min={min_score})"
          + (f", descartadas_sample={min(dump_count, len(descartadas_tmp))}" if dump_descartadas else ""))
    return salida

# -------- main --------

def main():
    ap = argparse.ArgumentParser(description="Scoring por cliente desde resultados consolidados")
    ap.add_argument("--clientes_dir", default="./clientes", help="Carpeta con *_config.py")
    ap.add_argument("--input", default=None, help="Ruta a un resultados_consolidados_*.json específico (opcional)")
    ap.add_argument("--min-score", type=int, default=None, help="Score mínimo para guardar (override)")
    ap.add_argument("--dump-descartadas", action="store_true", help="Genera archivo con muestra aleatoria de descartadas")
    ap.add_argument("--dump-count", type=int, default=20, help="Tamaño de la muestra de descartadas (default 20)")
    ap.add_argument("--dry-run", action="store_true", help="No escribe archivos de salida")
    args = ap.parse_args()

    cfg_paths = sorted(Path(args.clientes_dir).glob("*_config.py"))
    if not cfg_paths:
        print(f"No se encontraron configs en {args.clientes_dir}")
        return

    resumen = []
    for p in cfg_paths:
        cfg = cargar_config(p)
        res = procesar_cliente(cfg, args.input, args.min_score, args.dump_descartadas, args.dump_count, args.dry_run)
        resumen.append({
            "cliente": cfg.NOMBRE_CLIENTE,
            "procesadas": res.get("procesadas", 0),
            "guardadas": res.get("guardadas", 0)
        })

    print("\nResumen:")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

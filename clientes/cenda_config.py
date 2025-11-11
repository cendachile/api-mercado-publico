# ============================================================
# CONFIGURACIÓN GENERAL DEL CLIENTE
# ============================================================

NOMBRE_CLIENTE = "CENDA"

# Carpeta de salida base (se usa tanto en filtro_duro como en scoring)
DIRECTORIO_SALIDA = f"./resultados/{NOMBRE_CLIENTE.replace(' ', '_').lower()}"

# ============================================================
# FILTROS DUROS (ELIMINATORIOS)
# ============================================================

MONTO_MINIMO = 1_000_000       # 1 millón
MONTO_MAXIMO = 100_000_000     # 100 millones

TIPOS_LICITACION_ACEPTABLES = ["L1", "LE", "LP", "LQ", "LS"]

ESTADOS_ACEPTABLES = [5, 6]

MONEDAS_ACEPTABLES = ["CLP", "CLF", "UTM"]

DIAS_MINIMOS_PREPARACION = 7

# ============================================================
# PARÁMETROS DE SCORING
# ============================================================

PONDERACIONES = {
    "match_tematico": 40,
    "viabilidad_financiera": 25,
    "oportunidad_temporal": 20,
    "ventaja_geografica": 15,
}
assert sum(PONDERACIONES.values()) == 100, "Las ponderaciones deben sumar 100"

CATEGORIAS_UNSPSC_RELEVANTES = [
    "86101500", "86101600", "86101700", "86111500", "86111600",
    "86121500", "93151500", "93151600", "93151700",
    "80101500", "80111600", "92121500"
]

KEYWORDS_TEMATICAS = [
    "educacion", "educación", "capacitacion", "capacitación",
    "formacion", "formación", "enseñanza", "aprendizaje",
    "curso", "cursos", "taller", "talleres",
    "social", "comunitario", "inclusion", "vulnerable",
    "participacion", "ciudadana", "empoderamiento", "liderazgo",
    "jóvenes", "mujeres", "adulto mayor", "proyecto social",
    "consultoria", "asesoría"
]

KEYWORDS_PENALIZADORAS = [
    "construccion", "mantenimiento", "obras", "infraestructura",
    "pavimento", "iluminacion", "plaza", "pintura",
    "electricidad", "equipamiento", "muebles", "hospital",
    "edificio", "camino", "insumos", "equipamiento médico"
]

PESO_CATEGORIA_UNSPSC = 0.6
PESO_KEYWORDS = 0.4
MIN_KEYWORDS_MATCH = 2

MONTO_OPTIMO_MIN = 5_000_000
MONTO_OPTIMO_MAX = 50_000_000

DIAS_OPTIMOS_PREPARACION = 14
DIAS_MAXIMOS_BENEFICIO = 30

REGIONES_PRIORITARIAS = ["Región Metropolitana de Santiago"]

# ============================================================
# PARÁMETROS DE CONTROL Y LOGS
# ============================================================

LOG_LEVEL = "INFO"
GUARDAR_LOGS_ARCHIVO = True
ARCHIVO_LOG = f"./logs/scoring_{NOMBRE_CLIENTE.replace(' ', '_').lower()}.log"

SCORE_MINIMO_RESULTADO = 30
MAX_DIAS_ATRAS = 5

# ============================================================
# IA: FILTRO SEMÁNTICO GPT
# ============================================================

# 🔸 Descripción de los servicios o rubros del cliente
DESCRIPCION_CLIENTE = (
    "CENDA es una consultora especializada en capacitación y formación sobre derechos humanos, economía, participación ciudadana, derechos laborales, pensiones. Tambien hacen investigación sobre educación, economía, litio, minería. No realizan trabajos de construcción, compra y venta de insumos, instalaciones, remodelaciones, obras civiles o equipamiento médico, no venden equipamiento ni hacen adquisiciones de equipos ni insumos. Su foco es la formación, capacitación, realización de consultorias e informes"
)

# 🔸 Modelo de OpenAI a utilizar
IA_MODELO = "gpt-4o-mini"

# 🔸 API key específica del cliente
IA_API_KEY = "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"

# 🔸 Tamaño máximo de lote por solicitud a la IA
IA_BATCH_SIZE = 10  # número de licitaciones por bloque

# 🔸 Tiempo de espera entre llamadas para evitar rate limit
IA_PAUSA_ENTRE_LOTES = 2.0  # segundos



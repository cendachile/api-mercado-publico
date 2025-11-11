🧩 Sistema de Procesamiento de Licitaciones – Impakt

INTRODUCCIÓN

Este proyecto forma parte del ecosistema Impakt, y tiene como propósito automatizar la búsqueda, filtrado y análisis de licitaciones públicas mediante un flujo de procesamiento modular.

El proceso local recibe información sobre licitaciones desde la API de Impakt, la cual mantiene un registro actualizado de todas las licitaciones disponibles. Su objetivo es proveer datos de forma ágil y estructurada para que los distintos clientes puedan analizarlos según sus propios criterios.

RESUMEN FUNCIONAMIENTO

1) Cada cliente tiene una carpeta dedicada que contiene un archivo de configuración denominado:

<cliente>_config.py (por ejemplo cenda_config.py)

En este archivo se definen los parámetros personalizados para hacer match con las licitaciones más relevantes para ese cliente.


2) El archivo principal RUN.py ejecuta todo el flujo de trabajo en orden, coordinando los siguientes módulos:


0_actualizar_licitaciones.py = actualiza el registro local de licitaciones, que está en la carpeta "base_local"

1_filtro_duro.py = obtiene licitaciones nuevas de la base y a partir de parametros del cliente, ejecuta un filtro duro que deja fuera a todas las licitaciones que no cumplen	

2_scoring.py = realiza una evaluación en base a parametros del cliente para eliminar las licitaciones con una puntuación bajo un rango definible	

3_resumen.py = ordena los archivos de resultado	y prepara la información para el filtro de IA

4_filtro_IA.py = compara la descripción del cliente con el nombre y descripción de la licitación para definir binariamente (SI o NO) coincide con el cliente

5_comprobar_vigencia.py = revisa que las licitaciones seleccionadas por el proceso estén vigentes, sino, las quita y actualiza la base de datos

6_presentar_resultados.py = genera archivo de excel con todas las licitaciones "activas" de un cliente

COMO INSTALAR

1) Para instalar el proyecto, primero clona el repositorio con el comando:
git clone https://github.com/willem326/mercado_publico.git

2) Crea un entorno virtual ejecutando:
python -m venv env

3) Activa el entorno virtual:
En Windows: env\Scripts\activate
En Linux o macOS: source env/bin/activate

4) Instala las dependencias necesarias con:
pip install -r requirements.txt

5) Finalmente, ejecuta el proceso principal con:
python RUN.py

MEJORAS FUTURAS

*Sacar un par de api keys que están hardcodeadas

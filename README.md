# PROYECTO-EEP-LEARNING-NOTICIAS

Repositorio de código y pipeline para el proyecto integrador de Deep Learning:
detección de noticias falsas en política colombiana, replicando de forma
adaptada a Blanco-Fernández, Otero-Vizoso, Gil-Solla & García-Duque (2024),
*"Enhancing Misinformation Detection in Spanish Language with Deep Learning:
BERT and RoBERTa Transformer Models"*, Applied Sciences 14(21): 9729
(DOI: 10.3390/app14219729).

## Contenido del repositorio

- `Ejecucion_final_colombia_baseline_roberta_bne.ipynb` / `Ejecucion_final_espanola_baseline_roberta_bne.ipynb`: notebooks originales del proyecto (líneas base con RoBERTa-BNE).
- `fake_news_es_baseline.ipynb`: versión refactorizada, con el pipeline de entrenamiento/evaluación unificado.
- `dataset_politica_colombiana.xlsx`: corpus principal (ver "Estado actual del corpus" abajo).
- Scripts de recolección de datos (`scrape_*.py`, `add_political_candidates_to_dataset.py`, `check_satire.py`): documentados en la sección "Pipeline de expansión del corpus".
- Archivos `dataset_politica_colombiana.backup_*.xlsx`: copias de respaldo del corpus tomadas justo antes de cada fase de expansión, por si hace falta revertir algún paso.
- Archivos `*_candidates.csv`, `*_added.csv` y `*_run.log`: salidas intermedias de cada script de scraping (para auditoría y trazabilidad, no son necesarios para entrenar los modelos).

## Estado actual del corpus

`dataset_politica_colombiana.xlsx` tiene **3.259 filas** con columnas
`id, label, title, description, date, url` (label: `TRUE` = noticia real,
`FALSE` = noticia falsa/satírica/desinformación; fecha en formato `DD/MM/YYYY`).

| | Filas |
|---|---:|
| `TRUE` (reales) | 1.633 |
| `FALSE` (falsas) | 1.626 |
| **Total** | **3.259** |

El corpus original (heredado del curso) tenía 793 filas, muy desbalanceado
hacia lo real dentro de esa muestra pequeña (403 reales / 390 falsas) y sin
documentación de cómo se había construido. Todo lo que sigue documenta el
trabajo hecho para (a) entender ese corpus original, (b) ampliarlo con más
noticias falsas de fuentes ya representadas en él, y (c) balancear la
proporción real/falsa agregando más noticias reales.

## Pipeline de expansión del corpus

### 1. Diagnóstico del corpus original (`check_satire.py`)

Antes de tocar nada, se verificó que las 125 filas del corpus original
provenientes de sitios satíricos conocidos (`actualidadpanamericana.com`,
`elchiguirebipolar.net`) estuvieran correctamente etiquetadas como `FALSE`.
Resultado: sí, el 100 % estaba bien etiquetado.

### 2. Cobertura de sitios satíricos (`scrape_satirical_sources.py`)

Se comparó qué tanto del contenido político-colombiano publicado por esos
dos sitios satíricos ya estaba representado en el corpus, recorriendo sus
sitemaps XML (públicos, permitidos por `robots.txt`) y clasificando cada
artículo como "satírico político colombiano" o no, mediante:

- Un filtro de recall barato a nivel de URL (nombres de ciudades, políticos
  e instituciones colombianas en el slug).
- Una clasificación de precisión sobre el contenido real del artículo
  (título + descripción + primeros párrafos), buscando coincidencias de
  palabra/frase completa (no subcadena) contra dos listas: señales
  políticas fuertes (nombres de presidentes, FARC/ELN, Congreso, etc.) y
  señales débiles de lugar + contexto político (una ciudad colombiana
  combinada con un término como "reforma", "elecciones", "alcaldía", etc.).

Este proceso se iteró varias veces para corregir falsos positivos y
negativos (palabras genéricas como "gobierno" o "policía" usadas como
chiste en cualquier tema, o descripciones truncadas que cortaban la señal
política real a la mitad). El resultado final —**638 artículos** clasificados
como sátira política colombiana y ausentes del corpus— se agregó al dataset
(`add_political_candidates_to_dataset.py`), con `label=FALSE`, reconstruyendo
fecha de publicación y descripción a partir del cuerpo real del artículo.

### 3. Verificadores de datos: Colombiacheck (`scrape_colombiacheck.py`)

Colombiacheck publica cada verificación con metadatos estructurados
`schema.org/ClaimReview` (la afirmación revisada, la calificación —Falso,
Cuestionable, etc.— y la fecha), mucho más confiables que raspar texto
visible. Se recorrió su archivo paginado de chequeos, se extrajo cada
`ClaimReview`, se excluyeron los calificados como verdaderos, y se filtraron
los relacionados con política colombiana. Siguiendo la misma convención que
ya usaba el corpus original (toda afirmación revisada por un verificador de
hechos se etiqueta como `FALSE`, sin importar el matiz exacto de la
calificación), se agregaron **599 afirmaciones nuevas**, usando el texto de
la afirmación como título y el cuerpo de la revisión como descripción.

### 4. Otras fuentes de verificación evaluadas y **descartadas**

Antes de scrapear, se revisó el `robots.txt` de cada sitio. Dos quedaron
explícitamente fuera de este proyecto:

- **La Silla Vacía** (`lasillavacia.com`): su `robots.txt` tiene una sección
  titulada *"Entrenamiento de IA (no Google) - BLOQUEADOS"* que nombra
  explícitamente a `ClaudeBot` y `anthropic-ai` con `Disallow: /` para todo
  el sitio. Como este proyecto construye datos de entrenamiento para un
  modelo de ML, es exactamente el uso que esa política busca impedir, así
  que no se scrapeó nada de este dominio (ni su sección de noticias reales,
  que en el corpus original aportaba 95 filas, ni su sección de chequeos).
- **AFP Factual** (`factual.afp.com`): incluso una solicitud simple de
  `robots.txt` devuelve `403 Forbidden` desde su protección de bots
  (Akamai). No se intentó ningún método para eludir esa protección.

**Alternativa legítima pendiente para estas dos fuentes:** la API pública
*Fact Check Tools* de Google (endpoint *Claim Search*) permite consultar
por dominio (`reviewPublisherSiteFilter`) el contenido `ClaimReview` que un
sitio ya publicó para que Google lo indexe —es decir, se accedería a través
de los servidores de Google, no de los del sitio original, usando un canal
que el propio publicador habilitó para ese fin. AFP figura como publicador
soportado; no se confirmó si La Silla Vacía también lo está. Requiere que
alguien cree una clave de API gratuita en Google Cloud Console; no se
implementó en esta fase porque no se contaba con esa clave.

### 5. Balanceo con noticias reales (`scrape_elespectador_real_news.py`)

Con el corpus en 1.626 filas `FALSE` y solo 403 `TRUE`, se buscó cerrar esa
brecha agregando noticias reales. Se eligió **El Espectador** porque:

- Ya era, por lejos, la fuente real más representada en el corpus original
  (190 de las 403 filas `TRUE`).
- Su `robots.txt` no tiene ninguna restricción para bots de entrenamiento
  de IA (a diferencia de El Tiempo y Portafolio, que sí bloquean
  explícitamente a `ClaudeBot`/`anthropic-ai` y por eso quedaron fuera).
- Publica un sitemap dedicado a la sección "política" (más de 10.000
  artículos), con fecha de publicación incluida directamente en el XML.

Se muestrearon páginas del sitemap distribuidas a lo largo de todo el
archivo (no solo lo más reciente) para variedad temporal, se descartaron
URLs ya presentes en el corpus, y se extrajo título y descripción reales de
cada artículo. Resultado: **1.230 noticias reales nuevas**, etiquetadas
`TRUE`. (Nota técnica: la primera corrida de este script tenía un error de
escapado de `&` en las URLs de paginación del sitemap, que hacía que todas
las páginas "distintas" devolvieran el mismo resultado; se corrigió antes
de la corrida final.)

## Limitaciones y advertencias conocidas

- La clasificación de "es sobre política colombiana" en los scripts de
  sátira y de verificación de hechos se basa en coincidencia de palabras y
  frases, no en comprensión real del contenido. Se ajustó por varias
  rondas para reducir falsos positivos/negativos evidentes, pero no es
  perfecta.
- Persisten ~41 URLs duplicadas en el corpus total, heredadas del corpus
  original (los propios notebooks documentan que el corpus del artículo de
  referencia tenía cientos de filas idénticas repetidas). No se limpiaron
  como parte de este trabajo; el notebook `fake_news_es_baseline.ipynb` ya
  incluye un paso de eliminación de duplicados exactos antes de entrenar.
- El nuevo balance 50/50 es a nivel de conteo de filas, no necesariamente
  de estilo o época: las noticias falsas nuevas provienen de dos fuentes
  (sátira y chequeos), mientras que las reales nuevas provienen de una sola
  (El Espectador). Vale la pena tenerlo en cuenta al interpretar resultados
  de un modelo entrenado con este corpus.
- Los archivos `dataset_politica_colombiana.backup_*.xlsx` son puntos de
  restauración anteriores a cada fase de expansión, por si se necesita
  revertir alguna.

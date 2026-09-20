# PROYECTO-EEP-LEARNING-NOTICIAS

Repositorio de código y pipeline para el proyecto integrador de Deep Learning:
detección de noticias falsas en política colombiana, replicando de forma
adaptada a Blanco-Fernández, Otero-Vizoso, Gil-Solla & García-Duque (2024),
*"Enhancing Misinformation Detection in Spanish Language with Deep Learning:
BERT and RoBERTa Transformer Models"*, Applied Sciences 14(21): 9729
(DOI: 10.3390/app14219729). Ese artículo construyó un corpus sintético de
57.231 noticias políticas en español (46.000 entrenamiento / 11.231 prueba),
combinando *scraping* automatizado con generación asistida por LLM.

### El corpus original del artículo (español, no el colombiano)

El propio artículo declara su fuente de datos en la sección *Data
Availability Statement*, accesible a través del depósito en acceso abierto
del repositorio institucional de la Universidade de Vigo (Investigo,
`investigo.biblioteca.uvigo.es`, ítem `11093/8538`) — MDPI bloquea el acceso
automatizado al PDF directamente, así que se recuperó por esa vía:

- **Dataset**: [`kaggle.com/datasets/javieroterovizoso/spanish-political-fake-news`](https://www.kaggle.com/datasets/javieroterovizoso/spanish-political-fake-news)
  (CC BY 4.0). Descarga requiere una cuenta de Kaggle con token de API; no
  se incluye una copia en este repositorio.
- **Código de entrenamiento**: [`github.com/gssi-uvigo/debatrue`](https://github.com/gssi-uvigo/debatrue)
  (scripts de validación cruzada para BERT, BETO, RoBERTa-BNE, Bertin y
  XLM-RoBERTa-Base; no incluye una copia de los datos).

La descripción del dataset en Kaggle precisa varios detalles que el
artículo no explicita:

- Noticias reales obtenidas por *scraping* de **Público, La Marea y El
  Común**.
- Noticias falsas construidas de dos formas: alterando datos de las
  noticias reales, y generadas con IA.
- Rango de fechas: **abril de 2017 a junio de 2023**.
- Formato: CSV delimitado por `;`, columnas `ID;Label;Titulo;Descripcion;Fecha`
  (`Label`: 1 = real, 0 = falsa — misma convención que
  `dataset_politica_colombiana.xlsx`, pero **sin columna de URL**).

## Contenido del repositorio

| Archivo | Qué es |
|---|---|
| `dataset_politica_colombiana.xlsx` | Corpus principal, ampliado. Ver "Estado actual del corpus". |
| `dataset_politica_colombiana_original_793.xlsx` | El corpus **tal como se heredó**, sin ninguna de las tres fases de ampliación descritas abajo: 793 filas (403 `TRUE` / 390 `FALSE`), recuperado del historial de `git` (commit `7c693a1`, el último antes de esta ampliación). Se conserva para poder comparar contra el corpus actual o revertir. |
| `Ejecucion_final_colombia_baseline_roberta_bne.ipynb` | Notebook de modelado más completo: línea base clásica (TF-IDF) + RoBERTa-BNE, sobre el corpus colombiano. |
| `Ejecucion_final_espanola_baseline_roberta_bne.ipynb` | Casi idéntico al anterior; pensado para correr el mismo pipeline sobre un corpus español en vez del colombiano. |
| `fake_news_es_baseline.ipynb` | Versión refactorizada y unificada de los dos anteriores (ver "Diferencias entre los tres notebooks" abajo). |
| `auditoria_construccion_corpus.ipynb` | **Notebook de auditoría**: todo el código que se usó para ampliar el corpus de 793 a 3.259 filas, en el orden en que se ejecutó. No entrena ningún modelo — es un registro reproducible de cómo se construyeron los datos. |
| `finetuning_bayesiano_colombia.ipynb` | Ajuste fino de RoBERTa-BNE sobre el corpus colombiano, reemplazando el ajuste manual de hiperparámetros del artículo por una búsqueda bayesiana con Keras Tuner. Pensado para correrse de punta a punta en Colab con GPU. Ver detalle abajo. |

## Los notebooks de modelado

Los tres notebooks abordan el mismo problema (clasificación binaria
real/falsa sobre `dataset_politica_colombiana.xlsx`) con estructura de
secciones (`§1`, `§2`, ...) muy similar. Todos:

- Ajustan **RoBERTa-BNE** (`PlanTL-GOB-ES/roberta-base-bne`, con fallback a
  `BSC-LT/roberta-base-bne` porque el repositorio original del modelo fue
  despublicado) para clasificación binaria.
- Comparan contra una **línea base clásica** (TF-IDF + regresión logística /
  SVM lineal / Naive Bayes).
- Implementan **agrupamiento anti-fuga**: el artículo de referencia fabrica
  parte de sus noticias falsas alterando noticias reales (cambiando un
  nombre propio con spaCy, o una cifra con expresiones regulares), lo que
  genera pares casi idénticos con etiquetas opuestas. Si una partición
  aleatoria manda un miembro del par a entrenamiento y el otro a prueba, el
  modelo ve esencialmente el mismo texto en ambos lados. La solución:
  construir un grafo de variantes (título/descripción normalizados, unidos
  por *union-find*) y particionar por componente conexa completa, nunca por
  fila suelta.
- Usan `StratifiedGroupKFold` para particionar entrenamiento/validación/
  prueba respetando esos grupos y la proporción real/falsa.
- Reportan una **línea de referencia trivial** (predecir siempre la clase
  mayoritaria) como piso mínimo de comparación.

### Diferencias entre los tres notebooks

- **`Ejecucion_final_colombia_baseline_roberta_bne.ipynb`**: la versión más
  completa y con más diagnóstico (18 secciones en la parte de RoBERTa, más
  una segunda mitad de 15 secciones para la línea base clásica —
  originalmente parecen ser dos notebooks pegados). Incluye un generador de
  **dataset dummy** (§4) que crea noticias sintéticas en español con
  contexto político colombiano usando plantillas y `random`, *solo* para
  poder correr el pipeline de punta a punta si el CSV/XLSX real no está
  disponible todavía. El propio notebook advierte explícitamente que esos
  datos dummy **no sirven para reportar resultados** y que la guía del
  curso prohíbe reportar con datos sintéticos.
- **`Ejecucion_final_espanola_baseline_roberta_bne.ipynb`**: prácticamente
  el mismo notebook, apuntado a un corpus español en vez del colombiano
  (mismo generador dummy, misma estructura).
- **`fake_news_es_baseline.ipynb`**: reescritura que corrige varios
  problemas de las dos versiones anteriores — `CONFIG`, `fijar_semillas` y
  `cargar_y_limpiar` duplicados y redefinidos a mitad de camino; una
  expresión regular de limpieza mal escapada que nunca coincidía;
  hiperparámetros del artículo (pensados para 46.000 ejemplos) aplicados
  sin ajustar a un corpus de ~800; entrenamiento que colapsaba a predecir
  una sola clase sin que la parada temprana lo detectara. También
  **elimina el generador de datos sintéticos** ("prohibido por la guía de
  la asignatura") y en su lugar el notebook simplemente se detiene con un
  error claro si no encuentra el archivo real.

### `finetuning_bayesiano_colombia.ipynb`: búsqueda bayesiana en vez de ajuste manual

Toma el mismo modelo (RoBERTa-BNE) y el corpus colombiano actual (3.259
filas), pero reemplaza el ajuste manual de hiperparámetros del artículo por
`keras_tuner.BayesianOptimization`. El artículo mismo explica por qué usó
ajuste manual: descartó `GridSearchCV`, `RandomizedSearchCV`, Optuna y
Hyperopt por considerarlos costosos o propensos a pasar por alto
combinaciones importantes. Este notebook llena exactamente ese hueco.

- **Busca** los 5 hiperparámetros que el artículo ajustó a mano (tasa de
  aprendizaje, tamaño de lote, *dropout*, regularización L2, duración del
  entrenamiento vía parada temprana), usando los valores de su Tabla 3
  (RoBERTa: LR 1×10⁻⁵, lote 16, *dropout* 0.15, L2 0.001, 10 épocas) como
  **centro** del espacio de búsqueda, no como valores fijos.
- **Busca además** dos hiperparámetros que el artículo no reporta en
  absoluto (no aparece "patience" ni "ReduceLROnPlateau" en ningún lugar
  del texto): factor y paciencia de reducción de tasa de aprendizaje sobre
  meseta, y paciencia de parada temprana.
- **Mantiene igual que el artículo**: cero capas congeladas — el artículo
  dice explícitamente *"The entire model is fine-tuned without freezing
  any layers"*. No hay ningún hiperparámetro de congelamiento acá porque
  tampoco lo hay en el artículo.
- **Cambio de framework deliberado**: Keras Tuner es nativo de
  TensorFlow/Keras, así que este notebook usa
  `TFAutoModelForSequenceClassification` en vez del PyTorch de los otros
  tres notebooks. Es un cambio limitado a este notebook, no una migración
  del proyecto.
- **Pensado para correrse de punta a punta en Colab con GPU** sin edición
  previa: pide el archivo del corpus por un diálogo de subida, corre una
  prueba de humo barata (1 intento, 1 época, ~30 filas) para detectar
  fallas de integración antes de gastar tiempo real, mide el tiempo real
  por época en el hardware asignado y estima la duración total **antes**
  de lanzar la búsqueda completa, y guarda hiperparámetros ganadores,
  métricas de prueba e historial de intentos al final.
- **Compatibilidad Keras 3 (§1)**: Colab trae TensorFlow ≥2.16, cuyo
  `tf.keras` es Keras 3 por defecto — algo con lo que `transformers` (los
  modelos TF) y Keras Tuner todavía no son totalmente compatibles. La
  primera celda instala `tf-keras` y fija `TF_USE_LEGACY_KERAS=1` **antes**
  de importar `tensorflow`, y termina con un `assert` que falla con un
  mensaje explícito si el modo legado no tomó efecto (la solución en ese
  caso es reiniciar el entorno de ejecución y volver a correr esa celda
  primero, antes que cualquier otra).
- **`transformers` fijado por debajo de 5.0, sin el extra `[tf]` (§1)**: el
  26 de enero de 2026 se publicó `transformers` 5.0, que eliminó por
  completo el soporte TensorFlow/Flax — `TFAutoModelForSequenceClassification`
  y toda la familia `TF*` ya no existen ahí. Sin fijar versión, `pip
  install transformers[tf]` en Colab instala la serie 5.x y la importación
  falla de inmediato. La celda instala `"transformers>=4.44,<5.0"` y agrega
  un segundo `assert` explícito sobre la versión mayor instalada, para que
  un futuro cambio de este tipo falle con un mensaje claro en vez de un
  `ImportError` críptico más abajo en el notebook.

  El extra `[tf]` se quitó a propósito: fija `tensorflow<2.16,>2.9`, una
  restricción de antes de que existiera TF 2.16/Keras 3, hoy obsoleta.
  Como Colab ya trae TensorFlow ≥2.16 preinstalado, pedir `[tf]` hace que
  `pip` intente satisfacer esa versión vieja exigida contra la ya
  instalada y falle con "conflicting dependencies" — reproducido localmente
  con `pip install --dry-run` antes de aplicar el arreglo. `transformers`
  no necesita el extra para funcionar con TF: solo necesita poder
  importarlo en tiempo de ejecución, no que esté declarado como
  dependencia fija.

**Advertencia honesta:** el entorno donde se escribió este notebook no
tiene TensorFlow instalable (incompatibilidad con la versión de Python
disponible ahí), así que el código se revisó cuidadosamente contra la
documentación oficial pero **no se pudo ejecutar de punta a punta antes de
entregarlo** — a diferencia de los notebooks en PyTorch, que sí se
pudieron probar parcialmente. La prueba de humo (§12) existe justamente
para que un error de integración se note en menos de un minuto al
correrlo en Colab, no después de una búsqueda de una hora.

## El dataset original (793 filas heredadas)

**No hay código en este repositorio, en ninguna versión anterior de él, ni
en ningún commit del historial, que muestre cómo se construyó el corpus
original de 793 filas.** Esto se verificó explícitamente al inicio de este
trabajo (revisando los tres notebooks y el historial completo de `git`) y
sigue siendo cierto: solo se heredó el archivo `.xlsx` ya construido.

Lo que sí es observable inspeccionando esas 793 filas:

- Columnas: `id, label, title, description, date, url` (`date` en formato
  `DD/MM/YYYY`; `label` almacenado como texto `"TRUE"`/`"FALSE"`, no como
  booleano nativo de Excel).
- Balance original: 403 `TRUE` (reales) / 390 `FALSE` (falsas).
- Los `url` de las filas reales apuntan a medios establecidos —
  `elespectador.com` (190), `eltiempo.com` (81), `elcolombiano.com` (41),
  `caracol.com.co` (24), `lasillavacia.com` (95, sección de noticias, no
  de chequeos), `senado.gov.co`, `camara.gov.co`, `presidencia.gov.co`,
  entre otros.
- Los `url` de las filas falsas apuntan a dos sitios de sátira
  (`actualidadpanamericana.com`, `elchiguirebipolar.net`) y a tres
  verificadores de hechos (`colombiacheck.com`, `lasillavacia.com` en su
  sección de chequeos, `factual.afp.com`), donde el "titular" guardado es
  en realidad **la afirmación desinformativa** que el verificador revisó
  (no el titular del artículo de verificación), etiquetada `FALSE`.
- Los notebooks documentan (citando al artículo de referencia) que el
  corpus original contenía del orden de 466 filas idénticas repetidas —
  de ahí que todos incluyan un paso explícito de eliminación de duplicados
  exactos antes de particionar.

Cualquier afirmación sobre *cómo* se recolectaron esas 793 filas más allá de
lo anterior sería especulación, no algo verificable desde este repositorio.

## Estado actual del corpus

`dataset_politica_colombiana.xlsx` tiene **3.259 filas**, mismas columnas
que el original.

| | Filas |
|---|---:|
| `TRUE` (reales) | 1.633 |
| `FALSE` (falsas) | 1.626 |
| **Total** | **3.259** |

Las 2.466 filas nuevas (frente a las 793 originales) se agregaron en tres
fases, documentadas con código ejecutable completo en
**`auditoria_construccion_corpus.ipynb`**. Resumen:

### 1. Ampliación de sátira política (638 filas, `FALSE`)

Se recorrieron los *sitemaps* XML públicos de los dos sitios satíricos ya
presentes en el corpus original, para encontrar artículos de sátira
política colombiana que no estuvieran representados todavía. Cada
candidato se clasificó por su contenido real (título + descripción +
cuerpo del artículo, no solo el slug de la URL), buscando coincidencias de
palabra/frase completa contra señales políticas (nombres de presidentes,
FARC/ELN, Congreso, instituciones) — el proceso se ajustó varias veces
para eliminar falsos positivos de palabras genéricas usadas como chiste en
cualquier tema ("gobierno", "policía").

### 2. Verificador de hechos Colombiacheck (599 filas, `FALSE`)

Colombiacheck publica cada verificación con metadatos estructurados
`schema.org/ClaimReview` (afirmación revisada, calificación, fecha) —
mucho más confiable que raspar texto visible. Se excluyeron las
afirmaciones calificadas como verdaderas; el resto sigue la misma
convención que ya traía el corpus original (toda afirmación revisada por
un verificador se etiqueta `FALSE`, sin importar el matiz exacto de la
calificación: Falso, Cuestionable, etc.).



### 3. Balanceo con noticias reales de El Espectador (1.230 filas, `TRUE`)

Con el corpus en 1.626 `FALSE` y solo 403 `TRUE`, se agregaron noticias
reales para cerrar la brecha. Se eligió El Espectador porque ya era la
fuente real más representada en el corpus original (190 de 403 filas), y publica un sitemap dedicado a
la sección "política" con más de 10.000 artículos, muestreado a lo largo
de todo el archivo (no solo lo más reciente) para variedad temporal.

## Limitaciones y advertencias conocidas

- La clasificación de "es sobre política colombiana" en los scripts de
  sátira y de verificación de hechos se basa en coincidencia de palabras y
  frases sobre el texto real del artículo, no en comprensión del
  contenido. Se ajustó por varias rondas para reducir falsos
  positivos/negativos evidentes, pero no es perfecta — ver
  `auditoria_construccion_corpus.ipynb` para el detalle de cada ajuste.
- Persisten ~41 URLs duplicadas en el corpus total, heredadas en su
  mayoría del corpus original (ver sección anterior). No se limpiaron como
  parte de esta ampliación; los notebooks de modelado ya incluyen un paso
  de eliminación de duplicados exactos antes de entrenar.
- El balance 50/50 es a nivel de conteo de filas, no necesariamente de
  estilo o época: las noticias falsas nuevas provienen de dos fuentes
  (sátira y chequeos), mientras que las reales nuevas provienen de una
  sola (El Espectador). Vale la pena tenerlo en cuenta al interpretar
  resultados de un modelo entrenado con este corpus.
- Como se explicó arriba, como fue hecho prácticamente a mano, **no existe documentación ni código reproducible
  para el origen de las 793 filas originales** — solo para las 2.466
  agregadas en este trabajo.

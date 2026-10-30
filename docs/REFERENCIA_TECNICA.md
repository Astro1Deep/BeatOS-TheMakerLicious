# Referencia técnica · BeatOS 3.8.0

Revisión: 30 de octubre de 2026. [Manual de uso](MANUAL_COMPLETO.md) · [Compatibilidad por hardware](COMPATIBILIDAD_HARDWARE.md) · [Inicio](../README.md).

Esta referencia describe la implementación incluida, no una API pública versionada con garantía de estabilidad para clientes externos.

## 1. Responsabilidades del código

| Archivo | Responsabilidad y límites |
| --- | --- |
| `installer.py` | Menú local; invoca el indexador/servidor, limpieza explícita, inicialización del esquema y apertura de wiki. |
| `beatos_paths.py` | Ubicaciones de datos/configuración, detección de raíz instalada, accesos HTML y escritura del catálogo mediante archivos temporales. |
| `index_mpc_library.py` | Recorrido de biblioteca, etiquetas por reglas, medición RMS compatible, índice y generación de catálogo. |
| `docs/assets/po33-capture-worklet.js` | Captura estéreo PCM para respaldos PO; intercalado a 16 bits sin monitorizar audio de retorno. |
| `templates/catalogo.html` | Interfaz, filtros, estado del rack, reproducción, importación, hubs y solicitudes a la API. El estado de edición del rack vive en la página. |
| `serve_mpc.py` | HTTP local, medios con rangos, validación de rutas/origen, API y reindexación en segundo plano. |
| `hardware_kit_builder.py` | Parsers XPM/XPJ, resolución de muestras, exportadores, inspección limitada de backups y CLI. |
| `schema.sql` | Tablas e índices; el esquema no acredita compatibilidad física con los aparatos nombrados en comentarios históricos. |
| `build_release.py` | Paquete limpio con lista de código, documentación/recursos, plantillas vaciadas y manifiesto de integridad. |
| `audit_all_expansions.py` | Auditoría de expansiones orientada al entorno histórico del autor; no forma parte del flujo de instalación autónomo. |
| `scripts/` | Herramientas de mantenimiento/supervisión históricas; no se distribuyen ni se ejecutan por abrir el catálogo. |

### Utilidades históricas fuera del instalador

`audit_all_expansions.py` expone `run_expansion_audit(root_dir, output_report)` para recorrer XPM bajo `Expansions/`, usar el parser y resumir referencias resueltas/ausentes. Su raíz predeterminada es `/Volumes/MPCSMPL`; no presupone que haya exactamente nueve paquetes ni prueba integridad acústica de todas las capas. No se ejecuta ni se empaqueta con el núcleo instalado.

Los archivos `scripts/autodoctor.py` y `scripts/cerebro_faiss_engine.py` pertenecen al entorno histórico de supervisión/integración. No son botones adicionales del catálogo ni requisitos de búsqueda: el explorador actual filtra los registros de la página. No se ejecutaron para preparar este manual y no se describen como diagnósticos inocuos de lectura.

## 2. Comandos y valores predeterminados

Los ejemplos parten de la **carpeta que contiene los scripts**. En el ZIP está dentro de `BeatOS/`; en el clon es la raíz. Sustituye las rutas de ejemplo. En Windows puede usarse `py` en lugar de `python3`.

```bash
python3 installer.py
python3 index_mpc_library.py --path "/ruta/a/la biblioteca"
python3 serve_mpc.py "/ruta/a/la biblioteca" --port 8888 --no-browser
```

| Herramienta | Opciones implementadas |
| --- | --- |
| Indexador | `--path` / `-p`, por defecto directorio actual; `--output` / `-o`, por defecto `BeatOS/data/` de esa raíz. |
| Servidor | Ruta posicional opcional, `--port` / `-p`, `--no-browser`. Puerto predeterminado 8888; busca hasta 50 puertos desde el solicitado. |
| Kit builder | Subcomando `create`; requiere `--name`, `--b64` (lista JSON codificada en Base64) y `--root`; `--target` predeterminado `universal`. |
| Empaquetador | Ruta posicional del ZIP de salida. |

`--output` del indexador cambia la ubicación de SQLite/CSV/JSON, pero el HTML se sigue generando en `BeatOS/data/catalogo.html` de la biblioteca. El servidor no recibe una opción equivalente para esa base alternativa; para el recorrido normal conserva la salida predeterminada.

Sin ruta explícita, el servidor usa su detección histórica: instalación organizada, carpetas MPC-Sample/Expansions, posibles raíces padre, `/Volumes/MPCSMPL`, repositorio en Documents o directorio del código. Para un flujo reproducible indica siempre la biblioteca; no uses esa detección como selector de discos universal.

Ejecutar `hardware_kit_builder.py` sin subcomando no crea un kit: muestra información y consulta respaldos previstos por ese módulo. La CLI no expone el tempo ni las opciones PO del servidor en esta versión.

## 3. Datos generados

| Archivo relativo a la biblioteca | Contenido |
| --- | --- |
| `BeatOS/data/mpc_sample.db` | Tablas consultables; incluye rutas absolutas y relativas. |
| `BeatOS/data/mpc_sample_resumen.csv` | Filas de muestras con nombres, tipos, BPM, tonalidad, energía, tamaño y ruta. No es un volcado completo de todas las tablas. |
| `BeatOS/data/mpc_sample.json` | Fecha de generación, totales, distribución, proyectos y expansiones. No es el listado completo del rack ni una copia de todos los registros de audio. |
| `BeatOS/data/catalogo.html` | Datos y lógica de interfaz generados desde la plantilla. |
| `catalogo_universal.html`, `catalogo_mpc_sample.html` | Redirecciones al catálogo único. |
| `BeatOS/config/theme_config.json` | Tema guardado desde la API; no contiene una sesión de pads. |
| `Custom_Kits/<kit>/` | Entregas de exportación. |
| `BeatOS/data/po33_backups/` | WAV originales archivados con nombre saneado y SHA-256. No son índices regenerables ni sesiones del rack. |

El índice usa SQLite en modo WAL. Al copiar una base mientras está activa puede haber transacciones en archivos `-wal`/`-shm`; para una copia consistente detén escritores y usa el mecanismo de backup de SQLite o copia tras el cierre correcto. La base no sustituye los archivos de audio referidos.

### Tablas

| Tabla | Campos y uso principales |
| --- | --- |
| `sound_categories` | Código, nombre e icono de tipos. |
| `samples` | ID, filename, sample_format, sound_type, macro_category, sub_pack, bpm/bpm_tier, musical_key/camelot, energy_level, extensión, tamaño, full_path y rel_path. |
| `projects` | Nombre, ruta, tempo, clave, recuentos de referencias/ausentes, estado y tamaño. |
| `expansions` | Título, fabricante, tipo, versión/metadatos disponibles, carátula, recuentos, tamaño y ruta. Algunos valores se rellenan por defecto: no autentican el paquete. |
| `packs` | Tabla prevista por el esquema; el indexador actual la vacía pero no construye un catálogo de packs en ella. Las etiquetas macro/subpack de samples sí se rellenan. |

No hay ID estable entre reindexaciones ni un sistema de anotaciones personales preservadas en las tablas reconstruidas. El esquema incluye índices de consulta por nombre, tipo, categoría, BPM, tonalidad, Camelot y energía.

Consulta de sólo lectura desde la raíz de la biblioteca, si tienes `sqlite3` instalado:

```bash
sqlite3 -readonly "BeatOS/data/mpc_sample.db" "SELECT sound_type, COUNT(*) FROM samples GROUP BY sound_type;"
```

Ejemplos SQL:

```sql
SELECT filename, rel_path FROM samples
WHERE sound_type = 'DRUM_LOOP' AND bpm BETWEEN 88 AND 94
ORDER BY bpm, filename;

SELECT name, status, missing_samples_count FROM projects
WHERE status IN ('ATTENTION', 'ERROR');

SELECT filename, rel_path FROM samples
WHERE sound_type = 'UNKNOWN' OR energy_level = 'UNMEASURED';
```

El [capítulo SQLite](wiki/07-Consultas-Avanzadas-SQLite.md) contiene más consultas. La cabecera CSV y los campos JSON no son idénticos al esquema SQL.

## 4. Modelo del rack y parámetros exportados

En la web cada posición ocupada contiene ruta relativa, nombre, tipo, volumen, panorama, tono y mute. La API recibe sólo pads activos; los huecos no se envían como muestras silenciosas.

| Dato | Valor admitido por `create_kit` |
| --- | --- |
| Pads | Al menos uno, posiciones 1–16. |
| Fuente | Archivo existente resuelto dentro de `source_root`; la API aplica además la protección HTTP de rutas. |
| Volumen | Número finito 0–1, valor predeterminado 0,707946. |
| Panorama | Número finito 0–1; centro 0,5. |
| Afinación | De −36 a +36 semitonos; la interfaz prepara enteros y limita su editor a ±24. |
| Mute | Entero 0–32; 0 no corta otros pads. |
| Tempo | Número finito 30–300 BPM; predeterminado 120. Se usa en el XPJ generado; no estira todos los WAV al tempo. |
| PO | `max_total_sec` de 1–40 y `gap_ms` entero de 0–500. Predeterminados 40 y 150. |

| Destino | Posición | Volumen/tono/panorama/mutes del rack |
| --- | --- | --- |
| XPM/XPJ | Campos del programa/proyecto con muestras enlazadas. | Se escriben los parámetros implementados; el resultado requiere comprobación en el motor/modelo. |
| Maschine | `slot` y ruta de WAV en JSON. | Valores en mapa; WAV sin procesar esos ajustes. |
| SP-404MKII | Nombre y manifiesto de relación pad/archivo. | No se exportan como parámetros de proyecto; ajustarlos en hardware. |
| SP-404A/SX | Nombre `A01`–`A12`, sin relleno de huecos. | No se exportan como parámetros de proyecto. |
| PO | Cortes consecutivos, con relación al pad en JSON. | Volumen/tono procesados en mono y normalización de conjunto; sin panorama/mutes. |
| EP-133 | Slot, grupo y tecla propuestos en `meta.json`. | Valores en mapa; WAV sin procesar esos ajustes. |

Las escalas numéricas del mapa no garantizan que el control del fabricante use la misma unidad visual. En el editor web, 100% de volumen equivale aproximadamente a 0,707946 y el máximo visual puede superar la ganancia 1 que acepta el servidor. No traduzcas `volume=0.7` automáticamente a «70 dB» ni a un porcentaje de pico del WAV.

## 5. Parsers y resolución de muestras

XPM se lee como XML; XPJ, como gzip con texto/cabecera y JSON. Se interpretan las estructuras Drum implementadas, no todos los formatos que puedan llevar esas extensiones.

La búsqueda intenta la referencia y directorios de proyecto/paquete dentro de la biblioteca. Puede recurrir al nombre base y a una normalización de caracteres; esa coincidencia debe ser única. Dos candidatos ambiguos se consideran sin resolver. No busca arbitrariamente por todo el ordenador ni cruza la raíz de la biblioteca para arreglar un proyecto.

Los parsers pueden describir hasta 128 pads y varias pistas Drum; la página monta bancos de 16 y toma la primera capa activa. `layer_count` y `missing` explican esa simplificación. El fallback de pool sin pistas sólo usa las primeras 16 referencias. Exportar desde el rack no es un round-trip sin pérdidas del archivo de entrada.

La plantilla XPJ actual identifica AC50/Sample y versión interna de datos 28. Esa versión interna no se traduce automáticamente a un número de firmware; la [guía de hardware](COMPATIBILIDAD_HARDWARE.md) separa su procedencia del soporte de importación del fabricante.

## 6. API HTTP local

La API se sirve en el puerto impreso por el servidor. Host debe ser local con el puerto correcto; si hay Origin debe corresponder a esa misma vista HTTP. No es una API remota autenticada. No la expongas mediante túneles/proxy ni habilites acceso de red sin diseñar autorización.

Las solicitudes POST ordinarias se limitan a 1 MiB; la importación de backup WAV tiene su propio límite de 128 MiB. Muchas operaciones devuelven `success`/`error`; algunas rechazan también por estado HTTP y la inspección de tareas tiene su propio objeto. Comprueba **ambos**, no sólo HTTP 200. Las rutas de ejemplos son relativas a la biblioteca salvo los campos de resultado que indican rutas completas.

### Lectura

| Método y ruta | Entrada | Resultado y alcance |
| --- | --- | --- |
| `GET /api/status` | Sin cuerpo. | Raíz, recuento de muestras, espacio, indicador histórico MPCSMPL y estado de tarea. |
| `GET /api/task_status` | Sin cuerpo. | `running`, `task_name`, logs, success y marcas de inicio/fin. Logs acotados en memoria. |
| `GET /api/theme` | Sin cuerpo. | Preferencia de tema del archivo de ecosistema o valor predeterminado. |
| `GET /api/po33_backups` | Sin cuerpo. | Lista de inspecciones WAV; no valida payload. |
| `GET /api/po33_backup_audio?file=…` | Archivo dentro de una raíz de respaldo permitida. | WAV original; no convierte ni restaura. |
| `GET /api/download_file?path=…` | Archivo permitido dentro de la biblioteca. | Descarga del archivo, por ejemplo reel o ZIP EP. |
| `GET/HEAD` de medios y recursos | Ruta admitida y, para medios, Range opcional. | Catálogo, audio y recursos previstos; no publicación genérica del árbol privado de instalación. |

### Operaciones

| Método y ruta | Campos o condición | Efecto |
| --- | --- | --- |
| `POST /api/po33_backups?name=…` | Cuerpo binario WAV original y `Content-Type: audio/wav`; hasta 128 MiB. | Valida y archiva sin conversión; devuelve `backup` con inspección y SHA-256. No recibe JSON de muestras. |
| `POST /api/create_kit` | `name`, `target`, `pads`; opcionales `tempo`, `po_options`. | Crea nueva carpeta y entregas; devuelve `kit_path` y `targets`. |
| `POST /api/load_project` | `rel_path`, `track_index` opcional. | Lee XPJ y devuelve `project` para la copia del rack; no escribe el original. |
| `POST /api/load_xpm_program` | `rel_path`; admite alternativa con expansión y nombre de programa. | Devuelve `program`. Usar la ruta concreta evita confundir programas anidados. |
| `POST /api/list_expansion_programs` | `expansion_name`. | Explora XPM bajo `Expansions/` y devuelve metadatos/programas. |
| `POST /api/download_xpa` | `rel_path` del proyecto. | Respuesta ZIP con nombre XPA y ProjectData localizado; no conversión de formatos. |
| `POST /api/reindex` | Sin cuerpo necesario; no debe haber otra reindexación web activa. | Arranca el indexador en un hilo/proceso, consultable por task_status. |
| `POST /api/clean_metadata` | Acción explícita. | Borra auxiliares AppleDouble/DS_Store; en macOS ejecuta dot_clean. |
| `POST /api/reveal_in_finder` | `path` permitido y existente. | Abre Finder/Explorer/xdg-open según plataforma. |
| `POST /api/launch_ep_tool` | Acción explícita. | Abre la URL oficial; no importa muestras ni actualiza firmware. |
| `POST /api/sync_dashboard` | Script externo de Cerebro instalado. | Ejecuta esa integración local; no está en el núcleo distribuido. |
| `POST /api/theme` | `theme`. | Escribe preferencia local y archivo del ecosistema. |

Cuerpo ilustrativo para una muestra existente en tu biblioteca:

```json
{
  "name": "Kit_Prueba_01",
  "target": "ep133",
  "tempo": 90,
  "pads": [
    {"pad": 1, "rel_path": "Samples/Kick.wav", "volume": 0.707946,
     "pan": 0.5, "tune": 0, "mute_group": 1}
  ]
}
```

Para `target: "po33"`, `po_options` puede ser `{"max_total_sec": 20, "gap_ms": 150}`. No sustituyas una ruta ficticia por éxito esperado: el archivo debe existir dentro de la raíz. Los destinos de la CLI son `universal`, `mpc`, `maschine`, `sp404mk2`, `sp404a`, `po33` y `ep133`; algunas variantes de nombre aceptadas internamente no son opciones independientes de interfaz.

## 7. Escrituras, concurrencia e integraciones

La carpeta del kit se reserva sin sobrescritura para evitar dos exportaciones con el mismo nombre; los fallos intentan retirarla. No hay una transacción de hardware: un kit generado no significa que se haya transferido o guardado en el sampler.

La tarea de reindexación web tiene un bloqueo por proceso. No coordina automáticamente indexadores lanzados desde otra terminal ni varios servidores apuntando a la misma salida. No uses esas combinaciones para actualizar una misma biblioteca en paralelo.

El archivo PO se guarda mediante temporal y sustitución controlada, con bloqueo de importación. El inventario usa una caché en memoria por ruta/tamaño/mtime/ctime, no una base de datos que reconstruir. Importar lee el PCM completo declarado; inspeccionar calcula huella y comprueba cabecera/final de datos, con amplitud limitada a 192000 frames iniciales. `audio_compatible`, `wav_complete` y `capture_interrupted` condicionan el botón de restauración; `valid` y `payload_verified` no certifican el módem.

Los recursos de la aplicación y la lectura de medios tienen reglas diferentes: la API bloquea rutas fuera de raíz, privadas, ocultas y determinadas ubicaciones internas; los assets se sirven mediante rutas previstas. El endpoint de backups permite además sus directorios concretos. No interpretes el servidor como aislamiento frente a otros procesos locales con acceso a tu cuenta.

La sincronización de tema escribe `~/.gemini/antigravity/scratch/ecosystem_theme.json` y `BeatOS/config/theme_config.json`. La sincronización de dashboard busca `~/.gemini/antigravity/scratch/sync_master_dashboard.py`. Son dependencias del entorno personal, no archivos que todo usuario deba crear para usar BeatOS. La integración de tema registra nombres de otros sistemas, pero no acredita que estén ejecutándose.

## 8. Empaquetado y comprobaciones

Desde el código:

```bash
python3 -B -m unittest discover -s tests -v
node tests/test_library_ui.cjs
node tests/test_pad_audio.cjs
node tests/test_creator_identity.cjs
node tests/test_po33_backups.cjs
python3 -B build_release.py "/ruta/de/salida/BeatOS.zip"
```

El empaquetador incluye código de su lista, documentación y recursos admitidos, vacía muestras/eventos personales de las plantillas y genera `BeatOS/MANIFEST.sha256.json` bajo la carpeta versionada del ZIP. Comprueba integridad de miembros al construir. Ese manifiesto no es un backup de tu biblioteca ni verifica carga en hardware; compara además la procedencia y el SHA-256 del archivo descargado.

Las pruebas de instalación extraen el ZIP, crean una biblioteca sintética, indexan, sirven medios y ejercitan exportación según sus casos. La CI de Windows comprueba tanto el adjunto estable descargado como un ZIP del código del commit. No se debe atribuir el manual actualizado a una release antigua: publicar en main y reemplazar un adjunto de release son operaciones distintas.

## 9. Límites identificados en esta revisión

- No hay un perfil XPJ separado por modelo MPC; el template incluido es Sample/AC50.
- No hay proyecto nativo Maschine, SP o EP generado por BeatOS, ni decodificación de datos de backup PO. La restauración integrada prepara reproducción con confirmación, pero la recepción la realiza el aparato.
- El rack no persiste una sesión completa en disco y sólo exporta el banco visible.
- El deslizador de volumen y la validación del exportador tienen máximos distintos.
- El orden de «fecha» del explorador usa IDs; algunos indicadores de duración PO son aproximados.
- El script offline no conserva los controles web de tempo/opciones PO.
- Algunos textos/comentarios históricos del programa exageran compatibilidad, ausencia de dependencias o verificación de respaldos. Para el alcance real consulta estas tablas y el comportamiento de las funciones, no sólo sus cabeceras.

Estos límites se documentan sin cambiar el comportamiento de la aplicación en esta revisión del manual.

## 10. Glosario de formatos y medidas

| Término | Significado en este sistema |
| --- | --- |
| WAV / PCM | Contenedor de audio y codificación de muestras; la frecuencia, profundidad y canales siguen siendo requisitos separados. |
| XPM Drum | Programa MPC con asignaciones y parámetros de instrumento; no contiene por sí solo toda la canción. |
| XPJ | Proyecto MPC; su esquema y motor de procedencia importan, además de la extensión. |
| ProjectData | Carpeta de recursos del proyecto que debe acompañarlo cuando la entrega la utiliza. |
| XPA de BeatOS | ZIP de transporte generado por el endpoint del proyecto; no conversión certificada entre motores. |
| JSON de mapa | Descripción legible de asignaciones/ajustes, no necesariamente un formato que el fabricante importe. |
| Reel | Audio concatenado para grabar/cortar; no backup de patrones ni programa de sintetizador. |
| Hz / kHz | Muestras por segundo de audio digital; no BPM del kit. |
| Bit depth | Resolución de cada muestra PCM; no nivel de volumen por pad. |
| RMS / dBFS | Estimación de nivel y escala relativa al máximo digital; la etiqueta de energía de BeatOS usa ventanas. |
| BPM | Tempo declarado para organización o proyecto; no detección acústica ni estiramiento automático de todas las muestras. |
| Mute / choke group | Grupo de sonidos que se cortan entre sí en el motor que lo implemente. |
| Web MIDI | Acceso del navegador a dispositivos MIDI, usado por herramientas como EP Sample Tool; no significa que BeatOS controle todos los samplers por MIDI. |
| SHA-256 | Huella de integridad de archivos; no demuestra por sí sola autoría ni compatibilidad musical. |

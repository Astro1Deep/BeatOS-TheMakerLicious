"""ES/EN presentation of BeatOS API diagnostics.

This module never modifies source filenames, sample paths, or audio payloads.
The original diagnostic remains available as error_es / logs_es for debugging.
Do not use these translations as a substitute for stable machine error codes.
"""
from __future__ import annotations

from http.cookies import SimpleCookie
import re

EXACT_EN = {
    "Inventario del ecosistema actualizado.": "Ecosystem inventory refreshed.",
    "La biblioteca ya no está disponible.": "The library is no longer available.",
    "No se pudo limpiar toda la biblioteca.": "Could not clean the entire library.",
    "Ya hay una tarea de mantenimiento en curso.": "A maintenance task is already running.",
    "Ya hay una reindexación en ejecución en segundo plano.": "A maintenance task is already running.",
    "🚀 Reindexación iniciada en segundo plano con éxito.": "🚀 Reindexing started in the background.",
    'La biblioteca indicada no existe o no es una carpeta': 'The selected library does not exist or is not a directory',
    'Tema del ecosistema no válido.': 'Invalid ecosystem theme.',
    'No se pudo guardar el tema del ecosistema.': 'Could not save the ecosystem theme.',
    'Existe un enlace en el destino; no se ha sustituido': 'An existing link at the destination was preserved',
    'EP-133: el mapa de un kit admite 4 grupos de 12 sonidos (48 en total)': 'EP-133: a kit map supports four groups of 12 sounds (48 total)',
    'Presupuesto PO: entre 1 y 40 segundos': 'PO time budget must be between 1 and 40 seconds',
    'Pad duplicado': 'Duplicate pad',
    'SP-404A/SX: cada banco tiene 12 pads; mueve los sonidos de las posiciones 13–16 antes de exportar': 'SP-404A/SX: each bank has 12 pads; move any sounds from slots 13–16 before exporting',
    'El título de la expansión es obligatorio.': 'Expansion title is required.',
    'Ruta de expansión fuera del directorio Expansions': 'Expansion path is outside the Expansions directory',
    'Selecciona al menos un kit/proyecto con muestras válidas o carga muestras en el Rack de 16 pads.': 'Select at least one kit/project with valid samples or load samples into the 16-pad rack.',
    'La muestra es demasiado corta para dividirla en múltiples cortes.': 'The sample is too short to split into multiple slices.',
    'Script sync_master_dashboard.py y plantilla MASTER_ECOSISTEMA_DISCOS.html no encontrados.': 'The sync_master_dashboard.py script and MASTER_ECOSISTEMA_DISCOS.html template were not found.',
    'No se pudo abrir el archivo de descarga.': 'Could not open the file for download.',
    'Motor autochop no disponible.': 'Auto-chop engine is unavailable.',
    'Motor create_custom_expansion no disponible en el servidor.': 'The custom expansion builder is unavailable on the server.',
    'Función create_chromatic_kit no disponible en hardware_kit_builder.': 'The hardware kit builder does not provide create_chromatic_kit.',
    'Función build_rack_scale_bank no disponible.': 'The build_rack_scale_bank function is unavailable.',
    'Gestor mpcqol.conf no disponible.': 'The mpcqol.conf manager is unavailable.',
    'Gestor Melodee/settings no disponible.': 'The Melodee/settings manager is unavailable.',
    "El parámetro 'settings' debe ser un objeto JSON": "The 'settings' parameter must be a JSON object",
    "Se esperaba un objeto JSON": "Expected a JSON object",
    "El parámetro 'preset' debe ser texto": "The 'preset' parameter must be a string",
    "Falta parámetro 'rel_path'": "Missing parameter 'rel_path'",
    "Falta parámetro 'path'": "Missing parameter 'path'",
    "Falta parámetro 'expansion_name'": "Missing parameter 'expansion_name'",
    "Falta parámetro 'rel_path' o 'program_file'": "Missing 'rel_path' or 'program_file' parameter",
    "Los pads deben ser una lista o un objeto": "Pads must be an array or object",
    "Cada pad debe ser un objeto": "Each pad must be an object",
    "Proyecto no encontrado en la biblioteca": "Project not found in this library",
    "Programa XPM no encontrado en la biblioteca": "XPM program not found in this library",
    "Audio de backup no encontrado.": "Backup audio was not found.",
    "Archivo no encontrado.": "File was not found.",
    "Módulo hardware_kit_builder no disponible.": "Hardware kit builder module unavailable.",
    "Motor hardware_kit_builder no disponible en el servidor.": "Hardware kit builder is unavailable on the server.",
    "Función parse_xpj_project no disponible.": "XPJ project reader is unavailable.",
    "Función list_expansion_kits no disponible.": "Expansion program listing is unavailable.",
    "Función parse_xpm_program no disponible.": "XPM program reader is unavailable.",
    "Envía el archivo WAV original con Content-Type audio/wav": "Send the original WAV with Content-Type audio/wav",
    "Transferencia incompleta": "Transfer incomplete",
    "Content-Length no válido": "Invalid Content-Length",
    "Tamaño de petición no permitido": "Request size not allowed",
    "Las rutas privadas no están disponibles por HTTP": "Private paths are not available via HTTP",
    "Ruta fuera de la biblioteca": "Path is outside the library",
    "Use la interfaz local de BeatOS": "Use the local BeatOS interface",
    "Abre la herramienta oficial en Chrome, Edge o Firefox de escritorio; Safari no admite Web MIDI.": "Open the official tool in desktop Chrome, Edge or Firefox. Safari does not support this Web MIDI workflow.",
    "Abre la herramienta oficial en un navegador con Web MIDI": "Open the official tool in a Web MIDI compatible browser.",
    "Script sync_master_dashboard.py no encontrado.": "Optional sync_master_dashboard.py script not found.",
    "🚀 Iniciando reindexación de MPC Sample Database...": "🚀 Starting MPC sample database reindex…",
    "🎛️  AKAI MPC SAMPLE DATABASE & FINDER TOOLKIT": "🎛️  BEATOS — The MakerLicious — Sample library indexer",
    "❌ No se encontró el script de indexación.": "❌ The indexing script was not found.",
    "✔ Proceso finalizado correctamente.": "✔ Process completed successfully.",
    "❌ Error en el proceso de reindexación.": "❌ Reindexing failed.",
    "✔ dot_clean ejecutado en el volumen.": "✔ dot_clean completed on the volume.",
    "  💡 Presiona Ctrl+C en esta terminal para detener el servidor.\\n": "  💡 Press Ctrl+C to stop the server.\\n",
    "✔ Servidor web detenido correctamente.": "✔ Web server stopped successfully.",

    "Selecciona un WAV PCM de hasta 128 MiB": "Select a PCM WAV of up to 128 MiB",
    "WAV vacío o truncado; conserva y revisa la grabación original": "WAV is empty or truncated; preserve and inspect the original recording",
    "Carpeta de respaldos fuera de la biblioteca": "Backup folder is outside the selected library",
    "Existe otro archivo en el destino; no se ha sustituido": "An existing destination file was preserved and not replaced",
    "La pista seleccionada no contiene un programa de batería": "The selected track does not contain a Drum program",
    "Expansión fuera de la biblioteca": "Expansion is outside the library",
    "Esta conversión necesita FFmpeg. Instálalo o usa WAV PCM 16-bit/44.1kHz.": "This conversion requires FFmpeg. Install it or use 16-bit/44.1 kHz PCM WAV.",
    "Se requiere audio mono o estéreo no vacío": "Nonempty mono or stereo audio is required",
    "Audio vacío": "Audio is empty",
    "Tempo fuera de rango (30–300 BPM)": "Tempo out of range (30–300 BPM)",
    "Parámetros WAV no admitidos: usa PCM entre 8 y 384 kHz y de 1 a 8 canales": "Unsupported WAV parameters: use PCM at 8–384 kHz with 1–8 channels",
    "Separación PO: entre 0 y 500 ms": "PO gap must be between 0 and 500 ms",
    "Las pausas ocupan todo el presupuesto; reduce su duración": "The gaps exceed the time budget; reduce their duration",
    "Destino de exportación no reconocido": "Unrecognized export target",
    "El rack admite pads 1 a 16 y necesita al menos una muestra": "The rack supports pads 1–16 and requires at least one sample",
    "Ya existe un kit con ese nombre. Elige otro para conservar el original.": "A kit with this name already exists. Choose another name to preserve it.",
    "No se pudo leer el proyecto": "Could not read the project",
    "Programa ilegible": "Program cannot be read",
    "Servidor no disponible": "Server unavailable",
    "Acción rechazada": "Action rejected",
    'Archivo de audio externo no válido.': 'Invalid external audio file.',
    'Backup outside the library': 'Backup outside the library',
    'Carga muestras en el rack o indica un estilo para que Cerebro OS orqueste la sesión.': 'Load samples into the rack or enter a style prompt so Cerebro OS can orchestrate the session.',
    'Catalog recovery requires matching database and metadata; existing files were preserved': 'Catalog recovery requires matching database and metadata; existing files were preserved',
    'Classify this legacy recording with its device model before protocol verification': 'Classify this legacy recording with its device model before protocol verification',
    'Conflicting project metadata; prior entry not replaced': 'Conflicting project metadata; prior entry not replaced',
    'El límite de inspección es 128 MiB; el original sigue disponible para descargar': 'Inspection limit is 128 MiB; the original file remains available for download',
    'Expected JSON request': 'Expected JSON request',
    "Falta el parámetro 'sample_path' o 'sample'": "Missing 'sample_path' or 'sample' parameter",
    'File not found': 'File not found',
    'Incomplete or unsupported WAV recording': 'Incomplete or unsupported WAV recording',
    'Incomplete request': 'Incomplete request',
    'Invalid format': 'Invalid format',
    'La base de datos SQLite no está disponible.': 'The SQLite database is unavailable.',
    'La base de datos SQLite no existe todavía. Ejecuta una reindexación primero.': 'The SQLite database does not exist yet. Run a reindex first.',
    'La muestra externa no pertenece a una biblioteca montada autorizada.': 'The external sample does not belong to an authorized mounted library.',
    'La plantilla no declara SAMPLES': 'The template does not declare SAMPLES',
    'Missing backup file': 'Missing backup file',
    'Missing backup path': 'Missing backup path',
    'Mute group must be between 0 and 32': 'Mute group must be between 0 and 32',
    'Original backup WAV not found or symlinked': 'Original backup WAV not found or symlinked',
    'Project name must contain 1–160 characters': 'Project name must contain 1–160 characters',
    'Ruta de muestra externa requerida.': 'External sample path is required.',
    'Selecciona o carga primero una muestra en el pad activo.': 'First select or load a sample on the active pad.',
    'Selecciona una muestra o loop para dividir en pads.': 'Select a sample or loop to slice across pads.',
    'Symlinked backups are not supported': 'Symlinked backups are not supported',
    'Unsupported Pocket Operator backup model': 'Unsupported Pocket Operator backup model',
    'Unsupported/incomplete WAV; do not prepare restoration': 'Unsupported/incomplete WAV; do not prepare restoration',
    'No hay carpeta externa configurada para copiar el backup': 'No external folder is configured to copy this backup',
    'La carpeta externa configurada no está disponible o no tiene permisos de escritura': 'The configured external folder is unavailable or not writable',
    'La carpeta externa no tiene permisos de escritura': 'The external folder does not have write permission',
    'No hay carpeta externa configurada para guardar el backup': 'No external folder is configured to save this backup',
    'Configura una carpeta externa válida antes de activar el almacenamiento externo': 'Configure a valid external folder before enabling external storage',
    'Archivo WAV de respaldo no encontrado': 'Backup WAV file not found',
    'Ruta de backup no encontrada': 'Backup path not found',
    'Selector nativo disponible en macOS; escribe la ruta absoluta manualmente.': 'Native picker is available on macOS; enter the absolute path manually.',
    'Tiempo de espera agotado en el selector de carpetas': 'Folder picker timed out',
    'Ya hay una tarea en ejecución en segundo plano.': 'Another background task is already running.',
    '✔ Instalación de soporte completada.': '✔ Support installation completed.',
    '🎉 Indexación completada con éxito. Inicia BeatOS/ABRIR_BEATOS.command o el instalador de tu carpeta de código.': '🎉 Indexing completed successfully. Start BeatOS/ABRIR_BEATOS.command or the installer in your code folder.',
    'Asigna al menos 1 pad al Rack antes de guardar el perfil.': 'Assign at least 1 pad to the Rack before saving the profile.',
    'Modo de perfil no válido (usa studio_mastering, live_pa o baseline_original).': 'Invalid profile mode (use studio_mastering, live_pa, or baseline_original).',
    'Asigna al menos 1 pad al Rack antes de cambiar de perfil.': 'Assign at least 1 pad to the Rack before switching profiles.',
    "target_mode debe ser 'studio_mastering' o 'live_pa'.": "target_mode must be 'studio_mastering' or 'live_pa'.",
    'Se requiere set_id o pads activos para restaurar el perfil.': 'A set_id or active pads are required to restore the profile.',
    'No existe un snapshot guardado para este set todavía.': 'No saved snapshot exists for this set yet.',
    'No se encontró snapshot baseline_original para este set.': 'No baseline_original snapshot was found for this set.',
    'No se admiten enlaces simbólicos en muestras externas.': 'Symbolic links are not supported for external samples.',
    'No se admiten enlaces simbólicos en el destino.': 'Symbolic links are not supported at the destination.',
    "El parámetro 'start_project' debe ser texto": "The 'start_project' parameter must be a string",
    "El parámetro 'action' debe ser texto": "The 'action' parameter must be a string",
    'Indica la ruta del archivo WAV de bounce dentro de la biblioteca.': 'Provide the path to the bounce WAV file inside the library.',
    'Motor de medición acústica no disponible.': 'Acoustic metering engine is unavailable.',
    'La carpeta de instaladores no puede ser un enlace simbólico': 'The installers directory cannot be a symbolic link',
    'La ruta externa debe ser texto': 'External path must be a string',
    'Indica una ruta absoluta válida para la librería externa': 'Provide a valid absolute path for the external library',
    'La ruta de la librería externa debe ser absoluta': 'External library path must be absolute',
    'La ruta externa no puede contener segmentos ..': 'External path cannot contain .. segments',
    'La ruta externa debe ser un directorio real (sin enlaces simbólicos)': 'External path must be a real directory (no symbolic links)',
    'El directorio padre de la ruta externa no es válido o no existe': 'Parent directory of the external path is invalid or does not exist',
    'No se permite escribir backups dentro de directorios del sistema': 'Writing backups inside system directories is not allowed',
    'Configuración de librería no válida': 'Invalid library configuration',
    'storage_mode debe ser "default" o "external"': 'storage_mode must be "default" or "external"',
    'scan_external_dirs debe ser una lista': 'scan_external_dirs must be a list',
    'include_default_in_scan debe ser booleano': 'include_default_in_scan must be a boolean',
    'include_legacy_dirs debe ser booleano': 'include_legacy_dirs must be a boolean',
    'La subcarpeta de destino es un enlace simbólico': 'Target subfolder is a symbolic link',
    'Carpeta de destino fuera de la ruta externa': 'Target folder is outside the external path',
    'Selecciona un archivo de audio válido (.wav, .aif, .aiff, .flac).': 'Select a valid audio file (.wav, .aif, .aiff, .flac).',
    'Destino no válido: usa "default" o "external"': 'Invalid destination: use "default" or "external"',
    'La subcarpeta destino es un enlace simbólico': 'Destination subfolder is a symbolic link',
    'Destino fuera de la raíz permitida': 'Destination is outside the allowed root',
    'Existe otro archivo diferente con el mismo nombre en destino': 'A different file with the same name already exists at the destination',
    'Ya existe el proyecto MPC o su carpeta de muestras. Elige otro nombre para conservar el original.': 'An MPC project or its samples folder already exists. Choose another name to preserve the original.',
    'Ya existe el proyecto MPC o su carpeta de muestras. Elige otro nombre.': 'An MPC project or its samples folder already exists. Choose another name.',
    'Falta la carpeta de muestras del proyecto MPC': 'MPC project samples folder is missing',
    'Ruta de expansión obligatoria.': 'Expansion path is required.',
    'Imagen no válida: sube un PNG, JPG o WebP real.': 'Invalid image: upload a real PNG, JPG, or WebP file.',
    "El proyecto de arranque 'start_project' debe terminar en .mldp o .xpj": "Startup project 'start_project' must end in .mldp or .xpj",
    'Número de compases fuera de rango (1–16).': 'Bar count out of range (1–16).',
    'Parámetro steps debe ser un entero positivo.': 'The steps parameter must be a positive integer.',
}
PREFIX_EN = {
    'Archivo de muestra no encontrado: ': 'Sample file not found: ',
    'Archivo no encontrado: ': 'File not found: ',
    'Abierto en el explorador: ': 'Opened in file browser: ',
    'La carpeta externa no existe: ': 'External folder does not exist: ',
    'Muestra no encontrada: ': 'Sample not found: ',
    'Muestra de audio no encontrada: ': 'Audio sample not found: ',
    'Nombre de nota desconocido: ': 'Unknown note name: ',
    'No se pudo decodificar ': 'Could not decode ',
    'Preset mpcqol.conf desconocido: ': 'Unknown mpcqol.conf preset: ',
    'Preset Melodee desconocido: ': 'Unknown Melodee preset: ',
    "Ruta no encontrada: ": "Path not found: ",
    "Proyecto no encontrado: ": "Project not found: ",
    "La biblioteca no existe: ": "Library does not exist: ",
    "Parámetros WAV no admitidos: ": "Unsupported WAV parameters: ",
    "WAV PCM ilegible: ": "Unreadable PCM WAV: ",
    "Muestra ausente en pad ": "Missing sample on pad ",
    "Pad ": "Pad ",
    "✔ Purgados ": "✔ Removed ",
    "❌ Excepción durante ejecución: ": "❌ Execution error: ",
    "  📁 Raíz de Medios / Repositorio: ": "  📁 Media library root: ",
    "  🌐 URL del Catálogo Web:         ": "  🌐 Browser catalog URL: ",
    "✔ El servidor BeatOS ya está activo en segundo plano en ": "✔ BeatOS server is already running at ",
    "Puerto ": "Port ",
    "  💡 Presiona Ctrl+C en esta terminal para detener el servidor.": "  💡 Press Ctrl+C to stop the server.",
    "Ruta de Origen : ": "Source library: ",
    "Ruta de Salida : ": "Output directory: ",
    "Base de Datos  : ": "Database: ",
    "✔ Catálogo en Raíz: ": "✔ Catalog at root: ",
    "✔ Catálogo en Carpeta SQLite: ": "✔ Catalog in SQLite folder: ",
    "✔ Base de Datos SQLite: ": "✔ SQLite database: ",
    "  ✔ Expansión: ": "  ✔ Expansion: ",
    "  ✔ Proyecto: ": "  ✔ Project: ",
    "✔ Total muestras de audio: ": "✔ Total audio samples: ",
    "🔍 1. Buscando y analizando proyectos MPC (.xpj)...": "🔍 1. Scanning MPC projects (.xpj)…",
    "📦 2. Buscando Expansiones Oficiales MPC...": "📦 2. Scanning MPC expansions…",
    "🔊 3. Escaneando y clasificando muestras de audio...": "🔊 3. Scanning and classifying audio samples…",
    "📊 4. Generando archivos de exportación...": "📊 4. Writing index export files…",
    "🌐 5. Generando Catálogo Web HTML5 interactivo...": "🌐 5. Building interactive HTML5 catalog…",
    "🎉 Indexación completada con éxito.": "🎉 Indexing completed successfully.",
}
_SORTED_PREFIXES = sorted(PREFIX_EN.items(), key=lambda item: len(item[0]), reverse=True)


def get_request_language(headers):
    """An explicit header wins; otherwise trust only a strict two-value locale cookie."""
    header = headers.get("X-BeatOS-Language", "").lower().strip()
    if header in ("en", "es"):
        return header
    try:
        cookies = SimpleCookie()
        cookies.load(headers.get("Cookie", ""))
        cookie = cookies.get("beatos_locale")
        if cookie and cookie.value.lower() in ("en", "es"):
            return cookie.value.lower()
    except (ValueError, TypeError):
        pass
    return "en"


_DIAGNOSTIC_PATTERNS = tuple((re.compile(pattern), replacement) for pattern, replacement in (
    (r"Formato de nota inválido: (.+)\. Ejemplos válidos: (.+)", r"Invalid note format: \1. Valid examples: \2"),
    (r"Escala desconocida: (.+)\. Escalas disponibles: (.+)", r"Unknown scale: \1. Available scales: \2"),
    (r"El destino '([^']+)' admite pads 1 a (\d+); selecciona un destino específico para más bancos",
     r"Target '\1' supports pads 1–\2. Select a specific target to use more banks"),
    (r"Valor inválido (.+) para (.+) \(permitidos: (.+)\)", r"Invalid value \1 for \2 (allowed: \3)"),
    (r"Kit '([^']+)' generado exitosamente para destino '([^']+)'\.", r"Kit '\1' generated successfully for target '\2'."),
    (r"Cancelación de fase subgrave detectada entre PAD (\d+) y PAD (\d+) \(corr=([^)]+)\)\.",
     r"Sub-bass phase cancellation detected between PAD \1 and PAD \2 (corr=\3)."),
    (r"Oposición de fase en transiente Snare\+Clap entre PAD (\d+) y PAD (\d+) \(corr=([^)]+)\)\.",
     r"Transient phase opposition on Snare+Clap between PAD \1 and PAD \2 (corr=\3)."),
    (r"🛠️ Instalación de soporte \(([^)]+)\) iniciada en segundo plano\.",
     r"🛠️ Support installation (\1) started in the background."),
    (r"No se puede usar (.+) como carpeta de backups",
     r"Cannot use \1 as a backups folder"),
    (r"El volumen externo (.+) no está montado actualmente",
     r"External volume \1 is not currently mounted"),
    (r"Pad (\d+): nombre de muestra no válido",
     r"Pad \1: invalid sample name"),
    (r"Pad (\d+): muestra asignada no disponible: (.+)",
     r"Pad \1: assigned sample unavailable: \2"),
    (r"Formato de canales no admitido: (.+); requiere mono o estéreo",
     r"Unsupported channel count: \1; requires mono or stereo"),
    (r"Ya existe una expansión llamada '([^']+)'\.",
     r"An expansion named '\1' already exists."),
    (r"True Peak ([^\s]+ dBTP) excede techo seguro AK4558 \(([^)]+)\)\.",
     r"True Peak \1 exceeds safe AK4558 ceiling (\2)."),
    (r"Equivalencias aplicadas a SampQOL-OS \((\d+) claves en mpcqol\.conf\)\.",
     r"Mappings applied to SampQOL-OS (\1 keys in mpcqol.conf)."),
    (r"FAISS fallback omitido: (.+)",
     r"FAISS fallback skipped: \1"),
))


def translate_text(value, lang="en"):
    if lang != "en" or not isinstance(value, str):
        return value
    # Preserve leading line breaks from console progress without losing translations.
    indentation = value[:len(value) - len(value.lstrip("\r\n"))]
    body = value[len(indentation):]
    if body in EXACT_EN:
        return indentation + EXACT_EN[body]
    if body == "🎉 Indexación completada con éxito. Inicia BeatOS/ABRIR_BEATOS.command o el instalador de tu carpeta de código.":
        return indentation + "🎉 Indexing completed successfully. Start BeatOS/ABRIR_BEATOS.command or the installer in your code folder."
    cleanup = re.fullmatch(r"✔ Purgados (\d+) archivos ocultos de metadatos AppleDouble \(\._\* y \.DS_Store\)\.", body)
    if cleanup:
        return indentation + f"✔ Removed {cleanup.group(1)} AppleDouble/.DS_Store metadata files."
    port = re.fullmatch(r"Puerto (\d+) ocupado por otra biblioteca o servicio; esta biblioteca usa (\d+)\.", body)
    if port:
        return indentation + f"Port {port.group(1)} is busy; this library uses port {port.group(2)}."
    pad_missing = re.fullmatch(r"Pad (\d+): muestra ausente o fuera de la biblioteca", body)
    if pad_missing:
        return indentation + f"Pad {pad_missing.group(1)}: sample missing or outside the library"
    pad_range = re.fullmatch(r"Pad (\d+): (volume|pan|tune|mute_group|tempo) fuera de rango", body)
    if pad_range:
        return indentation + f"Pad {pad_range.group(1)}: {pad_range.group(2)} out of range"
    pad_error = re.fullmatch(r"No se pudo procesar pad (\d+): (.+)", body, re.DOTALL)
    if pad_error:
        return indentation + f"Could not process pad {pad_error[1]}: {translate_text(pad_error[2], lang)}"
    for pattern, replacement in _DIAGNOSTIC_PATTERNS:
        if match := pattern.fullmatch(body):
            return indentation + match.expand(replacement)
    for prefix, english in _SORTED_PREFIXES:
        if body.startswith(prefix):
            return indentation + english + body[len(prefix):]
    return value


def localize_api_payload(payload, lang="en"):
    """Return a new shallow JSON dictionary without editing global state or path fields."""
    if lang != "en" or not isinstance(payload, dict):
        return payload
    result = dict(payload)
    for name in ("error", "message"):
        value = payload.get(name)
        if isinstance(value, str) and value:
            result[name + "_es"] = value
            translated = translate_text(value, lang)
            if translated == value and name == "error" and value.lstrip("\r\n") not in EXACT_EN:
                translated = "Operation failed; original technical detail available in error_es."
            result[name] = translated
    logs = payload.get("logs")
    if isinstance(logs, list):
        result["logs_es"] = list(logs)
        result["logs"] = [translate_text(line, lang) for line in logs]
    phase_warnings = payload.get("phase_warnings")
    if isinstance(phase_warnings, list):
        result["phase_warnings_es"] = list(phase_warnings)
        result["phase_warnings"] = [translate_text(line, lang) for line in phase_warnings]
    return result

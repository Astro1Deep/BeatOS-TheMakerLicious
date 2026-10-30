"""ES/EN presentation of BeatOS API diagnostics.

This module never modifies source filenames, sample paths, or audio payloads.
The original diagnostic remains available as error_es / logs_es for debugging.
Do not use these translations as a substitute for stable machine error codes.
"""
from __future__ import annotations

from http.cookies import SimpleCookie

EXACT_EN = {
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
    "Selecciona un WAV PCM de hasta 128 MiB": "Select a PCM WAV of up to 128 MiB",
    "WAV vacío o truncado; conserva y revisa la grabación original": "WAV is empty or truncated; preserve and inspect the original recording",
    "Carpeta de respaldos fuera de la biblioteca": "Backup folder is outside the selected library",
    "Existe otro archivo en el destino; no se ha sustituido": "An existing destination file was preserved and not replaced",
    "La pista seleccionada no contiene un programa de batería": "The selected track does not contain a Drum program",
    "Expansión fuera de la biblioteca": "Expansion is outside the library",
    "Esta conversión necesita FFmpeg. Instálalo o usa WAV PCM 16-bit/44.1kHz.": "This conversion requires FFmpeg. Install it or use 16-bit/44.1 kHz PCM WAV.",
    "Se requiere audio mono o estéreo no vacío": "Nonempty mono or stereo audio is required",
    "Audio vacío": "Audio is empty",
    "Separación PO: entre 0 y 500 ms": "PO gap must be between 0 and 500 ms",
    "Las pausas ocupan todo el presupuesto; reduce su duración": "The gaps exceed the time budget; reduce their duration",
    "Destino de exportación no reconocido": "Unrecognized export target",
    "El rack admite pads 1 a 16 y necesita al menos una muestra": "The rack supports pads 1–16 and requires at least one sample",
    "Ya existe un kit con ese nombre. Elige otro para conservar el original.": "A kit with this name already exists. Choose another name to preserve it.",
    "No se pudo leer el proyecto": "Could not read the project",
    "Programa ilegible": "Program cannot be read",
    "Servidor no disponible": "Server unavailable",
    "Acción rechazada": "Action rejected",
}
PREFIX_EN = {
    "Ruta no encontrada: ": "Path not found: ",
    "Proyecto no encontrado: ": "Project not found: ",
    "La biblioteca no existe: ": "Library does not exist: ",
    "Parámetros WAV no admitidos: ": "Unsupported WAV parameters: ",
    "WAV PCM ilegible: ": "Unreadable PCM WAV: ",
    "Muestra ausente en pad ": "Missing sample on pad ",
    "Pad ": "Pad ",
    "✔ Purgados ": "✔ Removed ",
    "❌ Excepción durante ejecución: ": "❌ Execution error: ",
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
    return "es"


def translate_text(value, lang="es"):
    if lang != "en" or not isinstance(value, str):
        return value
    # Preserve leading line breaks from console progress without losing translations.
    indentation = value[:len(value) - len(value.lstrip("\\r\\n"))]
    body = value[len(indentation):]
    if body in EXACT_EN:
        return indentation + EXACT_EN[body]
    for prefix, english in _SORTED_PREFIXES:
        if body.startswith(prefix):
            return indentation + english + body[len(prefix):]
    return value


def localize_api_payload(payload, lang="es"):
    """Return a new shallow JSON dictionary without editing global state or path fields."""
    if lang != "en" or not isinstance(payload, dict):
        return payload
    result = dict(payload)
    for name in ("error", "message"):
        value = payload.get(name)
        if isinstance(value, str) and value:
            result[name + "_es"] = value
            translated = translate_text(value, lang)
            if translated == value and name == "error":
                translated = "Operation failed; original technical detail available in error_es."
            result[name] = translated
    logs = payload.get("logs")
    if isinstance(logs, list):
        result["logs_es"] = list(logs)
        result["logs"] = [translate_text(line, lang) for line in logs]
    return result

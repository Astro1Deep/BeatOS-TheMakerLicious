"""End-to-end API localization regression without real devices or personal libraries."""
import contextlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve_mpc


class APILanguageTests(unittest.TestCase):
    @contextlib.contextmanager
    def server(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = HTTPServer(("127.0.0.1", 0), serve_mpc.MPCAudioRequestHandler)
            server.root_dir = tmp
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield "http://127.0.0.1:" + str(server.server_port)
            finally:
                server.shutdown()
                thread.join(timeout=3)
                server.server_close()

    def request(self, url, data=None, headers=None):
        headers = headers or {}
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_hardware_errors_are_translated_without_modifying_pad_number(self):
        from beatos_i18n import translate_text
        cases = {
            "Tempo fuera de rango (30–300 BPM)": "Tempo out of range (30–300 BPM)",
            "Pad 5: muestra ausente o fuera de la biblioteca": "Pad 5: sample missing or outside the library",
            "Pad 7: tune fuera de rango": "Pad 7: tune out of range",
            "Parámetros WAV no admitidos: usa PCM entre 8 y 384 kHz y de 1 a 8 canales": "Unsupported WAV parameters: use PCM at 8–384 kHz with 1–8 channels",
        }
        for spanish, english in cases.items():
            with self.subTest(spanish=spanish):
                self.assertEqual(translate_text(spanish, "en"), english)
                self.assertEqual(translate_text(spanish, "es"), spanish)

    def test_dynamic_server_and_indexer_text_is_fully_english(self):
        from beatos_i18n import translate_text
        self.assertEqual(
            translate_text("✔ Purgados 3 archivos ocultos de metadatos AppleDouble (._* y .DS_Store).", "en"),
            "✔ Removed 3 AppleDouble/.DS_Store metadata files."
        )
        self.assertEqual(
            translate_text("Puerto 8888 ocupado por otra biblioteca o servicio; esta biblioteca usa 8889.", "en"),
            "Port 8888 is busy; this library uses port 8889."
        )
        self.assertEqual(
            translate_text("\n🎉 Indexación completada con éxito. Inicia BeatOS/ABRIR_BEATOS.command o el instalador de tu carpeta de código.", "en"),
            "\n🎉 Indexing completed successfully. Start BeatOS/ABRIR_BEATOS.command or the installer in your code folder."
        )

    def test_english_cookie_localizes_api_error_without_modifying_original(self):
        with self.server() as url:
            status, payload = self.request(url + "/api/load_project", data=b"{}", headers={
                "Cookie": "beatos_locale=en",
                "Content-Type": "application/json",
            })
            self.assertNotEqual(status, 200)
            self.assertIn("Missing", payload["error"])
            self.assertIn("Falta parámetro", payload["error_es"])
            self.assertNotEqual(payload["error"], payload["error_es"])

    def test_english_default_and_header_priority(self):
        with self.server() as url:
            status, payload = self.request(url + "/api/load_project", data=b"{}", headers={
                "Content-Type": "application/json",
            })
            self.assertNotEqual(status, 200)
            self.assertIn("Missing", payload["error"])
            _, en = self.request(url + "/api/load_project", data=b"{}", headers={
                "Cookie": "beatos_locale=es",
                "X-BeatOS-Language": "en",
                "Content-Type": "application/json",
            })
            self.assertIn("Missing", en["error"])
            _, spanish = self.request(url + "/api/load_project", data=b"{}", headers={"Cookie":"beatos_locale=es", "Content-Type":"application/json"})
            self.assertIn("Falta parámetro", spanish["error"])

    def test_server_console_honors_english_environment(self):
        import contextlib
        import io
        import os
        from unittest.mock import MagicMock, patch
        with tempfile.TemporaryDirectory() as tmp:
            fake = MagicMock()
            fake.serve_forever.side_effect = KeyboardInterrupt()
            output = io.StringIO()
            with patch.dict(os.environ, {"BEATOS_LANG": "en"}), patch.object(serve_mpc, "HTTPServer", return_value=fake), patch("serve_mpc.find_available_port", return_value=8888), contextlib.redirect_stdout(output):
                serve_mpc.run_server(tmp, port=8888, auto_open=False)
            self.assertIn("Media library root", output.getvalue())
            self.assertIn("Press Ctrl+C", output.getvalue())
            self.assertNotIn("Raíz de Medios", output.getvalue())

    def test_server_console_uses_english_for_blank_environment(self):
        import contextlib
        import io
        import os
        from unittest.mock import MagicMock, patch
        with tempfile.TemporaryDirectory() as tmp:
            fake = MagicMock()
            fake.serve_forever.side_effect = KeyboardInterrupt()
            output = io.StringIO()
            with patch.dict(os.environ, {"BEATOS_LANG": ""}), patch.object(serve_mpc, "HTTPServer", return_value=fake), patch("serve_mpc.find_available_port", return_value=8888), contextlib.redirect_stdout(output):
                serve_mpc.run_server(tmp, port=8888, auto_open=False)
            self.assertIn("Media library root", output.getvalue())
            self.assertIn("Press Ctrl+C", output.getvalue())
            self.assertNotIn("Raíz de Medios", output.getvalue())

    def test_task_logs_are_localized_per_request_not_mutated_globally(self):
        logs_before = list(serve_mpc.TASK_STATE["logs"])
        try:
            serve_mpc.TASK_STATE["logs"] = ["🚀 Iniciando reindexación de MPC Sample Database..."]
            with self.server() as url:
                _, payload = self.request(url + "/api/task_status", headers={"Cookie": "beatos_locale=en"})
                self.assertIn("Starting", payload["logs"][0])
                self.assertIn("Iniciando", payload["logs_es"][0])
                _, default = self.request(url + "/api/task_status")
                self.assertIn("Starting", default["logs"][0])
            self.assertIn("Iniciando", serve_mpc.TASK_STATE["logs"][0])
        finally:
            serve_mpc.TASK_STATE["logs"] = logs_before

    def test_all_backend_error_and_status_strings_translate_to_english(self):
        from beatos_i18n import EXACT_EN, localize_api_payload, translate_text

        sample_backend_strings = [
            "La base de datos SQLite no existe todavía. Ejecuta una reindexación primero.",
            "La base de datos SQLite no está disponible.",
            "Ruta de muestra externa requerida.",
            "Archivo de audio externo no válido.",
            "La muestra externa no pertenece a una biblioteca montada autorizada.",
            "Script sync_master_dashboard.py y plantilla MASTER_ECOSISTEMA_DISCOS.html no encontrados.",
            "Selecciona una muestra o loop para dividir en pads.",
            "Motor autochop no disponible.",
            "Motor create_custom_expansion no disponible en el servidor.",
            "Función create_chromatic_kit no disponible en hardware_kit_builder.",
            "Falta el parámetro 'sample_path' o 'sample'",
            "Selecciona o carga primero una muestra en el pad activo.",
            "Función build_rack_scale_bank no disponible.",
            "Gestor mpcqol.conf no disponible.",
            "No se pudo abrir el archivo de descarga.",
            "🚀 Reindexación iniciada en segundo plano con éxito.",
            "Ya hay una reindexación en ejecución en segundo plano.",
            "EP-133: el mapa de un kit admite 4 grupos de 12 sonidos (48 en total)",
            "Presupuesto PO: entre 1 y 40 segundos",
            "SP-404A/SX: cada banco tiene 12 pads; mueve los sonidos de las posiciones 13–16 antes de exportar",
            "El título de la expansión es obligatorio.",
            "Ruta de expansión fuera del directorio Expansions",
            "Selecciona al menos un kit/proyecto con muestras válidas o carga muestras en el Rack de 16 pads.",
            "La muestra es demasiado corta para dividirla en múltiples cortes.",
            "Existe un enlace en el destino; no se ha sustituido",
            "El límite de inspección es 128 MiB; el original sigue disponible para descargar",
            "Pad duplicado",
            "La plantilla no declara SAMPLES",
            "Archivo de muestra no encontrado: Samples/kick.wav",
            "Muestra no encontrada: Samples/808.wav",
            "Muestra de audio no encontrada: Samples/snare.wav",
            "Archivo no encontrado: Custom_Kits/test.zip",
            "No se pudo decodificar broken.wav",
            "Preset mpcqol.conf desconocido: turbo",
            "Abierto en el explorador: /tmp/demo",
            "Formato de nota inválido: 'Z9'. Ejemplos válidos: 'C2', 'F#1', 'Eb3'",
            "Nombre de nota desconocido: 'H#'",
            "Escala desconocida: 'hungarian'. Escalas disponibles: minor, major",
            "El destino 'po33' admite pads 1 a 16; selecciona un destino específico para más bancos",
            "Kit 'Boogie_Kit' generado exitosamente para destino 'mpc'.",
            "No se pudo procesar pad 4: Tempo fuera de rango (30–300 BPM)",
            "Valor inválido 99 para monitor (permitidos: [0, 1, 2])",
            "Cancelación de fase subgrave detectada entre PAD 1 y PAD 3 (corr=-0.72).",
            "Oposición de fase en transiente Snare+Clap entre PAD 2 y PAD 4 (corr=-0.65).",
            "Expected JSON request",
            "Incomplete request",
            "Missing backup path",
            "Symlinked backups are not supported",
            "Backup outside the library",
            "Unsupported/incomplete WAV; do not prepare restoration",
            "Missing backup file",
            "Classify this legacy recording with its device model before protocol verification",
            "Incomplete or unsupported WAV recording",
            "Mute group must be between 0 and 32",
            "Catalog recovery requires matching database and metadata; existing files were preserved",
            "Unsupported Pocket Operator backup model",
            "Project name must contain 1–160 characters",
            "Original backup WAV not found or symlinked",
            "Conflicting project metadata; prior entry not replaced",
        ]
        generic_fallback = "Operation failed; original technical detail available in error_es."
        for text in sample_backend_strings:
            with self.subTest(text=text):
                translated = translate_text(text, "en")
                localized = localize_api_payload({"error": text, "message": text}, "en")
                self.assertNotEqual(localized["error"], generic_fallback)
                self.assertEqual(localized["error"], translated)
                if text not in EXACT_EN or EXACT_EN[text] != text:
                    self.assertNotEqual(translated, text)
                    for marker in ("no encontrado", "no encontrada", "no disponible", "inválido", "desconocido", "fuera del", "Cancelación", "Oposición"):
                        self.assertNotIn(marker.lower(), translated.lower())

        phase_localized = localize_api_payload({
            "phase_warnings": [
                "Cancelación de fase subgrave detectada entre PAD 1 y PAD 2 (corr=-0.81)."
            ]
        }, "en")
        self.assertIn("Sub-bass phase cancellation", phase_localized["phase_warnings"][0])
        self.assertIn("Cancelación", phase_localized["phase_warnings_es"][0])

    def test_induced_api_errors_translate_cleanly_in_english(self):
        generic_fallback = "Operation failed; original technical detail available in error_es."
        with self.server() as url:
            cases = [
                ("/api/cerebro_autochop", b"{}", "Select a sample"),
                ("/api/rack_scale_spread", b"{}", "First select or load"),
                ("/api/cerebro_import_external_sample", b"{}", "External sample path"),
                ("/api/create_expansion", b'{"title":""}', "Expansion title is required"),
                ("/api/cerebro_master_produce", b"{}", "Load samples into the rack"),
            ]
            for endpoint, body, expected_en in cases:
                with self.subTest(endpoint=endpoint):
                    status, en_payload = self.request(
                        url + endpoint,
                        data=body,
                        headers={"Origin": url, "Content-Type": "application/json", "X-BeatOS-Language": "en"},
                    )
                    self.assertNotEqual(status, 200)
                    self.assertNotEqual(en_payload.get("error"), generic_fallback)
                    self.assertIn(expected_en, en_payload.get("error", ""))
                    _, es_payload = self.request(
                        url + endpoint,
                        data=body,
                        headers={"Origin": url, "Content-Type": "application/json", "X-BeatOS-Language": "es"},
                    )
                    self.assertNotEqual(es_payload.get("error"), en_payload.get("error"))


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

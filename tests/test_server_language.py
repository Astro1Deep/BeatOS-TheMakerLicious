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

    def test_spanish_default_and_header_priority(self):
        with self.server() as url:
            status, payload = self.request(url + "/api/load_project", data=b"{}", headers={
                "Content-Type": "application/json",
            })
            self.assertNotEqual(status, 200)
            self.assertIn("Falta parámetro", payload["error"])
            _, en = self.request(url + "/api/load_project", data=b"{}", headers={
                "Cookie": "beatos_locale=es",
                "X-BeatOS-Language": "en",
                "Content-Type": "application/json",
            })
            self.assertIn("Missing", en["error"])

    def test_task_logs_are_localized_per_request_not_mutated_globally(self):
        logs_before = list(serve_mpc.TASK_STATE["logs"])
        try:
            serve_mpc.TASK_STATE["logs"] = ["🚀 Iniciando reindexación de MPC Sample Database..."]
            with self.server() as url:
                _, payload = self.request(url + "/api/task_status", headers={"Cookie": "beatos_locale=en"})
                self.assertIn("Starting", payload["logs"][0])
                self.assertIn("Iniciando", payload["logs_es"][0])
                _, default = self.request(url + "/api/task_status")
                self.assertIn("Iniciando", default["logs"][0])
            self.assertIn("Iniciando", serve_mpc.TASK_STATE["logs"][0])
        finally:
            serve_mpc.TASK_STATE["logs"] = logs_before


if __name__ == "__main__":
    unittest.main()

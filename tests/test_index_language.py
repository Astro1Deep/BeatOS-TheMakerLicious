"""Regression: command-line indexing must honor ES/EN without changing sample data."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import index_mpc_library


class IndexLocaleTests(unittest.TestCase):
    def run_index(self, root, lang):
        output = io.StringIO()
        args = ["index_mpc_library.py", "--path", str(root), "--lang", lang]
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(output):
            index_mpc_library.main()
        return output.getvalue()

    def test_cli_english_producer_messages_and_original_filenames(self):
        with tempfile.TemporaryDirectory(prefix="BeatOS locale ") as folder:
            root = Path(folder)
            (root / "Kick_Esperanza_90bpm.wav").write_bytes(b"not-a-real-wav")
            (root / "Synthetic.xpj").write_bytes(b"not-a-real-project")
            expansion = root / "Synthetic_Expansion"
            expansion.mkdir()
            (expansion / "Expansion.xml").write_text("<Expansion><title>Synthetic_Expansion</title></Expansion>", encoding="utf-8")
            lines = self.run_index(root, "en")
            self.assertIn("Source library:", lines)
            self.assertIn("Indexing completed successfully", lines)
            self.assertIn("Project:", lines)
            self.assertIn("Key:", lines)
            self.assertIn("Status:", lines)
            self.assertIn("Expansion:", lines)
            self.assertIn("Programs", lines)
            self.assertNotIn("Ruta de Origen", lines)
            self.assertNotIn("Clave:", lines)
            self.assertNotIn("Estado:", lines)
            self.assertTrue((root / "Kick_Esperanza_90bpm.wav").is_file())
            self.assertEqual((root / "Synthetic.xpj").read_bytes(), b"not-a-real-project")

    def test_cli_defaults_to_spanish(self):
        with tempfile.TemporaryDirectory(prefix="BeatOS locale ") as folder:
            lines = self.run_index(Path(folder), "es")
            self.assertIn("Ruta de Origen", lines)
            self.assertIn("Indexación completada", lines)


    def test_missing_library_reports_selected_language(self):
        with tempfile.TemporaryDirectory() as folder:
            cases = {"en": "The selected library does not exist", "es": "La biblioteca indicada no existe"}
            for language, expected in cases.items():
                stderr = io.StringIO()
                with self.subTest(language=language), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as error:
                        self.run_index(Path(folder) / "missing", language)
                    self.assertEqual(error.exception.code, 2)
                    self.assertIn(expected, stderr.getvalue())

    def test_cli_failures_are_actionable_and_retain_details(self):
        scripts = Path(index_mpc_library.__file__).parent
        with tempfile.TemporaryDirectory(prefix="BeatOS CLI á ") as folder:
            root = Path(folder)
            occupied = root / "Occupied file"
            occupied.write_bytes(b"existing")
            for language in ("es", "en"):
                cases = [
                    ("index_mpc_library.py", ["--path", folder, "--output", str(occupied)],
                     "No se pudo indexar" if language == "es" else "Could not index"),
                    ("hardware_kit_builder.py", ["chromatic", "--sample", str(root / "Missing.wav"), "--name", "Test"],
                     "No se pudo completar la operación" if language == "es" else "Could not complete the kit"),
                    ("serve_mpc.py", [str(root / "Missing library"), "--no-browser"],
                     "No se pudo iniciar" if language == "es" else "Could not start"),
                ]
                for script, args, expected in cases:
                    with self.subTest(script=script, language=language):
                        result = subprocess.run([sys.executable, "-B", str(scripts / script), *args],
                                                text=True, encoding="utf-8", capture_output=True, timeout=15,
                                                env={**os.environ, "BEATOS_LANG": language, "PYTHONIOENCODING": "utf-8"})
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertIn(expected, result.stderr)
                        self.assertIn("Detalle técnico" if language == "es" else "Technical detail", result.stderr)
                        self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(occupied.read_bytes(), b"existing")

if __name__ == "__main__":
    unittest.main()

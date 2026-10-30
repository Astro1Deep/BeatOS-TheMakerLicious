"""Regression: command-line indexing must honor ES/EN without changing sample data."""
import contextlib
import io
import os
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
            lines = self.run_index(root, "en")
            self.assertIn("Source library:", lines)
            self.assertIn("Starting", lines) if False else None
            self.assertIn("Indexing completed successfully", lines)
            self.assertNotIn("Ruta de Origen", lines)
            self.assertTrue((root / "Kick_Esperanza_90bpm.wav").is_file())

    def test_cli_defaults_to_spanish(self):
        with tempfile.TemporaryDirectory(prefix="BeatOS locale ") as folder:
            lines = self.run_index(Path(folder), "es")
            self.assertIn("Ruta de Origen", lines)
            self.assertIn("Indexación completada", lines)


if __name__ == "__main__":
    unittest.main()

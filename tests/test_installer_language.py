"""Regression coverage for BeatOS installer localization (no extra startup prompt)."""
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import installer

class InstallerLanguageTests(unittest.TestCase):
    def test_english_from_cli_without_extra_menu_step(self):
        with patch.object(sys,"argv",["installer.py","--lang","en"]), patch.dict(os.environ,{"BEATOS_LANG":"es"}), patch("builtins.input",return_value="6") as answer, patch("builtins.print") as printed:
            self.assertEqual(installer.get_language(),"en")
            installer.main()
            answer.assert_called_once()
            all_lines="\n".join(str(a) for call in printed.call_args_list for a in call.args)
            self.assertEqual(answer.call_args.args[0], "Choose an option (1-6): ")
            self.assertIn("Exiting.",all_lines)
            self.assertIn("Universal installer",all_lines)
    def test_english_yes_no_question_contains_real_line_break(self):
        question="\n¿Deseas abrir el catálogo en tu navegador ahora? (s/n): "
        translated=installer.locale_text(question, "en")
        self.assertEqual(translated, "\nOpen the catalog in your browser now? (y/n): ")

    def test_english_default_and_explicit_spanish_override(self):
        with patch.object(sys,"argv",["installer.py"]), patch.dict(os.environ,{"BEATOS_LANG":""}), patch("builtins.input",return_value="6"), patch("builtins.print") as printed:
            self.assertEqual(installer.get_language(),"en")
            installer.main()
            self.assertIn("Exiting.",str(printed.call_args_list))
        with patch.object(sys,"argv",["installer.py","--lang","es"]), patch.dict(os.environ,{"BEATOS_LANG":""}):
            self.assertEqual(installer.get_language(),"es")
    def test_indexer_inherits_english_without_changing_command_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder, patch.object(sys, "argv", ["installer.py", "--lang", "en"]), patch("builtins.input", side_effect=["1", folder]), patch("builtins.print"), patch("installer.subprocess.run") as run:
            installer.main()
            self.assertEqual(run.call_args.kwargs["env"]["BEATOS_LANG"], "en")
            self.assertEqual(run.call_args.args[0][-2:], ["--path", folder])

    def test_server_receives_english_and_restores_parent_environment(self):
        with patch.object(sys, "argv", ["installer.py", "--lang", "en"]), patch.dict(os.environ, {"BEATOS_LANG": "es"}), patch("builtins.input", side_effect=["2", ""]), patch("builtins.print"), patch("serve_mpc.run_server") as start:
            start.side_effect = lambda *_args, **_kwargs: self.assertEqual(os.environ.get("BEATOS_LANG"), "en")
            installer.main()
            self.assertEqual(os.environ.get("BEATOS_LANG"), "es")

    def test_documentation_menu_uses_language_specific_wiki(self):
        with patch.object(sys,"argv",["installer.py"]), patch.dict(os.environ,{"BEATOS_LANG":""}), patch("builtins.input",return_value="5"), patch("installer.open_url_or_file") as open_doc, patch("builtins.print"):
            installer.main()
            self.assertIn("Home_EN.md",open_doc.call_args.args[0])
        with patch.object(sys,"argv",["installer.py","--lang","es"]), patch("builtins.input",return_value="5"), patch("installer.open_url_or_file") as open_doc, patch("builtins.print"):
            installer.main()
            self.assertIn("Home.md",open_doc.call_args.args[0])

    def test_english_from_environment(self):
        with patch.object(sys,"argv",["installer.py"]), patch.dict(os.environ,{"BEATOS_LANG":"en"}):
            self.assertEqual(installer.get_language(),"en")

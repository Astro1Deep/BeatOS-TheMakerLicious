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

    def test_spanish_default(self):
        with patch.object(sys,"argv",["installer.py"]), patch.dict(os.environ,{"BEATOS_LANG":""}), patch("builtins.input",return_value="6"), patch("builtins.print") as printed:
            self.assertEqual(installer.get_language(),"es")
            installer.main()
            self.assertIn("Saliendo.",str(printed.call_args_list))
    def test_english_from_environment(self):
        with patch.object(sys,"argv",["installer.py"]), patch.dict(os.environ,{"BEATOS_LANG":"en"}):
            self.assertEqual(installer.get_language(),"en")

"""Validate relative links in both language editions without following external URLs."""
from pathlib import Path
from urllib.parse import unquote
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

def destinations(md):
    text = re.sub(r"(?s)\x60{3}.*?\x60{3}", "", md)
    for m in re.finditer(r"\]\(", text):
        i, start, depth = m.end(), m.end(), 1
        while i < len(text) and depth:
            if text[i] == "(" and (i == 0 or text[i-1] != "\\"):
                depth += 1
            elif text[i] == ")" and (i == 0 or text[i-1] != "\\"):
                depth -= 1
            i += 1
        if depth == 0:
            yield text[start:i-1].strip()

class DocumentationLinks(unittest.TestCase):
    def test_github_readme_english_first_and_spanish_alternative(self):
        english = (ROOT / 'README.md').read_text(encoding='utf-8')
        spanish = (ROOT / 'README_ES.md').read_text(encoding='utf-8')
        self.assertIn('**Language: English (default)', english)
        self.assertIn('[Español / Spanish README](README_ES.md)',english)
        self.assertIn('**Idioma: Español', spanish)
        self.assertIn('[English / presentación principal](README.md)',spanish)
        self.assertIn('HARDWARE_EXPORT_PROTOCOLS.md',english)

    def test_internal_file_links_resolve(self):
        missing = []
        total = 0
        for document in sorted(ROOT.rglob("*.md")):
            if ".git" in document.parts:
                continue
            for href in destinations(document.read_text(encoding="utf-8")):
                if not href or href.startswith(("#", "http://", "https://", "mailto:", "data:")):
                    continue
                path = unquote(href.split("#", 1)[0].split("?", 1)[0].strip("<>"))
                if not path or path.startswith("plugin://"):
                    continue
                total += 1
                target = (document.parent / path).resolve()
                if not target.is_relative_to(ROOT) or not target.is_file():
                    missing.append(f"{document.relative_to(ROOT)} -> {path}")
        self.assertFalse(missing, "Broken local Markdown links:\n" + "\n".join(missing))
        self.assertGreater(total, 60, "Link scan appears incomplete")

if __name__ == "__main__":
    unittest.main()

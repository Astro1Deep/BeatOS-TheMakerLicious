"""Audit all local Markdown links in the bilingual BeatOS documentation.

Also accepts nested parentheses in legacy chapter filenames; external links and
GitHub heading fragments are not checked for availability in this test.
"""
from pathlib import Path
from urllib.parse import unquote
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

def destinations(md):
    text = re.sub(r"```[\\s\\S]*?```", "", md)
    for m in re.finditer(r"\\]\\(", text):
        i, depth, start = m.end(), 1, m.end()
        while i < len(text) and depth:
            if text[i] == "(" and (i == 0 or text[i-1] != "\\\\"):
                depth += 1
            elif text[i] == ")" and (i == 0 or text[i-1] != "\\\\"):
                depth -= 1
            i += 1
        if depth == 0:
            yield text[start:i-1].strip()

class DocumentationLinks(unittest.TestCase):
    def test_internal_file_links_resolve(self):
        missing=[]
        count=0
        for file in sorted(ROOT.rglob("*.md")):
            if ".git" in file.parts:
                continue
            for link in destinations(file.read_text(encoding="utf-8")):
                if not link or link.startswith(("#", "http://", "https://", "mailto:", "data:")):
                    continue
                relative=unquote(link.split("#",1)[0].split("?",1)[0].strip("<>"))
                if not relative or relative.startswith("plugin://"):
                    continue
                count += 1
                target=(file.parent/relative).resolve()
                if not target.is_relative_to(ROOT) or not target.is_file():
                    missing.append(f"{file.relative_to(ROOT)} -> {relative}")
        self.assertFalse(missing, "Broken local Markdown paths:\\n" + "\\n".join(missing))
        self.assertGreater(count, 60, "Unexpectedly few local links audited")

if __name__ == "__main__":
    unittest.main()

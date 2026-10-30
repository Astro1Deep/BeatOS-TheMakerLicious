"""Regression checks for the public UI demo and bilingual Pages discovery files."""
import importlib.util
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"tests"))
import capture_ui_preview


class PublicPreviewChecks(unittest.TestCase):
    def test_demo_records_are_synthetic_and_match_12_column_contract(self):
        records=capture_ui_preview.synthetic_records()
        self.assertGreaterEqual(len(records),12)
        for row in records:
            self.assertEqual(len(row),12)
            self.assertTrue(row[0].startswith("DEMO_"))
            self.assertEqual(row[3],"DEMO")
            self.assertTrue(row[-1].startswith("demo_media/"))
            self.assertFalse(Path(row[-1]).is_absolute())

    def test_real_catalog_template_is_used_for_previews(self):
        html=capture_ui_preview.build_page("en","samples")
        self.assertIn("BeatOS",html)
        self.assertIn("DEMO_Kick_BoomBap",html)
        self.assertIn("synthetic",html.lower())
        self.assertNotIn("__SAMPLE_COUNT__",html)
        rack=capture_ui_preview.build_page("es","rack")
        self.assertIn("switchTab('tab-rack'",rack)
        self.assertIn("localStorage.setItem('mpc_lang',",rack)

    def test_installed_asset_path_resolves_to_repo_branding(self):
        import urllib.request
        with capture_ui_preview.preview_server() as base:
            url=base+"/BeatOS/docs/assets/branding/user_blueprint_sheet_dark_4k.jpg"
            with urllib.request.urlopen(url,timeout=5) as response:
                self.assertEqual(response.status,200)
                self.assertEqual(response.read(3),b"\xff\xd8\xff")

    def test_bilingual_pages_have_canonical_and_hreflang(self):
        for name in ("index.html","index-es.html"):
            html=(ROOT/"docs"/name).read_text(encoding="utf-8")
            self.assertIn('rel="canonical"',html)
            self.assertIn('hreflang="en"',html)
            self.assertIn('hreflang="es"',html)
            self.assertIn('application/ld+json',html)
            self.assertIn('SoftwareApplication',html)
            self.assertIn('assets/screenshots/beatos-overview-',html)
            self.assertIn("BeatOS-TheMakerLicious",html)

    def test_sitemap_is_valid_and_not_confused_with_other_beatos(self):
        tree=ET.parse(ROOT/"docs"/"sitemap.xml")
        urls=[x.text for x in tree.iter() if x.tag.endswith("loc")]
        self.assertEqual(len(urls),2)
        self.assertTrue(all("astro1deep.github.io/BeatOS-TheMakerLicious/" in u for u in urls))

    def test_clean_zip_includes_readme_linked_landing_pages_and_screenshots(self):
        from build_release import build_release
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory(prefix="beatos-release-preview-") as folder:
            archive=Path(folder)/"BeatOS-source.zip"
            build_release(archive)
            with zipfile.ZipFile(archive) as z:
                names=set(z.namelist())
                prefix="BeatOS-3.8.0/BeatOS/"
                for relative in (
                    "docs/index.html", "docs/index-es.html",
                    "docs/assets/screenshots/beatos-overview-en.png",
                    "docs/assets/screenshots/beatos-overview-es.png",
                    "docs/assets/screenshots/beatos-rack-en.png",
                    "docs/assets/screenshots/beatos-hero-en.png",
                    "docs/SEO_DISCOVERY.md",
                ):
                    self.assertIn(prefix+relative,names,relative)

    def test_llm_pointer_disclaims_non_native_exports(self):
        txt=(ROOT/"docs"/"llms.txt").read_text(encoding="utf-8")
        self.assertIn("not native hardware backups",txt)
        self.assertIn("does not guarantee",txt)
        self.assertIn("Astro1Deep/BeatOS-TheMakerLicious",txt)


if __name__=="__main__":
    unittest.main()

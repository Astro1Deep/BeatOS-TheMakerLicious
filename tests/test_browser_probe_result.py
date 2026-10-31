"""Regression: browser smoke result must come from a rendered output element."""
import unittest
from smoke_browser_i18n import browser_probe_result

class BrowserProbeResultTests(unittest.TestCase):
    def test_embedded_script_literal_is_not_an_executed_browser_probe(self):
        html = '<!doctype html><html><body><script>const status="BEATOS_BROWSER_ES_EN_PASS";</script></body></html>'
        self.assertNotEqual(browser_probe_result(html), 'BEATOS_BROWSER_ES_EN_PASS')
    def test_actual_rendered_output_element_is_required(self):
        html = ('<html><body><script>const status="BEATOS_BROWSER_ES_EN_PASS";</script>'
                '<output id="i18n-browser-result">BEATOS_BROWSER_ES_EN_PASS</output></body></html>')
        self.assertEqual(browser_probe_result(html), 'BEATOS_BROWSER_ES_EN_PASS')
    def test_failed_or_partial_output_does_not_pass(self):
        for content in ('FAIL:missing locale test nodes','BEATOS_BROWSER_ES_EN_PASS-extra',''):
            with self.subTest(content=content):
                html = '<html><output id="i18n-browser-result">'+content+'</output></html>'
                self.assertNotEqual(browser_probe_result(html), 'BEATOS_BROWSER_ES_EN_PASS')
    def test_other_element_with_marker_is_not_valid(self):
        html = '<html><span id="i18n-browser-result">BEATOS_BROWSER_ES_EN_PASS</span></html>'
        self.assertNotEqual(browser_probe_result(html), 'BEATOS_BROWSER_ES_EN_PASS')

if __name__ == '__main__':
    unittest.main()

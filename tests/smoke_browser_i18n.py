"""Headless Chrome smoke test for BeatOS ES/EN UI on an actual local HTTP page.

Only reads a synthetic empty catalog. Does not touch real sample libraries or hardware.
"""
from html.parser import HTMLParser
from pathlib import Path
from threading import Thread
from contextlib import contextmanager
from tempfile import TemporaryDirectory
import shutil
import subprocess
import sys

class _ProbeOutputParser(HTMLParser):
    """Inspect rendered DOM elements, never matching literal JS source strings."""
    def __init__(self):
        super().__init__()
        self.results = []
        self.in_result = False

    def handle_starttag(self, tag, attrs):
        if tag == "output" and dict(attrs).get("id") == "i18n-browser-result":
            self.results.append("")
            self.in_result = True

    def handle_data(self, data):
        if self.in_result:
            self.results[-1] += data

    def handle_endtag(self, tag):
        if tag == "output":
            self.in_result = False


def browser_probe_result(html):
    parser = _ProbeOutputParser()
    parser.feed(html)
    return parser.results[0].strip() if len(parser.results) == 1 else None


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from index_mpc_library import render_catalog
import serve_mpc

PROBE = r"""
<script>
window.addEventListener('load', () => {
  const probe = document.createElement('span');
  probe.textContent = 'MyCustom-Sample_90bpm.wav';
  document.body.appendChild(probe);
  const controls = [...document.querySelectorAll('button')];
  const recording = controls.find(b => b.textContent.trim() === '⏺ Record backup');
  // Exact cookie value: en-US/es-MX are not accepted by the API's language parser.
  const localeCookie = () => {
    const cookie = document.cookie.split(';').map(value => value.trim())
      .find(value => value.startsWith('beatos_locale='));
    return cookie ? cookie.slice('beatos_locale='.length) : null;
  };
  const expected = [
    ['📻 Módem FSK & Restauración de Backups','📻 FSK modem & backup restore'],
    ['🎹 Mapeo Físico de Teclas EP-133 (12 Teclas por Grupo):','🎹 EP-133 physical key map (12 keys per group):'],
    ['🔄 Ejecutar Reindexación Completa','🔄 Reindex entire library'],
    ['🧹 Optimización para Hardware MPC & SP-404','🧹 MPC & SP-404 maintenance'],
    ['💾 Memoria & Capacidad','💾 Memory & capacity'],
    ['Guardar Ajustes','Save settings'],
    ['🔊 808s & Sub Bajos','🔊 808s & sub bass'],
    ['📂 Explorar Kits','📂 Browse kits'],
    ['🔀 Modo Mover','🔀 Move mode'],
    ['(Banco A: Pads 1 al 16)','(Bank A: pads 1–16)'],
    ['🎛️ Editar Pads en Rack','🎛️ Edit pads in rack'],
    ['⚡ Generar Kit EP-133','⚡ Generate EP-133 kit'],
    ['📁 Revelar en Finder','📁 Show in Finder'],
    ['Haz clic en','Click'],
    ['"Revelar en Finder"','"Show in Finder"'],
    ['Tipo y formato: estimados por nombre y carpeta de instrumento. Tonalidad: etiqueta del archivo; «nota» no confirma mayor/menor. Camelot sólo con modo declarado. Energía: nivel RMS aproximado de tres ventanas PCM (baja < −24, media hasta −12, alta ≥ −12 dBFS); no mide intensidad musical. Sin evidencia se indica sin identificar o sin medir.',
     'Type and format are estimated from filenames and instrument folders. The key label comes from the filename; a note alone does not establish major/minor mode. Camelot requires an explicit mode. Energy estimates RMS from three PCM windows (low < −24, medium to −12, high ≥ −12 dBFS); it does not measure perceived loudness. Missing evidence is shown as unidentified or unmeasured.']
  ];
  const findNode = phrase => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node=walker.nextNode())) if (node.nodeValue.trim() === phrase) return node;
    return null;
  };
  const localeNodes = expected.map(([es,en]) => ({es,en,node:findNode(en)}));
  const attributeExpected = [
    ['title','Restablecer todos los filtros y búsqueda','Reset all filters and search'],
    ['title','Modo Mover: Haz clic en dos pads consecutivamente para intercambiarlos de sitio de forma rápida','Move mode: click two pads in succession to swap their positions quickly'],
    ['aria-label','Reproductor y símbolos de Astro1Deep','Player and Astro1Deep symbols']
  ];
  const localeAttrs = attributeExpected.map(([attr,es,en]) => ({
    attr,es,en,
    node:[...document.querySelectorAll('['+attr+']')].find(el => el.getAttribute(attr) === en)
  }));
  const reporter = document.createElement('output');
  reporter.id = 'i18n-browser-result';
  document.body.appendChild(reporter);
  if (!recording || localeNodes.some(x => !x.node) || localeAttrs.some(x => !x.node)) {reporter.textContent = 'FAIL:missing locale test nodes'; return;}
  try {
    const initialEnglish = document.documentElement.lang === 'en' &&
      localeCookie() === 'en' &&
      recording.textContent.trim() === '⏺ Record backup' &&
      localeNodes.every(x => x.node.nodeValue.trim() === x.en) &&
      localeAttrs.every(x => x.node.getAttribute(x.attr) === x.en);
    setLanguage('es');
    setTimeout(() => {
      const spanishOK = recording.textContent.trim() === '⏺ Grabar backup' &&
        document.documentElement.lang === 'es' &&
        localeCookie() === 'es' &&
        localeNodes.every(x => x.node.nodeValue.trim() === x.es) &&
        localeAttrs.every(x => x.node.getAttribute(x.attr) === x.es);
      setLanguage('en');
      setTimeout(() => {
        const englishOK = recording.textContent.trim() === '⏺ Record backup' &&
          document.documentElement.lang === 'en' &&
          localeCookie() === 'en' &&
          localStorage.getItem('mpc_lang') === 'en' &&
          localeNodes.every(x => x.node.nodeValue.trim() === x.en) &&
          localeAttrs.every(x => x.node.getAttribute(x.attr) === x.en);
        const filenameOK = probe.textContent === 'MyCustom-Sample_90bpm.wav';
        reporter.textContent = initialEnglish && spanishOK && englishOK && filenameOK
          ? 'BEATOS_BROWSER_ES_EN_PASS'
          : 'FAIL:initial=' + initialEnglish + ',es=' + spanishOK + ',en=' + englishOK + ',filename=' + filenameOK;
      }, 100);
    }, 100);
  } catch (error) {reporter.textContent = 'FAIL:' + error.message;}

});
</script>
"""

@contextmanager
def local_site(html):
    # Exercise the actual BeatOS server and catalog route, not an isolated
    # SimpleHTTPRequestHandler test copy of the template.
    with TemporaryDirectory(prefix="beatos-i18n-smoke-") as folder:
        root = Path(folder)
        catalog = root / "BeatOS" / "data" / "catalogo.html"
        catalog.parent.mkdir(parents=True)
        if "</body>" not in html:
            raise RuntimeError("Catalog missing body")
        catalog.write_text(html.replace("</body>", PROBE + "\n</body>", 1), encoding="utf-8")
        server = serve_mpc.HTTPServer(("127.0.0.1", 0), serve_mpc.MPCAudioRequestHandler)
        server.root_dir = str(root)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield "http://127.0.0.1:" + str(server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

def main():
    browser = next((shutil.which(x) for x in ("google-chrome", "chromium", "chromium-browser") if shutil.which(x)), None)
    if not browser:
        raise SystemExit("Chrome/Chromium missing: real-browser verification cannot be marked passed")
    template = (ROOT / "templates" / "catalogo.html").read_text(encoding="utf-8")
    checked_in = (ROOT / "BeatOS" / "data" / "catalogo.html").read_text(encoding="utf-8")
    scenarios = (
        ("generated", render_catalog(template, [], {}), "/"),
        ("checked-in", checked_in, "/BeatOS/data/catalogo.html"),
    )
    for label, html, endpoint in scenarios:
        with local_site(html) as base, TemporaryDirectory(prefix="beatos-chrome-profile-") as profile:
            command = [
                browser, "--headless=new", "--no-sandbox", "--disable-gpu",
                "--disable-dev-shm-usage", "--disable-extensions",
                "--disable-background-networking", "--no-first-run",
                "--user-data-dir=" + profile, "--virtual-time-budget=4500",
                "--dump-dom", base + endpoint
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=50)
            if result.returncode or browser_probe_result(result.stdout) != "BEATOS_BROWSER_ES_EN_PASS":
                detail = result.stdout[-1500:] + "\n" + result.stderr[-900:]
                raise SystemExit("Browser UI locale smoke FAILED (" + label + "): " + detail)
    print("PASS: actual BeatOS HTTP routes (generated and checked-in) switched default EN→ES→EN without touching sample filenames")

if __name__ == "__main__":
    main()

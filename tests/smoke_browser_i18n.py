"""Headless Chrome smoke test for BeatOS ES/EN UI on an actual local HTTP page.

Only reads a synthetic empty catalog. Does not touch real sample libraries or hardware.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from functools import partial
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from index_mpc_library import render_catalog

PROBE = r"""
<script>
window.addEventListener('load', () => {
  const probe = document.createElement('span');
  probe.textContent = 'MyCustom-Sample_90bpm.wav';
  document.body.appendChild(probe);
  const controls = [...document.querySelectorAll('button')];
  const recording = controls.find(b => b.textContent.trim() === '⏺ Grabar backup');
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
    ['(Banco A: Pads 1 al 16)','(Bank A: pads 1–16)']
  ];
  const findNode = phrase => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node=walker.nextNode())) if (node.nodeValue.trim() === phrase) return node;
    return null;
  };
  const localeNodes = expected.map(([es,en]) => ({es,en,node:findNode(es)}));
  const reporter = document.createElement('output');
  reporter.id = 'i18n-browser-result';
  document.body.appendChild(reporter);
  if (!recording || localeNodes.some(x => !x.node)) {reporter.textContent = 'FAIL:missing locale test nodes'; return;}
  try {
    setLanguage('en');
    setTimeout(() => {
      const enOK = recording.textContent.trim() === '⏺ Record backup' &&
          document.documentElement.lang === 'en' &&
          document.cookie.includes('beatos_locale=en') &&
          localeNodes.every(x => x.node.nodeValue.trim() === x.en);
      setLanguage('es');
      setTimeout(() => {
        const esOK = recording.textContent.trim() === '⏺ Grabar backup' &&
            document.documentElement.lang === 'es' &&
            document.cookie.includes('beatos_locale=es') &&
            localeNodes.every(x => x.node.nodeValue.trim() === x.es);
        const fileOK = probe.textContent === 'MyCustom-Sample_90bpm.wav';
        reporter.textContent = enOK && esOK && fileOK
          ? 'BEATOS_BROWSER_ES_EN_PASS' : 'FAIL:en=' + enOK + ',es=' + esOK + ',file=' + fileOK;
      }, 80);
    }, 80);
  } catch (error) {reporter.textContent = 'FAIL:' + error.message;}
});
</script>
"""

@contextmanager
def local_site():
    with TemporaryDirectory(prefix="beatos-i18n-smoke-") as folder:
        template = (ROOT / "templates" / "catalogo.html").read_text(encoding="utf-8")
        html = render_catalog(template, [], {})
        if "</body>" not in html:
            raise RuntimeError("Catalog missing body")
        (Path(folder) / "index.html").write_text(html.replace("</body>", PROBE + "\n</body>", 1), encoding="utf-8")
        handler = partial(SimpleHTTPRequestHandler, directory=folder)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield "http://127.0.0.1:" + str(server.server_port) + "/index.html"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

def main():
    browser = next((shutil.which(x) for x in ("google-chrome", "chromium", "chromium-browser") if shutil.which(x)), None)
    if not browser:
        raise SystemExit("Chrome/Chromium missing: real-browser verification cannot be marked passed")
    with local_site() as url, TemporaryDirectory(prefix="beatos-chrome-profile-") as profile:
        command = [
            browser, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--disable-dev-shm-usage", "--disable-extensions",
            "--disable-background-networking", "--no-first-run",
            "--user-data-dir=" + profile, "--virtual-time-budget=4500",
            "--dump-dom", url
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=50)
        if result.returncode or "BEATOS_BROWSER_ES_EN_PASS" not in result.stdout:
            detail = result.stdout[-1500:] + "\n" + result.stderr[-900:]
            raise SystemExit("Browser UI locale smoke FAILED: " + detail)
        print("PASS: real headless Chrome toggled ES→EN→ES over HTTP and preserved sample name")

if __name__ == "__main__":
    main()

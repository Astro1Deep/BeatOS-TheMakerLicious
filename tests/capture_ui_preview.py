"""Capture authentic BeatOS catalog screenshots in headless Chromium.

Uses the actual rendered HTML template, synthetic metadata only and a loopback web server.
No personal media, audio, credentials, or hardware connections are needed.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json
import re
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets" / "screenshots"

import sys
sys.path.insert(0, str(ROOT))
from index_mpc_library import render_catalog


def synthetic_records():
    """Match the 12-column BeatOS browser contract; filenames are fictional."""
    sounds = [
        ("DEMO_Kick_BoomBap_88BPM.wav", "KICK", "ONE_SHOT", 88),
        ("DEMO_Snare_Tape_88BPM.wav", "SNARE", "ONE_SHOT", 88),
        ("DEMO_HiHat_Dust_88BPM.wav", "HIHAT", "ONE_SHOT", 88),
        ("DEMO_Break_Jungle_172BPM.wav", "LOOP", "LOOP", 172),
        ("DEMO_Bass_Neuro_174BPM.wav", "BASS", "ONE_SHOT", 174),
        ("DEMO_Rhodes_Jazzy_84BPM.wav", "KEYS", "LOOP", 84),
        ("DEMO_Perc_HandDrum_130BPM.wav", "PERCUSSION", "ONE_SHOT", 130),
        ("DEMO_Pad_Ambient_70BPM.wav", "PAD", "LOOP", 70),
        ("DEMO_Vocal_Chop_140BPM.wav", "VOCAL", "ONE_SHOT", 140),
        ("DEMO_808_Sub_140BPM.wav", "BASS", "ONE_SHOT", 140),
        ("DEMO_Kick_DnB_174BPM.wav", "KICK", "ONE_SHOT", 174),
        ("DEMO_Snare_DnB_174BPM.wav", "SNARE", "ONE_SHOT", 174),
        ("DEMO_HiHat_UKG_132BPM.wav", "HIHAT", "LOOP", 132),
        ("DEMO_Clap_Drill_140BPM.wav", "CLAP", "ONE_SHOT", 140),
        ("DEMO_FX_Riser_140BPM.wav", "FX", "ONE_SHOT", 140),
        ("DEMO_Vinyl_Texture_80BPM.wav", "TEXTURE", "LOOP", 80),
    ]
    return [
        [filename, kind, fmt, "DEMO", "Synthetic Samples", bpm,
         "C minor", "5A", "GROOVE", 0.08 + i * 0.01,
         "demo_media/" + filename, "demo_media/" + filename]
        for i, (filename,kind,fmt,bpm) in enumerate(sounds)
    ]


def build_page(language, tab):
    template=(ROOT / "templates" / "catalogo.html").read_text(encoding="utf-8")
    rendered=render_catalog(template, synthetic_records(), {"projects":[], "expansions":[]})
    # The release installs assets under BeatOS/docs; the source checkout keeps
    # those identical image files under docs/. Remap only preview URLs.
    rendered=rendered.replace('src="BeatOS/docs/assets/', 'src="docs/assets/')
    if language not in ("en","es") or tab not in ("samples","rack","hero"):
        raise ValueError("Invalid preview configuration")
    # Locale preference is set before BeatOS reads it. No navigation to remote URLs.
    setup=("<script>try{localStorage.setItem('mpc_lang'," +
           json.dumps(language) + ");}catch(e){}</script>")
    rendered=rendered.replace("<head>","<head>\n"+setup,1)
    preview_script=("""
<script>
document.addEventListener('DOMContentLoaded', () => {
  if ("RACK" === "rack") {
    const button=document.getElementById('tabBtnRack');
    switchTab('tab-rack', button);
  }
  const badge=document.createElement('div');
  badge.textContent='DEMO · Synthetic sample data · No connected hardware';
  Object.assign(badge.style,{
    position:'fixed',right:'18px',bottom:'18px',background:'rgba(10,12,22,.92)',
    color:'#facc15',padding:'9px 13px',zIndex:'10000',borderRadius:'8px',
    border:'1px solid #6b7280',fontFamily:'Arial,sans-serif',fontSize:'12px'
  });
  document.body.append(badge);
});
</script>
""").replace('"RACK"',json.dumps(tab))
    if tab != "hero":
        # A focused screenshot of the real workflow: only the tall decorative
        # header is hidden; the toolbar, controls and data are untouched.
        rendered=rendered.replace("</head>",
            "<style>header.beatos-brand,section.hero-banner{display:none!important}</style></head>",1)
    rendered=rendered.replace("</body>",preview_script+"</body>",1)
    return rendered


@contextmanager
def preview_server():
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            from urllib.parse import urlsplit
            endpoint=urlsplit(self.path).path
            # The installed distribution uses BeatOS/docs/assets/ while the
            # source checkout stores the exact same originals in docs/assets/.
            if endpoint.startswith("/BeatOS/docs/assets/"):
                self.path=self.path[len("/BeatOS"):]
                return super().do_GET()
            if endpoint in ("/api/status", "/api/po33_backups"):
                import json
                data=({"status":"online","root_dir":"DEMO_LIBRARY (synthetic, read-only)",
                       "card_mounted":False,"disk_free_gb":12.0,"disk_total_gb":24.0}
                      if endpoint=="/api/status" else {"success":True,"backups":[]})
                body=json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()
    handler=lambda *args, **kwargs: QuietHandler(*args,directory=str(ROOT),**kwargs)
    server=ThreadingHTTPServer(("127.0.0.1",0),handler)
    thread=Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:"+str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def save_preview(browser, url, destination, label):
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="beatos-preview-chrome-") as profile:
        command=[
            browser,"--headless=new","--no-sandbox","--disable-gpu","--disable-dev-shm-usage",
            "--no-first-run","--disable-background-networking","--disable-extensions",
            "--hide-scrollbars","--window-size=1500,1050",
            "--force-device-scale-factor=1","--virtual-time-budget=5500",
            "--user-data-dir="+profile, "--screenshot="+str(destination),url,
        ]
        response=subprocess.run(command,capture_output=True,text=True,timeout=70)
        if response.returncode or not destination.is_file():
            raise RuntimeError(label+" failed: "+response.stderr[-1300:])
    raw=destination.read_bytes()
    if raw[:8]!=b"\x89PNG\r\n\x1a\n" or len(raw)<12000:
        raise RuntimeError(label+" missing or empty PNG output")
    width,height=struct.unpack(">II",raw[16:24])
    if width<1100 or height<700:
        raise RuntimeError(label+" screenshot dimensions invalid")
    print(f"PASS {label}: {width}x{height}, {len(raw)} bytes")


def main():
    browser=next((shutil.which(name) for name in
                  ("google-chrome","chromium","chromium-browser") if shutil.which(name)),None)
    if not browser:
        raise SystemExit("Chrome/Chromium unavailable; screenshot is NOT verified")
    items=[
        ("beatos-hero-en.png","en","hero"),
        ("beatos-overview-en.png","en","samples"),
        ("beatos-overview-es.png","es","samples"),
        ("beatos-rack-en.png","en","rack"),
    ]
    with preview_server() as base:
        for filename, lang,tab in items:
            tmp=ROOT/("__beatos_visual_preview_"+lang+"_"+tab+".html")
            if tmp.exists():
                raise RuntimeError("Preview staging file already exists: "+str(tmp))
            try:
                tmp.write_text(build_page(lang,tab),encoding="utf-8")
                save_preview(browser,base+"/"+tmp.name,OUTPUT/filename,filename)
            finally:
                tmp.unlink(missing_ok=True)

if __name__=="__main__":
    main()

"""Exercise a large synthetic sample catalog in a real browser engine."""
import argparse
import json
import platform
from time import perf_counter

from playwright.sync_api import sync_playwright

from smoke_browser_i18n import ROOT, local_site, render_catalog


def verify(engine, count):
    filename = "Audición #única_90bpm.wav"
    records = [
        (f"Kick_{index:06}.wav", "KICK", "ONE_SHOT", "Demo", "Pack",
         90, "-", "-", "GROOVE", 0.1, f"Samples/Kick_{index:06}.wav", index + 1)
        for index in range(count - 1)
    ]
    records.append((filename, "KICK", "ONE_SHOT", "Demo", "Pack",
                    90, "-", "-", "GROOVE", 0.1, filename, count))
    template = (ROOT / "templates" / "catalogo.html").read_text(encoding="utf-8")
    html = render_catalog(template, records, {"total_samples": count})
    with local_site(html, filename) as base, sync_playwright() as playwright:
        browser = getattr(playwright, engine).launch()
        page = browser.new_page(locale="en-US", viewport={"width": 1440, "height": 900})
        start = perf_counter()
        page.goto(base, wait_until="domcontentloaded", timeout=20000)
        probe = page.locator("#i18n-browser-result")
        probe.wait_for(state="attached", timeout=10000)
        page.wait_for_function("document.querySelector('#i18n-browser-result')?.textContent.length > 0")
        assert probe.text_content() == "BEATOS_BROWSER_ES_EN_PASS", probe.text_content()
        page.locator("#tabBtnSamples").click()
        rows = page.locator("#tableBody tr")
        rows.first.wait_for(state="visible")
        ready_ms = round((perf_counter() - start) * 1000)
        assert rows.count() == 60
        page.locator("#btnNext").click()
        assert page.locator("#pageIndicator").inner_text().startswith("2 /")
        search = page.locator("#searchInput")
        start = perf_counter()
        search.fill("Audición #única")
        rows.get_by_text(filename, exact=True).wait_for(state="visible", timeout=5000)
        filter_ms = round((perf_counter() - start) * 1000)
        assert rows.count() == 1
        play = rows.get_by_role("button", name="▶ Play")
        # Activate the accessible control with the keyboard and verify decoded playback.
        play.focus()
        play.press("Enter")
        page.wait_for_function("document.querySelector('#audioPlayer').currentTime > 0", timeout=7000)
        print(json.dumps({"system": platform.system(), "engine": engine,
                          "browser_version": browser.version, "samples": count,
                          "http_html_size_bytes": len(html.encode()),
                          "ready_after_locale_probe_ms": ready_ms,
                          "filter_ms": filter_ms, "visible_rows_per_page": 60,
                          "keyboard_preview": True}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=("chromium", "firefox", "webkit"))
    parser.add_argument("--samples", type=int, choices=(29260, 70142), default=70142)
    args = parser.parse_args()
    verify(args.engine, args.samples)

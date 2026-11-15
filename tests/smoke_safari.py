"""Verify the catalog in shipping Safari on a macOS desktop runner."""
import json
from time import perf_counter

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from smoke_browser_i18n import ROOT, local_site, render_catalog


def main():
    sample_count = 70142
    preview = "Audición #única_90bpm.wav"
    records = [
        (f"Kick_{index:06}.wav", "KICK", "ONE_SHOT", "Demo", "Pack", 90, "-", "-",
         "GROOVE", 0.1, f"Samples/Kick_{index:06}.wav", index + 1)
        for index in range(sample_count - 1)
    ]
    records.append((preview, "KICK", "ONE_SHOT", "Demo", "Pack", 90, "-", "-",
                    "GROOVE", 0.1, preview, sample_count))
    template = (ROOT / "templates" / "catalogo.html").read_text(encoding="utf-8")
    html = render_catalog(template, records, {"total_samples": sample_count})
    with local_site(html, preview) as base, webdriver.Safari() as browser:
        browser.set_page_load_timeout(30)
        browser.set_window_size(1440, 900)
        wait = WebDriverWait(browser, 40)
        start = perf_counter()
        browser.get(base + "/?nativeSafari=1")
        probe = wait.until(lambda driver: driver.execute_script(
            "return document.getElementById('i18n-browser-result')?.textContent"))
        assert probe == "BEATOS_BROWSER_ES_EN_PASS", probe
        browser.find_element(By.ID, "tabBtnSamples").click()
        rows = browser.find_elements(By.CSS_SELECTOR, "#tableBody tr")
        ready_ms = round((perf_counter() - start) * 1000)
        assert len(rows) == 60
        browser.find_element(By.ID, "btnNext").click()
        assert browser.find_element(By.ID, "pageIndicator").text.startswith("2 /")
        field = browser.find_element(By.ID, "searchInput")
        start = perf_counter()
        field.send_keys("Audición #única")
        wait.until(lambda driver: preview in driver.find_element(By.ID, "tableBody").text)
        filter_ms = round((perf_counter() - start) * 1000)
        [row] = browser.find_elements(By.CSS_SELECTOR, "#tableBody tr")
        play = row.find_element(By.CSS_SELECTOR, ".btn-play")
        play.send_keys(Keys.ENTER)
        wait.until(lambda driver: driver.execute_script(
            "return document.getElementById('audioPlayer').currentTime > 0"))
        print(json.dumps({"browser": browser.capabilities["browserName"],
                          "browser_version": browser.capabilities["browserVersion"],
                          "samples": sample_count, "ready_after_locale_probe_ms": ready_ms,
                          "filter_ms": filter_ms, "visible_rows_per_page": 60,
                          "keyboard_preview": True}))


if __name__ == "__main__":
    main()

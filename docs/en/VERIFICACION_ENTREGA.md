# BeatOS delivery, integrity and verification

[Español](../VERIFICACION_ENTREGA.md) · [English installation](../../GUIA_INSTALACION_EN.md) · [Build/test commands](REFERENCIA_TECNICA.md#8-build-and-regression-checks)

BeatOS **3.8.0** has an organized release ZIP with an empty catalog, sanitized MPC templates and a member-level SHA-256 manifest. The source ZIP builder uses an explicit file allowlist; it does **not** package private sample libraries, live SQLite indexes, personal backups or account configurations.

## Stable release versus current source

The [latest stable release asset](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases/latest) is **not automatically rebuilt** when GitHub's `main` branch changes. The bilingual documentation and UI patches may exist only in current source or a **GitHub Actions development ZIP** until a newly tagged stable release is published. Do not advertise an older release archive as containing later improvements.

When downloading a stable asset, compare its SHA-256 checksum to the separate checksum file. On macOS `shasum -a 256 -c BeatOS-3.8.0-SHA256SUMS.txt` works from the download directory; on Linux, `sha256sum -c`; PowerShell provides `Get-FileHash <archive> -Algorithm SHA256`. Checksums prove byte-for-byte consistency with a stated digest, not independent author identity.

## Automated validation

The [GitHub Actions runs](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/actions) can report: Python 3.11/3.14 regression suite, JavaScript rack/audio/interface tests, bilingual ES/EN regression checks, documentation link validation, clean ZIP packaging, and native Windows installation using a synthetic sample library. A separate browser-smoke job exercises ES→EN→ES in a **headless Chrome** page served via local HTTP. Check the **exact latest commit's run result** before declaring those tests passed.

The runtime tests use synthetic audio, not a physically connected MPC, Maschine, SP-404, PO-33 or EP-133. They cannot certify firmware compatibility, every browser or interface language string, or the validity of recorded FSK modem payloads.

## Updating safely

Install in a fresh folder; preserve your musical library, projects and backed-up PO WAVs independently. Reindex against the intended library path; then **reload the entire browser page** after updating application code, which discards any in-memory unexported rack edits. An in-page “Reload projects” operation does not update old JavaScript.

The Windows CI installer test covers archive extraction, paths with spaces/accents, synthetic media indexing, local HTTP preview and sample-kit export/reimport; it is **not** a native graphical UI certification or a Windows ARM/hardware test.
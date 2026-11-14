# BeatOS — Discoverability, SEO and search-indexing checklist (ES / EN)

## What is currently true

- Official project: **Astro1Deep/BeatOS-TheMakerLicious**. Avoid confusing it with other projects named **BeatOS**.
- GitHub repository description, homepage URL (`https://astro1deep.github.io/BeatOS-TheMakerLicious/`), and **20 repository topics** are active: `akai-mpc`, `audio-tools`, `beatmaking`, `boombap`, `drum-kits`, `ep-133`, `lofi-hiphop`, `maschine`, `mpc`, `mpc-sample`, `music-production`, `po-33`, `pocket-operator`, `python`, `sample-library`, `sampling`, `sampqol`, `sp-404`, `sp404mk2`, `teenage-engineering`.
- GitHub Pages is configured to serve from `main` → `/docs` at `https://astro1deep.github.io/BeatOS-TheMakerLicious/`.
- The latest stable ZIP (`v3.8.0`) can be older than `main`; point testers who want the latest **Cerebro OS DSP / SampQOL OS / Legacy .PGM / Official Expansion Builder** features to clone/checkout `main` or wait for the next release tag.
- See the ready-to-use community & developer outreach templates in [KIT_DIFUSION_Y_COMUNIDAD.md](KIT_DIFUSION_Y_COMUNIDAD.md).

## Search Console & Webmaster Indexing Checklist

1. Verify `https://astro1deep.github.io/BeatOS-TheMakerLicious/` in **Google Search Console** (HTML tag or URL-prefix property once live) and submit `https://astro1deep.github.io/BeatOS-TheMakerLicious/sitemap.xml`.
2. Verify and submit the same sitemap in **Bing Webmaster Tools** (which also feeds DuckDuckGo/Yahoo organic search).
3. Inspect indexing with `site:astro1deep.github.io/BeatOS-TheMakerLicious/` and track clicks in Search Console. Submitting sitemaps accelerates discovery without guaranteeing immediate ranking.

## Accurate search phrases and topics

Use natural-language phrasing in the page and README, not massive hashtag repetition:

**English:** sample browser for beatmakers; 16-pad drum kit builder; Akai MPC project inspector; MPC XPM Drum export; Roland SP-404MKII WAV conversion; Native Instruments Maschine sample kit; PO-33 sample reel; EP-133 sample transfer; music production and sampling; local music library.

**Español:** biblioteca de samples para productores; explorador de samples; creación de drum kits; rack de 16 pads; inspector de proyectos Akai MPC; exportación WAV SP-404; samples para Maschine; PO-33 Pocket Operator; EP-133 K.O. II; beatmaking y sampling.

Potential additional **GitHub Topics** (optional, subject to the platform's topic limit and legitimacy): `sp404mk2`, `pocket-operator`, `teenage-engineering`, `beatmaker`, `drum-machine`, `music-producer`. Topics matter more for GitHub discovery than inserting #hashtags into README prose. The existing topics already cover most major hardware families.

Useful social tags for voluntary announcements (not a GitHub-search guarantee): **#BeatOS #TheMakerLicious #Beatmaking #MusicProduction #Sampling #AkaiMPC #SP404MKII #Maschine #PocketOperator #PO33 #EP133**.

## AI discovery

Use crawlable EN/ES documentation, precise capability descriptions, permanent URLs, version history and tests. `docs/llms.txt` is included as a **supplementary experimental pointer**, not as a mandated or universally supported AI indexing standard. Do not assert or imply that models automatically ingest each GitHub commit or that this file grants search ranking.

## Verification / limits

Documentation, metadata, schema markup and sitemaps can help crawlers understand a product. They do **not** guarantee indexing, search rank, inclusion in AI answers, endorsements, or certified support for all sampler firmwares.

Official references:
- GitHub topics: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics
- GitHub Pages: https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site
- Google indexing: https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl
- Search Console URL inspection: https://support.google.com/webmasters/answer/9012289

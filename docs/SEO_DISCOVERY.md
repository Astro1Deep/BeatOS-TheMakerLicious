# BeatOS — Discoverability, SEO and search-indexing checklist (ES / EN)

## What is currently true

- Official project: **Astro1Deep/BeatOS-TheMakerLicious**. Avoid confusing it with other projects named **BeatOS**.
- GitHub repository description and 14 topics already exist (observed 30 October 2026). The topics include: `akai-mpc`, `audio-tools`, `beatmaking`, `beatos`, `drum-kits`, `ep-133`, `maschine`, `mpc`, `music-production`, `po-33`, `python`, `sample-library`, `sampling`, `sp-404`.
- GitHub searches can discover terms in the repository **name, description, topics and README**. Keep capability claims accurate.
- GitHub Pages **is not enabled at the time this landing page is prepared**. The `docs/index.html` and `docs/index-es.html` files do not become a live site until Pages deployment is configured.
- The latest stable ZIP can be older than `main`. Do not advertise a development build as an already published stable release.

## Website publish and index procedure

1. In the repository **Settings → Pages**, set **Build and deployment → Deploy from a branch**, select **main** and **/docs**, then Save. GitHub Pages should publish at `https://astro1deep.github.io/BeatOS-TheMakerLicious/` (subject to account and deployment settings).
2. Wait for a successful Pages deployment and *open the actual EN and ES URLs*. Check images, screenshots, CTA links, favicon, mobile layout, alternate `hreflang` links, and the sitemap.
3. In **Google Search Console**, verify ownership of the published URL/property. Inspect the live page, request indexing when eligible, and submit `https://astro1deep.github.io/BeatOS-TheMakerLicious/sitemap.xml`. Submitting requests is not a guarantee of indexing or placement.
4. In **Bing Webmaster Tools**, use URL Inspection and submit the same sitemap after the Pages site is live and verifiable.
5. Once Pages is live, set the repository **About → Website** URL to `https://astro1deep.github.io/BeatOS-TheMakerLicious/`. The connected GitHub tools do not currently expose repository About/Pages editing, so this setting needs an authorized UI action.
6. Inspect indexing later with `site:astro1deep.github.io/BeatOS-TheMakerLicious/` and Search Console. Public search results alone can be incomplete or delayed.

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

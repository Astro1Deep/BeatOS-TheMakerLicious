# BeatOS artwork, voluntary support and audio format caveats

[Español](../INSTRUMENTOS_Y_APOYO.md) · [English manual](MANUAL_COMPLETO.md) · [Hardware support](COMPATIBILIDAD_HARDWARE.md)

The application's brand header is real browser text: **BeatOS · The MakerLicious · universal beatmaker station**. The original blueprint banner, theme variations and decorative patchbay artwork are preserved. The **Expand banner** control changes presentation only. Decorative labels inside original images are **not technical specifications**; uncertain details in artwork must be checked against the written hardware compatibility guide.

No newly generated artwork replaces the original source images in this version. Avoid inventing technical data in place of an editable original.

## Voluntary support

The app provides voluntary support links to [Ko-fi / Astro1Deep](https://ko-fi.com/astro1deep) and [GitHub Sponsors](https://github.com/sponsors/Astro1Deep). Each external service determines accepted payment amounts, currency and minimums; BeatOS does not configure payment settings, charge users, or require a donation to export. Documentation cannot guarantee a particular 1 EUR/USD amount will be accepted. An unverified PayPal.Me link is not treated as a confirmed payment route.

## Mute groups and delivery formats

The default rack mute scheme is **kick 1**, **hi-hat 2**, **snare 3**, others **0** (unrestricted); imported explicit groups, including 0, are respected. Each positive group silences other pad voices in that group, while different groups can overlap when the playback engine supports it.

MPC exports write implemented group parameters to XPM/XPJ structures; Maschine produces WAV and a **manual JSON mapping**, not a native MXGRP group; EP-133 produces WAV/map/ZIP, not a native backup; Roland SP exports audio without a native program; a Pocket Operator sample reel contains audio, not mute-group metadata.

Only the **first active sample layer** of the currently visible bank is previewed/exported. Structural file tests never replace a physical sampler load and save/reopen test.
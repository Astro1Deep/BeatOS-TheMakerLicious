# Astro1Deep — Ecosystem palette & theme

![Astro1Deep banner](../assets/branding/creator/astro1deep-banner.png)

**Visual direction: chrome obsidian.** The banner's dark, reflective emblem becomes a restrained monochrome interface: deep charcoal surfaces, cool-metal accents, and deliberately bright text. Keep the chrome effect for the mark; body copy stays flat and readable.

## Core palette

| Token | Color | Use |
|---|---|---|
| `void` | `#090A0C` | Deep background, cover and quiet visual space. |
| `canvas` | `#101216` | Main page and application background. |
| `surface` | `#171B20` | Cards, panels and navigation. |
| `raised` | `#20252B` | Elevated controls, fields and selected surfaces. |
| `line` | `#3C444E` | Dividers and non-interactive outlines. |
| `text` | `#F2F4F7` | Primary copy, headings and important controls. |
| `text-muted` | `#B8C0CA` | Secondary copy, metadata and descriptions. |
| `chrome` | `#C7D1DC` | Metallic accent for icons, links, selection and brand details. |
| `focus` | `#AFC2D4` | Visible keyboard focus and accessible interaction states. |

## Status colors

| State | Color | Use |
|---|---|---|
| Success | `#8ED8B3` | Confirmation and completed operations. |
| Warning | `#E9C879` | Caution, pending changes and warnings. |
| Error | `#FF858C` | Errors and destructive actions; never as the only signal. |
| Information | `#AFC2D4` | Help, data and neutral notifications. |

Pair status colors with meaningful text or icons; color is never the sole indicator.

## Verified contrast

Ratios use the WCAG relative-luminance formula. Every listed text combination exceeds **7:1**, above the **4.5:1** minimum for normal text.

| Foreground / background | Contrast |
|---|---:|
| `text` on `void` | 17.97:1 |
| `text-muted` on `void` | 10.78:1 |
| `chrome` on `surface` | 11.19:1 |
| `focus` on `void` | 10.84:1 |
| `success` on `void` | 11.91:1 |
| `warning` on `void` | 12.26:1 |
| `error` on `void` | 8.47:1 |
| `void` on a `chrome` button | 12.81:1 |

## CSS tokens

```css
:root {
  color-scheme: dark;
  --atd-void: #090a0c;
  --atd-canvas: #101216;
  --atd-surface: #171b20;
  --atd-raised: #20252b;
  --atd-line: #3c444e;
  --atd-text: #f2f4f7;
  --atd-text-muted: #b8c0ca;
  --atd-chrome: #c7d1dc;
  --atd-focus: #afc2d4;
  --atd-success: #8ed8b3;
  --atd-warning: #e9c879;
  --atd-danger: #ff858c;
  --atd-info: #afc2d4;
}

body {
  background: var(--atd-canvas);
  color: var(--atd-text);
}

:focus-visible {
  outline: 2px solid var(--atd-focus);
  outline-offset: 3px;
}

.button-primary {
  color: var(--atd-void);
  background: var(--atd-chrome);
}
```

## Usage principles

- **Brand:** place the metallic emblem on `void` or `canvas`; reserve its highlights and reflections for the logo and cover art.
- **Readability:** use `text` and `text-muted` for copy. Do not use dark metallic gray for text or apply chrome effects to paragraphs.
- **Hierarchy:** alternate `canvas`, `surface` and `raised` to distinguish areas; favor restrained borders, generous spacing and subtle shadows.
- **Accent:** use `chrome` for links, selection and primary actions, not every surface. Use dark text on chrome buttons.
- **Interaction:** retain visible keyboard focus and distinct hover/pressed states. Pair success and error colors with an icon or label.
- **GitHub:** use `void` for the banner or focused brand blocks. Keep README body copy on GitHub's normal page surface, with metallic accents in links, headings and badges rather than turning the whole README black.
- **Light-mode resilience:** this defines the ecosystem's dark identity; documents must remain understandable when GitHub renders them in a light theme and must not rely on background images to convey meaning.

**Result:** a moody, monochrome and metallic identity, with a separate interface layer designed to remain clear and legible.

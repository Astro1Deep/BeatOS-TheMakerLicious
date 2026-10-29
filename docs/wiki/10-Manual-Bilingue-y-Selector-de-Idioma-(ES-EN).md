# 🌐 10. Manual Bilingüe y Selector de Idioma (ES / EN) / Bilingual Manual

Este proyecto cuenta con soporte bilingüe nativo (**Español** e **Inglés**) tanto en la interfaz de usuario del catálogo interactivo como en la documentación técnica y las utilidades de consola.

---

## 🇪🇸 Modo Español (Por Defecto)

La interfaz en español proporciona terminología clara para productores hispanohablantes:
* Métricas del catálogo y de la tarjeta de memoria.
* Menú del instalador y comandos del terminal (`./install.sh`).
* Pestañas del explorador sonoro, proyectos y expansiones.
* Controles del rack de 16 pads, afinación, choke groups y exportación hardware.

---

## 🇬🇧 English Mode (International Beatmaker Workflow)

Clicking the **`🌐 ES | EN`** button in the top metrics bar instantly switches the entire user interface to English without reloading the page:

### Key Terminology Translation

| Español (ES) | English (EN) | Description |
| :--- | :--- | :--- |
| **Explorador de Samples** | **Sample Explorer** | High-performance search and preview engine for 34,000+ samples. |
| **Beatmaker Kit Rack** | **Beatmaker Kit Rack** | Interactive 16-pad drum rack with pad editor and hardware export. |
| **Selector de Pad** | **Pad Selector Dock** | Target pad assignment bar for one-click catalog sample mapping. |
| **Expansiones Oficiales** | **Official Expansions** | Native Akai MPC expansions with cover art and program details. |
| **Proyectos Standalone** | **Standalone Projects** | Integrity checker for `.xpj` projects and `_[ProjectData]` folders. |
| **Choke / Mute Group** | **Choke / Mute Group** | Mutual pad silencing for hi-hats and 808 bass lines. |
| **Limpiar Filtros** | **Clear Filters** | Instant filter reset for BPM, format, category and key. |

### Persistence & Configuration
The chosen language is automatically stored in the browser's `localStorage` (`mpc_lang`). Subsequent visits will remember your preferred language.

The web catalog uses its embedded translation dictionary and stores the selected language in localStorage. The repository also keeps the historical [`language_config.json`](../../language_config.json) reference:

```json
{
  "default": "es",
  "autoDetect": true,
  "supported": ["es", "en"]
}
```

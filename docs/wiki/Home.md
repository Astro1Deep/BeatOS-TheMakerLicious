<p align="center"><img src="../assets/branding/creator/eye-mirror-wide.png" alt="Símbolo de Astro1Deep" width="360"></p>

# BeatOS

**The MakerLicious**

[universal beatmaker station]

![Hardware de BeatOS](../assets/branding/user_blueprint_sheet_dark_4k.jpg)

BeatOS se ejecuta en el ordenador y combina un catálogo de samples propios, un inspector de proyectos MPC y un rack de 16 pads. Esta guía describe funciones verificadas en el código y sus límites; la aplicación no instala firmware en los samplers.

[Descargar instalador estable](https://github.com/Astro1Deep/mpc-sample-database/releases/latest) · [Instalación paso a paso](../../GUIA_INSTALACION.md) · [Compatibilidad y destinos](../../README.md#rack-y-destinos)

| Capítulo | Contenido |
| --- | --- |
| [1. Instalación](01-Instalacion-y-Puesta-en-Marcha.md) | ZIP organizado, código fuente, requisitos y arranque. |
| [2. Organización de la biblioteca](02-Organizacion-MicroSD-para-MPC.md) | Código y estado bajo BeatOS/, rutas musicales conservadas. |
| [3. Identificación de audio](03-Taxonomia-y-Deteccion-de-Audio.md) | Tipo por etiquetas, tonalidad declarada y nivel RMS aproximado. |
| [4. Proyectos MPC](04-Auditoria-de-Proyectos-MPC-(xpj).md) | Referencias, pistas de batería, bancos y edición de copias. |
| [5. Expansiones](05-Expansiones-Oficiales-Akai.md) | Programas XPM, proyectos XPJ, demos, samples y carátulas. |
| [6. Catálogo y preescucha](06-Catalogo-Web-y-Audio-Player.md) | Vista por HTTP, recarga y errores de conexión. |
| [7. SQLite](07-Consultas-Avanzadas-SQLite.md) | Esquema y consultas sobre la base de tu biblioteca. |
| [8. Rack y exportación](08-Universal-Hardware-Beatmaker-Rack-(MPC-Maschine-SP404-PO33).md) | Ajustes y alcance real de cada destino. |
| [9. PO-33, PO-133 y EP-133](09-Pocket-Operator-PO-33-KO-Studio-y-FSK-Modem.md) | Reels, WAV de intercambio e inspección limitada de respaldos. |
| [10. Idiomas](10-Manual-Bilingue-y-Selector-de-Idioma-(ES-EN).md) | Traducción parcial de la interfaz y preferencias del navegador. |
| [11. Discos e integraciones](11-Auto-Reconocimiento-y-Onboarding-de-Discos.md) | Biblioteca elegida e integración opcional con Cerebro. |

## Comprobar una instalación

La entrega comienza vacía. Indexa tus archivos, abre la interfaz conectada y comprueba la ruta activa. En Expansiones, «Ver proyectos» abre los XPJ de ese paquete; «Editar copia en rack» carga su pista de batería y muestra el banco visible. Los originales permanecen en su ubicación.

Las pruebas automatizadas cubren los formatos generados, navegación y fixtures de audio. No equivalen a una certificación de todos los modelos, navegadores o versiones de firmware. Consulta los límites antes de exportar.

## English

BeatOS is a desktop-hosted sample catalog, MPC project inspector and 16-pad kit rack. Download the release attachment for the organized installer and run `python3 BeatOS/installer.py` (`py BeatOS/installer.py` on Windows). Source checkouts keep the scripts at repository root. Index your own library, then serve that same location. Some labels and the terminal remain in Spanish. Native project playback, effects and multilayer editing require the manufacturer's software or hardware.

Creado por [Astro1Deep](https://github.com/Astro1Deep). Licencia [CC BY-NC-ND 4.0](../../LICENSE). [Apoyar el desarrollo](../../README.md#apoyo).

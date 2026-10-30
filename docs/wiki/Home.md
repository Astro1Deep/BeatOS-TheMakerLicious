<p align="center"><img src="../assets/branding/creator/astro1deep-banner.png" alt="Ojo y lágrima de Astro1Deep — BeatOS" width="100%"></p>

# BeatOS

**Idioma:** Español · [English documentation / Guías en inglés](Home_EN.md) · [Manual en inglés](../en/MANUAL_COMPLETO.md)

**The MakerLicious**

[universal beatmaker station]

BeatOS se ejecuta en el ordenador para explorar samples propios, preparar kits en un rack de 16 pads y exportarlos a Akai MPC, Native Instruments Maschine, Roland SP-404MK2, SP-404A/SX, PO-33/PO-133 y EP-133 K.O. II. Puedes trabajar desde muestras sueltas; la importación e inspección de XPJ/XPM es una vía adicional del ecosistema Akai.

El recorrido es biblioteca → rack → destino → archivos exportados → carga en el equipo o software. [Sigue el primer kit paso a paso](../../README.md#de-la-biblioteca-al-aparato-primer-kit) y consulta los formatos y límites antes de transferirlo. La aplicación no instala firmware en los samplers.

[Descargar instalador estable](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases/latest) · [Instalación paso a paso](../../GUIA_INSTALACION.md) · [Compatibilidad y destinos](../../README.md#rack-y-destinos)

## Manual completo y compatibilidad

[Manual por módulos](../MANUAL_COMPLETO.md) · [Hardware, modelos y formatos MPC](../COMPATIBILIDAD_HARDWARE.md) · [Referencia técnica y API](../REFERENCIA_TECNICA.md)

El XPJ exportado por BeatOS procede de una plantilla AC50/Sample. No se presenta como un proyecto genérico idéntico para Sample, One y Live; consulta los procedimientos y requisitos de versión en la matriz.

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

BeatOS is a desktop-hosted sample library and 16-pad kit workstation with export paths for Akai MPC, Native Instruments Maschine, Roland SP-404MK2, SP-404A/SX, PO-33/PO-133 and EP-133 K.O. II. Start from loose samples or import a copy of an MPC drum kit, then export the required format and load it into the destination device or software. Some exports require manual sample assignment; they are not native project backups. Download the release attachment for the organized installer and run `python3 BeatOS/installer.py` (`py BeatOS/installer.py` on Windows). Source checkouts keep the scripts at repository root. Index your own library, then serve that same location. Some labels and the terminal remain in Spanish. Native project playback, effects and multilayer editing require the manufacturer's software or hardware.

Creado por [Astro1Deep](https://github.com/Astro1Deep). Licencia [CC BY-NC-ND 4.0](../../LICENSE). [Apoyar el desarrollo](../../README.md#apoyo).

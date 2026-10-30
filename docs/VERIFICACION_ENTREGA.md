# Comprobación de la entrega

**Idioma:** Español · [English version](en/VERIFICACION_ENTREGA.md)

BeatOS 3.8.0 incluye un catálogo vacío, plantillas MPC saneadas y un manifiesto SHA-256 dentro de BeatOS/. El ZIP se construye desde una lista explícita; no incluye bibliotecas musicales, bases SQLite, backups ni configuraciones del autor.

## Descarga e integridad

Descarga el ZIP adjunto a la [versión estable](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases/latest) y su archivo de sumas. «Source code» es el repositorio de desarrollo, no el instalador organizado. En macOS, desde la carpeta de descargas:

```bash
shasum -a 256 -c BeatOS-3.8.0-SHA256SUMS.txt
```

En Linux usa `sha256sum -c` con ese mismo archivo. En PowerShell, `Get-FileHash .\BeatOS-3.8.0.zip -Algorithm SHA256` permite comparar el resultado con la suma publicada. Una suma comprueba integridad respecto a ese archivo; no es una firma criptográfica del autor.

## Pruebas realizadas

- Suite Python de regresión, pruebas JavaScript y auditoría de enlaces bilingües; consulta el recuento y los resultados de la ejecución de CI del commit correspondiente.
- GitHub Actions comprueba Python 3.11 y 3.14, lógica JavaScript, idiomas ES/EN, enlaces locales, una prueba real de navegador Chrome y generación del instalador; la versión estable anterior no incorpora automáticamente nuevas funciones.
- Instalación en carpeta con espacios y biblioteca separada; indexación repetida, un catálogo único, recursos y preescucha por HTTP.
- Inspector de proyectos, pistas/bancos, acceso a XPJ de expansiones y flujo de carga al rack; fallos que conservan la copia anterior.
- Exportaciones sobre fixtures sintéticos, rollback ante error y rechazo de rutas privadas, archivos ausentes y parámetros inválidos.
- Backups PO: importación/descarga byte a byte, SHA-256, detección de WAV truncado, rechazo de escapes de ruta, separación estéreo PCM y restauración con confirmación y sin autoplay. Captura probada en Chrome con una entrada estéreo sintética; no equivale a probar un volcado físico del PO.

Los resultados se ven en la pestaña [Actions](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/actions). El alcance no incluye una certificación de hardware físico ni una instalación real en todos los sistemas operativos. Los formatos de audio admitidos por el navegador y los recursos de cada proyecto pueden variar.

## Instalación y actualización

Sigue la [guía](../GUIA_INSTALACION.md) en una carpeta nueva. Conserva tu biblioteca y una copia de seguridad antes de actualizar una instalación existente. No se proporciona un migrador automático de instalaciones históricas ni una restauración de respaldos antiguos sobre el estado actual.

Abre el servidor sobre la biblioteca que acabas de indexar. Después de actualizar código, recarga la página completa: el botón «Recargar proyectos» sólo sustituye las tarjetas, no el JavaScript ya abierto. Cambiar de origen o cerrar la página descarta los ajustes del rack que no se hayan exportado.

El trabajo windows-release-install ejecuta el instalador real del ZIP estable y del ZIP construido desde las fuentes actuales en un ejecutor Windows. Comprueba rutas con espacios y acentos, índice SQLite, preescucha HTTP y exportación/reimportación MPC con WAV sintéticos. El resumen de cada ejecución identifica Windows, arquitectura, Python y SHA-256. Esto no certifica interacción gráfica, Windows ARM ni carga en un sampler físico.

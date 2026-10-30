# Comprobación de la entrega

BeatOS 3.7.0 incluye un catálogo vacío, plantillas MPC saneadas y un manifiesto SHA-256 dentro de BeatOS/. El ZIP se construye desde una lista explícita; no incluye bibliotecas musicales, bases SQLite, backups ni configuraciones del autor.

## Descarga e integridad

Descarga el ZIP adjunto a la [versión estable](https://github.com/Astro1Deep/mpc-sample-database/releases/latest) y su archivo de sumas. «Source code» es el repositorio de desarrollo, no el instalador organizado. En macOS, desde la carpeta de descargas:

```bash
shasum -a 256 -c BeatOS-3.7.0-SHA256SUMS.txt
```

En Linux usa `sha256sum -c` con ese mismo archivo. En PowerShell, `Get-FileHash .\BeatOS-3.7.0-layout.20261029.zip -Algorithm SHA256` permite comparar el resultado con la suma publicada. Una suma comprueba integridad respecto a ese archivo; no es una firma criptográfica del autor.

## Pruebas realizadas

- 50 pruebas Python y tres suites JavaScript sobre fuentes y ZIP extraído.
- GitHub Actions comprueba Python 3.11 y 3.14, lógica JavaScript y generación del instalador.
- Instalación en carpeta con espacios y biblioteca separada; indexación repetida, un catálogo único, recursos y preescucha por HTTP.
- Inspector de proyectos, pistas/bancos, acceso a XPJ de expansiones y flujo de carga al rack; fallos que conservan la copia anterior.
- Exportaciones sobre fixtures sintéticos, rollback ante error y rechazo de rutas privadas, archivos ausentes y parámetros inválidos.

Los resultados se ven en la pestaña [Actions](https://github.com/Astro1Deep/mpc-sample-database/actions). El alcance no incluye una certificación de hardware físico ni una instalación real en todos los sistemas operativos. Los formatos de audio admitidos por el navegador y los recursos de cada proyecto pueden variar.

## Instalación y actualización

Sigue la [guía](../GUIA_INSTALACION.md) en una carpeta nueva. Conserva tu biblioteca y una copia de seguridad antes de actualizar una instalación existente. No se proporciona un migrador automático de instalaciones históricas ni una restauración de respaldos antiguos sobre el estado actual.

Abre el servidor sobre la biblioteca que acabas de indexar. Después de actualizar código, recarga la página completa: el botón «Recargar proyectos» sólo sustituye las tarjetas, no el JavaScript ya abierto. Cambiar de origen o cerrar la página descarta los ajustes del rack que no se hayan exportado.

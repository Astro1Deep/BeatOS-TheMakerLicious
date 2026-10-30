<p align="center"><img src="docs/assets/branding/creator/eye-mirror-wide.png" alt="Ojo y lágrima de Astro1Deep" width="420"></p>

# BeatOS

**The MakerLicious**

[universal beatmaker station]

Biblioteca de samples, inspector de proyectos MPC y rack de 16 pads. Creado por **Astro1Deep** para explorar bibliotecas propias, preparar kits y revisar referencias antes de llevarlos al sampler.

Versión **3.7.1**. [Instaladores y versiones](https://github.com/Astro1Deep/mpc-sample-database/releases) · [Guía de instalación](GUIA_INSTALACION.md) · [Identidad del creador](docs/IDENTIDAD_DEL_CREADOR.md)

![Banner de hardware de BeatOS](docs/assets/branding/user_blueprint_sheet_dark_4k.jpg)

## Instalación

Requiere **Python 3.11 o superior**. El catálogo y el servidor usan la biblioteca estándar. FFmpeg es opcional para convertir audio y necesario en determinados formatos, frecuencias y ajustes de afinación. El sistema se ejecuta en el ordenador; no instala firmware en el sampler.

Descarga el archivo **BeatOS-3.7.1.zip** de [la versión estable](https://github.com/Astro1Deep/mpc-sample-database/releases/latest), junto a su archivo SHA-256. El ZIP adjunto a la versión es el instalador organizado; «Source code» descarga el repositorio de desarrollo, cuya estructura es distinta.

Descomprime en una carpeta nueva y abre una terminal en la carpeta que contiene `BeatOS/`:

```bash
python3 BeatOS/installer.py
```

En Windows usa `py BeatOS/installer.py`. En macOS también puedes abrir `BeatOS/ABRIR_BEATOS.command` después de indexar la biblioteca. En macOS/Linux, `./BeatOS/install.sh` abre el mismo menú.

1. Opción 1: indica la carpeta de tus propios samples y espera a que termine la indexación.
2. Opción 2: indica esa misma carpeta para abrir la interfaz conectada.
3. Comprueba la biblioteca activa en pantalla antes de generar un kit. Abrir el HTML por `file://` permite consultar el catálogo; las acciones necesitan el servidor.

Para servir una biblioteca separada:

```bash
python3 BeatOS/index_mpc_library.py --path "/ruta/a/tu/biblioteca"
python3 BeatOS/serve_mpc.py "/ruta/a/tu/biblioteca" --port 8888
```

Si prefieres clonar el repositorio, los scripts están en su raíz: `python3 installer.py`, `python3 index_mpc_library.py --path "/ruta/a/tu/biblioteca"` y `python3 serve_mpc.py "/ruta/a/tu/biblioteca"`. Los comandos anteriores con `BeatOS/` corresponden al ZIP organizado.

El repositorio y el instalador empiezan con una biblioteca vacía y templates MPC sin contenido personal. No incluyen samples comerciales, proyectos del autor ni una base de datos personal.

## Estructura limpia de la biblioteca

La entrega comprimida contiene sólo dos accesos HTML en la raíz y una carpeta `BeatOS/`. Dentro están el código, el lanzador `ABRIR_BEATOS.command`, la documentación, `data/` (base, CSV, JSON y un solo catálogo) y `config/` (preferencias locales). La reindexación no crea carpetas SQL/índices heredadas ni multiplica los HTML. Se omiten del instalador las ilustraciones históricas que ya no usa la interfaz.

La biblioteca musical conserva sus carpetas y rutas. Los kits creados quedan en `Custom_Kits/`. En el repositorio de desarrollo los scripts siguen en la raíz; allí se ejecuta `python3 installer.py`. En el ZIP organizado se ejecuta `python3 BeatOS/installer.py`.

## Biblioteca y menús

- Preescucha, búsqueda por palabras, filtros de tipo/formato/tempo/nivel y asignación al rack.
- Tipo y formato estimados por nombre y carpeta específica de instrumento; los ambiguos quedan sin identificar. Shakers y panderetas pertenecen a percusión.
- Tonalidad por etiquetas explícitas. Una nota de multisample no determina mayor/menor. Camelot sólo se muestra cuando se declara el modo.
- Energía como nivel RMS aproximado de tres ventanas de WAV PCM: baja < −24 dBFS, media < −12, alta ≥ −12. No representa intensidad musical ni LUFS. Formatos no leídos indican «Sin medir».
- Proyectos MPC: búsqueda, ordenación, paginación e inspección de pistas y bancos A–H. El rack edita una copia de la primera capa activa de cada pad; conserva el original.
- Expansiones: carátulas, programas, proyectos XPJ —incluidos demos y plantillas de subcarpetas— y samples. El acceso «Ver proyectos» filtra la carpeta exacta de la expansión; «Ver todos los proyectos» recupera la biblioteca completa. Preescucha y edición de copias Drum. Keygroup, PGM y AKP requieren su aplicación nativa.
- Recarga de proyectos/expansiones sin descartar el rack; reindexación manual desde la interfaz conectada.

[Manual por capítulos](docs/wiki/Home.md) · [Reglas de identificación y límites](docs/IDENTIFICACION_BIBLIOTECA.md) · [Proyectos y expansiones](docs/BIBLIOTECA_PROYECTOS_EXPANSIONES.md)

## Rack y destinos

Rack de 16 pads con volumen, paneo, afinación, intercambio de pads y grupos de mute. Por defecto bombo=1, hi-hat=2, caja=3; el resto queda libre. El grupo 0 y los grupos personalizados 1–32 se conservan al importar/exportar cuando el formato lo permite.

| Destino | Entrega |
| --- | --- |
| Akai MPC | Programa `.xpm`, proyecto `.xpj` y WAV con posiciones de pad y ajustes. |
| Roland SP-404MK2 | WAV y mapa de banco; conversión a 48 kHz cuando corresponde. |
| Roland SP-404A/SX | WAV y mapa de 12 pads. |
| Native Instruments Maschine | WAV y mapa JSON para asignación; no se genera un `.mxgrp` nativo. |
| PO-33 / PO-133 | Reel WAV, mapa y pausa ajustable de 0–500 ms dentro del presupuesto elegido de 1–40 s. La memoria libre real se comprueba en el dispositivo. |
| EP-133 K.O. II | WAV, mapa JSON y ZIP de transporte para la herramienta oficial; no es un backup nativo. |

La inspección de backups PO describe su cabecera/señal, sin certificar los datos internos. Los ajustes que no admite un destino deben aplicarse en el hardware. Las pruebas automáticas verifican estructura y audio sintético; la compatibilidad final depende del modelo y firmware.

## Seguridad y datos

El servidor escucha en `127.0.0.1`, valida origen/host y rechaza rutas fuera de la biblioteca. No lo expongas a Internet sin añadir autenticación. La creación de kits valida los archivos y parámetros, conserva originales y rechaza sobrescribir un kit existente.

La limpieza de metadatos es una acción explícita y elimina auxiliares AppleDouble/DS_Store. No es necesaria para abrir o indexar. Los scripts históricos de supervisión de `scripts/` no se instalan ni se arrancan con el instalador; no son sondas inocuas. La sincronización con Cerebro/DjProducerTool es una integración local opcional y no implica que esos sistemas estén instalados.

## Pruebas y distribución

```bash
python3 -B -m unittest discover -s tests -v
node tests/test_library_ui.cjs
node tests/test_pad_audio.cjs
node tests/test_creator_identity.cjs
python3 build_release.py "/ruta/de/salida/BeatOS.zip"
```

El flujo de CI incluye una instalación funcional del ZIP en Windows, además de las regresiones de Linux. Los informes identifican el sistema operativo y el SHA-256 probado; no certifican hardware físico ni todos los Windows de escritorio. Node.js sólo es necesario para las comprobaciones JavaScript. El empaquetador usa una lista explícita de componentes, vacía los templates MPC y genera un manifiesto SHA-256. No empaqueta la biblioteca, bases SQLite, respaldos o configuraciones personales.

## Apoyo

Puedes apoyar el desarrollo desde [GitHub Sponsors](https://github.com/sponsors/Astro1Deep) o [Ko-fi](https://ko-fi.com/astro1deep), con el importe que admita cada plataforma.

## 📄 Licencia y Cláusula de Atribución

Este proyecto está protegido bajo la licencia **Creative Commons Atribución-NoComercial-SinDerivadas 4.0 Internacional (CC BY-NC-ND 4.0)** con estipulaciones de autoría por **Iván (Astro1Deep)**:

1. **Atribución Obligatoria**: Todo uso debe conservar de manera visible el crédito original a Iván (Astro1Deep) y el enlace al repositorio oficial.
2. **Aprobación Expresa para Derivadas**: Queda expresamente prohibida la publicación, distribución o bifurcación alterada sin la autorización previa por escrito del autor.
3. **Uso No Comercial**: Libre y gratuito para uso personal, artístico y educativo en producción musical.

Consulta el texto íntegro en [LICENSE](LICENSE) o [LICENSE.md](LICENSE.md).

<p align="center"><img src="docs/assets/branding/creator/astro1deep-banner.png" alt="Ojo y lágrima de Astro1Deep — BeatOS" width="100%"></p>

# BeatOS

**The MakerLicious**

[universal beatmaker station]

**BeatOS es una estación de preparación de kits para varios samplers y entornos de producción musical**, creada por **Astro1Deep**. Reúne una biblioteca de samples con búsqueda y preescucha, un rack de 16 pads y exportadores para **Akai MPC, Native Instruments Maschine, Roland SP-404MK2, SP-404A/SX, Teenage Engineering PO-33/PO-133 y EP-133 K.O. II**.

El flujo central es **explorar tu biblioteca → montar y ajustar un kit → elegir destino → generar los archivos → cargarlos en el aparato o software correspondiente**. Puedes partir de samples sueltos sin tener una MPC. La inspección de proyectos XPJ y programas XPM es una función adicional para recuperar referencias y editar copias de kits del ecosistema Akai.

## English overview — BeatOS / The MakerLicious

**BeatOS** is a local, Python-based **sample library browser and 16-pad beatmaking toolkit** for music producers, DJs and hardware sampler users. Browse and audition samples, assemble drum kits, inspect supported Akai MPC projects, and prepare destination-specific exports for **Akai MPC, Native Instruments Maschine, Roland SP-404MKII / SP-404A / SP-404SX, Teenage Engineering PO-33 / PO-133 and EP-133 K.O. II**.

Export formats and supported parameters vary by destination; producing an export does **not** guarantee native project compatibility with every model or firmware. BeatOS runs on a computer and does not install sampler firmware. See [hardware compatibility](docs/COMPATIBILIDAD_HARDWARE.md), [technical reference](docs/REFERENCIA_TECNICA.md) and the [installation guide](GUIA_INSTALACION.md).

**Related music software:** [DJProducerTools](https://github.com/Astro1Deep/DjProducerTool) — macOS DJ music-library organization, metadata workflows, audio-file auditing and duplicate analysis.

Versión **3.8.0**. [Instaladores y versiones](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases) · [Guía de instalación](GUIA_INSTALACION.md) · 

> **Release status / Estado de distribución:** Bilingual UI fixes and documentation on `main` may be newer than the existing stable ZIP. GitHub Actions publishes a **development-only** clean ZIP for the current commit; it is not a replacement for an officially tagged stable release. See the [bilingual QA audit and remaining validation gates](docs/AUDITORIA_INTEGRAL_BILINGUE_2026-10-30.md).
>
> **Estado técnico:** la interfaz funciona en ES/EN en las pruebas automatizadas, pero todavía **no se certifica una localización del 100 % de los mensajes del backend** ni compatibilidad universal con todos los firmwares.

## Documentation / Documentación (ES · EN)

| Topic / Tema | English | Español |
| --- | --- | --- |
| Installation / Instalación | [Quick start](GUIA_INSTALACION_EN.md) | [Guía de instalación](GUIA_INSTALACION.md) |
| Complete manual / Manual completo | [20-chapter user manual](docs/en/MANUAL_COMPLETO.md) | [Manual de 20 capítulos](docs/MANUAL_COMPLETO.md) |
| Hardware support / Compatibilidad | [Device loading & limits](docs/en/COMPATIBILIDAD_HARDWARE.md) | [Modelos y formatos](docs/COMPATIBILIDAD_HARDWARE.md) |
| Technical details / Referencia técnica | [CLI, SQLite & HTTP API](docs/en/REFERENCIA_TECNICA.md) | [CLI, SQLite y API](docs/REFERENCIA_TECNICA.md) |
| Wiki / Guías temáticas | [English guide index](docs/wiki/Home_EN.md) | [Inicio en español](docs/wiki/Home.md) |

**For producers and beatmakers:** sample library management, 16-pad drum kit creation, Akai MPC Drum programs, Maschine, SP-404MKII, PO-33/PO-133 and EP-133 export workflows. BeatOS runs locally; the ES/EN UI selector covers supported labels, while some runtime texts remain in Spanish. Sample names and your private audio files are never translated.

## Manual del sistema

- **[Manual completo por módulos](docs/MANUAL_COMPLETO.md):** instalación, bibliotecas, identificación, búsqueda, escucha, rack, proyectos, expansiones, hubs, exportación, mantenimiento y diagnóstico.
- **[Compatibilidad y carga por hardware](docs/COMPATIBILIDAD_HARDWARE.md):** MPC Sample frente a One/Live, modelos y versiones, Maschine, SP-404, PO-33/PO-133 y EP-133.
- **[Referencia técnica](docs/REFERENCIA_TECNICA.md):** formatos, parámetros, estructura de datos, API, comandos y límites conocidos.

**MPC Sample no debe confundirse con MPC One/Live.** El XPJ de BeatOS deriva de una plantilla AC50/Sample; el XPM es una entrega Drum diferente. El intercambio con otros motores MPC depende de su versión y del procedimiento de Akai. Consulta la matriz antes de cargar un proyecto: generar el archivo no certifica su carga en todos los modelos.

## Instalación

Requiere **Python 3.11 o superior**. El catálogo y el servidor usan la biblioteca estándar. FFmpeg es opcional para convertir audio y necesario en determinados formatos, frecuencias y ajustes de afinación. El sistema se ejecuta en el ordenador; no instala firmware en el sampler.

Descarga el archivo **BeatOS-3.8.0.zip** de [la versión estable](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases/latest), junto a su archivo SHA-256. El ZIP adjunto a la versión es el instalador organizado; «Source code» descarga el repositorio de desarrollo, cuya estructura es distinta.

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

El mismo rack sirve como origen para todos los exportadores. Elige un destino para generar sólo su entrega, o **Bundle Universal** para crear las seis entregas en una misma operación. Cada una adapta el kit a su formato; los parámetros que el aparato no recibe con el archivo se ajustan allí manualmente.

| Destino | Archivos que genera BeatOS | Cómo continuar y límites |
| --- | --- | --- |
| **Akai MPC: distinguir Sample y otros motores** | Programa Drum `.xpm` y proyecto `.xpj` derivado de plantilla **AC50/Sample**, cada uno con sus muestras. | No son proyectos intercambiables por compartir marca/extensión. Revisa [modelo, versión y procedimiento de carga](docs/COMPATIBILIDAD_HARDWARE.md#1-mpc-sample-frente-a-mpc-one-y-mpc-live). BeatOS no ejecuta la conversión oficial MPC3→Sample ni preserva la canción original. |
| **Native Instruments Maschine** | WAV en `Samples/Group_A/` y mapa `Groups/*_Maschine_Map.json`. | Carga los WAV y asigna sonidos y parámetros siguiendo el mapa. No se genera un grupo `.mxgrp` nativo. |
| **Roland SP-404MK2** | WAV PCM 16-bit/48 kHz para hasta 16 pads y `sp404mk2_manifest.json`. | Transfiere las muestras e impórtalas con el procedimiento del equipo; comprueba la asignación. No es un proyecto o backup nativo, y el manifiesto no transmite ajustes del rack. |
| **Roland SP-404A/SX** | WAV PCM 16-bit/44.1 kHz, nombrados `A01.wav`–`A12.wav`. | Prepara la importación con el procedimiento del modelo. **Sólo se exportan los pads 1–12**: mueve antes los sonidos de los pads 13–16 si los necesitas. No se genera un mapa JSON ni se transfieren los ajustes del rack. |
| **PO-33 / PO-133** | Un reel WAV mono PCM 16-bit/44.1 kHz y manifiesto de cortes. | Reproduce y graba el reel por la entrada de audio del PO; revisa cortes y TRIM. Volumen y afinación se procesan en el audio y el conjunto se normaliza; panorama y mutes no se transfieren. |
| **EP-133 K.O. II** | WAV PCM 16-bit/44.1 kHz mono/estéreo, `meta.json`, guía de carga y ZIP de transporte. | Extrae el ZIP e importa los WAV con EP Sample Tool. El mapa propone las 12 teclas de A y las primeras cuatro de B; asignación, volumen, panorama, tono y mutes se aplican manualmente. No es un backup nativo. |

### De la biblioteca al aparato: primer kit

1. **Abre la biblioteca conectada.** Indexa tu carpeta de samples e inicia el servidor con esa misma ruta. Comprueba en pantalla qué biblioteca está activa; las exportaciones se escriben allí, aunque el código esté instalado en otra carpeta.
2. **Busca y escucha.** Filtra las muestras y asígnalas al rack. También puedes abrir una copia de un XPM Drum o de una pista de batería XPJ. En ese caso, el rack toma la primera capa activa y exporta los 16 pads del banco visible A–H; no exporta todo el proyecto.
3. **Prepara los pads.** Cambia posiciones, volumen, panorama, afinación y grupos de mute. El grupo 0 permite superposición; los valores predeterminados son bombo=1, hi-hat=2 y caja=3. Revisa la tabla para saber qué ajustes viajan al destino. Shuffle rellena por categorías, por lo que conviene escuchar el resultado.
4. **Elige el formato.** En «Exportar Kit», escribe un nombre y selecciona «Destino de Hardware». Para un SP-404A/SX, concentra el kit en los primeros 12 pads. Para PO, usa el Hub PO si necesitas ajustar presupuesto de memoria y pausas: admite 1–40 s y 0–500 ms; la exportación normal del rack usa 40 s y 150 ms.
5. **Genera y localiza la entrega.** Pulsa «Generar Kit en Tarjeta MicroSD». El nombre del botón no obliga a usar una tarjeta: la salida se guarda en `Custom_Kits/<nombre>/` dentro de la biblioteca activa. El aviso de resultado muestra las rutas. Si ya existe ese kit, utiliza otro nombre para conservarlo.
6. **Transfiere y comprueba.** Usa los archivos de la subcarpeta de tu destino según la tabla anterior. Escucha los pads, revisa asignaciones, niveles, afinación y mutes en el equipo o software. Exporta tu trabajo antes de cambiar de origen o cerrar la página.

Por ejemplo, un kit de ocho golpes creado desde WAV sueltos puede salir como programa MPC, muestras para Maschine, archivos para SP-404, reel PO o paquete EP-133 sin importar previamente ningún proyecto Akai. «Universal» ejecuta todos los exportadores: no crea un único archivo que todos los aparatos puedan abrir.

### Dónde queda cada entrega

Con el bundle universal, `Custom_Kits/<nombre>/` contiene `Akai_MPC/`, `NI_Maschine/`, `Roland_SP404MK2/`, `Roland_SP404A/`, `Pocket_Operator_PO33/` y `Teenage_Engineering_EP133/`. Al elegir un destino individual sólo se crea su subcarpeta. Las carpetas internas y manifiestos concretos se detallan en la [guía del rack y exportación](docs/wiki/08-Universal-Hardware-Beatmaker-Rack-(MPC-Maschine-SP404-PO33).md).

### Conversión y errores de exportación

FFmpeg permite convertir formatos o frecuencias distintos y procesar afinación en el reel PO. Sin él sólo se admiten las fuentes PCM compatibles con la conversión solicitada; por ejemplo, pasar de 44.1 a 48 kHz para SP-404MK2 requiere FFmpeg. Si falla una conversión, se informa del error y se retira la entrega parcial. En el bundle universal, el fallo de un destino cancela el conjunto: si sólo necesitas un aparato, selecciona ese destino.

Para PO, introduce la memoria que tengas libre: BeatOS no puede consultarla. El reel puede recortar muestras con fade-out para caber en el presupuesto, y las pausas cuentan dentro de él. Consulta la [guía de PO-33/PO-133 y EP-133](docs/wiki/09-Pocket-Operator-PO-33-KO-Studio-y-FSK-Modem.md) antes de cargar audio o manejar respaldos.

El Hub PO permite grabar WAV estéreo sin compresión, importar, archivar y descargar respaldos originales con SHA-256, y preparar su restauración con confirmación. El volcado del propio PO conserva sonidos y patrones; BeatOS no convierte proyectos MPC en proyectos nativos del PO ni certifica los datos del módem. Consulta el [flujo completo de backups](docs/wiki/09-Pocket-Operator-PO-33-KO-Studio-y-FSK-Modem.md).

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

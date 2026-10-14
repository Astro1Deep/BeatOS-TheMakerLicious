# 📁 2. Organización MicroSD para Akai MPC

El sistema operativo interno de Akai MPC (un Linux optimizado para audio en tiempo real) navega por las carpetas de la tarjeta Micro SD o unidad SSD leyendo la tabla de asignación de archivos de abajo hacia arriba. Cuando una tarjeta contiene carpetas anidadas en exceso (más de 4 niveles) o miles de muestras sin categorizar, la rueda de datos (*Jog Wheel*) y la pantalla táctil pierden fluidez.

Esta sección presenta la **Arquitectura Ergonómica de 7 Macro-Categorías**, diseñada tras probar cientos de gigabytes en hardware MPC Standalone.

---

## 🗂️ Estructura Raíz Recomendada de la Tarjeta

En el directorio raíz de tu tarjeta Micro SD (`/Volumes/TU_TARJETA`), mantén únicamente estas 3 carpetas principales:

```text
/Volumes/TU_TARJETA/
├── catalogo_mpc_sample.html      # Catálogo Web accesible con doble clic
├── Expansions/                   # Expansiones Oficiales con Expansion.xml
├── MPC-Sample/                   # Librerías de Producción y Proyectos
│   ├── Projects/                 # Proyectos Standalone (.xpj + _[ProjectData])
│   └── Samples/                  # Las 7 Macro-Categorías de Sonidos
└── SQLITE_DATABASE/              # Motor de Datos SQLite, CSV, JSON y Toolkit
```

---

## 🧱 Las 7 Macro-Categorías de Sonidos

Dentro de `MPC-Sample/Samples/`, las carpetas están numeradas del `01` al `07` para que el explorador del MPC las ordene alfabéticamente en la parte superior sin importar cómo las filtre el usuario:

```text
MPC-Sample/Samples/
├── 01_BOOM_BAP_&_LOFI/           # Samples clásicos, vinilo, texturas analógicas y cajas crujientes
├── 02_TRAP_&_MODERN_HIPHOP/      # 808s afinados, hi-hat rolls, snares cortantes y drill
├── 03_ELECTRONIC_&_HOUSE/        # Bombos de 4x4, claps abiertos, tops, sintetizadores y groove
├── 04_DRUM_KITS_&_ACOUSTIC/      # Baterías reales, toms, platos, congas, percusión acústica
├── 05_SERATO_&_DJ_TOOLS/         # Stems, acapellas de batalla, cue points y scratches
├── 06_SYNTHS_KEYS_&_LOOPS/       # Teclas, pianos Rhodes, riffs de guitarra, bajos y melodías
└── 07_ARTIST_&_COLLECTIONS/      # Paquetes temáticos de productores específicos
```

---

## 🛡️ Reglas de Oro para Proyectos MPC (.xpj)

1. **Nunca separes el archivo `.xpj` de su carpeta de datos**:
   Si tu proyecto se llama `MiBeat.xpj`, Akai MPC creará obligatoriamente a su lado `MiBeat_[ProjectData]/`. Si mueves o renombras el archivo `.xpj` sin renombrar exactamente igual la carpeta `_[ProjectData]`, el hardware marcará los samples como desaparecidos (`Missing Samples`).
2. **Ubicación centralizada**:
   Guarda siempre tus sesiones en `MPC-Sample/Projects/`. Esto permite que el indexador audite en 1 segundo la integridad de cada sample referenciado.
3. **Evita caracteres conflictivos en proyectos**:
   Evita barras inclinadas (`/`, `\`), signos de interrogación (`?`), asteriscos (`*`) o comillas en los nombres de proyectos.

---

## 🧹 El Problema Oculto: Archivos AppleDouble (`._*`) en macOS

Cuando conectas una tarjeta Micro SD con formato **ExFAT** o **FAT32** a un ordenador con macOS, el sistema operativo de Apple crea silenciosamente un archivo "sombra" que empieza por `._` por cada archivo o carpeta que visualizas en el Finder (por ejemplo, para `Kick01.wav`, macOS genera `._Kick01.wav`).

* **¿Por qué es un problema grave en el MPC?**:
  El MPC no sabe que esos archivos son metadatos de macOS. Intenta cargarlos como archivos de audio normales, provocando el mensaje de error:
  `"Unable to read file"` o `"Unsupported sample format"`, y duplicando la lista en pantalla con nombres fantasma.
* **Solución Automática**:
  El instalador `install.sh` y el indexador incorporan limpieza nativa antes de procesar la tarjeta:
  ```bash
  ./install.sh # Selecciona Opción 3 (Limpiar archivos fantasma)
  ```
  O directamente en tu terminal:
  ```bash
  dot_clean -m /Volumes/TU_TARJETA
  find /Volumes/TU_TARJETA -name "._*" -delete
  find /Volumes/TU_TARJETA -name ".DS_Store" -delete
  ```

---

## 💾 Formato de la Tarjeta Micro SD

Para la máxima estabilidad en hardware Akai MPC:
* **Formato Recomendado**: **ExFAT** con tamaño de bloque de **128 KB** o **256 KB**.
* **Capacidad**: Compatible con tarjetas Micro SDHC y Micro SDXC de hasta 1 TB.
* **Velocidad**: Recomendado mínimo **U3 / V30 / A2** (ej: SanDisk Extreme, Samsung EVO Plus) para una carga instantánea de proyectos grandes.

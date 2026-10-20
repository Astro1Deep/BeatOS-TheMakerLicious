# 🎛️ 08. Universal Hardware Beatmaker Rack (MPC, Maschine, SP-404 & PO-33)

El **Universal Beatmaker Kit Rack** es la estación central de diseño rítmico del catálogo. Permite a los productores ensamblar, probar y exportar kits de 16 pads para múltiples plataformas de hardware y software de forma simultánea.

---

## 🕹️ 1. Asignación y Control de Pads en Tiempo Real

El rack cuenta con una cuadrícula visual de **16 pads (Banco A: 1 al 16)** calibrada con:

1. **Triggering Auditivo Directo**:
   - Disparo por ratón o mediante atajos de teclado físico del ordenador:
     - Fila 1 (Pads 1-4): Teclas `Z`, `X`, `C`, `V`
     - Fila 2 (Pads 5-8): Teclas `A`, `S`, `D`, `F`
     - Fila 3 (Pads 9-12): Teclas `Q`, `W`, `E`, `R`
     - Fila 4 (Pads 13-16): Teclas `1`, `2`, `3`, `4`

2. **Dock de Asignación Rápida**:
   - En el explorador de muestras, pulsa el botón **`📥 Asignar`** en cualquier fila de la tabla para cargar inmediatamente ese sample en el pad activo seleccionado en el Dock superior.

3. **AI Shuffle (16 Pads)**:
   - El botón **`🎲 AI Shuffle`** utiliza reglas heurísticas de producción para rellenar automáticamente los 16 pads con una combinación balanceada (Kicks, Snares, Hats, Percs, 808s, Chops melódicos y FX).

---

## ⚙️ 2. Inspector Universal de Pads (`⚙️`)

Cada pad dispone de un botón de ajustes individuales que despliega el **Pad Inspector Modal**:

* **Volumen Relativo**: Ajuste de ganancia lineal (0.0 a 1.0, por defecto 0.707 [-3 dB]).
* **Paneo Estéreo (Pan)**: De 0.0 (100% Izquierda) a 1.0 (100% Derecha), con 0.5 como Centro exacto.
* **Afinación (Tune)**: Transposición en semitonos musicales desde **-24 st** (2 octavas abajo) hasta **+24 st** (2 octavas arriba).
* **Choke / Mute Groups (1-8)**:
  - *Grupo 1*: Asignado típicamente a Hi-Hats abiertos y cerrados para corte mutuo.
  - *Grupo 2*: Asignado a líneas de bajo y 808 para evitar solapamientos destructivos de graves.
* **Intercambio Dinámico de Pads (Swap)**:
  - Permite mover un sample y toda su configuración a otro pad sin perder ajustes ni tener que reasignar manualmente.

---

## 🚀 3. Motores de Exportación Hardware Soportados

El motor autónomo [`hardware_kit_builder.py`](file:///Users/ivan/Documents/mpc-sample-database/hardware_kit_builder.py) compila el kit según los estándares nativos de cada fabricante:

### A. Akai MPC Standalone (.xpm & .xpj)
* Genera un archivo XML `MPCVObject` versión 2.1 compatible con MPC One, Live, X, Key y MPC Software.
* Mapea capas de velocidad (Layer 1 a 4), curvas de volumen cúbicas y mute groups nativos de Akai.
* Crea el proyecto `.xpj` con su correspondiente carpeta `_[ProjectData]`.

### B. Native Instruments Maschine (.mxgrp / Bundle)
* Estructura los 16 pads con nombres estandarizados y mapeo MIDI en C3 (Root Note 60).
* Organiza los samples en la subcarpeta `Samples/Group_A/` lista para importar en Maschine MK3, Plus y Mikro.

### C. Roland SP-404MK2 & Serie SP
* Exporta los 16 pads directamente al formato de importación rápida del **Banco A**.
* Calibra el formato de audio a **WAV 16-bit / 48 kHz** nativo de Roland, eliminando conversiones de sample rate en el hardware.
* Compatible con el firmware oficial de Roland, secuenciador TR-REC y extensiones de la comunidad (como DOOM OS).

### D. Roland SP-404A / SX
* Mapea los primeros 12 pads al Banco A con formato **WAV 16-bit / 44.1 kHz**.

### E. Teenage Engineering Pocket Operator (PO-33 & PO-133)
* Genera una tira **Drum Reel** única con pausas calibradas de 150 ms para auto-slicing automático en los pads 9-16.

### F. Teenage Engineering EP-133 K.O. II
* Exporta paquetes de respaldo estándar **`.pak`** comprimidos en ZIP con manifiesto `meta.json` y carpeta de muestras `sounds/`.
* Mapea los 16 pads divididos en Grupo A (pads 1-9) y Grupo B (pads 10-16) calibrados a **WAV 16-bit / 44.1 kHz**.
* Compatible directamente con **EP Sample Tool** vía WebUSB / Drag-and-Drop y gestión nativa de proyectos en el hardware.

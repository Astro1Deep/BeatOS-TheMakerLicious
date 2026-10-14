# 📦 5. Expansiones Oficiales Akai MPC

Las expansiones son paquetes sonoros auto-contenidos que Akai Professional y diseñadores de sonido de terceros empaquetan con programas listos para tocar en los 16 pads, secuencias pre-grabadas y una interfaz gráfica en la pantalla táctil del MPC.

---

## 📍 Ubicación Obligatoria en la Tarjeta

Para que el hardware Akai MPC Standalone muestre la expansión en su navegador dedicado de expansiones (icono de rejilla en el menú Browser), la carpeta debe ubicarse obligatoriamente en la raíz de la tarjeta bajo el directorio:

```text
/Volumes/TU_TARJETA/Expansions/
├── Backyard Jams/
│   ├── Expansion.xml             # Metadatos oficiales requeridos
│   ├── [Artwork]/cover.png       # Carátula que se ve en la pantalla táctil
│   ├── Kits/                     # Programas de pads (.xpm)
│   └── Samples/                  # Muestras de audio vinculadas
├── Borough Chops/
├── Rare Vibrations/
└── Real Horns/
```

> [!IMPORTANT]
> Si colocas una expansión dentro de `MPC-Sample/Samples/`, el MPC la tratará como carpetas genéricas de audio y no mostrará la carátula gráfica ni los programas en el menú de expansiones.

---

## 📄 El Archivo `Expansion.xml`

El archivo `Expansion.xml` define cómo se presenta el kit en la interfaz gráfica del MPC. El indexador del toolkit lee este archivo XML extrayendo:

```xml
<?xml version="1.0" encoding="utf-8"?>
<expansion>
    <identifier>com.akaipro.mpc.expansion.backyardjams</identifier>
    <title>Backyard Jams</title>
    <version>1.0.0</version>
    <manufacturer>Akai Professional</manufacturer>
    <type>Expansion</type>
    <img src="Artwork/cover.png"/>
    <description>Soulful boom bap and summer vibes</description>
</expansion>
```

El script extrae:
* **`title`**: Nombre oficial de la expansión.
* **`manufacturer`**: Fabricante o diseñador de sonido (ej: Akai Professional, Rawcutz, MSXII).
* **`programs_count`**: Número total de kits o programas de batería (`.xpm` / `.pgm`).
* **`samples_count`**: Cantidad de samples asignados a la expansión.
* **`size_mb`**: Espacio ocupado en disco por la expansión.

---

## 🎛️ Formatos de Programas Soportados

* **`.xpm`**: Formato estándar de programa moderno para MPC 2.x y 3.x (MPC Live, One, X, Key).
* **`.pgm`**: Formato de programa clásico de la serie MPC 1000 / 2500 / 5000.
* **`.akp`**: Programas de sampler Akai antiguos (serie S5000/S6000).

---

## 🌐 Pestaña de Expansiones en el Catálogo

En la pestaña **🎛️ Expansiones Oficiales** del catálogo HTML5 interactivo, cada paquete se muestra con su resumen de programas y samples, junto con un botón para **📋 Copiar Ruta Expansión** que te permite ubicarla rápidamente en tu explorador de archivos.

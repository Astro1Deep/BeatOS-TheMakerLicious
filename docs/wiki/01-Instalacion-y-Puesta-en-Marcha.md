# 🚀 1. Instalación y Puesta en Marcha

Esta guía explica cómo descargar, configurar y ejecutar el **Akai MPC Sample Database Toolkit** en tu ordenador para indexar cualquier tarjeta Micro SD, disco SSD o carpeta local de samples.

---

## 📋 Requisitos del Sistema

* **Sistema Operativo**: macOS (10.14+), Linux (Ubuntu, Debian, Fedora, Arch) o Windows (10/11).
* **Python**: Python 3.8 o superior (Python 3.10+ recomendado).
* **Dependencias Externas**: **NINGUNA**. El toolkit utiliza exclusivamente módulos nativos de la biblioteca estándar de Python (`sqlite3`, `json`, `csv`, `os`, `re`, `gzip`, `xml.etree.ElementTree`, `http.server`).
* **Hardware Soportado**: Tarjetas Micro SD o discos externos formateados preferentemente en **ExFAT** o **FAT32** para compatibilidad con Akai MPC.

---

## 📥 Paso 1: Clonar o Descargar el Repositorio

Abre tu terminal favorita y ejecuta:

```bash
git clone https://github.com/Astro1Deep/mpc-sample-database.git
cd mpc-sample-database
```

*(Si no utilizas Git, puedes descargar el archivo ZIP directamente desde GitHub y descomprimirlo en tu carpeta de preferencia).*

---

## ⚡ Paso 2: Ejecución del Instalador

El toolkit ofrece dos vías según tu sistema operativo:

### En macOS y Linux (Bash)
El instalador `install.sh` incluye interfaz de colores y auto-detección del entorno:

```bash
chmod +x install.sh
./install.sh
```

El menú te presentará las siguientes opciones:
1. **🚀 Indexar automáticamente tarjeta Micro SD o carpeta**: Solicita la ruta y procesa todos tus samples.
2. **🌐 Iniciar Servidor Web Local y Abrir Catálogo**: Lanza un servidor ligero en el puerto `8888` y abre el navegador para reproducción 100% garantizada.
3. **🧹 Limpiar archivos fantasma de macOS**: Pone a cero los archivos `._*` y `.DS_Store` en la tarjeta.
4. **🗄️ Inicializar una Base de Datos SQLite vacía**: Crea `mpc_sample_master.db` directamente con la estructura DDL de `schema.sql`.
5. **📚 Abrir Wiki y Documentación Oficial**: Abre la wiki del proyecto en tu navegador.

---

### En Windows (o Multiplataforma con Python)
En sistemas Windows (o si prefieres ejecutar directamente vía Python en cualquier plataforma):

```bash
python3 installer.py
```
*(O `python installer.py` en Windows)*.

---

## 🛠️ Paso 3: Indexación Directa por Línea de Comandos

Si eres un usuario avanzado o deseas integrar la indexación en tus propios scripts de automatización, puedes invocar directamente `index_mpc_library.py`:

```bash
# Ejemplo: Indexar una tarjeta Micro SD montada en macOS
python3 index_mpc_library.py --path "/Volumes/MPCSMPL"

# Ejemplo: Especificar una carpeta de salida personalizada para la base de datos
python3 index_mpc_library.py --path "/Volumes/MPCSMPL" --output "/Volumes/MPCSMPL/SQLITE_DATABASE"

# Ejemplo en Windows
python index_mpc_library.py --path "E:\"
```

---

## 📂 Archivos Generados tras la Indexación

Una vez finalizado el proceso, encontrarás en tu tarjeta o directorio seleccionado:

1. **`catalogo_mpc_sample.html`** (en la raíz): Catálogo visual interactivo accesible con doble clic.
2. **`SQLITE_DATABASE/mpc_sample.db`**: Base de datos relacional SQLite 3 con índices de alta velocidad.
3. **`SQLITE_DATABASE/mpc_sample.json`**: Metadatos globales y volcado de proyectos y expansiones.
4. **`SQLITE_DATABASE/mpc_sample_resumen.csv`**: Hoja de cálculo con todos los samples, lista para importar en Excel o Numbers.
5. **`SQLITE_DATABASE/catalogo_mpc_sample.html`**: Copia espejo del catálogo en el subdirectorio de datos.

> [!TIP]
> Si expulsas la tarjeta y la insertas en tu Akai MPC Live, One, X o Key, tus carpetas de sonido y proyectos estarán intactos y limpios de cualquier archivo basura del sistema operativo.

# 🌐 6. Catálogo Web y Reproductor de Audio

El **Catálogo Web HTML5** (`catalogo_mpc_sample.html`) es la interfaz gráfica que conecta tu ordenador con la tarjeta de memoria del Akai MPC. Te permite buscar, filtrar y escuchar cualquier sample en milisegundos sin depender de software pesado de edición de audio.

---

## 🎨 Características de la Interfaz

1. **Búsqueda Instantánea Multidimensional**:
   Puedes escribir cualquier término en la barra superior:
   * Por tipo de instrumento: `808`, `kick`, `snare`, `rhodes`, `guitar`.
   * Por tempo exacto: `140`, `90`, `124`.
   * Por tonalidad o Camelot: `Dm`, `7A`, `8B`, `F#m`.
   * Por nombre de pack o sub-carpeta.
2. **Chips de Acceso Rápido**:
   Botones rediseñados para aislar en un solo clic: Kicks, Snares, Claps, Hi-Hats, Címbalos, Percusión, 808s, Pianos/Sintes, Loops Melódicos, Breakbeats, Vocales o Efectos.
3. **Paginación Inteligente**:
   Muestra lotes de 60 registros por página con scroll suave. Esto garantiza un rendimiento a 60 FPS en el navegador incluso con catálogos de más de 30,000 muestras.
4. **Reproductor de Audio Flotante**:
   Una barra fija en la parte inferior con control de volumen, scrubber de reproducción y el nombre del sample en curso.
5. **Botón 📋 Copiar Ruta MPC**:
   Copia al portapapeles la ruta relativa exacta (ej: `MPC-Sample/Samples/01_BOOM_BAP_&_LOFI/Kick_Vinyl_01.wav`) para encontrarla inmediatamente en el hardware Akai MPC.

---

## 🔊 Solución al Sandbox Local (`file://`) en Navegadores

Los navegadores web modernos basados en Chromium (Google Chrome, Brave, Microsoft Edge, Opera) y Safari aplican una política de seguridad estricta:
* Si abres un archivo HTML local haciendo doble clic (`file:///Volumes/TARJETA/catalogo_mpc_sample.html`), el navegador restringe a veces la carga de archivos de audio ubicados en directorios superiores o con caracteres especiales (`&`, `#`, espacios).

El toolkit incorpora una **solución dual en 2 niveles**:

### Nivel 1: Codificación Segmento por Segmento
El reproductor en JavaScript no utiliza un `encodeURI` simple (que deja caracteres conflictivos como `#` y `&` intactos), sino que divide la ruta por carpetas y codifica cada segmento individualmente:
```javascript
const encodedPath = relPath.split('/').map(seg => encodeURIComponent(seg)).join('/');
```
Además, coloca una copia de `catalogo_mpc_sample.html` tanto en la raíz de la tarjeta como en `SQLITE_DATABASE/` para que las rutas relativas sean siempre descendentes (`./MPC-Sample/...`), permitidas por el sandbox de Chrome.

---

### Nivel 2: Servidor Local Ligero (Garantía al 100%)
Si prefieres saltarte cualquier restricción del navegador y tener la experiencia de reproducción más fluida posible:

1. Ejecuta `./install.sh` en tu terminal y elige la **Opción 2**:
   ```bash
   ./install.sh
   # Elige: 2) Iniciar Servidor Web Local y Abrir Catálogo
   ```
2. O ejecuta en una sola línea de comando:
   ```bash
   python3 -m http.server 8888 --directory "/Volumes/TU_TARJETA"
   ```
3. Tu navegador se abrirá instantáneamente en `http://localhost:8888/catalogo_mpc_sample.html`.

> [!TIP]
> Bajo `http://localhost`, el audio fluye sin ninguna restricción de seguridad en cualquier navegador del mundo.

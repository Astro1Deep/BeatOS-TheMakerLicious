<p align="center"><img src="docs/assets/branding/creator/astro1deep-banner.png" alt="BeatOS — proyecto de Astro1Deep" width="100%"></p>

# BeatOS — The MakerLicious
**Explorador local de samples · rack de 16 pads · exportación orientada a hardware**

**Idioma: Español · [English / presentación principal](README.md)**

BeatOS es una estación de creación musical basada en samples y preparación de kits para **músicos, beatmakers y productores musicales**. Permite explorar y preescuchar bibliotecas, organizar sonidos, montar y editar kits en un rack de 16 pads, inspeccionar proyectos MPC compatibles y preparar exportaciones para distintos samplers. **Nuestro objetivo es alcanzar la máxima fidelidad a los proyectos nativos de cada hardware:** generar kits y proyectos que sus máquinas puedan cargar y editar de forma natural, conservar ajustes específicos y, cuando el formato lo permita, ofrecer una edición de parámetros más profunda que los métodos habituales de importación. La compatibilidad nativa se desarrollará y validará por modelo y firmware; actualmente, algunos destinos reciben WAV y mapas de asignación en lugar de proyectos nativos.

![Interfaz real de BeatOS en español, con datos sintéticos](docs/assets/screenshots/beatos-overview-es.png)

<details><summary>Otras capturas reales de la interfaz</summary>

![Rack de 16 pads](docs/assets/screenshots/beatos-rack-en.png)

![Presentación visual](docs/assets/screenshots/beatos-hero-en.png)

</details>

## Instalación

Necesitas Python 3.11 o posterior, un navegador de escritorio y una carpeta de samples propia. FFmpeg es recomendable y obligatorio para determinadas conversiones de audio y frecuencia.

1. Descarga el **archivo adjunto a la versión estable** desde [Versiones publicadas](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases/latest) y verifica el SHA-256. No confundas el ZIP del instalador con el ZIP automático del código fuente.
2. Descomprime en una carpeta nueva, sin sobrescribir bibliotecas existentes.
3. Abre una terminal desde la carpeta contenedora de `BeatOS/` y ejecuta:

```bash
python3 BeatOS/installer.py --lang es
# En Windows:
py BeatOS/installer.py --lang es
```

Utiliza la opción **1** para indexar y **2** para abrir el servidor local. En un clon del repositorio, ejecuta `python3 installer.py --lang es` desde su raíz.

**Idiomas:** por defecto, el primer inicio se muestra en inglés. Puedes seleccionar **ES** desde el encabezado web. La preferencia se conserva en el navegador; para terminal, utiliza `--lang es` o `BEATOS_LANG=es`. Ni los nombres de archivos, ni las rutas, ni los nombres de proyectos privados se traducen.

> **Importante:** el código de `main` puede ser más reciente que el instalador estable 3.8.0. Para actualizar una instalación, instala una distribución nueva y regenera el catálogo de tu biblioteca tras conservar tus copias. [Estado de la auditoría](docs/AUDITORIA_INTEGRAL_BILINGUE_2026-10-30.md).

## Objetivo: edición y exportación con fidelidad nativa

La meta no es limitarse a recopilar WAV: **BeatOS debe evolucionar hacia un editor avanzado de kits y proyectos específico para cada sampler**. Queremos que el usuario prepare un kit en el ordenador, edite los parámetros que su máquina realmente admite y pueda cargarlo, seguir trabajándolo y volver a guardarlo en el hardware sin perder asignaciones.

El desarrollo prioriza **bancos y pads, capas/zonas de velocidad, afinación, envolventes, inicio/fin y loop, volumen, panorama, grupos choke/mute, modo de disparo, BPM y referencias de muestras**, cuando estén disponibles en cada dispositivo. Cuando se investiguen formatos de proyecto compatibles, también podrá estudiarse la edición de efectos, patrones y otros parámetros soportados.

Para un mismo destino distinguiremos explícitamente **(1) WAV para importar**, **(2) kit con mapeo asistido**, **(3) proyecto nativo editable verificado** y **(4) exportación avanzada de parámetros**, sin dar por completado ningún nivel hasta superar las pruebas de carga, modificación y relectura en el equipo y firmware correspondientes. Ni un ZIP renombrado ni un manifiesto JSON convierten un paquete en un backup nativo.

Seguimiento técnico: [propuesta de compatibilidad y edición nativa](docs/HARDWARE_EXPORT_PROTOCOLS.md#8-protocolo-mínimo-de-aceptación-física). Los formatos propietarios o no documentados exigen investigación autorizada, archivos de prueba originales y verificación de ida y vuelta; nunca se deben modificar respaldos reales como experimento.

**Hoja de ruta técnica:** [Fidelidad de proyectos nativos y edición avanzada por hardware — issue #11](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/issues/11).

## Formatos y límites por hardware

| Sistema | Exportación de BeatOS | Limitación esencial |
| --- | --- | --- |
| **Akai MPC** | Programa Drum `.xpm`, proyecto `.xpj` derivado de plantilla Sample y WAV | El proyecto Sample/AC50 no equivale automáticamente al formato nativo de MPC One/Live/X. |
| **NI Maschine** | WAV y mapa JSON de asignaciones | No genera un `.mxgrp` nativo; hay que realizar la asignación en Maschine. |
| **Roland SP-404MKII** | WAV PCM 16-bit/48 kHz para hasta 16 pads; manifiesto JSON | No genera copia nativa de proyecto o patrones; requiere importación. |
| **Roland SP-404A/SX** | WAV PCM 16-bit/44.1 kHz, pads A01–A12 | No es un backup nativo y se limita a 12 pads de un banco. |
| **PO-33/PO-133** | Reel de batería mono 44.1 kHz con mapa de cortes | Se graba por audio y se revisa en TRIM; no constituye backup módem. |
| **EP-133 K.O. II** | WAV 16-bit/44.1 kHz, `meta.json` y ZIP | El ZIP solo transporta archivos; no es un backup restaurable del aparato. |

**Generar un archivo no equivale a verificar su carga.** Consulta las guías para comprobar nombres, parámetros PCM, referencias, límites de memoria, mapeo de pads y reproducción en hardware real.

## Manuales y documentación

| Materia | Español | Inglés |
| --- | --- | --- |
| Instalación | [Guía de instalación](GUIA_INSTALACION.md) | [Installation guide](GUIA_INSTALACION_EN.md) |
| Uso completo | [Manual de 20 capítulos](docs/MANUAL_COMPLETO.md) | [Complete manual](docs/en/MANUAL_COMPLETO.md) |
| Protocolos de exportación | [Guía avanzada y validación](docs/HARDWARE_EXPORT_PROTOCOLS.md) | [Advanced export protocols](docs/en/HARDWARE_EXPORT_PROTOCOLS.md) |
| Modelos y limitaciones | [Compatibilidad](docs/COMPATIBILIDAD_HARDWARE.md) | [Compatibility](docs/en/COMPATIBILIDAD_HARDWARE.md) |
| API, SQLite y CLI | [Referencia técnica](docs/REFERENCIA_TECNICA.md) | [Technical reference](docs/en/REFERENCIA_TECNICA.md) |
| Temas específicos | [Wiki en español](docs/wiki/Home.md) | [English Wiki](docs/wiki/Home_EN.md) |

## Seguridad y pruebas

El servidor se utiliza **en local**, sin autenticación de usuarios remotos: no publiques su puerto en Internet. Conserva los WAV de origen, proyectos originales y copias de seguridad del hardware. Las pruebas automáticas verifican integridad, estructura, API e interacción web, pero la fidelidad final exige cargar, reproducir, guardar y volver a abrir el kit en el modelo y firmware concretos.

**Autoría:** [Astro1Deep](https://github.com/Astro1Deep) · [Repositorio](https://github.com/Astro1Deep/BeatOS-TheMakerLicious) · [Versiones estables](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/releases) · [Sitio en español](docs/index-es.html).

**Versión estable documentada:** 3.8.0. Comprueba siempre el manifiesto y la suma SHA-256 de la descarga concreta.

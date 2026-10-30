# Compatibilidad y carga por hardware · BeatOS 3.8.0

Revisión: **30 de octubre de 2026**. [Manual completo](MANUAL_COMPLETO.md) · [Inicio](../README.md) · [Referencia técnica](REFERENCIA_TECNICA.md).

## Cómo interpretar la compatibilidad

Esta guía separa tres evidencias: **archivo generado** (lo que implementa BeatOS), **procedimiento del fabricante** (lo que admite su software/firmware) y **prueba física** (carga y escucha de esa entrega en un modelo y versión concretos). Las pruebas automáticas de BeatOS comprueban archivos y audio sintético; no certifican todos los equipos de una familia. No hay un registro de pruebas físicas adjunto a esta revisión.

Un WAV, un programa, un proyecto y un backup tienen funciones distintas. Compartir una extensión no prueba que dos motores interpreten el mismo contenido. Tampoco el nombre de una carpeta ni una ilustración de un aparato garantiza compatibilidad.

## 1. MPC Sample frente a MPC One y MPC Live

**No se deben tratar como proyectos idénticos e intercambiables sin conversión o requisitos de versión.** Akai documenta en MPC 3.8 dos operaciones: cargar proyectos de MPC Sample en MPC desktop/standalone y exportar una pista Drum como archivo MPC Sample. La segunda se hace en desktop con `File > Export > As MPC Sample File`; en standalone, desde una pista Drum, `Mode Menu > Save > Save Drum Track As MPC Sample File`. La misma nota advierte que los proyectos standalone de 3.4–3.8 no son retrocompatibles con desktop 2.15. Eso no acredita la compatibilidad de cada archivo producido por BeatOS. [Notas oficiales de MPC 3.8, páginas 1–2](https://cdn.inmusicbrands.com/Software/AM20P3C8FWUPGZL12/MPC%203.8%20Release%20Notes.pdf).

La ficha y el manual inicial de Sample aún contienen el anuncio de una integración futura con MPC3. Para las operaciones incorporadas en 3.8 se toma la nota de esa versión como referencia más específica; no se convierte un anuncio antiguo en una prohibición vigente. Conserva el número de versión real de ambos extremos al comprobar un intercambio. [Especificaciones oficiales de MPC Sample](https://www.akaipro.com/guides/mpc-sample/technical_specifications.htm).

### Qué hace el exportador MPC de BeatOS

La opción `mpc` produce **dos entregas diferentes** en una operación:

| Entrega | Estructura | Alcance comprobable en el código |
| --- | --- | --- |
| Programa Drum XPM | `Akai_MPC/<kit>.xpm` y WAV junto al archivo. | XML construido con la plantilla Drum; asignación de muestras, volumen, panorama, afinación y mutes implementados. No equivale a un proyecto de MPC Sample. |
| Proyecto XPJ | `Akai_MPC/<kit>/<kit>.xpj` y `<kit>_[ProjectData]/`. | Gzip con JSON, derivado de la plantilla incluida. Esta declara `originalCreatorProductIdentifier=AC50`, `lastSavedProductIdentifier=AC50`, `engineMode=Sample` y `data.version=28`. Es una plantilla de la familia Sample, no un perfil independiente One/Live. |

La identificación AC50 coincide con el modelo publicado por Akai. Es evidencia de la procedencia estructural de la plantilla, no una certificación del fichero modificado por BeatOS. [Modelo AC50 en las especificaciones de Sample](https://www.akaipro.com/guides/mpc-sample/technical_specifications.htm).

El rack exporta los **16 pads visibles** como un kit nuevo. No convierte un proyecto completo del usuario ni preserva sus secuencias, automatizaciones, plugins, efectos, mezclador o cuatro capas por pad. Los campos y la secuencia base de una plantilla no son una copia de la canción original.

BeatOS no llama a la operación oficial «As MPC Sample File», no detecta el firmware del aparato y no elige automáticamente un esquema diferente para Sample, One, Live o X. El resultado debe cargarse y verificarse en una copia de trabajo.

Akai describe el XPM Drum como un programa de muestras asignadas a pads que se carga dentro de un proyecto. Esa función no lo convierte en el proyecto completo ni en el XPJ de Sample. [Programas y carga, soporte oficial Akai](https://support.akaipro.com/en/support/solutions/articles/69000804211-akai-pro-mpc-series-understanding-and-loading-programs).

### Matriz de modelos y familias MPC

| Modelo o familia | Ruta de trabajo con BeatOS | Qué no se debe suponer |
| --- | --- | --- |
| **MPC Sample (AC50)** | XPJ derivado de la plantilla Sample con su carpeta ProjectData; alternativa: cargar los WAV y asignarlos en el equipo. | Que un XPM sea su formato de proyecto o que admita un proyecto completo de otra MPC sin la exportación adecuada. |
| **MPC One / One+** | Programa XPM y WAV como entrega de kit; para el XPJ de procedencia Sample, revisar la ruta documentada en MPC 3.8. | Que todos los firmwares o motores anteriores lean ese XPJ. |
| **MPC Live / Live II / Live III** | Misma distinción entre programa XPM y proyecto de procedencia Sample; comprobar versión y referencias. | Que «Live» identifique una sola generación o compatibilidad bidireccional de proyectos. |
| **MPC X / X SE y Key 37 / Key 61** | Archivos de kit para el motor MPC; comprobar en la versión instalada la importación que corresponda. | Que compartir ecosistema reproduzca plugins, efectos o secuencias que BeatOS no exporta. |
| **MPC XL / Force** | Revisar el procedimiento específico del motor instalado antes de usar la entrega MPC. | Que el nombre del exportador sea una certificación de estos modelos. |
| **One G2 / Key 37 G2 u otras revisiones posteriores** | Comprobar sus notas oficiales y hacer una prueba con un kit pequeño. | Extender automáticamente la compatibilidad documentada para otra revisión de hardware. |
| **MPC Studio / Studio MKII** | Abrir los archivos en MPC Software en el ordenador; el controlador maneja ese software. | Que Studio sea un sampler standalone con una tarjeta donde cargar el proyecto. |
| **Renaissance y otros controladores** | La compatibilidad depende del software y controlador instalados en el ordenador; no existe un exportador BeatOS por controlador. | Que su aparición en comentarios históricos del repositorio garantice soporte actual de drivers. |
| **MPC60, 2000/2000XL, 1000/2500, 500, 4000/5000 y formatos heredados** | No hay exportador específico para estas generaciones. Usar sólo un flujo de audio/formato comprobado para el modelo. | Que XPM/XPJ modernos sean archivos nativos de estas máquinas o que el tema visual «Vintage» los convierta. |

La nota 3.8 enumera modelos concretos, incluidos One, Live, X, Key, XL y Force; no afirma que cada entrega BeatOS esté validada en ellos. Consulta también las [notas oficiales vigentes](https://www.akaipro.com/mpc-release-notes/) para revisiones posteriores. MPC Studio MKII se documenta como controlador de MPC Software en su [FAQ oficial](https://support.akaipro.com/en/support/solutions/articles/69000799777-akai-pro-mpc-studio-mkii-frequently-asked-questions).

### Carga y comprobación de una entrega MPC

1. Anota modelo exacto y versión de firmware/software. Conserva una copia de tu proyecto y trabaja con un nombre nuevo.
2. Genera un kit pequeño en BeatOS; elige `mpc`. No renombres un XPM como XPJ ni cambies extensiones para forzar la carga.
3. Para probar un **programa**, conserva el XPM y sus WAV juntos y cárgalo en el motor MPC que admita ese programa. Para probar el **XPJ**, copia la carpeta del proyecto completa con `_[ProjectData]` junto al XPJ.
4. En One/Live u otro motor MPC3 que vaya a abrir el XPJ Sample, comprueba la función documentada para la versión instalada. Si necesitas volver hacia Sample desde un proyecto de ese motor, usa su exportación oficial de pista Drum a Sample; BeatOS no sustituye ese paso.
5. Si el proyecto no carga, conserva el original, registra el error y usa los WAV para reconstruir el kit. No lo presentes como una conversión válida porque el archivo se haya generado.
6. Comprueba que cada pad reproduce su sonido, su posición, nivel, panorama, tono y grupo de mute. Guarda una copia desde el propio aparato y vuelve a abrirla antes de dar la prueba por terminada.

## 2. Native Instruments Maschine

### Modelos y diferencia entre controlador y standalone

**Maschine MK3, Mikro MK3 y Studio** se usan con el software Maschine del ordenador. La generación del controlador y sus drivers condicionan la versión de software que puedes usar; el exportador BeatOS no instala ni autoriza ese software. El flujo ordenador/controlador aparece en la [guía oficial Mikro](https://www.native-instruments.com/pages/maschine-mikro-quickstart). Para MK1/MK2 y otras generaciones, consulta la [compatibilidad oficial de Maschine 3](https://support.native-instruments.com/support/solutions/articles/69000879549-maschine-3-faq) antes de cambiar de versión.

**Maschine+** dispone de funcionamiento standalone. NI documenta almacenamiento y muestras de usuario en su [manual de Maschine+](https://docs.native-instruments.com/online-guides/maschine-plus-manual/en/working-with-maschine-). Los formatos y rutas admitidos dependen de su versión; existen diferencias entre los manuales del motor anterior y las [actualizaciones a Maschine 3](https://support.native-instruments.com/support/solutions/articles/69000879542-maschine-how-to-use-the-maschine-3-update-on-maschine-). La entrega BeatOS sigue siendo WAV a 44.1 kHz y mapa, aunque el motor admita más formatos.

| Familia NI | Aplicación de la entrega BeatOS |
| --- | --- |
| Maschine MK3, Mikro MK3 y Studio | WAV cargados en Maschine del ordenador y ajustes manuales desde el mapa. |
| Maschine Jam | Control del entorno Maschine; no es una unidad que reciba un proyecto de samples de BeatOS por sí sola. |
| Maschine+ | WAV en el almacenamiento de usuario y asignación en su motor standalone, o flujo del software en modo controlador. |
| Maschine MK1/MK2 y Mikro MK1/MK2 | NI indica que estos controladores no son compatibles con Maschine 3; un WAV generado no elimina el requisito de un software/driver compatible anterior. |

La distinción de generaciones y el soporte de MK3, Studio, Jam y Plus procede de la [FAQ oficial de Maschine 3](https://support.native-instruments.com/support/solutions/articles/69000879549-maschine-3-faq), no del nombre genérico del exportador.

### Carga del kit

1. Genera con destino `maschine`.
2. Conserva `NI_Maschine/<kit>/Samples/Group_A/` y `Groups/<kit>_Maschine_Map.json`.
3. En ordenador, carga los WAV en los Sounds de un grupo vacío. En Maschine+, transfiere los WAV al almacenamiento de muestras de usuario admitido por su versión y cárgalos desde su navegador. La carpeta generada por BeatOS no se instala automáticamente como expansión NI.
4. Usa `slot`, `file`, `volume`, `pan`, `tune` y `choke_group` del mapa como referencia para la asignación y los ajustes; interpreta sus escalas según la referencia técnica.
5. Guarda el grupo/proyecto **desde Maschine** si quieres su formato nativo.

BeatOS no genera `.mxgrp`, patrones, escenas, cadenas de plugins ni proyectos Maschine. El JSON no se importa como grupo nativo. Los WAV conservan los niveles originales: los ajustes del rack van en el mapa, no están procesados en esos WAV.

## 3. Roland SP-404MKII / SP-404MK2

BeatOS usa la clave `sp404mk2` y escribe WAV PCM 16-bit/48 kHz en `Roland_SP404MK2/<kit>/`, con nombres `PAD_01_…wav` y un manifiesto. `pad`, `file` y `original` describen el origen; no son una instrucción que el SP ejecute automáticamente.

Roland distingue importación por SD y por aplicación. Su soporte confirma conversión interna a 48 kHz/16-bit y posibles problemas con sonidos inferiores a 100 ms. La aplicación permite arrastrar muestras a pads y advierte que cargar sobre un pad ocupado lo sobrescribe. [Formatos oficiales](https://support.roland.com/hc/en-us/articles/4408190553883-SP-404MK2-What-audio-file-formats-can-be-imported-into-the-SP-404MK2) · [Manual oficial de la aplicación, importar muestras](https://static.roland.com/assets/media/pdf/SP-404mk2_app_eng02_W.pdf).

1. Genera `sp404mk2`; instala FFmpeg si tus fuentes no son ya PCM compatibles a 48 kHz.
2. Revisa los WAV y el manifiesto antes de transferirlos.
3. Usa la importación por SD del firmware instalado o arrastra los WAV a pads libres en la aplicación oficial. Un nombre `PAD_05` no garantiza asignación automática al pad 5; compruébala.
4. Ajusta en el SP volumen, panorama, afinación, modos de disparo y mutes que necesites. BeatOS no los transmite en un proyecto SP.
5. Guarda y verifica desde el aparato. No confundas estos WAV con un backup ni con «IMPORT PROJECT» de Roland.

**DOOM OS:** el selector de BeatOS lo menciona, pero no existe un exportador separado, un protocolo ni una prueba de carga de ese sistema en el repositorio. Se genera la misma carpeta de WAV; no se certifican funciones de firmware alternativo.

## 4. Roland SP-404A y SP-404SX

El destino `sp404a` genera WAV PCM 16-bit/44.1 kHz `A01.wav`–`A12.wav`, sólo para posiciones ocupadas del rango 1–12. **Los pads 13–16 del rack no se incluyen.** Tampoco se genera mapa JSON, patrón o backup nativo.

Para SX, Roland documenta copiar WAV/AIFF a `ROLAND/IMPORT`, usar `FUNC + pad 3`, elegir banco/pad y confirmar con REC. Puede sobrescribir muestras. Su manual indica importación por orden de nombre y retirada de los archivos importados de esa carpeta; el nombre del archivo no preserva por sí solo huecos entre pads. [Procedimiento oficial SX](https://support.roland.com/hc/en-us/articles/201977679-SP-404SX-Importing-Samples) · [Manual SX, página 36](https://cdn.roland.com/assets/media/pdf/SP-404SX_OM.pdf).

Para A, consulta las instrucciones de importación de su [manual oficial](https://static.roland.com/assets/media/pdf/SP-404A_eng01_W.pdf); no uses combinaciones de teclas de MKII como si fueran las de A/SX.

1. Coloca los sonidos necesarios en los pads 1–12 y exporta `sp404a`.
2. Conserva una copia de la tarjeta y de los WAV exportados. Usa una tarjeta preparada para tu modelo sin formatear la única copia de tus datos.
3. Prepara `ROLAND/IMPORT` según el manual del aparato. No vuelques en ella todos los destinos del bundle.
4. Si el kit tiene huecos, importa/asigna de forma controlada y comprueba cada posición: el exportador no crea WAV silenciosos de relleno.
5. Reproduce los doce pads y ajusta en el SP los parámetros y mutes.

El **SP-404 original** usa otro procedimiento y CompactFlash; no tiene perfil BeatOS dedicado. Que pueda recibir ciertos WAV no convierte la carpeta `sp404a` en un proyecto para ese equipo. [Importación oficial del SP-404 original](https://support.roland.com/hc/en-us/articles/201960319-SP-404-Importing-WAV-AIFF-Files-From-a-Computer).

## 5. Teenage Engineering PO-33 K.O! y PO-133

BeatOS genera **un reel de audio**, no un archivo que se copie al PO por USB o tarjeta. Los manuales del fabricante describen 40 s de memoria compartida y grabación por LINE IN; en la sección de batería las teclas disparan cortes del sonido grabado. [Guía PO-33](https://teenage.engineering/guides/po-33/en) · [Guía PO-133](https://teenage.engineering/guides/po-133/en).

1. Consulta los segundos libres del PO. En el Hub de BeatOS indica ese presupuesto, entre 1 y 40 s, y pausas entre 0 y 500 ms. La exportación general usa 40 s/150 ms; no consulta el dispositivo.
2. Genera o preescucha el reel. Revisa en `<kit>_PO33_Slices.json` la duración, cortes y si se ha aplicado recorte.
3. Conecta una salida de audio del ordenador/interfaz a LINE IN. Prueba primero el nivel sin saturar; no existe un porcentaje universal válido para todas las salidas.
4. Graba el reel en un slot de batería elegido, siguiendo RECORD + slot 9–16. Los hasta 16 golpes del reel son cortes dentro de ese sonido: no son 16 slots independientes transferidos con metadatos.
5. Revisa TRIM de cada corte y reproduce el kit. Las pausas favorecen la separación, pero no garantizan un corte automático perfecto.

El reel es mono PCM 16-bit/44.1 kHz. El exportador procesa tono y volumen y normaliza el conjunto; pierde panorama y grupos de mute. Si el audio no cabe, puede recortar las colas con fade-out. Los huecos del rack no crean cortes vacíos: el manifiesto relaciona `slice_number` con `source_pad`.

Los WAV de **backup por módem** son otro flujo. El Hub permite captura estéreo PCM, importación/archivo original con SHA-256 y preparación de un reproductor detenido para restaurar tras confirmación. Comprueba estructura WAV y amplitud inicial acotada, pero no decodifica los datos ni acredita la recepción. La captura interrumpida se conserva como INCOMPLETO y debe repetirse. [Recorrido completo de captura, recuperación, archivo y restauración](MANUAL_COMPLETO.md#12-respaldos-po).

**Otros Pocket Operators:** el tema PO-20 no implica un exportador; no hay perfiles específicos para PO-12, PO-14, PO-16, PO-20, PO-24, PO-28, PO-32, PO-35 o PO-137. No extrapoles el reel y el procedimiento del PO-33 a otros motores.

## 6. Teenage Engineering EP-133 K.O. II

El destino `ep133` produce muestras en `sounds/`, un `meta.json`, `README_EP133_KO_II.txt` y `<kit>_EP133.zip`. Los WAV son PCM 16-bit/44.1 kHz, mono/estéreo según la fuente. El mapa contiene datos del rack; no se aplican automáticamente al importar el audio.

1. Genera `ep133` desde el rack o el Hub EP.
2. Extrae el ZIP si usas esa entrega. El ZIP de BeatOS es transporte de archivos, no un backup de proyecto o sistema EP.
3. Conecta el aparato por USB-C con un cable de datos. Abre [EP Sample Tool](https://teenage.engineering/apps/ep-sample-tool), autoriza el acceso que solicite y usa un navegador de escritorio compatible con Web MIDI. Consulta el apartado [Sample Tool de la guía oficial](https://teenage.engineering/guides/ep-133/functions).
4. Importa los WAV en posiciones libres o decide expresamente cuáles reemplazar. Los prefijos numéricos de BeatOS son referencias, no una reserva de IDs en el aparato.
5. Aplica el mapa: pads 1–12 → grupo A, teclas 1–9, punto, 0, ENTER; pads 13–16 → grupo B, teclas 1–4. Ajusta volumen, panorama, tono y mute en el EP según tu uso.
6. Guarda y vuelve a cargar el trabajo desde el equipo/herramienta oficial. BeatOS no instala firmware ni gestiona el almacenamiento interno del EP.

La guía oficial consultada se identifica como versión 2.5 y anuncia 128 MB; esto no garantiza memoria libre ni describe todas las versiones anteriores. El audio de intercambio a 44.1 kHz elegido por BeatOS no debe confundirse con la frecuencia de grabación interna del aparato. [Guía oficial EP-133](https://teenage.engineering/guides/ep-133).

No hay perfiles BeatOS separados para EP-1320, EP-40, EP-133 de otra edición u otros productos EP. Antes de reutilizar WAV, confirma el procedimiento del modelo; no reutilices un mapa de teclas como si fuera un backup compatible.

## 7. Registro mínimo de una prueba física

Para declarar una entrega comprobada, anota: versión/commit de BeatOS, destino, nombre del kit, modelo exacto, firmware/software, método de transferencia, formatos de origen, parámetros utilizados, resultado por pad y resultado después de guardar y reabrir. Incluye qué no se pudo probar. Una carga sin error no acredita todavía niveles, tono, mutes, cortes o referencias.

Prueba con un kit pequeño que incluya golpes cortos/largos, una muestra estéreo, un pad vacío, tono distinto de cero y dos sonidos del mismo mute. En A/SX comprueba los límites de 12 pads y los huecos; en PO, presupuesto y cortes; en MPC, distingue XPM de XPJ. Mantén esa prueba separada de tu proyecto principal.

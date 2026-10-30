# BeatOS — Auditoría técnica y documental ES/EN

**Proyecto:** BeatOS — The MakerLicious · **Rama auditada:** `main` · **Fecha:** 30 de octubre de 2026  
**Responsable de las modificaciones:** revisión técnica asistida con GitHub Actions; **no es un certificado independiente**.

**Idiomas:** [Español](MANUAL_COMPLETO.md) · [English manual](en/MANUAL_COMPLETO.md)  
[Compatibilidad ES](COMPATIBILIDAD_HARDWARE.md) · [Hardware EN](en/COMPATIBILIDAD_HARDWARE.md)

## 1. Alcance y principio de evidencia

Se inspeccionaron el código de la interfaz (`templates/catalogo.html`), instalador Python, estructura de empaquetado, tests automáticos, README, manuales, guías de compatibilidad y navegación ES/EN. Las pruebas se ejecutan en el repositorio de GitHub sobre muestras **sintéticas**, sin copiar bibliotecas personales ni sobrescribir equipos del usuario.

**Criterio:** distinguir (a) fuente modificada, (b) test automatizado superado, (c) experiencia gráfica en navegador, (d) compatibilidad en hardware real y (e) ZIP estable publicado. Un resultado en (a) o (b) no demuestra (d) ni actualiza automáticamente (e).

## 2. Hallazgos corregidos

| ID | Hallazgo | Corrección | Evidencia / límite |
| --- | --- | --- | --- |
| I18N-01 | Solo parte de los paneles de la interfaz se traducían; faltaban decenas de textos estáticos en PO, EP, rack, mantenimiento y ayuda. | Se amplió el diccionario reversible a **354 entradas de texto UI** y **93 patrones/mensajes** (recuento de entradas, no porcentaje de cobertura global). | Barrido estático heurístico sin cadenas candidatas remanentes en la plantilla examinada; no certifica todos los mensajes generados en ejecución. |
| I18N-02 | La navegación ES→EN→ES no tenía una prueba de navegador real. | Prueba Chrome headless por HTTP con biblioteca sintética: PO, EP-133, mantenimiento, editor y conservación de nombre de archivo. | `tests/smoke_browser_i18n.py`, job `browser-locale`; revisar run del commit. |
| I18N-03 | Guardar o recuperar idioma podía lanzar una excepción si el navegador bloqueaba localStorage. | Lectura/escritura defensivas: la sesión sigue operativa, aunque sin persistir la preferencia cuando el almacenamiento está restringido. | `tests/test_i18n.cjs`. |
| I18N-04 | El instalador no traducía correctamente una pregunta de confirmación con salto de línea. | Diccionario corregido y test de pregunta EN con salto real; disponible mediante `--lang en` o `BEATOS_LANG=en`. | `tests/test_installer_language.py`. |
| AUDIO-01 | El deslizador de ganancia llegaba a **150 %**, pero `savePadEditor` dividía por 141,25 y podía generar ganancia >1 rechazada por el exportador. | Máximo visual **141 %**, equivalente a ≈0,998 de ganancia; el resto de validaciones API continúa intacto. | Test de regresión en `tests/test_i18n.cjs`; manuales ES/EN actualizados. |
| DOC-01 | Enlaces al nombre histórico del repositorio y cruces ES/EN incompletos. | Se corrigieron enlaces documentales, añadieron índices y capítulos equivalentes ES/EN. | `tests/test_documentation_links.py` recorre rutas locales y tolera paréntesis en los nombres. No comprueba disponibilidad de URLs externas. |
| DOC-02 | Cinco documentos complementarios sin equivalente EN; una referencia permanecía en 3.7.0 y el recuento fijo de tests era obsoleto. | Se publicaron cinco guías adicionales en inglés, enlaces recíprocos, versión 3.8.0 en la página histórica y texto de verificación actualizado. | `docs/en/` y `docs/wiki/en/`. |
| DIST-01 | El empaquetador de desarrollo no incluía la guía de instalación inglesa. | Se añadió `GUIA_INSTALACION_EN.md` al allowlist y se configuró la carga de ZIP de **desarrollo** a GitHub Actions. | `build_release.py` y workflow `checks.yml`. |
| DOC-03 | Ciertas instrucciones/UI insinuaban compatibilidad DOOM OS no implementada o asignación automática de pads. | Se sustituyeron por advertencias verificables sobre importar WAV manualmente y no certificar un perfil DOOM OS. | La matriz de hardware distingue archivo, firmware y prueba física. |

### 2.1 Cobertura documental organizada

- Manual de usuario: **20 secciones ES y 20 EN**.
- Wiki: **11 guías temáticas ES y 11 EN**, con índices de navegación por idioma.
- Referencia técnica, compatibilidad, instalación: versión en **ambos idiomas**.
- Cinco documentos complementarios de proyectos, estructura, identificación, identidad/apoyo y verificación: **ES y EN**.
- Nombres de muestras, rutas privadas, credenciales y títulos del usuario **no deben traducirse ni publicarse**.

## 3. Pruebas y trazabilidad

El pipeline `checks.yml` incorpora:

1. Pruebas Python en **3.11 y 3.14** (indexador, servidor, instalador, parsers, muestras y regresiones).
2. Tests Node de interfaz, audio, mutes, PO backups y localización reversible.
3. Test de enlaces locales Markdown para todos los documentos del repositorio.
4. Empaquetado limpio del ZIP y manifiesto SHA-256.
5. Instalación e indexación **con samples sintéticos** en ejecutor Windows; prueba tanto el ZIP estable descargado como un ZIP generado de fuentes.
6. Smoke de **Chrome real** sobre un catálogo sintético y HTTP localhost, comprobando vuelta ES→EN→ES.
7. Publicación de artefactos **BeatOS-main-py3.11** y **BeatOS-main-py3.14** desde el código actual cuando termina correctamente la compilación.

**Referencia de una ejecución correcta con navegador real:** [GitHub Actions 41090423715](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/actions/runs/41090423715). Para cambios posteriores, **exigir una ejecución correcta del commit exacto**, no reutilizar el éxito de un commit antiguo.

## 4. Límites y trabajo aún no certificado

| Prioridad | Pendiente | Motivo |
| --- | --- | --- |
| **P0 · Localización integral** | Traducción exhaustiva y verificable de **todos** los errores generados por `serve_mpc.py`, `hardware_kit_builder.py`, CLI del indexador y procesos auxiliares. | Los diccionarios de la interfaz no traducen necesariamente los detalles arbitrarios del backend. **No declarar 100 % ES/EN hasta cerrar esta cobertura y hacer pruebas de errores inducidos**. |
| **P1 · Distribución pública** | Publicar una **nueva release estable** con el ZIP reconstruido y checksums, después de inspeccionar los artefactos actuales. | Una modificación de `main` no reemplaza `BeatOS-3.8.0.zip` de la release previa. Los ZIP de Actions son builds de desarrollo; no anunciarlos como estables. |
| **P1 · Hardware** | Validación física con modelo y firmware de cada perfil (MPC, Maschine, SP-404MKII, SP-404A/SX, PO-33/PO-133 y EP-133). | Las pruebas con archivos sintéticos no validan carga, mutes, tono, clips, almacenamiento, FSK o recuperación real. |
| **P1 · Plataformas y rendimiento** | Revisión visual/accesibilidad y rendimiento con bibliotecas voluminosas en Safari, Firefox y Windows/macOS. | Una prueba Chrome/Linux es evidencia de integración específica, no compatibilidad universal. |
| **P2 · Visibilidad orgánica** | Comprobar indexación externa en Google y mejorar títulos/resúmenes/temas del repositorio. | Google rastrea a su propio ritmo; un README no garantiza indexación ni ranking. |

## 5. Requisitos para cierre definitivo

**NO se considera completada una certificación integral mientras queden P0/P1 sin pruebas.** Para cerrar deben existir: tests que induzcan errores en ambos idiomas; ejecución CI verde del commit final; revisión gráfica y de accesibilidad; ZIP de nueva release con SHA-256 comprobado; pruebas físicas documentadas para los dispositivos que se pretendan anunciar como certificados.

El objetivo es publicar software usable por beatmakers y productores sin confundir archivo generado, proyecto nativo, firmware compatible o restauración validada. Esta auditoría registra cambios y límites de manera explícita, sin convertir hipótesis o una CI verde en garantía universal.

## 6. Adenda — segunda auditoría y ejecución de pruebas (30/10/2026)

**Commit con CI completamente superada:** `db6101c15ed4c7e5c38ec498f6b51cc34f5d425c`. [Ejecución GitHub Actions #41094521144](https://github.com/Astro1Deep/BeatOS-TheMakerLicious/actions/runs/41094521144): Python 3.11, Python 3.14, Chrome headless ES→EN→ES, Windows y generación de ZIP de desarrollo terminan correctamente. Hay artefactos `BeatOS-main-py3.11` y `BeatOS-main-py3.14`; **no constituyen un nuevo release estable**.

### 6.1 Fallos adicionales reproducidos y corregidos

- **API-LOCALE-01:** errores JSON y estado de tareas solo en español. `beatos_i18n.py` y el serializador JSON del servidor presentan un error traducido por petición cuando la preferencia es EN, y conservan el original en `error_es`; los registros originales permanecen en `logs_es`. La preferencia se transmite mediante cookie de idioma `beatos_locale` con SameSite=Strict o cabecera explícita `X-BeatOS-Language` (prioritaria). Ningún nombre de sample o ruta de origen se traduce. La traducción es por reglas reconocidas; los errores desconocidos devuelven texto genérico en inglés y el detalle original en `error_es`.
- **INDEX-LOCALE-02:** salida del indexador en español aunque el instalador se seleccionase en inglés. El indexador admite `--lang es|en` o `BEATOS_LANG`; se traducen las fases principales, rutas informativas, nombres de campos de proyectos y expansiones; el instalador transmite temporalmente la preferencia al indexador y al servidor y restaura el entorno anterior al terminar.
- **CLI-REGRESSION-03:** la primera implementación del helper de salida entraba en recursión, lo que impedía indexar también en Windows. El error fue reproducido por CI y corregido en el código real; los tests de indexación y entrega posteriores ya pasan.
- **SERVER-LOCALE-04:** mensajes de inicio/parada del servidor con nombres de carpeta y estado de conexión españoles; traducidos cuando el entorno se selecciona en inglés.
- **VALIDATION-LOCALE-05:** errores comunes de exportador sin traducción (tempo, ganancia/pad, ausencia de samples, WAV, FFmpeg); se añadieron traducciones específicas y tests de preservación de números e identificadores.
- **BROWSER-LOCALE-06:** la prueba de Chrome verifica que la cookie ES/EN se actualiza al cambiar de idioma y que se conservan los nombres de samples.

**Cobertura de regresión:** `tests/test_server_language.py`, `tests/test_index_language.py`, `tests/test_installer_language.py`, `tests/test_i18n.cjs` y `tests/smoke_browser_i18n.py`. Los resultados deben asociarse al commit indicado, no inferirse de un estado anterior.

### 6.2 Declaración de alcance y pendientes que no deben ocultarse

- **La interfaz no está certificada al 100 %:** la cobertura estructural de la plantilla y la prueba en Chrome son positivas, pero no existe todavía un recorrido exhaustivo de todas las variantes dinámicas, accesibilidad/teclado y navegadores en cada plataforma.
- **Los detalles internos de errores desconocidos del backend no están traducidos exhaustivamente:** para EN se presenta un mensaje genérico en inglés y el diagnóstico original en `error_es`; algunas líneas de salida técnica de procesos auxiliares pueden conservar español en `logs` si no existe correspondencia. Evitar anunciar «100 % localizado» hasta cubrir casos raros con pruebas de errores inducidos.
- **Falta una release estable revisada y firmada:** los ZIP de Actions son builds de desarrollo y se deben tratar como tales. Deben publicarse una versión nueva y su SHA-256 verificable, preservando la release anterior para rollback.
- **No se certifica compatibilidad física en todos los samplers/firmwares:** los tests actuales son sintéticos; cargar en MPC, Maschine, SP-404, PO y EP y verificar guardado/reapertura requiere dispositivos reales y registro de modelo/firmware.

**Regla de cierre:** «CI verde» acredita que las pruebas existentes pasan; no demuestra ausencia absoluta de defectos, localización total ni seguridad de cada dispositivo. Se recomienda no etiquetar como estable una nueva versión antes de cerrar los P0 realmente observables y probar el ZIP final descargable.


## 7. Continuación de auditoría — localización dinámica y estabilidad del pipeline (30/10/2026)

Esta ampliación se realizó sobre el último estado auditado y registra los defectos encontrados con pruebas reproducibles. **Ningún resultado de CI se presupone para commits posteriores sin inspeccionar su ejecución.**

| Código | Hallazgo reproducible | Reparación aplicada | Verificación |
| --- | --- | --- | --- |
| P0-PO-MENSAJES | Los textos dinámicos de grabación, importación, estado de copia, restauración y errores PO podían quedar en español con UI inglesa. | Se añadió traducción de estados críticos al mostrarse y tratamiento explícito de mensajes dinámicos con SHA-256, sin modificar el hash ni el WAV. | `tests/test_i18n.cjs`, pruebas de confirmación de restauración y estructura de backups. |
| P0-PO-IDIOMA | Una advertencia PO ya visible no cambiaba automáticamente de idioma cuando se pulsaba ES/EN. | Se conserva el texto canónico del último aviso y se vuelve a renderizar en el idioma activo. | Regresión ES→EN→ES en `tests/test_i18n.cjs`. |
| P1-EXP-TARJETAS | Las tarjetas de expansión creadas dinámicamente mantenían botones, accesibilidad y mensaje sin resultados en español. | `renderExpansionProgramsList` genera directamente textos ES/EN; conserva exactamente el nombre y ruta de cada programa. Se rerenderiza la vista si el selector cambia con el modal abierto. | Regresión de renderizado de cards y controles de expansión en `tests/test_i18n.cjs`. |
| P1-WINDOWS-CI | La descarga de release estable consultaba la ruta antigua `Astro1Deep/mpc-sample-database` y podía agotar cuota API tras la redirección. | Se usa `Astro1Deep/BeatOS-TheMakerLicious` directamente en el workflow, conservando autorización de la API. | CI Windows `windows-release-install`, también verifica el ZIP de fuente actualizado. |

**Evidencias intermedias confirmadas:** el commit `427bcff292be6d836bfb2d29be3d5bca4629f8dc` pasó los cuatro trabajos de CI después de reparar la consulta de release; el commit `2e5f7d1c895b2369054b59e990e1de9a97c445cc` pasó los cuatro trabajos después de corregir las tarjetas de expansiones. **Para aceptar los cambios posteriores de avisos PO, es necesaria una CI verde asociada al último commit.**

### 7.1 Cierre técnico parcial, no certificación absoluta

- **Localización:** las pantallas principales, capturas y estados PO, API JSON e indexador están cubiertos por pruebas, pero aún pueden existir excepciones de errores poco frecuentes o bibliotecas de terceros sin traducción. El diseño conserva `error_es` para inspección y muestra un mensaje genérico EN cuando no existe una equivalencia verificada.
- **Distribución:** el paquete de **desarrollo** se genera y prueba en CI; la antigua release estable **no se ha sustituido**. Antes de anunciar una versión pública nueva hace falta publicar assets, comprobar hashes y verificar la versión descargable final.
- **Hardware:** MPC, Maschine, SP-404MKII/A/SX, PO-33/PO-133 y EP-133 requieren validación real por modelo y firmware, guardado y reapertura; ningún test sintético demuestra compatibilidad física universal.
- **Accesibilidad y portabilidad:** una comprobación Chrome headless no acredita por sí sola Safari, Firefox ni accesibilidad integral en macOS/Windows.

**Estado global:** se han reparado defectos funcionales y de documentación, con trazabilidad de pruebas y rollback por commit. El objetivo de «cero errores» no es certificable en un sistema no trivial; corresponde exigir ausencia de defectos críticos conocidos, pruebas reproducibles y declaración honesta de los límites.

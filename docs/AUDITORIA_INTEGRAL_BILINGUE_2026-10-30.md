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

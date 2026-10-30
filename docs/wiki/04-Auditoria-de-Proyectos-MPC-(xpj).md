# Proyectos MPC: inspección, bancos y ajustes

Abre BeatOS por HTTP desde `BeatOS/ABRIR_BEATOS.command`. Las páginas abiertas como archivo permiten explorar el catálogo, pero el servidor rechaza sus operaciones. La interfaz muestra la biblioteca activa para distinguir el Mac de la tarjeta.

La pestaña Proyectos permite buscar, recargar el catálogo, mostrar/copiar la ruta e inspeccionar pistas de batería. Se carga la ruta registrada, sin adivinar ubicaciones ni sustituirla por muestras elegidas por nombre.

Para proyectos gzip/ACVS JSON compatibles se conserva el orden de pads, huecos, asignaciones repetidas y grupos de mute explícitos. Puedes elegir pista y banco A–H. Cada banco se edita en el rack de 16 pads; los ajustes quedan en memoria al cambiar de banco. Cambiar de pista/origen vuelve a importar sus valores; recargar el origen descarta la copia de trabajo. Exporta antes de cambiar de proyecto o cerrar la página.

Volumen, panorama, afinación y mutes se ajustan por pad. El tempo elegido se exporta al nuevo XPJ. La exportación crea un kit nuevo con los 16 pads visibles: no sobrescribe el original y no reproduce sus secuencias, efectos, automatizaciones o capas múltiples. La interfaz muestra muestras ausentes y pads multicapa; usa sólo la primera capa activa para esta copia. Los programas Keygroup requieren el motor MPC.

El estado del índice informa de referencias de archivo, no certifica reproducción física. `ERROR` señala un archivo que no se pudo leer; `ATTENTION`, referencias ausentes; `INDEX_OK`, referencias encontradas por el indexador. La inspección en vivo comprueba las muestras de la pista seleccionada. Una referencia ambigua no se sustituye por otra muestra con el mismo nombre.

«Recargar proyectos» vuelve a leer el catálogo guardado sin vaciar el rack. «Reindexar» reconstruye metadatos y actualiza el catálogo único en BeatOS/data/ y sus dos accesos HTML en la raíz. No modifica los proyectos ni ejecuta reparaciones del sistema.

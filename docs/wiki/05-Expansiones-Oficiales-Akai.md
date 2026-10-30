# Expansiones MPC

BeatOS lee los metadatos disponibles de Expansion.xml y cataloga sus archivos. La tarjeta conserva las carpetas existentes. El navegador de programas del servidor busca bajo `Expansions/`; no instala ni redistribuye packs comerciales.

Cada tarjeta de expansión permite:

- **Ver programas:** lista los XPM legibles, incluidos los de subcarpetas. Drum permite editar una copia; Keygroup mantiene las acciones de archivo y muestra para preescucha, pero requiere el motor MPC.
- **Ver proyectos:** abre en Proyectos los XPJ indexados de la carpeta exacta del paquete, incluidos demos y plantillas anidados. Muestra el número real de archivos del índice. No confunde carpetas con nombres similares.
- **Explorar samples:** filtra el catálogo por la carpeta del paquete; permite preescuchar y asignar al rack.
- **Mostrar en Finder / Copiar ruta:** localiza el contenido original.

«Ver todos los proyectos» elimina el filtro del paquete. Buscar, ordenar, paginar y recargar siguen disponibles. Recargar lee el catálogo guardado; tras añadir o quitar archivos, reindexa la biblioteca para actualizarlo.

Los recuentos de programas pueden incluir XPM, PGM y AKP; el inspector editable se limita a XPM Drum. Los proyectos XPJ compatibles se inspeccionan por pista de batería y banco. Una expansión puede no contener proyectos; un XPJ puede requerir plugins o recursos externos y no tener una batería editable.

El rack crea una copia de la primera capa activa por pad. No reproduce las secuencias, efectos ni plugins del proyecto original. Para escuchar el proyecto completo, abre su archivo con MPC y sus recursos originales.

[Inspección de proyectos](04-Auditoria-de-Proyectos-MPC-(xpj).md) · [Ajustes y exportación](08-Universal-Hardware-Beatmaker-Rack-(MPC-Maschine-SP404-PO33).md)

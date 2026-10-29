# Organización de BeatOS

```text
Biblioteca/
├── catalogo_universal.html       acceso ligero
├── catalogo_mpc_sample.html      acceso compatible
├── BeatOS/
│   ├── ABRIR_BEATOS.command      inicio en macOS
│   ├── installer.py / install.sh
│   ├── serve_mpc.py / index_mpc_library.py
│   ├── hardware_kit_builder.py / beatos_paths.py
│   ├── templates/ / docs/ / tests/
│   ├── data/                    SQLite, CSV, JSON y catálogo único
│   └── config/                  preferencias locales
└── carpetas musicales existentes
```

El programa no distribuye archivos de código por la biblioteca ni crea nuevos índices antiguos. No genera bytecode en la tarjeta. Los archivos .db-wal/.db-shm son componentes temporales legítimos de SQLite y, si son necesarios, permanecen en data/. Los kits son contenido musical y siguen en Custom_Kits/. Las carpetas ocultas de macOS se mantienen bajo control del sistema operativo.

Los enlaces HTTP antiguos de catálogos SQL/INDEX continúan abriendo el catálogo actual sin recrear carpetas ni copias. Las rutas de comandos antiguos se sustituyen por BeatOS/ABRIR_BEATOS.command o por los scripts de BeatOS/. La estructura interna de BeatOS no se sirve por HTTP, salvo el catálogo y los recursos gráficos; la base, configuración y código no se exponen mediante rutas estáticas ni descargas genéricas.

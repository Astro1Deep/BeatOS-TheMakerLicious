# Choosing libraries, removable disks and optional integrations

**BeatOS 3.8.0 · English** · [Español / Versión española](../11-Auto-Reconocimiento-y-Onboarding-de-Discos.md) · [Complete English manual](../../en/MANUAL_COMPLETO.md#15-maintenance-and-integrations) · [Hardware compatibility](../../en/COMPATIBILIDAD_HARDWARE.md)

BeatOS uses the library path explicitly chosen during indexing and server startup; this can be a local folder or any mounted disk. Always verify **Active Library** before generating outputs or reindexing. The historical label MPCSMPL reflects a past environment and is **not a required SD-card name**. Cerebro OS, DJProducerTools and external dashboard/theme sync are **optional integrations**, not components required to search and export a kit. Legacy maintenance scripts are separate and can modify files or service state; do not run them as routine read-only diagnostics. To switch to a second library, stop the server, index the new location, and start the server explicitly against the new root. Your audio is not moved automatically.

---

[English documentation index](../Home_EN.md) · [Installation](../../../GUIA_INSTALACION_EN.md) · [Technical API / SQLite reference](../../en/REFERENCIA_TECNICA.md)

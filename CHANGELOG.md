# Changelog

Todos los cambios notables de PyTSGenerator se documentan en este fichero.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el versionado usa [Semantic Versioning](https://semver.org/lang/es/).

---

## [1.1.0] — 2025

### Añadido
- Arquitectura modular completa con `BaseModule` y `MODULES_REGISTRY`.
- Estado global compartido (`session`) para credenciales HDA entre módulos.
- Sistema de logging rotativo a fichero (`logs/pytsgenerator.log`).
- Panel de notificaciones persistente con niveles `info / success / warning / error`.
- Toast clicable con cierre anticipado.
- Panel de bienvenida con flujo de trabajo guiado y estado de dependencias.
- Indicador de sesión HDA en la barra superior.
- `ReprojectMixin`: reproyección de CRS opcional tras descarga.
- `CropMixin`: recorte al área de interés mediante shapefile tras descarga.
- Soporte de interpolación bilineal en extracción por puntos (`scipy`).
- Validación de dependencias críticas al arranque con diagnóstico en UI.

### Modificado
- Refactorización de los módulos de descarga en `DownloadBaseModule` (~80 % de código duplicado eliminado).
- Normalización de nombres de módulos y atributos (`NAME`, `ICON`, `DESCRIPTION`).

---

## [1.0.0] — 2026

### Añadido
- Primera versión funcional con módulos independientes por script.
- Descarga de productos STPPI y HR-VPP desde WEkEO HDA.
- Renombrado de TIFs con extracción de fecha `YYYYMMDD`.
- Agregación zonal básica (media, mediana, percentiles) sobre polígonos.

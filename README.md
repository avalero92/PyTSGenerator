# 🛰️ PyTSGenerator

**PyTSGenerator** es una herramienta de escritorio modular desarrollada en Python para la generación automatizada de series temporales de teledetección a partir de productos del *Copernicus Land Monitoring Service* (CLMS). Proporciona un flujo de trabajo guiado que abarca desde la descarga de imágenes hasta la extracción de estadísticos zonales sobre geometrías vectoriales.

> Desarrollado por **Alexey Valero-Jorge** --- Centro de Investigación y Tecnología Agroalimentaria de Aragón (CITA).

------------------------------------------------------------------------

## Características principales

-   **Descarga de productos STPPI** (*Short-Term Plant Phenology Indicator*) desde la API HDA de WEkEO/Copernicus.
-   **Descarga de productos HR-VPP** (*High-Resolution Vegetation Phenology and Productivity*) con soporte para múltiples tipos de producto (SOSD, EOSD, MAXD, MINV, MAXV, AMPL, LENGTH, SPROD, TPROD, QFLAG2).
-   **Renombrado normalizado** de archivos TIF, extrayendo la fecha `YYYYMMDD` del nombre original para facilitar el manejo de series temporales.
-   **Agregación zonal** sobre GeoTIFFs: extracción de estadísticos (media, mediana, desviación estándar, percentiles, suma ponderada, etc.) usando geometrías vectoriales (polígonos o puntos).
-   **Post-procesado opcional** tras la descarga: reproyección de CRS y recorte al área de interés mediante shapefile.
-   Interfaz gráfica de escritorio (*tkinter*) con sistema de notificaciones, log rotativo y flujo de trabajo guiado.

------------------------------------------------------------------------

## Flujo de trabajo recomendado

```         
[1] Descarga STPPI  →  [2] Descarga HR-VPP  →  [3] Renames HR-VPP  →  [4] Agregación Zonal
```

Cada paso es independiente y puede ejecutarse por separado.

------------------------------------------------------------------------

## Requisitos del sistema

-   **Python** ≥ 3.10
-   Sistema operativo: Windows, macOS o Linux
-   Cuenta activa en [WEkEO HDA](https://www.wekeo.eu/) para los módulos de descarga

------------------------------------------------------------------------

## Instalación

### 1. Clonar el repositorio

``` bash
git clone https://github.com/avalero92/PyTSGenerator.git
cd PyTSGenerator
```

> Sustituye `YOUR_USERNAME` por tu usuario de GitHub cuando publiques el repositorio.

### 2. Crear un entorno virtual (recomendado)

``` bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 3. Instalar dependencias

``` bash
pip install -r requirements.txt
```

### 4. Ejecutar la aplicación

``` bash
python main_app.py
```

------------------------------------------------------------------------

## Dependencias

| Paquete     | Uso                                                   | Obligatorio |
|-------------|-------------------------------------------------------|-------------|
| `rasterio`  | Lectura/escritura de GeoTIFFs y máscaras              | ✅ Sí       |
| `geopandas` | Carga de archivos vectoriales (Shapefile, GeoJSON...) | ✅ Sí       |
| `numpy`     | Cálculo de estadísticos en la agregación zonal        | ✅ Sí       |
| `scipy`     | Interpolación bilineal en extracción por puntos       | ✅ Sí       |
| `hda`       | Acceso a la API HDA de WEkEO (descargas Copernicus)   | ✅ Sí\*     |
| `keyring`   | Almacenamiento seguro de credenciales HDA             | ⚠️ Opcional |

> \* Sólo necesario para los módulos de descarga (STPPI y HR-VPP). Los módulos de renombrado y agregación zonal funcionan sin conexión.

------------------------------------------------------------------------

## Configuración de credenciales HDA

Los módulos de descarga requieren una cuenta gratuita en [WEkEO](https://www.wekeo.eu/). Las credenciales se introducen en la interfaz gráfica y pueden guardarse de forma segura mediante `keyring`. También pueden configurarse mediante las variables de entorno `HDA_USER` y `HDA_PASSWORD`.

------------------------------------------------------------------------

## Estructura del proyecto

```         
PyTSGenerator/
├── main_app.py                  # Orquestador principal (GUI + registro de módulos)
├── requirements.txt             # Dependencias Python
├── LICENSE                      # Licencia MIT
├── README.md                    # Este fichero
└── modules/
    ├── base.py                  # Clase base BaseModule
    ├── download_base.py         # Lógica común de descarga HDA
    ├── download_stppi.py        # Módulo descarga STPPI
    ├── download_hrvpp.py        # Módulo descarga HR-VPP
    ├── renames_hrvpp.py         # Módulo renombrado TIF
    ├── agregacion_zonal.py      # Módulo agregación zonal
    ├── reproject_mixin.py       # Mixin reproyección de CRS
    └── crop_mixin.py            # Mixin recorte por shapefile
```

------------------------------------------------------------------------

## Añadir un nuevo módulo

La arquitectura modular permite extender la herramienta con nuevos módulos en tres pasos:

``` python
# 1. Crear modules/mi_modulo.py heredando de BaseModule
from modules.base import BaseModule

class MiModulo(BaseModule):
    NAME = "Mi Módulo"
    ICON = "🔧"

    def build_ui(self):
        ...  # construir la interfaz tkinter aquí

# 2. Registrarlo en main_app.py → MODULES_REGISTRY
MODULES_REGISTRY = [
    ...
    ("modules.mi_modulo", "MiModulo", "Descripción breve del módulo."),
]
# 3. ¡Listo! Aparecerá automáticamente en el sidebar.
```

------------------------------------------------------------------------

## Cita

Si utilizas PyTSGenerator en una publicación científica, por favor cítalo como:

```         
Valero-Jorge, A. (2025). PyTSGenerator: A modular desktop tool for remote sensing
time series generation from Copernicus Land products (v1.1).
Centro de Investigación y Tecnología Agroalimentaria de Aragón (CITA).
https://doi.org/10.5281/zenodo.XXXXXXX
```

> El DOI se actualizará tras el depósito en Zenodo.

------------------------------------------------------------------------

## Licencia

Este proyecto está bajo la licencia **MIT**. Consulta el fichero [LICENSE](LICENSE) para más detalles.

------------------------------------------------------------------------

## Contacto

**Alexey Valero-Jorge**\
Centro de Investigación y Tecnología Agroalimentaria de Aragón (CITA)\
📧 [avalero\@cita-aragon.es](avalero@cita-aragon.es)\
🔗 ORCID: <https://orcid.org/0000-0002-5993-7346>

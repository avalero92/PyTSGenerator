"""
download_stppi.py — Módulo de búsqueda y descarga de productos STPPI.

Producto: Short-Term Plant Phenology Indicator (STPPI)
Dataset:  EO:EEA:DAT:CLMS_HRVPP_ST

Post-descarga (ambas opcionales e independientes):
  · ReprojectMixin → reproyectar al CRS elegido, sobreescribir o carpeta.
  · CropMixin      → recortar al BBox del shapefile, sobreescribir o carpeta.
"""

import logging
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import Optional

try:
    import geopandas as gpd
    _HAS_GEOPANDAS = True
except ImportError:
    _HAS_GEOPANDAS = False

from modules.reproject_mixin import ReprojectMixin
from modules.crop_mixin import CropMixin
from modules.download_base import DownloadBaseModule

logger = logging.getLogger(__name__)


class DownloadSTPPIModule(ReprojectMixin, CropMixin, DownloadBaseModule):
    """
    Módulo de descarga de productos STPPI.

    MRO: DownloadSTPPIModule → ReprojectMixin → CropMixin → DownloadBaseModule

    Pipeline post-descarga (en orden):
      1. reproject_if_needed()  — si el checkbox de reproyección está activo
      2. crop_if_needed()       — si el checkbox de recorte está activo
    """

    NAME            = "Download STPPI"
    ICON            = "🛰️"
    DESCRIPTION     = (
        "Busca y descarga productos Short-Term Plant Phenology Indicator "
        "(STPPI) del Copernicus Land Monitoring Service (CLMS) vía API HDA de WEkEO. "
        "Admite delimitación por shapefile (BBox), reproyección de CRS opcional "
        "y recorte automático al área de interés."
    )
    DEFAULT_DATASET = "EO:EEA:DAT:CLMS_HRVPP_ST"

    PRODUCT_FIELDS = [
        {
            "attr":        "var_product_type",
            "label":       "🛰️ Tipo de Producto",
            "placeholder": "PPI",
            "query_key":   "productType",
            "row":         0,
            "col":         1,
        },
        {
            "attr":        "var_platform",
            "label":       "🔢 Plataforma",
            "placeholder": " ",
            "query_key":   "platformSerialIdentifier",
            "row":         0,
            "col":         2,
        },
    ]

    # ── Campos extra ─────────────────────────────────────────────────────────

    def _build_extra_fields(self, frame: tk.Frame) -> None:
        """
        Añade al frame de parámetros:
          1. Shapefile → BBox automático              (filas 9-12)
          2. Reproyección opcional  (ReprojectMixin)  (filas 13-16)
          3. Recorte opcional       (CropMixin)        (filas 17-20)
        """
        C = self.app.COLORS

        # ── Separador inicial ─────────────────────────────────────────
        tk.Frame(frame, bg=C["border"], height=1).grid(
            row=9, column=0, columnspan=3,
            sticky="ew", padx=0, pady=(10, 6))

        # ── Shapefile ─────────────────────────────────────────────────
        tk.Label(frame, text="📂 Shapefile (BBox)",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"],
                 anchor="w").grid(
            row=10, column=0, columnspan=3,
            sticky="w", padx=(0, 8), pady=(0, 2))

        self._var_shp_path = tk.StringVar(value="")
        tk.Entry(
            frame,
            textvariable=self._var_shp_path,
            font=("Segoe UI", 9),
            bg=C["input_bg"], fg=C["fg"],
            relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["accent"],
            state="readonly",
        ).grid(row=11, column=0, columnspan=2,
               sticky="ew", padx=(0, 8), pady=(0, 4), ipady=6)

        self._btn(frame, "📂  Examinar…", self._browse_shapefile,
                  style="secondary").grid(
            row=11, column=2, sticky="ew", pady=(0, 4))

        tk.Label(frame,
                 text="Opcional · el BBox del shapefile rellena automáticamente el campo BBox",
                 font=("Segoe UI", 8, "italic"),
                 bg=C["card"], fg=C["fg_muted"],
                 anchor="w").grid(
            row=12, column=0, columnspan=3,
            sticky="w", pady=(0, 8))

        # ── Reproyección (ReprojectMixin) ─────────────────────────────
        self._build_reproject_fields(frame, start_row=13)

        # ── Recorte (CropMixin) ───────────────────────────────────────
        self._build_crop_fields(frame, start_row=17)

    # ── Shapefile → BBox ─────────────────────────────────────────────────────

    def _browse_shapefile(self) -> None:
        path = filedialog.askopenfilename(
            title="Seleccionar shapefile de área de interés",
            filetypes=[("Shapefile", "*.shp"), ("Todos los archivos", "*.*")],
        )
        if not path:
            return
        self._var_shp_path.set(path)
        logger.info("Shapefile seleccionado: %s", path)
        bbox_data = self._bbox_from_shapefile(path)
        if bbox_data:
            bbox_str = ", ".join(str(v) for v in bbox_data)
            self.var_bbox.set(bbox_str)
            self.app.notify(f"📂 BBox extraído: {bbox_str}", level="success")
        else:
            self.app.notify(
                "⚠️ No se pudo extraer el BBox del shapefile.", level="warning")

    def _bbox_from_shapefile(self, shapefile_path: str) -> Optional[list]:
        if not _HAS_GEOPANDAS:
            self.app.notify(
                "⚠️ geopandas no está instalado.  pip install geopandas",
                level="error")
            return None
        path = Path(shapefile_path)
        if not path.exists():
            return None
        try:
            gdf = gpd.read_file(path)
            if gdf.crs is None:
                logger.warning("Shapefile sin CRS; se asume WGS-84.")
            elif gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            min_lon, min_lat, max_lon, max_lat = gdf.total_bounds
            return [round(float(v), 6) for v in (min_lon, min_lat, max_lon, max_lat)]
        except Exception as exc:
            logger.error("Error leyendo shapefile '%s': %s", path, exc)
            return None

    # ── Hook post-descarga ────────────────────────────────────────────────────

    def on_product_downloaded(self, local_path: str) -> str:
        """
        Pipeline post-descarga:
          1. Reproyección (si activada).
          2. Recorte al BBox (si activado).
        """
        local_path = self.reproject_if_needed(local_path)
        local_path = self.crop_if_needed(local_path)
        return local_path

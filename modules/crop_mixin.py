"""
crop_mixin.py — Mixin reutilizable para recorte de rásters por BBox de shapefile.

Diseñado para ser heredado junto a DownloadBaseModule en cualquier módulo
que ya disponga de:
  · self._var_shp_path   — ruta del shapefile seleccionado
  · self.var_bbox        — StringVar con BBox (xmin,ymin,xmax,ymax) en WGS-84
  · self.var_download_dir — StringVar con la carpeta de descarga base
  · self.app             — referencia a la aplicación (para notify / COLORS)

Añade al frame que se le pase (_build_crop_fields) los controles:
  ┌─────────────────────────────────────────────────────────────────────┐
  │  ✂️ RECORTE POST-DESCARGA                                          │
  │  [✓] Recortar imagen al BBox del shapefile                         │
  │      ● Sobreescribir imagen original          (modo simple)        │
  │      ○ Guardar en otra carpeta  [__carpeta__] [📂 Examinar]        │
  │                                                                     │
  │  ℹ️  El tile completo se descarga siempre; el recorte es opcional. │
  └─────────────────────────────────────────────────────────────────────┘

El recorte se realiza mediante rasterio (rasterio.mask.mask).
Si rasterio no está instalado, se avisa al usuario en lugar de fallar.

Modo usuario básico
───────────────────
  Marcar el checkbox es todo lo que hay que hacer. Por defecto sobreescribe
  el archivo original para no ocupar espacio doble.

Modo usuario avanzado
──────────────────────
  Elegir «Guardar en otra carpeta» y especificar (o examinar) la ruta destino.
  El original queda intacto; el recortado se guarda con el mismo nombre de
  fichero en la carpeta elegida.
"""

from __future__ import annotations

import os
import logging
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import Optional

try:
    import rasterio
    import rasterio.mask
    _HAS_RASTERIO = True
except ImportError:
    _HAS_RASTERIO = False

try:
    import geopandas as gpd
    from shapely.geometry import box
    _HAS_GEOPANDAS = True
except ImportError:
    _HAS_GEOPANDAS = False

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────────────────

_CROP_SUFFIX = "_crop"   # sufijo añadido al nombre cuando se sobreescribe


class CropMixin:
    """
    Mixin que añade la lógica y la UI de recorte por BBox de shapefile.

    Uso en la subclase
    ------------------
    1. Heredar CropMixin **antes** de DownloadBaseModule:
           class DownloadHRVPPModule(CropMixin, DownloadBaseModule): …
    2. Llamar a _build_crop_fields(frame) desde _build_extra_fields(frame),
       justo después del separador de CRS:
           def _build_extra_fields(self, frame):
               …  # shapefile + CRS (código existente)
               self._build_crop_fields(frame, start_row=16)
    3. Llamar a crop_if_needed(local_path) desde on_product_downloaded:
           def on_product_downloaded(self, local_path):
               local_path = super().on_product_downloaded(local_path)
               return self.crop_if_needed(local_path)
    """

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_crop_fields(self, frame: tk.Frame, start_row: int = 16) -> None:
        """
        Añade los controles de recorte al frame de parámetros de búsqueda.

        Parameters
        ----------
        frame:
            El mismo tk.Frame ``search`` del base module.
        start_row:
            Fila de la cuadrícula donde empezar a pintar los widgets.
            Debe ser mayor que la última fila usada por _build_extra_fields.
        """
        C = self.app.COLORS  # type: ignore[attr-defined]

        # ── Variables internas ────────────────────────────────────────
        self._var_crop_enabled  = tk.BooleanVar(value=False)
        self._var_crop_mode     = tk.StringVar(value="overwrite")  # overwrite | folder
        self._var_crop_dir      = tk.StringVar(value="")

        # ── Separador ────────────────────────────────────────────────
        tk.Frame(frame, bg=C["border"], height=1).grid(
            row=start_row, column=0, columnspan=3,
            sticky="ew", padx=0, pady=(10, 6))

        # ── Encabezado con checkbox ───────────────────────────────────
        hdr = tk.Frame(frame, bg=C["card"])
        hdr.grid(row=start_row + 1, column=0, columnspan=3,
                 sticky="ew", pady=(0, 4))

        tk.Checkbutton(
            hdr,
            text="✂️  Recortar imagen descargada al BBox del shapefile",
            variable=self._var_crop_enabled,
            command=self._on_crop_toggle,
            font=("Segoe UI", 9, "bold"),
            bg=C["card"], fg=C["fg"],
            activebackground=C["card"],
            selectcolor=C["input_bg"],
            anchor="w",
            cursor="hand2",
        ).pack(fill="x")

        # ── Subpanel de opciones (se habilita/deshabilita con el checkbox) ────
        self._crop_options_frame = tk.Frame(
            frame, bg=C["card"],
            padx=24,   # sangría para mostrar que depende del checkbox
        )
        self._crop_options_frame.grid(
            row=start_row + 2, column=0, columnspan=3,
            sticky="ew", pady=(0, 4))

        # Radio: sobreescribir
        self._rb_overwrite = tk.Radiobutton(
            self._crop_options_frame,
            text="🔄  Sobreescribir el archivo original  (recomendado · ahorra espacio)",
            variable=self._var_crop_mode,
            value="overwrite",
            command=self._on_mode_change,
            font=("Segoe UI", 9),
            bg=C["card"], fg=C["fg"],
            activebackground=C["card"],
            selectcolor=C["input_bg"],
            anchor="w",
            cursor="hand2",
        )
        self._rb_overwrite.pack(fill="x", pady=(2, 0))

        # Radio: carpeta alternativa
        self._rb_folder = tk.Radiobutton(
            self._crop_options_frame,
            text="📁  Guardar en otra carpeta  (conserva el tile original intacto)",
            variable=self._var_crop_mode,
            value="folder",
            command=self._on_mode_change,
            font=("Segoe UI", 9),
            bg=C["card"], fg=C["fg"],
            activebackground=C["card"],
            selectcolor=C["input_bg"],
            anchor="w",
            cursor="hand2",
        )
        self._rb_folder.pack(fill="x", pady=(2, 6))

        # Fila de carpeta destino (visible sólo en modo "folder")
        self._crop_dir_row = tk.Frame(
            self._crop_options_frame, bg=C["card"])
        self._crop_dir_row.pack(fill="x", pady=(0, 4))

        self._crop_dir_entry = tk.Entry(
            self._crop_dir_row,
            textvariable=self._var_crop_dir,
            font=("Segoe UI", 9),
            bg=C["input_bg"], fg=C["fg"],
            relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["accent"],
            state="readonly",
        )
        self._crop_dir_entry.pack(
            side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        self._btn_crop_dir = self._btn(  # type: ignore[attr-defined]
            self._crop_dir_row,
            "📂  Examinar…",
            self._choose_crop_dir,
            style="secondary",
        )
        self._btn_crop_dir.pack(side="left")

        # Texto de ayuda
        tk.Label(
            self._crop_options_frame,
            text=(
                "ℹ️  Se necesita un shapefile seleccionado arriba para que el "
                "recorte funcione.  El tile completo siempre se descarga primero."
            ),
            font=("Segoe UI", 8, "italic"),
            bg=C["card"], fg=C["fg_muted"],
            anchor="w",
            wraplength=540,
            justify="left",
        ).pack(fill="x", pady=(0, 4))

        # Estado inicial: panel deshabilitado
        self._on_crop_toggle()

    # ── Callbacks de UI ──────────────────────────────────────────────────────

    def _on_crop_toggle(self) -> None:
        """Habilita o deshabilita el subpanel de opciones según el checkbox."""
        enabled = self._var_crop_enabled.get()
        state   = "normal" if enabled else "disabled"
        for w in _iter_widgets(self._crop_options_frame):
            try:
                w.config(state=state)
            except tk.TclError:
                pass
        if enabled:
            # Asegura que la visibilidad de la fila de carpeta es coherente
            self._on_mode_change()

    def _on_mode_change(self) -> None:
        """Muestra u oculta la fila de carpeta destino."""
        if not self._var_crop_enabled.get():
            return
        show = self._var_crop_mode.get() == "folder"
        if show:
            self._crop_dir_row.pack(fill="x", pady=(0, 4))
        else:
            self._crop_dir_row.pack_forget()

    def _choose_crop_dir(self) -> None:
        """Abre el explorador para elegir la carpeta de recortes."""
        path = filedialog.askdirectory(
            title="Seleccionar carpeta donde guardar las imágenes recortadas")
        if path:
            self._var_crop_dir.set(path)

    # ── Lógica de recorte ────────────────────────────────────────────────────

    def crop_if_needed(self, src_path: str) -> str:
        """
        Si el checkbox de recorte está activado y hay un shapefile válido,
        recorta el GeoTIFF al BBox del shapefile.

        Modos de guardado
        -----------------
        • overwrite → el recortado reemplaza al original (mismo path).
        • folder    → se guarda en la carpeta elegida conservando el nombre.

        Returns
        -------
        str
            Ruta del archivo resultante (recortado o sin tocar).
        """
        if not getattr(self, "_var_crop_enabled", None):
            return src_path
        if not self._var_crop_enabled.get():
            return src_path

        shp_path = getattr(self, "_var_shp_path", None)
        if shp_path is None or not shp_path.get():
            self.app.notify(  # type: ignore[attr-defined]
                "⚠️ Recorte activado pero no hay shapefile seleccionado. "
                "Se conserva el tile completo.",
                level="warning")
            return src_path

        bbox = self._bbox_from_var_bbox()
        if bbox is None:
            self.app.notify(  # type: ignore[attr-defined]
                "⚠️ No se pudo determinar el BBox para el recorte.",
                level="warning")
            return src_path

        dst_path = self._resolve_crop_dst(src_path)
        result   = self._do_crop(src_path, bbox, dst_path)
        return result if result else src_path

    def _bbox_from_var_bbox(self) -> Optional[list[float]]:
        """
        Lee el BBox actual de self.var_bbox (rellenado por el explorador
        de shapefile o manualmente por el usuario).

        Returns [xmin, ymin, xmax, ymax] en WGS-84, o None.
        """
        raw = getattr(self, "var_bbox", None)
        if raw is None:
            return None
        val = raw.get().strip()
        if not val:
            return None
        try:
            parts = [float(x.strip()) for x in val.split(",")]
            if len(parts) != 4:
                return None
            return parts
        except ValueError:
            return None

    def _resolve_crop_dst(self, src_path: str) -> str:
        """
        Calcula la ruta destino del recorte según el modo elegido.

        overwrite → mismo path que el origen (el original será reemplazado).
        folder    → carpeta elegida + mismo nombre de fichero.
        """
        mode = self._var_crop_mode.get()

        if mode == "folder":
            folder = self._var_crop_dir.get().strip()
            if not folder:
                # Si no eligió carpeta, usamos una subcarpeta «recortados»
                folder = os.path.join(
                    self.var_download_dir.get().strip() or  # type: ignore[attr-defined]
                    os.path.dirname(src_path),
                    "recortados")
                self._var_crop_dir.set(folder)
                self.app.notify(  # type: ignore[attr-defined]
                    f"📁 Carpeta de recortes no especificada; "
                    f"se usará: {folder}",
                    level="warning")
            os.makedirs(folder, exist_ok=True)
            return os.path.join(folder, os.path.basename(src_path))
        else:
            # overwrite: guardamos en un temporal con sufijo y luego reemplazamos
            base, ext = os.path.splitext(src_path)
            return f"{base}{_CROP_SUFFIX}{ext}"

    def _do_crop(self, src_path: str, bbox: list[float], dst_path: str) -> Optional[str]:
        """
        Recorta el GeoTIFF ``src_path`` al bounding-box ``bbox`` y lo guarda
        en ``dst_path``.

        El BBox llega en WGS-84 (EPSG:4326); se reproyecta al CRS del ráster
        si es necesario antes de recortar.

        Returns
        -------
        str | None
            Ruta del archivo recortado, o None si falló.
        """
        if not _HAS_RASTERIO:
            self.app.notify(  # type: ignore[attr-defined]
                "⚠️ rasterio no está instalado — no se puede recortar.\n"
                "Instálalo con:  pip install rasterio",
                level="error")
            return None

        if not os.path.exists(src_path):
            logger.error("Archivo origen no encontrado para recortar: %s", src_path)
            return None

        xmin, ymin, xmax, ymax = bbox

        try:
            with rasterio.open(src_path) as src:
                raster_crs = src.crs

                # ── Construir la geometría de recorte en el CRS del ráster ──
                if _HAS_GEOPANDAS and raster_crs:
                    import geopandas as gpd
                    from shapely.geometry import box as shapely_box
                    gdf_bbox = gpd.GeoDataFrame(
                        geometry=[shapely_box(xmin, ymin, xmax, ymax)],
                        crs="EPSG:4326")
                    if raster_crs.to_epsg() != 4326:
                        gdf_bbox = gdf_bbox.to_crs(raster_crs)
                    shapes = [gdf_bbox.geometry[0].__geo_interface__]
                else:
                    # Sin geopandas: usar el BBox directamente (asume mismo CRS)
                    from shapely.geometry import box as shapely_box
                    shapes = [shapely_box(xmin, ymin, xmax, ymax).__geo_interface__]

                # Leer scale/offset antes de cerrar src (tags GDAL de escala
                # interna usados por productos CLMS: PPI real = int / 1000, etc.)
                band_scales  = list(src.scales)  if src.scales  else [1.0] * src.count
                band_offsets = list(src.offsets) if src.offsets else [0.0] * src.count

                out_image, out_transform = rasterio.mask.mask(
                    src, shapes, crop=True, nodata=src.nodata)
                out_meta = src.meta.copy()
                out_meta.update({
                    "driver":    "GTiff",
                    "height":    out_image.shape[1],
                    "width":     out_image.shape[2],
                    "transform": out_transform,
                    # Preservar dtype explícitamente: los productos enteros
                    # escalados (int16/uint16) no deben convertirse a float
                    "dtype":     src.meta["dtype"],
                    "compress":  "deflate",   # compresión sin pérdida
                    "tiled":     True,
                })

                # Propagar nodata si el original lo declara
                if src.nodata is not None:
                    out_meta["nodata"] = src.nodata

                with rasterio.open(dst_path, "w", **out_meta) as dst:
                    dst.write(out_image)
                    # Restaurar scale/offset para que lectores externos
                    # (QGIS, xarray, snap…) apliquen el factor correcto
                    dst.scales  = tuple(band_scales)
                    dst.offsets = tuple(band_offsets)

            logger.info("Recorte completado: %s → %s", src_path, dst_path)

            # Si el modo es «overwrite»: sustituir el original por el recortado
            if dst_path != src_path and dst_path.endswith(_CROP_SUFFIX + os.path.splitext(dst_path)[1]):
                os.replace(dst_path, src_path)
                logger.info("Original sobreescrito con el recorte: %s", src_path)
                self.app.notify(  # type: ignore[attr-defined]
                    f"✂️ Imagen recortada al BBox del shapefile "
                    f"(sobreescrito): {os.path.basename(src_path)}",
                    level="success")
                return src_path
            else:
                self.app.notify(  # type: ignore[attr-defined]
                    f"✂️ Imagen recortada guardada en: {dst_path}",
                    level="success")
                return dst_path

        except Exception as exc:
            logger.error(
                "Error recortando '%s': %s", src_path, exc, exc_info=True)
            self.app.notify(  # type: ignore[attr-defined]
                f"❌ Error al recortar {os.path.basename(src_path)}: {exc}",
                level="error")
            return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _iter_widgets(widget: tk.Widget):
    """Generador que recorre recursivamente todos los hijos de un widget."""
    yield widget
    for child in widget.winfo_children():
        yield from _iter_widgets(child)

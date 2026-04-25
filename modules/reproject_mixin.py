"""
reproject_mixin.py — Mixin reutilizable para reproyección opcional de rásters.

Mismo patrón UX que CropMixin:
  · Checkbox para activar/desactivar (desactivado por defecto).
  · Combobox con los CRS más habituales.
  · Dos modos de guardado:
      - Sobreescribir el original.
      - Guardar en otra carpeta.

Uso en la subclase
------------------
1. Heredar ReprojectMixin antes de DownloadBaseModule:
       class DownloadHRVPPModule(ReprojectMixin, CropMixin, DownloadBaseModule): …
2. Llamar a _build_reproject_fields(frame, start_row=N) desde _build_extra_fields.
3. Llamar a reproject_if_needed(local_path) desde on_product_downloaded.
"""

from __future__ import annotations

import os
import logging
import tkinter as tk
from tkinter import ttk, filedialog
from typing import Optional

try:
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    _HAS_RASTERIO = True
except ImportError:
    _HAS_RASTERIO = False

logger = logging.getLogger(__name__)

# ── CRS disponibles ──────────────────────────────────────────────────────────
CRS_OPTIONS = {
    "— Selecciona un CRS —":                 "",
    "WGS 84 (EPSG:4326)":                    "EPSG:4326",
    "WGS 84 / Pseudo-Mercator (EPSG:3857)":  "EPSG:3857",
    "ETRS89 (EPSG:4258)":                    "EPSG:4258",
    "ETRS89 / UTM zone 28N (EPSG:25828)":    "EPSG:25828",
    "ETRS89 / UTM zone 29N (EPSG:25829)":    "EPSG:25829",
    "ETRS89 / UTM zone 30N (EPSG:25830)":    "EPSG:25830",
    "ETRS89 / UTM zone 31N (EPSG:25831)":    "EPSG:25831",
    "ETRS89 / UTM zone 32N (EPSG:25832)":    "EPSG:25832",
    "ETRS89 / UTM zone 33N (EPSG:25833)":    "EPSG:25833",
    "ETRS89 / LAEA Europe (EPSG:3035)":      "EPSG:3035",
    "ED50 / UTM zone 29N (EPSG:23029)":      "EPSG:23029",
    "ED50 / UTM zone 30N (EPSG:23030)":      "EPSG:23030",
    "ED50 / UTM zone 31N (EPSG:23031)":      "EPSG:23031",
}
CRS_LABELS = list(CRS_OPTIONS.keys())

_REPROJ_SUFFIX = "_reproj"


class ReprojectMixin:
    """
    Mixin que añade la lógica y UI de reproyección opcional al CRS elegido.

    UI generada por _build_reproject_fields()
    ------------------------------------------
    ┌──────────────────────────────────────────────────────────────────┐
    │  🌐 REPROYECCIÓN POST-DESCARGA                                   │
    │  [✓] Reproyectar imagen descargada a otro CRS                   │
    │      [— Selecciona un CRS ————————————————————▼]                │
    │      ● Sobreescribir el archivo original                        │
    │      ○ Guardar en otra carpeta  [____________] [📂 Examinar]    │
    │  ℹ️  El archivo original siempre se descarga primero.           │
    └──────────────────────────────────────────────────────────────────┘
    """

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_reproject_fields(self, frame: tk.Frame, start_row: int = 9) -> None:
        """
        Pinta los controles de reproyección en el frame de búsqueda.

        Parameters
        ----------
        frame     : El tk.Frame ``search`` del base module.
        start_row : Primera fila de la cuadrícula libre.
        """
        C = self.app.COLORS  # type: ignore[attr-defined]

        # Variables internas
        self._var_reproj_enabled = tk.BooleanVar(value=False)
        self._var_reproj_crs     = tk.StringVar(value=CRS_LABELS[0])
        self._var_reproj_mode    = tk.StringVar(value="overwrite")
        self._var_reproj_dir     = tk.StringVar(value="")

        # ── Separador ────────────────────────────────────────────────
        tk.Frame(frame, bg=C["border"], height=1).grid(
            row=start_row, column=0, columnspan=3,
            sticky="ew", padx=0, pady=(10, 6))

        # ── Checkbox encabezado ───────────────────────────────────────
        tk.Checkbutton(
            frame,
            text="🌐  Reproyectar imagen descargada a otro CRS",
            variable=self._var_reproj_enabled,
            command=self._on_reproj_toggle,
            font=("Segoe UI", 9, "bold"),
            bg=C["card"], fg=C["fg"],
            activebackground=C["card"],
            selectcolor=C["input_bg"],
            anchor="w",
            cursor="hand2",
        ).grid(row=start_row + 1, column=0, columnspan=3,
               sticky="w", pady=(0, 4))

        # ── Subpanel ──────────────────────────────────────────────────
        self._reproj_options_frame = tk.Frame(frame, bg=C["card"], padx=24)
        self._reproj_options_frame.grid(
            row=start_row + 2, column=0, columnspan=3,
            sticky="ew", pady=(0, 4))

        # Combobox CRS
        tk.Label(self._reproj_options_frame,
                 text="CRS de destino:",
                 font=("Segoe UI", 9),
                 bg=C["card"], fg=C["fg"],
                 anchor="w").pack(fill="x", pady=(2, 2))

        self._reproj_crs_combo = ttk.Combobox(
            self._reproj_options_frame,
            textvariable=self._var_reproj_crs,
            values=CRS_LABELS,
            state="readonly",
            font=("Segoe UI", 10),
        )
        self._reproj_crs_combo.pack(fill="x", pady=(0, 8), ipady=4)
        self._reproj_crs_combo.current(0)

        # Radios de guardado
        self._rb_reproj_overwrite = tk.Radiobutton(
            self._reproj_options_frame,
            text="🔄  Sobreescribir el archivo original  (recomendado · ahorra espacio)",
            variable=self._var_reproj_mode,
            value="overwrite",
            command=self._on_reproj_mode_change,
            font=("Segoe UI", 9),
            bg=C["card"], fg=C["fg"],
            activebackground=C["card"],
            selectcolor=C["input_bg"],
            anchor="w",
            cursor="hand2",
        )
        self._rb_reproj_overwrite.pack(fill="x", pady=(0, 2))

        self._rb_reproj_folder = tk.Radiobutton(
            self._reproj_options_frame,
            text="📁  Guardar en otra carpeta  (conserva el archivo original)",
            variable=self._var_reproj_mode,
            value="folder",
            command=self._on_reproj_mode_change,
            font=("Segoe UI", 9),
            bg=C["card"], fg=C["fg"],
            activebackground=C["card"],
            selectcolor=C["input_bg"],
            anchor="w",
            cursor="hand2",
        )
        self._rb_reproj_folder.pack(fill="x", pady=(0, 6))

        # Fila carpeta destino
        self._reproj_dir_row = tk.Frame(self._reproj_options_frame, bg=C["card"])
        self._reproj_dir_row.pack(fill="x", pady=(0, 4))

        tk.Entry(
            self._reproj_dir_row,
            textvariable=self._var_reproj_dir,
            font=("Segoe UI", 9),
            bg=C["input_bg"], fg=C["fg"],
            relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["accent"],
            state="readonly",
        ).pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        self._btn(  # type: ignore[attr-defined]
            self._reproj_dir_row,
            "📂  Examinar…",
            self._choose_reproj_dir,
            style="secondary",
        ).pack(side="left")

        # Ayuda
        tk.Label(
            self._reproj_options_frame,
            text="ℹ️  Sin reproyección el archivo conserva el CRS original "
                 "(normalmente ETRS89/UTM 33N · EPSG:32633).",
            font=("Segoe UI", 8, "italic"),
            bg=C["card"], fg=C["fg_muted"],
            anchor="w", wraplength=540, justify="left",
        ).pack(fill="x", pady=(0, 4))

        # Estado inicial: deshabilitado
        self._on_reproj_toggle()

    # ── Callbacks UI ─────────────────────────────────────────────────────────

    def _on_reproj_toggle(self) -> None:
        enabled = self._var_reproj_enabled.get()
        state   = "normal" if enabled else "disabled"
        for w in _iter_widgets(self._reproj_options_frame):
            try:
                w.config(state=state)
            except tk.TclError:
                pass
        if enabled:
            self._on_reproj_mode_change()

    def _on_reproj_mode_change(self) -> None:
        if not self._var_reproj_enabled.get():
            return
        if self._var_reproj_mode.get() == "folder":
            self._reproj_dir_row.pack(fill="x", pady=(0, 4))
        else:
            self._reproj_dir_row.pack_forget()

    def _choose_reproj_dir(self) -> None:
        path = filedialog.askdirectory(
            title="Seleccionar carpeta donde guardar las imágenes reproyectadas")
        if path:
            self._var_reproj_dir.set(path)

    # ── Lógica ───────────────────────────────────────────────────────────────

    def reproject_if_needed(self, src_path: str) -> str:
        """
        Si el checkbox está activo y se eligió un CRS válido, reproyecta
        el GeoTIFF y devuelve la ruta resultante.

        Modos de guardado
        -----------------
        overwrite → reemplaza el original.
        folder    → guarda en la carpeta elegida con el mismo nombre.
        """
        if not getattr(self, "_var_reproj_enabled", None):
            return src_path
        if not self._var_reproj_enabled.get():
            return src_path

        crs_str = CRS_OPTIONS.get(self._var_reproj_crs.get(), "")
        if not crs_str:
            self.app.notify(  # type: ignore[attr-defined]
                "⚠️ Reproyección activada pero no se eligió ningún CRS. "
                "Se conserva el CRS original.",
                level="warning")
            return src_path

        if not _HAS_RASTERIO:
            self.app.notify(  # type: ignore[attr-defined]
                "⚠️ rasterio no está instalado — no se puede reproyectar.\n"
                "Instálalo con:  pip install rasterio",
                level="error")
            return src_path

        if not os.path.exists(src_path):
            logger.error("Archivo origen no encontrado para reproyectar: %s", src_path)
            return src_path

        dst_path = self._resolve_reproj_dst(src_path, crs_str)
        result   = self._do_reproject(src_path, crs_str, dst_path)
        return result if result else src_path

    def _resolve_reproj_dst(self, src_path: str, crs_str: str) -> str:
        """Calcula la ruta destino según el modo elegido."""
        mode = self._var_reproj_mode.get()

        if mode == "folder":
            folder = self._var_reproj_dir.get().strip()
            if not folder:
                folder = os.path.join(
                    self.var_download_dir.get().strip() or  # type: ignore[attr-defined]
                    os.path.dirname(src_path),
                    "reproyectados")
                self._var_reproj_dir.set(folder)
                self.app.notify(  # type: ignore[attr-defined]
                    f"📁 Carpeta de reproyección no especificada; "
                    f"se usará: {folder}",
                    level="warning")
            os.makedirs(folder, exist_ok=True)
            return os.path.join(folder, os.path.basename(src_path))
        else:
            # overwrite: temporal con sufijo, luego reemplaza
            base, ext = os.path.splitext(src_path)
            return f"{base}{_REPROJ_SUFFIX}{ext}"

    def _do_reproject(self, src_path: str, crs_str: str, dst_path: str) -> Optional[str]:
        """Reproyecta src_path al CRS crs_str y guarda en dst_path."""
        try:
            with rasterio.open(src_path) as src:
                transform, width, height = calculate_default_transform(
                    src.crs, crs_str, src.width, src.height, *src.bounds)
                meta = src.meta.copy()
                meta.update({
                    "crs":       crs_str,
                    "transform": transform,
                    "width":     width,
                    "height":    height,
                    "compress":  "deflate",
                    # Preservar tipo de dato explícitamente para no perder
                    # la escala entera de productos CLMS (PPI, VPP, etc.)
                    "dtype":     src.meta["dtype"],
                })

                # Propagar nodata si el original lo declara
                if src.nodata is not None:
                    meta["nodata"] = src.nodata

                # Leer scale/offset por banda (tags GDAL de escala interna)
                # para restaurarlos en el destino tras la escritura
                band_scales  = []
                band_offsets = []
                for i in range(1, src.count + 1):
                    band_scales.append(src.scales[i - 1]  if src.scales  else 1.0)
                    band_offsets.append(src.offsets[i - 1] if src.offsets else 0.0)

                with rasterio.open(dst_path, "w", **meta) as dst:
                    for i in range(1, src.count + 1):
                        reproject(
                            source=rasterio.band(src, i),
                            destination=rasterio.band(dst, i),
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=transform,
                            dst_crs=crs_str,
                            resampling=Resampling.nearest,
                        )
                    # Restaurar scale/offset en el destino
                    dst.scales  = tuple(band_scales)
                    dst.offsets = tuple(band_offsets)

            # Si es overwrite: sustituir el original
            if dst_path != src_path and _REPROJ_SUFFIX in dst_path:
                os.replace(dst_path, src_path)
                logger.info("Original sobreescrito con reproyección: %s", src_path)
                self.app.notify(  # type: ignore[attr-defined]
                    f"🌐 Reproyectado a {crs_str} "
                    f"(sobreescrito): {os.path.basename(src_path)}",
                    level="success")
                return src_path
            else:
                logger.info("Reproyectado %s → %s (%s)", src_path, dst_path, crs_str)
                self.app.notify(  # type: ignore[attr-defined]
                    f"🌐 Reproyectado a {crs_str}: {dst_path}",
                    level="success")
                return dst_path

        except Exception as exc:
            logger.error("Error reproyectando '%s' a %s: %s",
                         src_path, crs_str, exc, exc_info=True)
            self.app.notify(  # type: ignore[attr-defined]
                f"❌ Error al reproyectar {os.path.basename(src_path)}: {exc}",
                level="error")
            return None


# ── Helper ───────────────────────────────────────────────────────────────────

def _iter_widgets(widget: tk.Widget):
    yield widget
    for child in widget.winfo_children():
        yield from _iter_widgets(child)

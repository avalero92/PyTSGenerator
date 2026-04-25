"""
agregacion_zonal.py — Módulo de Agregación Zonal.

Extraído del Módulo 5 de S2Spectra_app_v20.py (run_aggregation).
Extrae estadísticos zonales de GeoTIFFs a partir de un archivo
vectorial (polígonos o puntos).

Registrar en main_app.py → MODULES_REGISTRY:
    ("modules.agregacion_zonal", "AgregacionZonalModule"),
"""

import os
import re
import glob
import threading
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext

from modules.base import BaseModule

# ──────────────────────────────────────────────────────────────────────
# Constante nodata por defecto (igual que S2Spectra)
# ──────────────────────────────────────────────────────────────────────
NODATA_VALUE = -9999.0


# ══════════════════════════════════════════════════════════════════════
# FUNCIÓN DE CÓMPUTO (extraída de S2Spectra run_aggregation)
# ══════════════════════════════════════════════════════════════════════

def run_aggregation(params, log_fn, done_fn, progress_fn=None):
    """
    Módulo de agregación zonal.

    Parámetros esperados en params:
      tif_folder   : str   carpeta con GeoTIFFs de entrada
      vector_path  : str   Shapefile / GeoJSON / GPKG con entidades
      banda        : str   nombre de banda/índice a procesar
      out_folder   : str   carpeta de salida
      id_field     : str   campo identificador ('auto' = índice)
      geom_type    : str   'polygon' | 'point' | 'auto'
      point_method : str   'nearest' | 'bilinear'
      percentiles  : list  e.g. [5, 25, 50, 75, 95]
      stats        : list  subconjunto de: 'mean','median','std',
                           'min','max','range','cv',
                           'sum_weighted','count_px','p_list'
      nodata       : float valor nodata (default -9999)
    """
    import numpy as np
    from rasterio.mask import mask as rio_mask
    from scipy.ndimage import map_coordinates

    def _prog(v, txt=""):
        if progress_fn:
            progress_fn(v, txt)

    try:
        import rasterio
        import geopandas as gpd

        tif_folder   = params["tif_folder"]
        vector_path  = params["vector_path"]
        banda        = params["banda"].strip()
        out_folder   = params["out_folder"]
        id_field     = params.get("id_field", "auto")
        geom_type    = params.get("geom_type", "auto")
        point_method = params.get("point_method", "nearest")
        percentiles  = params.get("percentiles", [5, 25, 50, 75, 95])
        req_stats    = set(params.get("stats",
                           ["mean", "median", "std", "min", "max",
                            "range", "cv", "sum_weighted", "count_px"]))
        nodata       = params.get("nodata", NODATA_VALUE)

        log_fn(f"📂 Carpeta TIFs : {tif_folder}")
        log_fn(f"🗺  Vector       : {vector_path}")
        log_fn(f"🎯 Banda         : {banda}")
        log_fn(f"📁 Salida        : {out_folder}")

        os.makedirs(out_folder, exist_ok=True)

        # ── 1. Cargar vector ─────────────────────────────────────
        log_fn("\n── PASO 1 · Cargando archivo vectorial ──")
        _prog(2, "⏳ Cargando vector...")
        gdf   = gpd.read_file(vector_path)
        n_ent = len(gdf)
        log_fn(f"   ✔ {n_ent} entidades  |  CRS: {gdf.crs}")

        if n_ent == 0:
            log_fn("❌ El archivo vectorial no contiene entidades.")
            done_fn(success=False)
            return

        geom_types_found = set(gdf.geom_type.unique())
        if geom_type == "auto":
            geom_type = "point" if geom_types_found <= {"Point", "MultiPoint"} else "polygon"
        log_fn(f"   Modo: {'Polígonos (ponderación por área)' if geom_type == 'polygon' else 'Puntos'}")

        if id_field == "auto" or id_field not in gdf.columns:
            ids = [f"ent_{i:04d}" for i in range(n_ent)]
        else:
            ids = [str(v) for v in gdf[id_field].values]

        # ── 2. Listar TIFs ───────────────────────────────────────
        log_fn("\n── PASO 2 · Buscando GeoTIFFs ──────────")
        _prog(5, "⏳ Buscando TIFs...")
        _EXCL = re.compile(
            r'(_SG|_WH|_KF|_RMSE_|_BIAS_|_ROUGH_|_GAPS_|_smooth_|_metrics_|'
            r'noise_freq|_CLASE|_PROB_|_classified|_probability)')
        _DATE = re.compile(r'(\d{8})')

        tif_list = []
        for t in sorted(glob.glob(os.path.join(tif_folder, "*.tif"))):
            bn = os.path.basename(t)
            if _EXCL.search(bn):
                continue
            m = _DATE.search(bn)
            tif_list.append((m.group(1) if m else os.path.splitext(bn)[0], t))

        if not tif_list:
            log_fn(f"❌ No se encontraron TIFs en: {tif_folder}")
            done_fn(success=False)
            return
        log_fn(f"   ✔ {len(tif_list)} TIFs  ({tif_list[0][0]} → {tif_list[-1][0]})")

        # ── 3. Reprojectar vector ────────────────────────────────
        log_fn("\n── PASO 3 · Reproyectando vector ────────")
        _prog(8, "⏳ Reproyectando vector...")
        with rasterio.open(tif_list[0][1]) as src0:
            raster_crs = src0.crs
            tfm0       = src0.transform
            px_area    = abs(tfm0.a) * abs(tfm0.e)

        gdf_r = gdf.to_crs(raster_crs) if gdf.crs != raster_crs else gdf.copy()
        log_fn(f"   ✔ CRS raster: {raster_crs}")

        # ── Helpers internos ─────────────────────────────────────
        def _weighted_mask_polygon(geom, src):
            from rasterio.features import rasterize
            try:
                out_image, out_transform = rio_mask(
                    src, [geom.__geo_interface__],
                    crop=True, all_touched=True, filled=False, nodata=nodata)
            except Exception:
                return np.array([]), np.array([])

            data_2d = out_image[band_idx]
            H, W = data_2d.shape
            if H == 0 or W == 0:
                return np.array([]), np.array([])

            w_in = rasterize([(geom.__geo_interface__, 1.0)],
                             out_shape=(H, W), transform=out_transform,
                             fill=0.0, dtype="float32", all_touched=False)
            w_border = rasterize([(geom.__geo_interface__, 1.0)],
                                 out_shape=(H, W), transform=out_transform,
                                 fill=0.0, dtype="float32", all_touched=True)
            partial = (w_border - w_in).astype(bool)
            weight_2d = w_in.astype(float)
            weight_2d[partial] = 0.5

            raw = np.array(data_2d if not hasattr(data_2d, "data") else data_2d.data,
                           dtype=float)
            valid_mask = (~data_2d.mask if hasattr(data_2d, "mask") else (raw != nodata))
            valid_mask &= (weight_2d > 0) & np.isfinite(raw)

            return raw.ravel()[valid_mask.ravel()], weight_2d.ravel()[valid_mask.ravel()]

        def _extract_point(geom, data_full, tfm):
            from rasterio.transform import rowcol
            try:
                x, y = geom.x, geom.y
                if point_method == "nearest":
                    row, col = rowcol(tfm, x, y)
                    H, W = data_full.shape
                    if 0 <= row < H and 0 <= col < W:
                        v = data_full[row, col]
                        return float(v) if np.isfinite(v) else np.nan
                    return np.nan
                else:
                    row_f = (y - tfm.f) / tfm.e
                    col_f = (x - tfm.c) / tfm.a
                    v = map_coordinates(data_full, [[row_f], [col_f]],
                                        order=1, mode="nearest")[0]
                    return float(v) if np.isfinite(v) else np.nan
            except Exception:
                return np.nan

        def _compute_stats(vals, wts):
            row_d = {}
            if len(vals) == 0:
                nulls = {s: np.nan for s in req_stats}
                nulls.update({f"p{p:02d}": np.nan for p in percentiles})
                return nulls

            w = wts if wts is not None and len(wts) == len(vals) else np.ones_like(vals)
            w_sum = w.sum()

            if "mean" in req_stats:
                row_d["mean"] = float(np.average(vals, weights=w))
            if "median" in req_stats:
                row_d["median"] = float(np.median(vals))
            if "std" in req_stats:
                if w_sum > 0:
                    mu = np.average(vals, weights=w)
                    row_d["std"] = float(np.sqrt(np.average((vals - mu) ** 2, weights=w)))
                else:
                    row_d["std"] = np.nan
            if "min" in req_stats:
                row_d["min"] = float(vals.min())
            if "max" in req_stats:
                row_d["max"] = float(vals.max())
            if "range" in req_stats:
                row_d["range"] = float(vals.max() - vals.min())
            if "cv" in req_stats:
                mu = np.average(vals, weights=w)
                sd = row_d.get("std", np.nan)
                row_d["cv"] = float(sd / mu * 100) if mu != 0 else np.nan
            if "sum_weighted" in req_stats:
                row_d["sum_weighted"] = float((vals * w).sum())
            if "count_px" in req_stats:
                row_d["count_px"] = int(len(vals))
            for p in percentiles:
                row_d[f"p{p:02d}"] = float(np.percentile(vals, p))

            return row_d

        # ── 4. Procesar TIFs ─────────────────────────────────────
        log_fn("\n── PASO 4 · Extrayendo estadísticos ─────")
        _prog(10, "⏳ Procesando TIFs...")

        n_tifs   = len(tif_list)
        all_rows = []
        stat_cols = None
        errors   = 0
        band_idx = 0

        for ti, (fecha_str, tif_path) in enumerate(tif_list):
            pct = 10 + int(80 * ti / n_tifs)
            _prog(pct, f"⏳ {ti+1}/{n_tifs}  {fecha_str}")
            try:
                with rasterio.open(tif_path) as src:
                    bnames = [src.descriptions[i] or "" for i in range(src.count)]
                    band_idx = next((i for i, bn in enumerate(bnames)
                                     if banda.upper() in bn.upper()), 0)

                    if geom_type == "point":
                        data_full = src.read(band_idx + 1).astype(float)
                        data_full[data_full == nodata] = np.nan
                        tfm = src.transform

                    for eid, row_geom in zip(ids, gdf_r.itertuples()):
                        geom   = row_geom.geometry
                        row_d  = {"fecha": fecha_str, "id": eid}

                        if geom_type == "polygon":
                            vals, wts = _weighted_mask_polygon(geom, src)
                            stats = _compute_stats(vals, wts)
                        else:
                            val = _extract_point(geom, data_full, tfm)
                            vals = np.array([]) if np.isnan(val) else np.array([val])
                            stats = _compute_stats(vals, None)

                        row_d.update(stats)
                        all_rows.append(row_d)

                        if stat_cols is None:
                            stat_cols = list(stats.keys())

            except Exception as ex:
                log_fn(f"   ⚠️  {fecha_str}: {ex}")
                errors += 1
                continue

            if (ti + 1) % max(1, n_tifs // 10) == 0 or ti == n_tifs - 1:
                log_fn(f"   ✔  {ti+1}/{n_tifs}  ({fecha_str})")

        if not all_rows:
            log_fn("❌ No se generaron resultados. Revisa la banda y el vector.")
            done_fn(success=False)
            return

        # ── 5. Exportar CSVs ─────────────────────────────────────
        import csv
        import pandas as pd

        log_fn("\n── PASO 5 · Exportando resultados ───────")
        _prog(92, "⏳ Guardando CSVs...")

        # 5a. CSV largo (fecha × entidad)
        pct_cols      = [f"p{p:02d}" for p in percentiles]
        all_possible  = (["mean","median","std","min","max","range","cv",
                          "sum_weighted","count_px"] + pct_cols)
        col_order     = ["fecha", "id"] + (stat_cols or [])
        col_order    += [c for c in all_possible
                         if c not in col_order and c in (stat_cols or [])]

        largo_path = os.path.join(out_folder, f"{banda}_aggregation_largo.csv")
        with open(largo_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=col_order, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        log_fn(f"   ✔ CSV largo:    {os.path.basename(largo_path)}  ({len(all_rows)} filas)")

        # 5b. CSVs pivotados (series temporales por entidad)
        df = pd.DataFrame(all_rows)
        for sc in (stat_cols or []):
            if sc not in df.columns:
                continue
            pivot = df.pivot_table(index="fecha", columns="id",
                                   values=sc, aggfunc="first")
            pivot.index.name = "fecha"
            pivot.to_csv(os.path.join(out_folder, f"{banda}_{sc}_timeseries.csv"),
                         encoding="utf-8")
        log_fn(f"   ✔ CSVs pivotados: {len(stat_cols or [])} archivos")

        # 5c. CSV resumen estadístico global
        resumen_rows = []
        for sc in (stat_cols or []):
            if sc not in df.columns:
                continue
            col_v = pd.to_numeric(df[sc], errors="coerce").dropna()
            resumen_rows.append({
                "estadistico": sc,
                "media_global": float(col_v.mean()) if len(col_v) else float("nan"),
                "std_global"  : float(col_v.std())  if len(col_v) else float("nan"),
                "min_global"  : float(col_v.min())  if len(col_v) else float("nan"),
                "max_global"  : float(col_v.max())  if len(col_v) else float("nan"),
            })
        res_path = os.path.join(out_folder, f"{banda}_aggregation_resumen.csv")
        pd.DataFrame(resumen_rows).to_csv(res_path, index=False, encoding="utf-8")
        log_fn(f"   ✔ CSV resumen:  {os.path.basename(res_path)}")

        _prog(100, "✅ Agregación completada.")
        log_fn(f"\n{'='*55}")
        log_fn(f"✅ AGREGACIÓN COMPLETADA")
        log_fn(f"   TIFs procesados : {n_tifs - errors}/{n_tifs}")
        log_fn(f"   Entidades       : {n_ent}")
        log_fn(f"   Estadísticos    : {', '.join(stat_cols or [])}")
        log_fn(f"   Archivos salida : {out_folder}")
        if errors:
            log_fn(f"   ⚠️  {errors} TIF(s) con errores")
        log_fn(f"{'='*55}")
        done_fn(success=True)

    except Exception as ex:
        import traceback
        log_fn(f"❌ ERROR inesperado: {ex}")
        log_fn(traceback.format_exc())
        done_fn(success=False)


# ══════════════════════════════════════════════════════════════════════
# MÓDULO TKINTER
# ══════════════════════════════════════════════════════════════════════

class AgregacionZonalModule(BaseModule):
    """
    Módulo de Agregación Zonal.
    Extrae estadísticos zonales de GeoTIFFs usando un archivo vectorial.

    UI organizada igual que los módulos de descarga:
      · Encabezado con título + descripción
      · Secciones tipo acordeón (colapsables) para no saturar la pantalla
      · Mismos estilos de Entry, Button y Label que DownloadBaseModule
    """
    NAME = "Agregación Zonal"
    ICON = "📊"
    DESCRIPTION = (
        "Extrae estadísticos zonales de GeoTIFFs a partir de un archivo vectorial. "
        "Para polígonos: ponderación exacta por fracción de área del píxel. "
        "Para puntos: extracción por píxel más cercano o interpolación bilineal. "
        "Salidas: CSV largo (fecha×entidad), CSVs pivotados y CSV resumen."
    )

    # Estadísticos disponibles: (clave_interna, etiqueta_UI, activo_por_defecto)
    _STAT_DEFS = [
        ("mean",         "📐 Media ponderada",            True),
        ("median",       "〰️ Mediana",                   True),
        ("std",          "📊 Desviación estándar",        True),
        ("min",          "⬇️ Mínimo",                    True),
        ("max",          "⬆️ Máximo",                    True),
        ("range",        "↕️ Rango (máx − mín)",          True),
        ("cv",           "〽️ Coef. de variación (%)",    False),
        ("sum_weighted", "∑  Suma ponderada",             False),
        ("count_px",     "🔢 Nº píxeles válidos",         True),
    ]

    # Opciones de geometría y métodos para puntos
    _GEOM_OPTIONS   = [("🤖  Auto-detectar", "auto"),
                       ("🔷  Polígonos",     "polygon"),
                       ("📍  Puntos",        "point")]
    _POINT_METHODS  = [("Píxel más cercano",      "nearest"),
                       ("Interpolación bilineal", "bilinear")]

    # ------------------------------------------------------------------
    # UI principal
    # ------------------------------------------------------------------
    def build_ui(self):
        C = self.app.COLORS

        # ── Contenedor con scroll ──────────────────────────────────────
        canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        vsb    = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        main = tk.Frame(canvas, bg=C["bg"])
        win  = canvas.create_window((0, 0), window=main, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        main.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # ── Encabezado ─────────────────────────────────────────────────
        hdr = tk.Frame(main, bg=C["bg"])
        hdr.pack(fill="x", padx=32, pady=(24, 0))
        tk.Label(hdr, text=f"{self.ICON}  {self.NAME}",
                 font=("Segoe UI", 14, "bold"),
                 bg=C["bg"], fg=C["fg"]).pack(anchor="w")
        tk.Label(hdr, text=self.DESCRIPTION,
                 font=("Segoe UI", 9),
                 bg=C["bg"], fg=C["fg_muted"],
                 justify="left", wraplength=700).pack(anchor="w", pady=(4, 16))

        # ── Separador bajo el encabezado ───────────────────────────────
        tk.Frame(main, bg=C["border"], height=1).pack(
            fill="x", padx=32, pady=(0, 12))

        # ── Variables de datos ─────────────────────────────────────────
        self.tif_var       = tk.StringVar()
        self.vec_var       = tk.StringVar()
        self.out_var       = tk.StringVar()
        self.banda_var     = tk.StringVar(value="NDVI")
        self.id_var        = tk.StringVar(value="auto")
        self.geom_var      = tk.StringVar(value="auto")
        self.pt_method_var = tk.StringVar(value="nearest")
        self.pct_var       = tk.StringVar(value="5, 25, 50, 75, 95")
        self.nodata_var    = tk.StringVar(value="-9999")
        self.progress_var  = tk.DoubleVar(value=0)
        self.stat_vars     = {k: tk.BooleanVar(value=d)
                              for k, _, d in self._STAT_DEFS}

        # ── Secciones colapsables ──────────────────────────────────────
        self._build_section_rutas(main, C)
        self._build_section_banda(main, C)
        self._build_section_entidades(main, C)
        self._build_section_estadisticos(main, C)
        self._build_section_ejecucion(main, C)

        tk.Frame(main, bg=C["bg"], height=24).pack()

    # ------------------------------------------------------------------
    # Secciones colapsables (acordeón)
    # ------------------------------------------------------------------

    def _accordion(self, parent, C, title: str, expanded: bool = True):
        """
        Crea un panel colapsable al estilo de los módulos de descarga.

        Devuelve (header_frame, body_frame).
        El body_frame es el contenedor donde se colocan los controles.
        Clic en el header alterna la visibilidad del body.
        """
        wrapper = tk.Frame(parent, bg=C["bg"])
        wrapper.pack(fill="x", padx=32, pady=(0, 6))

        # Cabecera clicable ─────────────────────────────────────────────
        hdr = tk.Frame(wrapper, bg=C["card"], cursor="hand2")
        hdr.pack(fill="x")

        arrow_var = tk.StringVar(value="▾" if expanded else "▸")
        tk.Label(hdr, textvariable=arrow_var,
                 font=("Segoe UI", 10), bg=C["card"],
                 fg=C["accent"]).pack(side="left", padx=(14, 4), pady=10)
        tk.Label(hdr, text=title,
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"]).pack(side="left", pady=10)

        # Cuerpo ────────────────────────────────────────────────────────
        body = tk.Frame(wrapper, bg=C["card"], padx=20, pady=12)
        if expanded:
            body.pack(fill="x")

        # Separador inferior ────────────────────────────────────────────
        tk.Frame(wrapper, bg=C["border"], height=1).pack(fill="x")

        def _toggle(e=None):
            if body.winfo_ismapped():
                body.pack_forget()
                arrow_var.set("▸")
            else:
                body.pack(fill="x")
                arrow_var.set("▾")

        hdr.bind("<Button-1>", _toggle)
        for child in hdr.winfo_children():
            child.bind("<Button-1>", _toggle)

        return hdr, body

    def _entry_row(self, parent, C, var, label: str, kind: str = "dir"):
        """
        Fila estándar: etiqueta + Entry readonly + botón Examinar.
        Mismo aspecto que los módulos de descarga.
        """
        tk.Label(parent, text=label,
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"],
                 anchor="w").pack(fill="x", pady=(0, 2))

        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=(0, 8))

        tk.Entry(row, textvariable=var,
                 font=("Segoe UI", 9),
                 bg=C["input_bg"], fg=C["fg"],
                 relief="flat", bd=0,
                 highlightthickness=1,
                 highlightbackground=C["border"],
                 highlightcolor=C["accent"],
                 state="readonly").pack(
            side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        def _browse():
            if kind == "dir":
                p = filedialog.askdirectory(
                    title=f"Seleccionar {label.rstrip(':')}")
            else:
                p = filedialog.askopenfilename(
                    title=f"Seleccionar {label.rstrip(':')}",
                    filetypes=[("Vectoriales", "*.shp *.geojson *.gpkg *.json"),
                               ("Todos los archivos", "*.*")])
            if p:
                var.set(p)

        self._btn(row, "📂  Examinar…", _browse,
                  style="secondary").pack(side="left")

    def _btn(self, parent, text: str, command, style: str = "primary"):
        """Botón estándar igual al de los módulos de descarga."""
        C = self.app.COLORS
        if style == "primary":
            bg, fg, abg = C["accent"], "white", C.get("accent_dark", C["accent"])
        else:
            bg  = C.get("btn_secondary_bg", C["card"])
            fg  = C["fg"]
            abg = C.get("btn_secondary_hover", C["border"])
        return tk.Button(parent, text=text, command=command,
                         font=("Segoe UI", 9),
                         bg=bg, fg=fg,
                         activebackground=abg, activeforeground=fg,
                         relief="flat", bd=0, padx=12, pady=6,
                         cursor="hand2")

    def _label_muted(self, parent, C, text: str):
        tk.Label(parent, text=text,
                 font=("Segoe UI", 8, "italic"),
                 bg=C["card"], fg=C["fg_muted"],
                 anchor="w", wraplength=560, justify="left").pack(
            fill="x", pady=(0, 6))

    # ------------------------------------------------------------------
    # Sección 1 — Rutas
    # ------------------------------------------------------------------
    def _build_section_rutas(self, parent, C):
        _, body = self._accordion(parent, C, "📂  RUTAS DE ENTRADA Y SALIDA",
                                  expanded=True)
        self._entry_row(body, C, self.tif_var,
                        "Carpeta de GeoTIFFs de entrada:", kind="dir")
        self._entry_row(body, C, self.vec_var,
                        "Archivo vectorial (.shp / .geojson / .gpkg):", kind="file")
        self._entry_row(body, C, self.out_var,
                        "Carpeta de salida:", kind="dir")

    # ------------------------------------------------------------------
    # Sección 2 — Banda / índice
    # ------------------------------------------------------------------
    def _build_section_banda(self, parent, C):
        _, body = self._accordion(parent, C, "🎯  BANDA / ÍNDICE A PROCESAR",
                                  expanded=True)

        tk.Label(body, text="Nombre de banda o índice:",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"], anchor="w").pack(fill="x", pady=(0, 2))

        br = tk.Frame(body, bg=C["card"])
        br.pack(fill="x", pady=(0, 4))

        self.banda_combo = ttk.Combobox(
            br, textvariable=self.banda_var,
            values=["NDVI"], width=28,
            font=("Segoe UI", 9), state="normal")
        self.banda_combo.pack(side="left", ipady=4)

        self._btn(br, "🔍  Detectar bandas", self._detect_bands,
                  style="secondary").pack(side="left", padx=(10, 0))

        self._label_muted(body, C,
            "Detecta automáticamente las descripciones de banda de los TIFs. "
            "También puedes escribir el nombre directamente.")

    # ------------------------------------------------------------------
    # Sección 3 — Entidades vectoriales
    # ------------------------------------------------------------------
    def _build_section_entidades(self, parent, C):
        _, body = self._accordion(parent, C, "📍  ENTIDADES VECTORIALES",
                                  expanded=False)

        # Campo ID
        tk.Label(body, text="Campo identificador (ID):",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"], anchor="w").pack(fill="x", pady=(0, 2))
        id_r = tk.Frame(body, bg=C["card"])
        id_r.pack(fill="x", pady=(0, 4))
        tk.Entry(id_r, textvariable=self.id_var, width=22,
                 font=("Segoe UI", 9),
                 bg=C["input_bg"], fg=C["fg"],
                 relief="flat", bd=0,
                 highlightthickness=1,
                 highlightbackground=C["border"],
                 highlightcolor=C["accent"]).pack(side="left", ipady=5)
        tk.Label(id_r, text="  'auto' = índice 0, 1, 2…",
                 font=("Segoe UI", 8),
                 bg=C["card"], fg=C["fg_muted"]).pack(side="left", padx=(8, 0))

        # Separador
        tk.Frame(body, bg=C["border"], height=1).pack(
            fill="x", pady=(8, 10))

        # Tipo de geometría — Combobox en lugar de radiobuttons
        tk.Label(body, text="Tipo de geometría:",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"], anchor="w").pack(fill="x", pady=(0, 2))

        geom_labels = [lbl for lbl, _ in self._GEOM_OPTIONS]
        geom_values = {lbl: val for lbl, val in self._GEOM_OPTIONS}
        values_rev  = {val: lbl for lbl, val in self._GEOM_OPTIONS}

        self._geom_label_var = tk.StringVar(
            value=values_rev.get(self.geom_var.get(), geom_labels[0]))

        def _on_geom_change(event=None):
            self.geom_var.set(
                geom_values.get(self._geom_label_var.get(), "auto"))
            self._toggle_point_method(body, C)

        geom_combo = ttk.Combobox(
            body,
            textvariable=self._geom_label_var,
            values=geom_labels,
            state="readonly",
            font=("Segoe UI", 9),
            width=26)
        geom_combo.pack(anchor="w", ipady=4, pady=(0, 8))
        geom_combo.bind("<<ComboboxSelected>>", _on_geom_change)

        # Método para puntos — visible sólo cuando geom = point
        self._pt_method_frame = tk.Frame(body, bg=C["card"])
        # No se empaca aquí; _toggle_point_method decide

        tk.Label(self._pt_method_frame, text="Método de extracción para puntos:",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"], anchor="w").pack(fill="x", pady=(0, 2))

        pt_labels = [lbl for lbl, _ in self._POINT_METHODS]
        pt_values = {lbl: val for lbl, val in self._POINT_METHODS}
        pt_rev     = {val: lbl for lbl, val in self._POINT_METHODS}

        self._pt_label_var = tk.StringVar(
            value=pt_rev.get(self.pt_method_var.get(), pt_labels[0]))

        def _on_pt_change(event=None):
            self.pt_method_var.set(
                pt_values.get(self._pt_label_var.get(), "nearest"))

        ttk.Combobox(
            self._pt_method_frame,
            textvariable=self._pt_label_var,
            values=pt_labels,
            state="readonly",
            font=("Segoe UI", 9),
            width=26).pack(anchor="w", ipady=4, pady=(0, 4))

        geom_combo.bind("<<ComboboxSelected>>",
                        lambda e: (_on_geom_change(), _on_pt_change()))

        self._label_muted(body, C,
            "En modo 'Auto-detectar' el tipo se infiere del archivo vectorial.")

    # ------------------------------------------------------------------
    # Sección 4 — Estadísticos y percentiles
    # ------------------------------------------------------------------
    def _build_section_estadisticos(self, parent, C):
        _, body = self._accordion(parent, C,
                                  "📈  ESTADÍSTICOS Y PERCENTILES",
                                  expanded=False)

        # ── Estadísticos ──────────────────────────────────────────────
        tk.Label(body, text="Estadísticos a exportar:",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"], anchor="w").pack(fill="x", pady=(0, 6))

        grid_f = tk.Frame(body, bg=C["card"])
        grid_f.pack(fill="x", pady=(0, 4))
        for col in range(2):
            grid_f.columnconfigure(col, weight=1)

        for i, (key, label, _) in enumerate(self._STAT_DEFS):
            tk.Checkbutton(
                grid_f, text=f"  {label}",
                variable=self.stat_vars[key],
                font=("Segoe UI", 9),
                bg=C["card"], fg=C["fg"],
                selectcolor=C["input_bg"],
                activebackground=C["card"],
                anchor="w", cursor="hand2",
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=6, pady=2)

        # Botones seleccionar/deseleccionar todos
        sel_row = tk.Frame(body, bg=C["card"])
        sel_row.pack(anchor="w", pady=(4, 10))
        self._btn(sel_row, "✅  Todos", self._stats_select_all,
                  style="secondary").pack(side="left", padx=(0, 6))
        self._btn(sel_row, "☐  Ninguno", self._stats_select_none,
                  style="secondary").pack(side="left")

        # Separador
        tk.Frame(body, bg=C["border"], height=1).pack(
            fill="x", pady=(2, 10))

        # ── Percentiles ───────────────────────────────────────────────
        tk.Label(body, text="Percentiles (separados por coma, 0–100):",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"], anchor="w").pack(fill="x", pady=(0, 2))

        tk.Entry(body, textvariable=self.pct_var, width=36,
                 font=("Segoe UI", 9),
                 bg=C["input_bg"], fg=C["fg"],
                 relief="flat", bd=0,
                 highlightthickness=1,
                 highlightbackground=C["border"],
                 highlightcolor=C["accent"]).pack(anchor="w", ipady=5, pady=(0, 4))

        self._label_muted(body, C,
            "Ejemplo: 5, 25, 50, 75, 95  ·  Déjalo vacío para no exportar percentiles.")

        # Separador
        tk.Frame(body, bg=C["border"], height=1).pack(
            fill="x", pady=(2, 10))

        # ── Nodata ────────────────────────────────────────────────────
        tk.Label(body, text="Valor nodata:",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"], anchor="w").pack(fill="x", pady=(0, 2))

        tk.Entry(body, textvariable=self.nodata_var, width=16,
                 font=("Segoe UI", 9),
                 bg=C["input_bg"], fg=C["fg"],
                 relief="flat", bd=0,
                 highlightthickness=1,
                 highlightbackground=C["border"],
                 highlightcolor=C["accent"]).pack(anchor="w", ipady=5, pady=(0, 4))

        self._label_muted(body, C,
            "Los píxeles con este valor se excluyen del cálculo.  Por defecto: -9999.")

    # ------------------------------------------------------------------
    # Sección 5 — Ejecución + log
    # ------------------------------------------------------------------
    def _build_section_ejecucion(self, parent, C):
        _, body = self._accordion(parent, C, "🚀  EJECUCIÓN Y RESULTADOS",
                                  expanded=True)

        # Barra de progreso
        self.progress_lbl = tk.Label(body, text="",
                                     font=("Segoe UI", 9),
                                     bg=C["card"], fg=C["accent"])
        self.progress_lbl.pack(anchor="w", pady=(0, 4))

        ttk.Progressbar(body, variable=self.progress_var,
                        maximum=100).pack(fill="x", pady=(0, 10))

        # Botón principal
        self.run_btn = tk.Button(
            body, text="▶  CALCULAR ESTADÍSTICOS",
            command=self._on_run,
            font=("Segoe UI", 10, "bold"),
            bg=C["accent"], fg="white",
            activebackground=C.get("accent_dark", C["accent"]),
            activeforeground="white",
            relief="flat", bd=0, padx=20, pady=9,
            cursor="hand2")
        self.run_btn.pack(anchor="w", pady=(0, 14))

        # Separador
        tk.Frame(body, bg=C["border"], height=1).pack(fill="x", pady=(0, 10))

        # Log
        tk.Label(body, text="📋  Log de ejecución:",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"], anchor="w").pack(fill="x", pady=(0, 4))

        self.log_box = scrolledtext.ScrolledText(
            body, height=14,
            font=("Consolas", 9),
            bg=C.get("input_bg", "#1e1e2e"),
            fg=C["fg"],
            relief="flat", bd=0, wrap="word",
            state="disabled")
        self.log_box.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Helpers UI
    # ------------------------------------------------------------------

    def _toggle_point_method(self, body=None, C=None):
        """Muestra u oculta el panel de método para puntos."""
        geom = self.geom_var.get()
        if geom in ("point", "auto"):
            self._pt_method_frame.pack(fill="x", pady=(0, 6))
        else:
            self._pt_method_frame.pack_forget()

    def _stats_select_all(self):
        for v in self.stat_vars.values():
            v.set(True)

    def _stats_select_none(self):
        for v in self.stat_vars.values():
            v.set(False)

    def _detect_bands(self):
        folder = self.tif_var.get().strip()
        if not folder or not os.path.isdir(folder):
            self.app.notify("⚠️ Selecciona primero la carpeta de TIFs.",
                            level="warning")
            return
        try:
            import rasterio
            bands = set()
            for t in sorted(glob.glob(os.path.join(folder, "*.tif")))[:5]:
                try:
                    with rasterio.open(t) as src:
                        for i in range(src.count):
                            d = src.descriptions[i]
                            if d:
                                bands.add(d)
                except Exception:
                    pass
            if not bands:
                self.app.notify("⚠️ No se detectaron descripciones de banda.",
                                level="warning")
                return
            band_list = sorted(bands)
            self.banda_combo["values"] = band_list
            self.banda_var.set(band_list[0])
            self.app.notify(f"✅ {len(band_list)} banda(s) detectada(s).",
                            level="success")
        except ImportError:
            self.app.notify("❌ rasterio no está instalado.", level="error")

    def _log(self, msg: str):
        self.after(0, self._log_main, msg)

    def _log_main(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_progress(self, value, text=""):
        self.after(0, self._set_progress_main, value, text)

    def _set_progress_main(self, value, text):
        self.progress_var.set(value)
        if text:
            self.progress_lbl.config(text=text)

    def _done(self, success: bool):
        self.after(0, self._done_main, success)

    def _done_main(self, success: bool):
        self.run_btn.configure(state="normal")
        msg = "✅ Agregación completada." if success else "❌ Finalizado con errores."
        self.progress_lbl.config(text=msg)
        self.app.notify(msg, level="success" if success else "error")

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------
    def _on_run(self):
        # Validar rutas obligatorias
        for label, var in [("Carpeta TIFs",    self.tif_var),
                            ("Archivo vectorial", self.vec_var),
                            ("Carpeta de salida", self.out_var)]:
            if not var.get().strip():
                self.app.notify(f"⚠️ Falta: {label}", level="warning")
                return

        # Parsear percentiles
        try:
            pct_raw    = self.pct_var.get().strip()
            percentiles = ([int(x.strip()) for x in pct_raw.split(",")
                            if x.strip()] if pct_raw else [])
        except ValueError:
            self.app.notify(
                "⚠️ Percentiles inválidos. Usa enteros separados por coma.",
                level="warning")
            return

        # Parsear nodata
        try:
            nodata = float(self.nodata_var.get())
        except ValueError:
            self.app.notify("⚠️ Valor nodata inválido.", level="warning")
            return

        # Estadísticos seleccionados
        stats_sel = [k for k, v in self.stat_vars.items() if v.get()]
        if not stats_sel:
            self.app.notify("⚠️ Selecciona al menos un estadístico.",
                            level="warning")
            return

        params = {
            "tif_folder"  : self.tif_var.get().strip(),
            "vector_path" : self.vec_var.get().strip(),
            "banda"       : self.banda_var.get().strip(),
            "out_folder"  : self.out_var.get().strip(),
            "id_field"    : self.id_var.get().strip(),
            "geom_type"   : self.geom_var.get(),
            "point_method": self.pt_method_var.get(),
            "percentiles" : percentiles,
            "stats"       : stats_sel,
            "nodata"      : nodata,
        }

        # Limpiar log y lanzar
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress_var.set(0)
        self.progress_lbl.config(text="")
        self.run_btn.configure(state="disabled")

        threading.Thread(
            target=run_aggregation,
            args=(params, self._log, self._done),
            kwargs={"progress_fn": self._set_progress},
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def on_show(self):
        pass

    def on_hide(self):
        pass

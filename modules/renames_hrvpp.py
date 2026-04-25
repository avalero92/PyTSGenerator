"""
renames_hrvpp.py — Módulo de renombrado de imágenes TIF.

Fusiona las apps Shiny:
  - renamesVI_v2_ (STPPI): extrae fecha YYYYMMDD del nombre y renombra a YYYYMMDD.tif
  - renamesVPP    (VPP):   misma lógica con ruta escrita manualmente

Registrar en main_app.py → MODULES_REGISTRY.
"""

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from datetime import datetime

from modules.base import BaseModule


class RenamesHRVPPModule(BaseModule):
    """
    Módulo de renombrado de imágenes TIF para series temporales.
    Permite elegir entre el flujo STPPI (selector de carpeta) y
    el flujo VPP (ruta escrita manualmente).
    """
    NAME = "Renames HR-VPP"
    ICON = "✏️"

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def build_ui(self):
        C = self.app.COLORS

        # ── Encabezado ─────────────────────────────────────────────────
        tk.Label(
            self,
            text="✏️ Renombrado de Imágenes TIF",
            font=("Segoe UI", 14, "bold"),
            bg=C["bg"], fg=C["fg"]
        ).pack(pady=(28, 4))

        tk.Label(
            self,
            text="Renombra archivos .tif extrayendo la fecha YYYYMMDD del nombre original.",
            font=("Segoe UI", 9),
            bg=C["bg"], fg=C["fg_muted"]
        ).pack(pady=(0, 18))

        # ── Card principal ──────────────────────────────────────────────
        card = tk.Frame(self, bg=C["card"], padx=24, pady=22)
        card.pack(padx=36, pady=0, fill="x")

        # ── Selector de tipo (menú desplegable) ────────────────────────
        tk.Label(
            card,
            text="Selecciona el tipo de producto a renombrar:",
            font=("Segoe UI", 9, "bold"),
            bg=C["card"], fg=C["fg"]
        ).pack(anchor="w")

        self.tipo_var = tk.StringVar(value="STPPI")
        combo = ttk.Combobox(
            card,
            textvariable=self.tipo_var,
            values=["STPPI", "VPP"],
            state="readonly",
            font=("Segoe UI", 10),
            width=20
        )
        combo.pack(anchor="w", pady=(6, 18))
        combo.bind("<<ComboboxSelected>>", self._on_tipo_change)

        # ── Frame STPPI (selector de carpeta con botón) ────────────────
        self.frame_stppi = tk.Frame(card, bg=C["card"])
        self.frame_stppi.pack(fill="x")

        tk.Label(
            self.frame_stppi,
            text="📁 Carpeta con imágenes TIF (STPPI):",
            font=("Segoe UI", 9, "bold"),
            bg=C["card"], fg=C["fg"]
        ).pack(anchor="w")

        row_stppi = tk.Frame(self.frame_stppi, bg=C["card"])
        row_stppi.pack(fill="x", pady=(4, 0))

        self.stppi_path_var = tk.StringVar()
        tk.Entry(
            row_stppi,
            textvariable=self.stppi_path_var,
            font=("Segoe UI", 10),
            bg=C["input_bg"], fg=C["fg"],
            relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["accent"],
            state="readonly"
        ).pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        tk.Button(
            row_stppi,
            text="Examinar…",
            command=self._browse_stppi,
            font=("Segoe UI", 9),
            bg=C["accent"], fg="white",
            activebackground=C["accent_dark"],
            activeforeground="white",
            relief="flat", bd=0,
            padx=12, pady=6,
            cursor="hand2"
        ).pack(side="left")

        tk.Label(
            self.frame_stppi,
            text="Ejemplo de archivo: S2A_MSIL2A_20230115T105231_… → 20230115.tif",
            font=("Segoe UI", 8),
            bg=C["card"], fg=C["fg_muted"]
        ).pack(anchor="w", pady=(6, 0))

        # ── Frame VPP (selector de carpeta con botón, igual que STPPI) ──
        self.frame_vpp = tk.Frame(card, bg=C["card"])
        # No se empaqueta hasta que se seleccione VPP

        tk.Label(
            self.frame_vpp,
            text="📁 Carpeta con imágenes TIF (VPP):",
            font=("Segoe UI", 9, "bold"),
            bg=C["card"], fg=C["fg"]
        ).pack(anchor="w")

        row_vpp = tk.Frame(self.frame_vpp, bg=C["card"])
        row_vpp.pack(fill="x", pady=(4, 0))

        self.vpp_path_var = tk.StringVar()
        tk.Entry(
            row_vpp,
            textvariable=self.vpp_path_var,
            font=("Segoe UI", 10),
            bg=C["input_bg"], fg=C["fg"],
            relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=C["border"],
            highlightcolor=C["accent"],
            state="readonly"
        ).pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        tk.Button(
            row_vpp,
            text="Examinar…",
            command=self._browse_vpp,
            font=("Segoe UI", 9),
            bg=C["accent"], fg="white",
            activebackground=C["accent_dark"],
            activeforeground="white",
            relief="flat", bd=0,
            padx=12, pady=6,
            cursor="hand2"
        ).pack(side="left")

        tk.Label(
            self.frame_vpp,
            text="Ejemplo de archivo: VPP_2023_S2_T30TXM-010m_V105_s1_SOSD.tif → 2023.tif",
            font=("Segoe UI", 8),
            bg=C["card"], fg=C["fg_muted"]
        ).pack(anchor="w", pady=(6, 0))

        # ── Botón ejecutar ─────────────────────────────────────────────
        tk.Button(
            card,
            text="🚀 Renombrar Imágenes",
            command=self._on_rename,
            font=("Segoe UI", 10, "bold"),
            bg=C["accent"], fg="white",
            activebackground=C["accent_dark"],
            activeforeground="white",
            relief="flat", bd=0,
            padx=18, pady=9,
            cursor="hand2"
        ).pack(pady=(20, 0))

        # ── Card de resultados ─────────────────────────────────────────
        card_results = tk.Frame(self, bg=C["card"], padx=24, pady=18)
        card_results.pack(padx=36, pady=(16, 28), fill="both", expand=True)

        tk.Label(
            card_results,
            text="📊 Resultados",
            font=("Segoe UI", 10, "bold"),
            bg=C["card"], fg=C["fg"]
        ).pack(anchor="w", pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(
            card_results,
            font=("Consolas", 9),
            bg=C.get("input_bg", "#1e1e2e"),
            fg=C["fg"],
            relief="flat",
            bd=0,
            height=12,
            wrap="word",
            state="disabled"
        )
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------
    def _on_tipo_change(self, event=None):
        """Muestra el frame correspondiente según el tipo seleccionado."""
        if self.tipo_var.get() == "STPPI":
            self.frame_vpp.pack_forget()
            self.frame_stppi.pack(fill="x")
        else:
            self.frame_stppi.pack_forget()
            self.frame_vpp.pack(fill="x")

    def _browse_stppi(self):
        """Abre el diálogo para seleccionar carpeta (flujo STPPI)."""
        folder = filedialog.askdirectory(title="Seleccionar carpeta con imágenes TIF (STPPI)")
        if folder:
            self.stppi_path_var.set(folder)

    def _browse_vpp(self):
        """Abre el diálogo para seleccionar carpeta (flujo VPP)."""
        folder = filedialog.askdirectory(title="Seleccionar carpeta con imágenes TIF (VPP)")
        if folder:
            self.vpp_path_var.set(folder)

    def _on_rename(self):
        """Obtiene la ruta según el tipo y ejecuta el renombrado."""
        tipo = self.tipo_var.get()

        if tipo == "STPPI":
            carpeta = self.stppi_path_var.get().strip()
            if not carpeta:
                self.app.notify("⚠️ Selecciona una carpeta primero (STPPI).", level="warning")
                return
        else:  # VPP
            carpeta = self.vpp_path_var.get().strip()
            if not carpeta:
                self.app.notify("⚠️ Selecciona una carpeta primero (VPP).", level="warning")
                return

        if not os.path.isdir(carpeta):
            self.app.notify("❌ La carpeta no existe o no es válida.", level="error")
            return

        self._run_rename(carpeta, tipo)

    # ------------------------------------------------------------------
    # Lógica de renombrado (equivalente a renames.image.IV en R)
    # ------------------------------------------------------------------
    def _run_rename(self, carpeta: str, tipo: str):
        """
        Renombra todos los .tif en `carpeta` extrayendo la fecha YYYYMMDD
        del nombre original.  Misma lógica que las dos apps Shiny.
        """
        archivos = [
            f for f in os.listdir(carpeta)
            if f.lower().endswith(".tif")
        ]

        self._log_clear()
        self._log(f"{'='*52}")
        self._log(f"  RENOMBRADO  [{tipo}]  —  {datetime.now():%Y-%m-%d %H:%M:%S}")
        self._log(f"  Carpeta: {carpeta}")
        self._log(f"{'='*52}\n")

        if not archivos:
            self._log("⚠️  No se encontraron archivos .tif en la carpeta.")
            self.app.notify("⚠️ No hay archivos .tif en la carpeta.", level="warning")
            return

        renombrados = 0
        errores = 0

        for nombre in archivos:
            if tipo == "VPP":
                # Formato VPP: VPP_YYYY_… → YYYY.tif
                match = re.search(r"(?:^|_)VPP_(\d{4})_", nombre)
                if not match:
                    # Fallback: primer grupo de 4 dígitos que parezca un año
                    match = re.search(r"(?<![\d])(20\d{2})(?![\d])", nombre)
                if not match:
                    self._log(f"⚠️  Sin año (YYYY) en nombre VPP: {nombre}")
                    errores += 1
                    continue
                nuevo_nombre = f"{match.group(1)}.tif"
            else:
                # Formato STPPI: extrae fecha YYYYMMDD → YYYYMMDD.tif
                match = re.search(r"\d{8}", nombre)
                if not match:
                    self._log(f"⚠️  Sin fecha (YYYYMMDD) en nombre STPPI: {nombre}")
                    errores += 1
                    continue
                nuevo_nombre = f"{match.group()}.tif"
            origen = os.path.join(carpeta, nombre)
            destino = os.path.join(carpeta, nuevo_nombre)

            if os.path.exists(destino) and origen != destino:
                self._log(f"❌  Ya existe destino, omitido: {nuevo_nombre}")
                errores += 1
                continue

            try:
                os.rename(origen, destino)
                self._log(f"✅  {nombre}  →  {nuevo_nombre}")
                renombrados += 1
            except OSError as exc:
                self._log(f"❌  Falló '{nombre}': {exc}")
                errores += 1

        self._log(f"\n{'─'*52}")
        self._log(f"  Renombrados correctamente : {renombrados}")
        self._log(f"  Con errores / omitidos    : {errores}")
        self._log(f"  Total .tif encontrados    : {len(archivos)}")
        self._log(f"{'─'*52}")

        if renombrados > 0:
            self.app.notify(f"✅ {renombrados} archivo(s) renombrado(s) correctamente.", level="success")
        else:
            self.app.notify("⚠️ No se renombró ningún archivo.", level="warning")

    # ------------------------------------------------------------------
    # Helpers de log
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log_clear(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def on_show(self):
        pass

    def on_hide(self):
        pass

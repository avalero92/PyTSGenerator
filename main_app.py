"""
main_app.py — Orquestador principal de la aplicación modular.

Mejoras implementadas:
  - Estado global compartido (session) para credenciales y configuración
  - Sistema de logging a fichero con RotatingFileHandler
  - Validación de dependencias críticas al arranque
  - Panel de bienvenida con flujo guiado
  - Panel de notificaciones persistente (además del toast)
  - Toast clicable y con niveles (info / warning / error / success)
  - Gestión robusta de errores en carga de módulos con diagnóstico
  - Footer con versión y enlace a documentación

Para añadir un nuevo módulo:
    1. Crear modules/mi_modulo.py heredando de BaseModule
    2. Añadirlo a MODULES_REGISTRY abajo
    3. ¡Listo!
"""

import tkinter as tk
from tkinter import ttk
import importlib
import sys
import os
import logging
import traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime

# ── Registro de módulos ──────────────────────────────────────────────────────
# Formato: (nombre_módulo_python, clase, descripción_breve)
# El orden determina el orden en el sidebar y en la pantalla de bienvenida.
MODULES_REGISTRY = [
    (
        "modules.download_stppi",
        "DownloadSTPPIModule",
        "Busca y descarga productos Short-Term Plant Phenology Indicator (STPPI) desde el HDA de Copernicus.",
    ),
    (
        "modules.download_hrvpp",
        "DownloadHRVPPModule",
        "Busca y descarga productos de Fenología de Alta Resolución (HR-VPP) desde el HDA de Copernicus.",
    ),
    (
        "modules.renames_hrvpp",
        "RenamesHRVPPModule",
        "Renombra imágenes TIF extrayendo la fecha YYYYMMDD del nombre original para normalizar series temporales.",
    ),
    (
        "modules.agregacion_zonal",
        "AgregacionZonalModule",
        "Extrae estadísticos zonales (media, mediana, percentiles…) de GeoTIFFs usando geometrías vectoriales.",
    ),
    # Añade aquí futuros módulos:
    # ("modules.otro_modulo", "OtroModulo", "Descripción del módulo."),
]

# ── Dependencias opcionales con mensaje de diagnóstico ───────────────────────
OPTIONAL_DEPS = {
    "rasterio":   "Necesario para Agregación Zonal y lectura de GeoTIFFs.",
    "geopandas":  "Necesario para Agregación Zonal (archivos vectoriales).",
    "numpy":      "Necesario para cálculo de estadísticos en Agregación Zonal.",
    "scipy":      "Necesario para interpolación bilineal en puntos.",
    "hda":        "Necesario para descargas desde el HDA de Copernicus (STPPI / HR-VPP).",
    "keyring":    "Recomendado para almacenamiento seguro de credenciales.",
}


# ── Configuración del logger de aplicación ───────────────────────────────────

def _setup_logger() -> logging.Logger:
    """Configura el logger de la aplicación con salida a fichero y consola."""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "pytsgenerator.log")

    logger = logging.getLogger("PyTSGenerator")
    logger.setLevel(logging.DEBUG)

    # Handler rotativo: máx 2 MB × 3 ficheros
    fh = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024,
                             backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))

    # Handler de consola (solo WARNING+)
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    if not logger.handlers:
        logger.addHandler(fh)
        logger.addHandler(ch)

    return logger


# ── Pantalla de bienvenida ───────────────────────────────────────────────────

class WelcomePanel(tk.Frame):
    """
    Panel de bienvenida que se muestra al arrancar la aplicación.
    Presenta un resumen de los módulos disponibles y el flujo recomendado.
    """

    FLOW_STEPS = [
        ("1", "Descarga STPPI",    "modules.download_stppi",    "DownloadSTPPIModule"),
        ("2", "Descarga HR-VPP",   "modules.download_hrvpp",    "DownloadHRVPPModule"),
        ("3", "Renombrado TIF",    "modules.renames_hrvpp",     "RenamesHRVPPModule"),
        ("4", "Agregación Zonal",  "modules.agregacion_zonal",  "AgregacionZonalModule"),
    ]

    def __init__(self, parent, app):
        C = app.COLORS
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._build(C)

    def _build(self, C):
        # Scroll
        canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["bg"])
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))

        # ── Cabecera ──────────────────────────────────────────────────────
        hdr = tk.Frame(inner, bg=C["accent"], pady=32)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🛰️  PyTSGenerator",
                 font=("Segoe UI", 22, "bold"),
                 bg=C["accent"], fg="white").pack()
        tk.Label(hdr,
                 text="Herramienta modular para la generación de series temporales de teledetección",
                 font=("Segoe UI", 10),
                 bg=C["accent"], fg="#c3caf5").pack(pady=(6, 0))

        # ── Flujo recomendado ─────────────────────────────────────────────
        tk.Label(inner, text="Flujo de trabajo recomendado",
                 font=("Segoe UI", 12, "bold"),
                 bg=C["bg"], fg=C["fg"]).pack(anchor="w", padx=40, pady=(28, 10))

        flow_frame = tk.Frame(inner, bg=C["bg"])
        flow_frame.pack(fill="x", padx=40)

        for i, (step, name, mod_path, cls_name) in enumerate(self.FLOW_STEPS):
            col = tk.Frame(flow_frame, bg=C["card"],
                           relief="flat", padx=18, pady=18,
                           highlightthickness=1,
                           highlightbackground=C["card_border"])
            col.grid(row=0, column=i, padx=8, sticky="nsew")
            flow_frame.columnconfigure(i, weight=1)

            # Número de paso
            tk.Label(col, text=step,
                     font=("Segoe UI", 18, "bold"),
                     bg=C["accent_light"], fg=C["accent"],
                     width=3, relief="flat").pack()

            # Nombre
            tk.Label(col, text=name,
                     font=("Segoe UI", 10, "bold"),
                     bg=C["card"], fg=C["fg"],
                     wraplength=130).pack(pady=(8, 4))

            # Descripción del módulo desde el registro
            desc = next(
                (d for mp, cn, d in
                 [(e[0], e[1], e[2]) for e in MODULES_REGISTRY]
                 if mp == mod_path and cn == cls_name),
                ""
            )
            tk.Label(col, text=desc,
                     font=("Segoe UI", 8),
                     bg=C["card"], fg=C["fg_muted"],
                     wraplength=130, justify="left").pack()

            # Flecha entre pasos
            if i < len(self.FLOW_STEPS) - 1:
                tk.Label(flow_frame, text="→",
                         font=("Segoe UI", 18),
                         bg=C["bg"], fg=C["fg_muted"]).grid(
                    row=0, column=i, sticky="e", padx=(0, 4))

            # Botón de acceso directo
            target_name = None
            for mp, cn, _ in MODULES_REGISTRY:
                if mp == mod_path and cn == cls_name:
                    try:
                        m = importlib.import_module(mp)
                        target_name = getattr(m, cn).NAME
                    except Exception:
                        pass
                    break

            if target_name:
                tk.Button(
                    col, text=f"Abrir →",
                    command=lambda n=target_name: self.app.show_module(n),
                    font=("Segoe UI", 8, "bold"),
                    bg=C["accent"], fg="white",
                    activebackground=C["accent_dark"],
                    activeforeground="white",
                    relief="flat", bd=0,
                    padx=10, pady=4, cursor="hand2"
                ).pack(pady=(10, 0))

        # ── Estado de dependencias ────────────────────────────────────────
        tk.Label(inner, text="Estado de dependencias",
                 font=("Segoe UI", 12, "bold"),
                 bg=C["bg"], fg=C["fg"]).pack(anchor="w", padx=40, pady=(32, 10))

        deps_frame = tk.Frame(inner, bg=C["card"],
                              padx=20, pady=16,
                              highlightthickness=1,
                              highlightbackground=C["card_border"])
        deps_frame.pack(fill="x", padx=40, pady=(0, 8))

        for pkg, desc in OPTIONAL_DEPS.items():
            try:
                importlib.import_module(pkg)
                estado = ("✅", "#38a169", "Instalado")
            except ImportError:
                estado = ("⚠️", "#dd6b20", "No encontrado")

            row = tk.Frame(deps_frame, bg=C["card"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=estado[0], font=("Segoe UI", 10),
                     bg=C["card"]).pack(side="left")
            tk.Label(row, text=f"  {pkg}",
                     font=("Consolas", 9, "bold"),
                     bg=C["card"], fg=estado[1]).pack(side="left")
            tk.Label(row, text=f"  —  {desc}",
                     font=("Segoe UI", 9),
                     bg=C["card"], fg=C["fg_muted"]).pack(side="left")

        tk.Label(
            inner,
            text="Si alguna dependencia falta, instálala con:  pip install <paquete>",
            font=("Segoe UI", 8, "italic"),
            bg=C["bg"], fg=C["fg_muted"]
        ).pack(anchor="w", padx=40, pady=(6, 40))


# ── Panel de notificaciones persistente ─────────────────────────────────────

class NotificationPanel(tk.Frame):
    """
    Panel lateral/inferior que acumula notificaciones con nivel y timestamp.
    Clicable para limpiar. Accesible desde cualquier módulo vía app.notify().
    """

    _COLORS_BY_LEVEL = {
        "success": ("#38a169", "#f0fff4", "✅"),
        "warning": ("#dd6b20", "#fffaf0", "⚠️"),
        "error":   ("#e53e3e", "#fff5f5", "❌"),
        "info":    ("#3182ce", "#ebf8ff", "ℹ️"),
    }

    def __init__(self, parent, app):
        C = app.COLORS
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._entries: list[dict] = []
        self._build(C)

    def _build(self, C):
        header = tk.Frame(self, bg=C["card_border"], pady=6, padx=12)
        header.pack(fill="x")
        tk.Label(header, text="🔔  Notificaciones",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card_border"], fg=C["fg"]).pack(side="left")
        tk.Button(header, text="Limpiar",
                  command=self._clear,
                  font=("Segoe UI", 8),
                  bg=C["card_border"], fg=C["fg_muted"],
                  relief="flat", bd=0, cursor="hand2").pack(side="right")

        self._list_frame = tk.Frame(self, bg=C["bg"])
        self._list_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self._empty_lbl = tk.Label(
            self._list_frame,
            text="Sin notificaciones recientes.",
            font=("Segoe UI", 8, "italic"),
            bg=C["bg"], fg=C["fg_muted"])
        self._empty_lbl.pack(pady=10)

    def add(self, message: str, level: str = "info"):
        C = self.app.COLORS
        color, bg, icon = self._COLORS_BY_LEVEL.get(
            level, self._COLORS_BY_LEVEL["info"])

        self._empty_lbl.pack_forget()
        self._entries.append({"msg": message, "level": level,
                               "time": datetime.now()})

        row = tk.Frame(self._list_frame, bg=bg,
                       highlightthickness=1, highlightbackground=color,
                       padx=8, pady=5)
        row.pack(fill="x", pady=2)

        tk.Label(row, text=icon, font=("Segoe UI", 10),
                 bg=bg).pack(side="left", padx=(0, 6))
        tk.Label(row, text=message,
                 font=("Segoe UI", 8),
                 bg=bg, fg=C["fg"],
                 wraplength=180, justify="left",
                 anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(row, text=datetime.now().strftime("%H:%M"),
                 font=("Segoe UI", 7),
                 bg=bg, fg=C["fg_muted"]).pack(side="right")

    def _clear(self):
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._entries.clear()
        self._empty_lbl = tk.Label(
            self._list_frame,
            text="Sin notificaciones recientes.",
            font=("Segoe UI", 8, "italic"),
            bg=self.app.COLORS["bg"], fg=self.app.COLORS["fg_muted"])
        self._empty_lbl.pack(pady=10)


# ── Aplicación principal ─────────────────────────────────────────────────────

class MainApp(tk.Tk):
    """
    Orquestador principal de PyTSGenerator.

    Atributos públicos para módulos hijos:
      self.session   : dict  — estado global compartido (credenciales, config…)
      self.logger    : Logger — logger de la aplicación
      self.COLORS    : dict  — paleta de colores
      self.notify()  — añade notificación persistente + toast
      self.show_toast() — toast temporal sin registrar
    """

    # ── Paleta de colores ────────────────────────────────────────────────────
    COLORS = {
        # Fondos
        "bg":           "#f0f2f5",
        "sidebar_bg":   "#1e1e2e",
        "card":         "#ffffff",
        "card_border":  "#e2e8f0",
        "input_bg":     "#f8fafc",
        # Texto
        "fg":           "#1a202c",
        "fg_muted":     "#718096",
        "fg_sidebar":   "#e2e8f0",
        "fg_sidebar_m": "#a0aec0",
        # Acento
        "accent":       "#5a67d8",
        "accent_dark":  "#434190",
        "accent_light": "#ebf4ff",
        # Bordes
        "border":       "#cbd5e0",
        "selected_bg":  "#2d3748",
        # Niveles notificación
        "success":      "#38a169",
        "warning":      "#dd6b20",
        "error":        "#e53e3e",
    }

    SIDEBAR_W   = 230
    NOTIF_W     = 220
    TITLE       = "🛰️  PyTSGenerator"
    VERSION     = "v1.1"
    AUTHOR      = "CLMS · Copernicus Land Monitoring Service"

    def __init__(self):
        super().__init__()
        self.title(self.TITLE)
        self.geometry("1260x740")
        self.minsize(900, 560)
        self.configure(bg=self.COLORS["bg"])

        # ── Estado global compartido ─────────────────────────────────────
        self.session: dict = {
            # Credenciales HDA (compartidas entre módulos de descarga)
            "hda_user":         "",
            "hda_pass":         "",
            # Rutas persistentes de sesión
            "last_download_dir": "",
            "last_vector_path":  "",
            "last_tif_folder":   "",
            # Flags de configuración
            "hda_verified":      False,
        }

        # ── Logger ───────────────────────────────────────────────────────
        self.logger = _setup_logger()
        self.logger.info("=" * 60)
        self.logger.info(f"PyTSGenerator {self.VERSION} arrancando")
        self.logger.info(f"Python {sys.version}")
        self.logger.info("=" * 60)

        # ── Estructuras internas ─────────────────────────────────────────
        self._modules:      dict[str, tk.Frame]  = {}
        self._active:       str | None           = None
        self._sidebar_btns: dict[str, tk.Label]  = {}
        self._failed_mods:  list[tuple]          = []   # (cls_name, error)

        # ── Construir interfaz ───────────────────────────────────────────
        self._build_layout()
        self._build_toast()
        self._check_dependencies()
        self._load_modules()

        # Mostrar pantalla de bienvenida primero
        self.show_module("__welcome__")

    # ── Layout principal ─────────────────────────────────────────────────────

    def _build_layout(self):
        C = self.COLORS

        # ── Sidebar izquierdo ─────────────────────────────────────────────
        self.sidebar = tk.Frame(self, bg=C["sidebar_bg"], width=self.SIDEBAR_W)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo / título
        header = tk.Frame(self.sidebar, bg=C["sidebar_bg"], pady=22)
        header.pack(fill="x")
        tk.Label(header, text="🛰️",
                 font=("Segoe UI", 26),
                 bg=C["sidebar_bg"], fg=C["fg_sidebar"]).pack()
        tk.Label(header, text="PyTSGenerator",
                 font=("Segoe UI", 12, "bold"),
                 bg=C["sidebar_bg"], fg=C["fg_sidebar"]).pack()
        tk.Label(header, text=self.VERSION,
                 font=("Segoe UI", 8),
                 bg=C["sidebar_bg"], fg=C["fg_sidebar_m"]).pack(pady=(2, 0))

        ttk.Separator(self.sidebar, orient="horizontal").pack(
            fill="x", padx=16, pady=8)

        # Botón de bienvenida
        self._add_sidebar_static_btn("🏠  Inicio", "__welcome__")

        ttk.Separator(self.sidebar, orient="horizontal").pack(
            fill="x", padx=16, pady=(4, 8))

        tk.Label(self.sidebar, text="  MÓDULOS",
                 font=("Segoe UI", 7, "bold"),
                 bg=C["sidebar_bg"], fg=C["fg_sidebar_m"],
                 anchor="w").pack(fill="x", padx=12, pady=(0, 4))

        # Contenedor de botones de módulos (se rellena en _load_modules)
        self.nav_frame = tk.Frame(self.sidebar, bg=C["sidebar_bg"])
        self.nav_frame.pack(fill="x", padx=8)

        # ── Footer del sidebar ─────────────────────────────────────────
        footer = tk.Frame(self.sidebar, bg=C["sidebar_bg"])
        footer.pack(side="bottom", fill="x", pady=10)
        ttk.Separator(self.sidebar, orient="horizontal").pack(
            side="bottom", fill="x", padx=16, pady=(0, 10))
        tk.Label(footer, text=self.AUTHOR,
                 font=("Segoe UI", 7),
                 bg=C["sidebar_bg"], fg=C["fg_sidebar_m"],
                 wraplength=200).pack(padx=8)

        # ── Área de contenido central ─────────────────────────────────────
        self.content_area = tk.Frame(self, bg=C["bg"])
        self.content_area.pack(side="left", fill="both", expand=True)

        # Barra superior
        topbar = tk.Frame(self.content_area, bg=C["card"], height=52, pady=12)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        self.topbar_title = tk.Label(
            topbar, text="", font=("Segoe UI", 13, "bold"),
            bg=C["card"], fg=C["fg"], anchor="w")
        self.topbar_title.pack(side="left", padx=20)

        # Indicador de sesión HDA en la topbar
        self.hda_status_lbl = tk.Label(
            topbar, text="⬤  HDA: sin conectar",
            font=("Segoe UI", 8),
            bg=C["card"], fg=C["fg_muted"])
        self.hda_status_lbl.pack(side="right", padx=16)

        # Separador
        tk.Frame(self.content_area, bg=C["border"], height=1).pack(fill="x")

        # Contenedor de módulos apilados
        self.module_container = tk.Frame(self.content_area, bg=C["bg"])
        self.module_container.pack(fill="both", expand=True)

        # ── Panel de notificaciones derecho ───────────────────────────────
        notif_container = tk.Frame(self, bg=C["bg"], width=self.NOTIF_W)
        notif_container.pack(side="right", fill="y")
        notif_container.pack_propagate(False)

        # Toggle para mostrar/ocultar el panel
        self._notif_visible = True
        self._notif_container = notif_container

        self.notif_panel = NotificationPanel(notif_container, self)
        self.notif_panel.pack(fill="both", expand=True)

        # Botón toggle en topbar
        self._notif_toggle_btn = tk.Button(
            topbar,
            text="🔔",
            command=self._toggle_notif_panel,
            font=("Segoe UI", 11),
            bg=C["card"], fg=C["fg_muted"],
            activebackground=C["card"],
            relief="flat", bd=0,
            cursor="hand2", padx=6)
        self._notif_toggle_btn.pack(side="right", padx=(0, 4))

    def _toggle_notif_panel(self):
        """Muestra u oculta el panel de notificaciones."""
        if self._notif_visible:
            self._notif_container.pack_forget()
            self._notif_visible = False
            self._notif_toggle_btn.config(fg=self.COLORS["fg_muted"])
        else:
            # Reposicionar: debe ir a la derecha del content_area
            self._notif_container.pack(side="right", fill="y")
            self._notif_visible = True
            self._notif_toggle_btn.config(fg=self.COLORS["accent"])

    def _add_sidebar_static_btn(self, label: str, key: str):
        """Añade un botón estático al sidebar (p.ej. Inicio)."""
        C = self.COLORS
        btn_frame = tk.Frame(self.sidebar, bg=C["sidebar_bg"], cursor="hand2")
        btn_frame.pack(fill="x", padx=8, pady=2)

        lbl = tk.Label(
            btn_frame,
            text=f"  {label}",
            font=("Segoe UI", 10),
            bg=C["sidebar_bg"], fg=C["fg_sidebar"],
            anchor="w", pady=10, padx=8)
        lbl.pack(fill="x")
        self._sidebar_btns[key] = lbl

        for w in (btn_frame, lbl):
            w.bind("<Button-1>", lambda e, k=key: self.show_module(k))
            w.bind("<Enter>",
                   lambda e, wf=btn_frame, l=lbl: (
                       wf.config(bg=C["selected_bg"]),
                       l.config(bg=C["selected_bg"])))
            w.bind("<Leave>",
                   lambda e, k=key, wf=btn_frame, l=lbl: (
                       wf.config(bg=C["selected_bg"] if self._active == k else C["sidebar_bg"]),
                       l.config(bg=C["selected_bg"] if self._active == k else C["sidebar_bg"])))

    # ── Comprobación de dependencias ─────────────────────────────────────────

    def _check_dependencies(self):
        """Verifica dependencias opcionales y registra avisos en el logger."""
        missing = []
        for pkg in OPTIONAL_DEPS:
            try:
                importlib.import_module(pkg)
                self.logger.debug(f"Dependencia OK: {pkg}")
            except ImportError:
                missing.append(pkg)
                self.logger.warning(
                    f"Dependencia no encontrada: {pkg} — {OPTIONAL_DEPS[pkg]}")

        if missing:
            self.logger.warning(
                f"Faltan {len(missing)} dependencia(s): {', '.join(missing)}")

    # ── Carga de módulos ─────────────────────────────────────────────────────

    def _load_modules(self):
        C = self.COLORS

        # Panel de bienvenida como módulo especial
        welcome = WelcomePanel(self.module_container, self)
        welcome.place(relwidth=1, relheight=1)
        welcome.lower()
        self._modules["__welcome__"] = welcome

        for entry in MODULES_REGISTRY:
            mod_path, cls_name = entry[0], entry[1]
            try:
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name)
                name = cls.NAME
                icon = getattr(cls, "ICON", "📦")

                frame = cls(self.module_container, self)
                frame.place(relwidth=1, relheight=1)
                frame.lower()
                self._modules[name] = frame

                self.logger.info(f"Módulo cargado: {cls_name} → '{name}'")

                # Botón en sidebar
                btn_frame = tk.Frame(self.nav_frame, bg=C["sidebar_bg"],
                                     cursor="hand2")
                btn_frame.pack(fill="x", pady=2)

                lbl = tk.Label(
                    btn_frame,
                    text=f"  {icon}  {name}",
                    font=("Segoe UI", 10),
                    bg=C["sidebar_bg"], fg=C["fg_sidebar"],
                    anchor="w", pady=10, padx=8)
                lbl.pack(fill="x")
                self._sidebar_btns[name] = lbl

                for widget in (btn_frame, lbl):
                    widget.bind("<Button-1>",
                                lambda e, n=name: self.show_module(n))
                    widget.bind("<Enter>",
                                lambda e, w=btn_frame, lbl_=lbl: (
                                    w.config(bg=C["selected_bg"]),
                                    lbl_.config(bg=C["selected_bg"])))
                    widget.bind("<Leave>",
                                lambda e, n=name, w=btn_frame, lbl_=lbl: (
                                    w.config(bg=C["selected_bg"]
                                             if self._active == n
                                             else C["sidebar_bg"]),
                                    lbl_.config(bg=C["selected_bg"]
                                                if self._active == n
                                                else C["sidebar_bg"])))

            except Exception as exc:
                tb = traceback.format_exc()
                self._failed_mods.append((cls_name, str(exc)))
                self.logger.error(
                    f"Error cargando módulo '{cls_name}': {exc}\n{tb}")
                self._add_failed_module_btn(cls_name, str(exc))

        # Mostrar advertencia si hubo fallos
        if self._failed_mods:
            names = ", ".join(c for c, _ in self._failed_mods)
            self.after(800, lambda: self.notify(
                f"⚠️ {len(self._failed_mods)} módulo(s) no cargaron: {names}. "
                "Revisa logs/pytsgenerator.log.",
                level="error", duration=8000))

    def _add_failed_module_btn(self, cls_name: str, error: str):
        """Añade un botón deshabilitado en el sidebar para módulos fallidos."""
        C = self.COLORS
        btn_frame = tk.Frame(self.nav_frame, bg=C["sidebar_bg"])
        btn_frame.pack(fill="x", pady=2)
        lbl = tk.Label(
            btn_frame,
            text=f"  ❌  {cls_name}",
            font=("Segoe UI", 9, "italic"),
            bg=C["sidebar_bg"], fg="#e53e3e",
            anchor="w", pady=8, padx=8)
        lbl.pack(fill="x")
        lbl.bind("<Button-1>", lambda e: self.notify(
            f"Módulo '{cls_name}' no pudo cargarse: {error}", level="error"))

    # ── Navegación ───────────────────────────────────────────────────────────

    def show_module(self, name: str):
        C = self.COLORS
        if name not in self._modules:
            self.logger.warning(f"show_module: '{name}' no encontrado.")
            return

        # Ocultar módulo activo
        if self._active and self._active in self._modules:
            old = self._modules[self._active]
            old.lower()
            try:
                old.on_hide()
            except AttributeError:
                pass
            except Exception as exc:
                self.logger.warning(f"on_hide error en '{self._active}': {exc}")

            if self._active in self._sidebar_btns:
                b = self._sidebar_btns[self._active]
                b.config(bg=C["sidebar_bg"])
                b.master.config(bg=C["sidebar_bg"])

        # Mostrar nuevo módulo
        self._active = name
        frame = self._modules[name]
        frame.lift()
        try:
            frame.on_show()
        except AttributeError:
            pass
        except Exception as exc:
            self.logger.warning(f"on_show error en '{name}': {exc}")

        self.logger.debug(f"Módulo activo: {name}")

        # Actualizar topbar
        if name == "__welcome__":
            self.topbar_title.config(text="🏠  Inicio")
        else:
            cls = type(frame)
            icon = getattr(cls, "ICON", "📦")
            self.topbar_title.config(text=f"{icon}  {name}")

        # Resaltar botón en sidebar
        if name in self._sidebar_btns:
            b = self._sidebar_btns[name]
            b.config(bg=C["selected_bg"])
            b.master.config(bg=C["selected_bg"])

    # ── API pública para módulos ─────────────────────────────────────────────

    def notify(self, message: str, level: str = "info", duration: int = 4000):
        """
        Notificación persistente (panel derecho) + toast temporal.
        Niveles: 'info' | 'success' | 'warning' | 'error'
        """
        self.notif_panel.add(message, level=level)
        self.show_toast(message, duration=duration, level=level)
        self.logger.log(
            logging.ERROR if level == "error"
            else logging.WARNING if level == "warning"
            else logging.INFO,
            f"[notify:{level}] {message}")

    def update_hda_status(self, connected: bool, user: str = ""):
        """Actualiza el indicador de sesión HDA en la topbar."""
        if connected:
            self.hda_status_lbl.config(
                text=f"⬤  HDA: {user}",
                fg=self.COLORS["success"])
        else:
            self.hda_status_lbl.config(
                text="⬤  HDA: sin conectar",
                fg=self.COLORS["fg_muted"])
        self.session["hda_verified"] = connected

    # ── Toast de notificaciones ──────────────────────────────────────────────

    _TOAST_COLORS = {
        "info":    ("#2b2d42", "white"),
        "success": ("#276749", "white"),
        "warning": ("#7b341e", "white"),
        "error":   ("#742a2a", "white"),
    }

    def _build_toast(self):
        self._toast = tk.Label(
            self, text="",
            font=("Segoe UI", 9),
            bg="#2b2d42", fg="white",
            padx=16, pady=9,
            relief="flat",
            cursor="hand2")
        self._toast.bind("<Button-1>", self._dismiss_toast)
        self._toast_after = None

    def show_toast(self, message: str, duration: int = 4000,
                   level: str = "info"):
        """
        Muestra una notificación temporal en la esquina inferior derecha.
        Clicable para cerrar anticipadamente.
        """
        bg, fg = self._TOAST_COLORS.get(level, self._TOAST_COLORS["info"])
        self._toast.config(text=f"  {message}  ", bg=bg, fg=fg)
        self._toast.place(relx=1.0, rely=1.0, anchor="se", x=-20, y=-20)
        self._toast.lift()
        if self._toast_after:
            self.after_cancel(self._toast_after)
        self._toast_after = self.after(duration, self._dismiss_toast)

    def _dismiss_toast(self, _event=None):
        self._toast.place_forget()
        if self._toast_after:
            self.after_cancel(self._toast_after)
            self._toast_after = None


# ── Punto de entrada ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    app = MainApp()
    app.mainloop()

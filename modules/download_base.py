"""
download_base.py — Clase base compartida para los módulos de descarga HDA.

Contiene toda la lógica y UI común entre DownloadSTPPIModule y
DownloadHRVPPModule (~80 % del código original duplicado).

Cada módulo hijo sólo necesita declarar:
  - NAME, ICON, DESCRIPTION
  - PRODUCT_FIELDS   : lista de dicts que definen los campos de búsqueda extra
  - DEFAULT_DATASET  : valor por defecto del Dataset ID
  - _build_extra_fields(frame) : (opcional) campos adicionales específicos

No registrar directamente en MODULES_REGISTRY — usar las subclases.
"""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

from modules.base import BaseModule

# ── Intentar importar keyring para credenciales seguras ─────────────────────
try:
    import keyring
    _KEYRING_OK = True
except ImportError:
    _KEYRING_OK = False

# Servicio usado en keyring para almacenar credenciales HDA
_KEYRING_SERVICE = "PyTSGenerator_HDA"

# Reintentos para la conexión HDA
_MAX_RETRIES    = 3
_RETRY_DELAYS   = [2, 5, 10]   # segundos entre reintentos


class DownloadBaseModule(BaseModule):
    """
    Clase base para módulos de descarga de productos Copernicus vía HDA.

    Subclases deben definir:
        NAME            str   — nombre visible en sidebar
        ICON            str   — emoji de icono
        DESCRIPTION     str   — descripción corta para la pestaña Estado
        DEFAULT_DATASET str   — Dataset ID por defecto
        PRODUCT_FIELDS  list  — campos extra de búsqueda (ver formato abajo)

    Formato de PRODUCT_FIELDS:
        [
            {"attr": "var_product_type",  "label": "🛰️ Product Type",
             "placeholder": "SOSD",       "col": 1},
            ...
        ]
        Cada dict puede incluir opcionalmente:
            "widget": "combobox"  →  genera un Combobox en lugar de Entry
            "values": [...]       →  lista de opciones para el Combobox
    """

    NAME            = "Download Base"
    ICON            = "⬇️"
    DESCRIPTION     = "Módulo de descarga genérico."
    DEFAULT_DATASET = ""
    PRODUCT_FIELDS  = []

    # ── Ciclo de vida del módulo ─────────────────────────────────────────────

    def build_ui(self):
        C = self.app.COLORS

        # Estado interno
        self._hda_client      = None
        self._search_results  = None
        self._downloaded_files: list[str] = []
        self._cancel_event    = threading.Event()
        self._is_downloading  = False

        # Notebook
        style = ttk.Style()
        style.configure("DL.TNotebook",     background=C["bg"])
        style.configure("DL.TNotebook.Tab", padding=[12, 6],
                        font=("Segoe UI", 10))

        self.nb = ttk.Notebook(self, style="DL.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=12, pady=12)

        self._build_search_tab()
        self._build_viz_tab()
        self._build_status_tab()

    def on_show(self):
        """Al mostrar el módulo: sincroniza credenciales desde session."""
        sess = self.app.session
        if sess.get("hda_user") and not self.var_user.get():
            self.var_user.set(sess["hda_user"])
        if sess.get("hda_pass") and not self.var_pass.get():
            self.var_pass.set(sess["hda_pass"])
        if sess.get("last_download_dir"):
            self.var_download_dir.set(sess["last_download_dir"])
        self._sync_hda_client()
        self._refresh_status()

    def on_hide(self):
        """Al ocultar el módulo: persiste credenciales en session."""
        self._save_credentials_to_session()

    # ── Persistencia de credenciales ─────────────────────────────────────────

    def _save_credentials_to_session(self):
        """Guarda usuario/carpeta en el estado global. Nunca la contraseña."""
        self.app.session["hda_user"] = self.var_user.get().strip()
        self.app.session["last_download_dir"] = self.var_download_dir.get()

    def _save_credentials_keyring(self):
        """Persiste usuario y contraseña en el keyring del SO (si disponible)."""
        if not _KEYRING_OK:
            return
        user = self.var_user.get().strip()
        pwd  = self.var_pass.get().strip()
        if user and pwd:
            try:
                keyring.set_password(_KEYRING_SERVICE, user, pwd)
                self.app.logger.info(
                    f"Credenciales guardadas en keyring para: {user}")
            except Exception as exc:
                self.app.logger.warning(f"keyring.set_password falló: {exc}")

    def _load_credentials_keyring(self):
        """Recupera contraseña del keyring para el usuario actual."""
        if not _KEYRING_OK:
            return
        user = self.var_user.get().strip()
        if not user:
            return
        try:
            pwd = keyring.get_password(_KEYRING_SERVICE, user)
            if pwd:
                self.var_pass.set(pwd)
                self.app.logger.info(
                    f"Credenciales recuperadas de keyring para: {user}")
        except Exception as exc:
            self.app.logger.warning(f"keyring.get_password falló: {exc}")

    def _sync_hda_client(self):
        """
        Si ya existe un cliente HDA verificado en session y las credenciales
        coinciden, reutiliza la conexión sin volver a autenticar.
        """
        if (self.app.session.get("hda_verified")
                and self.app.session.get("hda_user") == self.var_user.get().strip()
                and self._hda_client is None):
            # Reconstruir cliente desde sesión verificada
            try:
                import hda
                conf = hda.Configuration(
                    user=self.app.session["hda_user"],
                    password=self.app.session.get("hda_pass", ""))
                self._hda_client = hda.Client(config=conf)
                self.app.logger.debug(
                    f"[{self.NAME}] Cliente HDA reutilizado desde session.")
            except Exception:
                pass

    # ── PESTAÑA 1: BÚSQUEDA Y DESCARGA ──────────────────────────────────────

    def _build_search_tab(self):
        C = self.app.COLORS
        tab = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(tab, text="  🔍 Búsqueda y Descarga  ")

        # Canvas con scroll
        canvas = tk.Canvas(tab, bg=C["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["bg"])
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        # Scroll con rueda del ratón
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(
                            int(-1 * (e.delta / 120)), "units"))

        # ── Credenciales ──────────────────────────────────────────────
        self._section(inner, "🔐 Credenciales HDA")
        cred = tk.Frame(inner, bg=C["card"], padx=16, pady=14)
        cred.pack(fill="x", padx=16, pady=(0, 12))

        self.var_user = tk.StringVar()
        self.var_pass = tk.StringVar()

        self._field(cred, "👤 Usuario HDA", self.var_user,
                    row=0, col=0, placeholder="usuario@ejemplo.com")
        self._field(cred, "🔑 Contraseña", self.var_pass,
                    row=0, col=1, show="●")

        cred.columnconfigure((0, 1), weight=1)

        # Botones de credenciales
        btn_cred = tk.Frame(cred, bg=C["card"])
        btn_cred.grid(row=2, column=0, columnspan=2,
                      sticky="w", pady=(10, 0))

        if _KEYRING_OK:
            self._btn(btn_cred, "💾 Guardar credenciales",
                      self._on_save_credentials,
                      style="secondary").pack(side="left", padx=(0, 8))
            self._btn(btn_cred, "🔓 Cargar guardadas",
                      self._load_credentials_keyring,
                      style="secondary").pack(side="left")
        else:
            tk.Label(btn_cred,
                     text="ℹ️ Instala 'keyring' para guardar credenciales de forma segura.",
                     font=("Segoe UI", 8, "italic"),
                     bg=C["card"], fg=C["fg_muted"]).pack(side="left")

        # ── Carpeta de descarga ────────────────────────────────────────
        self._section(inner, "📁 Destino de Descarga")
        dir_card = tk.Frame(inner, bg=C["card"], padx=16, pady=14)
        dir_card.pack(fill="x", padx=16, pady=(0, 12))
        dir_card.columnconfigure(0, weight=1)

        self.var_download_dir = tk.StringVar(value="")
        dir_row = tk.Frame(dir_card, bg=C["card"])
        dir_row.grid(row=0, column=0, columnspan=2, sticky="ew")

        self._lbl(dir_row, "Carpeta donde se guardarán los archivos:").pack(
            anchor="w", pady=(0, 4))

        dir_input = tk.Frame(dir_row, bg=C["card"])
        dir_input.pack(fill="x")
        tk.Entry(dir_input, textvariable=self.var_download_dir,
                 font=("Segoe UI", 9),
                 bg=C["input_bg"], fg=C["fg"],
                 relief="flat", bd=0,
                 highlightthickness=1,
                 highlightbackground=C["border"],
                 highlightcolor=C["accent"],
                 state="readonly").pack(
            side="left", fill="x", expand=True, ipady=6)
        self._btn(dir_input, "Examinar…", self._choose_dir,
                  style="secondary").pack(side="left", padx=(8, 0))

        # Estimación de espacio (se actualiza tras la búsqueda)
        self.space_lbl = tk.Label(
            dir_card, text="",
            font=("Segoe UI", 8),
            bg=C["card"], fg=C["fg_muted"])
        self.space_lbl.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self._btn(dir_card, "✅ Conectar con HDA",
                  self._check_config, style="success").grid(
            row=2, column=0, columnspan=2,
            pady=(12, 0), sticky="ew")

        # Indicador de estado de conexión
        self.conn_lbl = tk.Label(
            dir_card, text="⬤  Sin conectar",
            font=("Segoe UI", 8),
            bg=C["card"], fg=C["fg_muted"])
        self.conn_lbl.grid(row=3, column=0, sticky="w", pady=(6, 0))

        # ── Parámetros de búsqueda ─────────────────────────────────────
        self._section(inner, f"🔍 Parámetros de Búsqueda — {self.NAME}")
        search = tk.Frame(inner, bg=C["card"], padx=16, pady=14)
        search.pack(fill="x", padx=16, pady=(0, 12))
        search.columnconfigure((0, 1, 2), weight=1)

        # Dataset ID siempre en fila 0, col 0
        self.var_dataset_id = tk.StringVar()
        self._field(search, "📊 Dataset ID", self.var_dataset_id,
                    row=0, col=0, placeholder=self.DEFAULT_DATASET)

        # Campos extra definidos por la subclase
        for fdef in self.PRODUCT_FIELDS:
            attr  = fdef["attr"]
            var   = tk.StringVar()
            setattr(self, attr, var)
            self._field(
                search, fdef["label"], var,
                row=fdef.get("row", 0),
                col=fdef.get("col", 1),
                colspan=fdef.get("colspan", 1),
                placeholder=fdef.get("placeholder", ""))

        # Tile, fechas y BBox (comunes a ambos productos)
        self.var_tile_id = tk.StringVar()
        self.var_start   = tk.StringVar()
        self.var_end     = tk.StringVar()
        self.var_bbox    = tk.StringVar()

        self._field(search, "🧩 Tile ID",      self.var_tile_id,
                    row=2, col=0, placeholder="30TYM")
        self._field(search, "📅 Fecha inicio", self.var_start,
                    row=2, col=1, placeholder="2023-01-01")
        self._field(search, "📅 Fecha fin",    self.var_end,
                    row=2, col=2, placeholder="2023-12-31")
        self._field(search, "🗺️ BBox  (xmin, ymin, xmax, ymax)",
                    self.var_bbox, row=4, col=0, colspan=3,
                    placeholder="-3.8, 40.3, -3.6, 40.5")

        # Hook para campos extra de la subclase (shapefile, CRS, etc.)
        # Se llama aquí, dentro del mismo frame ``search``, para que los
        # widgets compartan colores, columnas y padding del formulario.
        if callable(getattr(self, "_build_extra_fields", None)):
            self._build_extra_fields(search)

        # Validación visual de fechas
        self.var_start.trace_add("write", self._validate_dates)
        self.var_end.trace_add(  "write", self._validate_dates)

        self.date_warn_lbl = tk.Label(
            search, text="", font=("Segoe UI", 8),
            bg=C["card"], fg=C["error"])
        self.date_warn_lbl.grid(row=6, column=0, columnspan=3,
                                sticky="w", pady=(4, 0))

        # Botones de acción
        btn_row = tk.Frame(search, bg=C["card"])
        btn_row.grid(row=8, column=0, columnspan=3,
                     pady=(14, 0), sticky="ew")
        btn_row.columnconfigure((0, 1, 2), weight=1)

        self.search_btn = self._btn(
            btn_row, "🔍 Buscar Productos", self._do_search)
        self.search_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.download_btn = self._btn(
            btn_row, "⬇️ Descargar Todo",
            self._do_download, style="success")
        self.download_btn.grid(row=0, column=1, sticky="ew", padx=(0, 6))

        self.cancel_btn = self._btn(
            btn_row, "⏹ Cancelar",
            self._do_cancel, style="danger")
        self.cancel_btn.grid(row=0, column=2, sticky="ew")
        self.cancel_btn.config(state="disabled")

        # ── Barra de progreso de descarga ──────────────────────────────
        prog_card = tk.Frame(inner, bg=C["card"], padx=16, pady=10)
        prog_card.pack(fill="x", padx=16, pady=(0, 12))
        self.dl_prog_lbl = tk.Label(
            prog_card, text="",
            font=("Segoe UI", 8),
            bg=C["card"], fg=C["accent"])
        self.dl_prog_lbl.pack(anchor="w")
        self.dl_prog_var = tk.DoubleVar(value=0)
        ttk.Progressbar(
            prog_card, variable=self.dl_prog_var,
            maximum=100, length=400).pack(fill="x", pady=(4, 0))

        # ── Panel de resultados de búsqueda ────────────────────────────
        self._section(inner, "📋 Resultados de la Búsqueda")
        res_card = tk.Frame(inner, bg=C["card"], padx=12, pady=10)
        res_card.pack(fill="x", padx=16, pady=(0, 16))
        self.result_text = tk.Text(
            res_card, height=10, font=("Consolas", 9),
            bg=C["input_bg"], fg=C["fg"],
            insertbackground=C["fg"],
            relief="flat", bd=0, wrap="word", state="disabled")
        self.result_text.pack(fill="both", expand=True)
        self._set_result(
            "📭 Sin resultados todavía.\n\n"
            "   1. Conecta con el HDA (introduce credenciales y pulsa "
            "'Conectar')\n"
            "   2. Rellena los parámetros de búsqueda\n"
            "   3. Pulsa 'Buscar Productos'")

        # Espacio final
        tk.Frame(inner, bg=C["bg"], height=20).pack()

    # ── PESTAÑA 2: VISUALIZACIÓN ─────────────────────────────────────────────

    def _build_viz_tab(self):
        C = self.app.COLORS
        tab = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(tab, text="  🖼️ Archivos Descargados  ")

        # Barra de herramientas
        toolbar = tk.Frame(tab, bg=C["card"], padx=12, pady=8)
        toolbar.pack(fill="x")
        self._lbl(toolbar, "Galería de archivos descargados").pack(
            side="left")
        self._btn(toolbar, "🔄 Actualizar",
                  self._refresh_gallery, style="secondary").pack(
            side="right")
        self._btn(toolbar, "📂 Abrir carpeta",
                  self._open_download_dir, style="secondary").pack(
            side="right", padx=(0, 6))

        tk.Frame(tab, bg=C["border"], height=1).pack(fill="x")

        # Galería de miniaturas
        gal_outer = tk.Frame(tab, bg=C["input_bg"])
        gal_outer.pack(fill="both", expand=True, padx=0, pady=0)

        self.gallery_canvas = tk.Canvas(
            gal_outer, bg=C["input_bg"], highlightthickness=0)
        gscroll = ttk.Scrollbar(
            gal_outer, orient="vertical",
            command=self.gallery_canvas.yview)
        self.gallery_canvas.configure(yscrollcommand=gscroll.set)
        gscroll.pack(side="right", fill="y")
        self.gallery_canvas.pack(fill="both", expand=True)

        self.gallery_inner = tk.Frame(
            self.gallery_canvas, bg=C["input_bg"])
        self.gallery_canvas.create_window(
            (0, 0), window=self.gallery_inner, anchor="nw")
        self.gallery_inner.bind("<Configure>", lambda e:
            self.gallery_canvas.configure(
                scrollregion=self.gallery_canvas.bbox("all")))

        # Panel de detalle de imagen seleccionada
        self._section(tab, "🔍 Vista Previa")
        self.img_frame = tk.Frame(tab, bg=C["card"],
                                  height=260)
        self.img_frame.pack(fill="x", padx=16, pady=(0, 12))
        self.img_frame.pack_propagate(False)
        tk.Label(
            self.img_frame,
            text="Haz clic en un archivo de la galería para previsualizarlo",
            font=("Segoe UI", 10),
            bg=C["card"], fg=C["fg_muted"]
        ).pack(expand=True)

        # Estado inicial de la galería
        tk.Label(
            self.gallery_inner,
            text="Aún no hay archivos descargados.",
            font=("Segoe UI", 10),
            bg=C["input_bg"], fg=C["fg_muted"]
        ).pack(padx=20, pady=40)

    # ── PESTAÑA 3: ESTADO DEL SISTEMA ───────────────────────────────────────

    def _build_status_tab(self):
        C = self.app.COLORS
        tab = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(tab, text="  ⚙️ Estado  ")

        self._section(tab, "📊 Estado de la Sesión")
        sys_card = tk.Frame(tab, bg=C["card"], padx=12, pady=10)
        sys_card.pack(fill="x", padx=16, pady=(0, 12))
        self.sys_text = tk.Text(
            sys_card, height=14, font=("Consolas", 9),
            bg=C["input_bg"], fg=C["fg"],
            relief="flat", bd=0, state="disabled", wrap="word")
        self.sys_text.pack(fill="both", expand=True)

        self._btn(tab, "🔄 Actualizar Estado",
                  self._refresh_status,
                  style="secondary").pack(padx=16, pady=4, anchor="w")

        self._section(tab, "ℹ️ Acerca de este módulo")
        info = tk.Frame(tab, bg=C["card"], padx=16, pady=12)
        info.pack(fill="x", padx=16, pady=(0, 16))
        for line in [self.DESCRIPTION,
                     "",
                     "Campos de búsqueda disponibles:",
                     f"  • Dataset ID (obligatorio):  {self.DEFAULT_DATASET}",
                     ] + [f"  • {f['label']}: {f.get('placeholder','')}"
                          for f in self.PRODUCT_FIELDS] + [
                     "  • Tile ID, Fecha inicio/fin, BBox (opcionales)",
                     "",
                     "Requiere el paquete 'hda':  pip install hda",
                     "Credenciales seguras:       pip install keyring",
                     ]:
            tk.Label(info, text=line, font=("Segoe UI", 9),
                     bg=C["card"], fg=C["fg"],
                     anchor="w").pack(fill="x", pady=1)

    # ── LÓGICA: CONFIGURACIÓN Y CONEXIÓN ────────────────────────────────────

    def _choose_dir(self):
        path = filedialog.askdirectory(
            title="Seleccionar carpeta de descarga")
        if path:
            self.var_download_dir.set(path)
            self.app.session["last_download_dir"] = path
            self._update_space_estimate()

    def _on_save_credentials(self):
        self._save_credentials_keyring()
        self.app.notify(
            f"💾 Credenciales guardadas para '{self.var_user.get().strip()}'.",
            level="success")

    def _check_config(self):
        """Verifica carpeta y conecta con HDA con reintentos."""
        dl = self.var_download_dir.get().strip()
        if not dl:
            messagebox.showwarning(
                "Carpeta requerida",
                "Selecciona una carpeta de descarga antes de conectar.")
            return

        user = self.var_user.get().strip()
        pwd  = self.var_pass.get().strip()
        if not user or not pwd:
            messagebox.showwarning(
                "Credenciales requeridas",
                "Introduce usuario y contraseña.")
            return

        self._set_conn_status("⏳ Conectando…", self.app.COLORS["fg_muted"])
        self.search_btn.config(state="disabled")

        def _run():
            os.makedirs(dl, exist_ok=True)
            last_exc = None

            for attempt in range(_MAX_RETRIES):
                try:
                    import hda
                    conf = hda.Configuration(user=user, password=pwd)
                    client = hda.Client(config=conf)
                    # Test rápido de conexión
                    _ = client  # Si lanza, falla aquí
                    self._hda_client = client
                    # Actualizar sesión global
                    self.app.session["hda_user"]     = user
                    self.app.session["hda_pass"]     = pwd
                    self.app.session["hda_verified"] = True
                    self.after(0, self._on_connect_success, user)
                    self.app.logger.info(
                        f"[{self.NAME}] HDA conectado como '{user}' "
                        f"(intento {attempt+1})")
                    return
                except ImportError:
                    self.after(0, self._on_connect_error,
                               "El paquete 'hda' no está instalado.\n"
                               "Ejecuta:  pip install hda")
                    return
                except Exception as exc:
                    last_exc = exc
                    self.app.logger.warning(
                        f"[{self.NAME}] Intento {attempt+1} fallido: {exc}")
                    if attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_DELAYS[attempt]
                        self.after(0, self._set_conn_status,
                                   f"⏳ Reintentando ({attempt+2}/{_MAX_RETRIES})…",
                                   self.app.COLORS["warning"])
                        time.sleep(delay)

            self.after(0, self._on_connect_error, str(last_exc))

        threading.Thread(target=_run, daemon=True).start()

    def _on_connect_success(self, user: str):
        self._set_conn_status(f"⬤  Conectado como {user}",
                              self.app.COLORS["success"])
        self.search_btn.config(state="normal")
        self.app.update_hda_status(True, user)
        self.app.notify(
            f"✅ [{self.NAME}] Conexión HDA establecida como '{user}'.",
            level="success")
        self._refresh_status()

    def _on_connect_error(self, msg: str):
        self._set_conn_status("⬤  Error de conexión", self.app.COLORS["error"])
        self.search_btn.config(state="normal")
        self.app.notify(
            f"❌ [{self.NAME}] No se pudo conectar al HDA: {msg}",
            level="error", duration=8000)
        messagebox.showerror("Error de conexión HDA", msg)

    def _set_conn_status(self, text: str, color: str):
        self.conn_lbl.config(text=text, fg=color)

    # ── LÓGICA: BÚSQUEDA ────────────────────────────────────────────────────

    def _validate_dates(self, *_):
        """Valida que fecha_inicio <= fecha_fin al escribir."""
        s = self.var_start.get().strip()
        e = self.var_end.get().strip()
        if not s or not e:
            self.date_warn_lbl.config(text="")
            return
        try:
            ds = datetime.strptime(s, "%Y-%m-%d")
            de = datetime.strptime(e, "%Y-%m-%d")
            if ds > de:
                self.date_warn_lbl.config(
                    text="⚠️ La fecha de inicio es posterior a la fecha de fin.")
            else:
                self.date_warn_lbl.config(text="")
        except ValueError:
            self.date_warn_lbl.config(
                text="⚠️ Formato de fecha inválido. Usa YYYY-MM-DD.")

    def _build_query(self) -> dict:
        """
        Construye el dict de query HDA con los campos comunes.
        Las subclases pueden sobreescribir para añadir campos extra.
        """
        query = {"dataset_id": self.var_dataset_id.get().strip()
                               or self.DEFAULT_DATASET}
        for fdef in self.PRODUCT_FIELDS:
            val = getattr(self, fdef["attr"]).get().strip()
            if val:
                query[fdef["query_key"]] = val

        if self.var_tile_id.get().strip():
            query["tileId"] = self.var_tile_id.get().strip()
        if self.var_start.get().strip():
            query["start"] = self.var_start.get().strip()
        if self.var_end.get().strip():
            query["end"] = self.var_end.get().strip()

        bbox_str = self.var_bbox.get().strip()
        if bbox_str:
            try:
                vals = [float(x.strip()) for x in bbox_str.split(",")]
                if len(vals) == 4:
                    query["bbox"] = vals
                else:
                    self.app.notify(
                        "⚠️ BBox debe tener 4 valores: xmin,ymin,xmax,ymax",
                        level="warning")
            except ValueError:
                self.app.notify(
                    "⚠️ BBox contiene valores no numéricos.", level="warning")

        return query

    def _do_search(self):
        if not self._hda_client:
            messagebox.showwarning(
                "Sin conexión",
                "Primero conecta con el HDA usando el botón 'Conectar'.")
            return

        if not self.var_dataset_id.get().strip():
            messagebox.showwarning(
                "Dataset requerido",
                f"El campo 'Dataset ID' es obligatorio.\n"
                f"Ejemplo: {self.DEFAULT_DATASET}")
            return

        self.search_btn.config(state="disabled")
        self._set_result(f"🔍 Buscando productos {self.NAME}…\nPor favor espere.")

        def _run():
            try:
                query = self._build_query()
                self.app.logger.info(
                    f"[{self.NAME}] Búsqueda iniciada: {query}")

                self._search_results = self._hda_client.search(query)
                total = len(list(self._search_results))

                lines = [
                    f"📊 RESULTADOS — {self.NAME}",
                    "═" * 40,
                    f"🔢 Productos encontrados: {total}",
                    f"📋 Query:  {query}",
                    "",
                ]

                if total > 0:
                    self._update_space_estimate(total)
                    lines.append("Primeros 5 resultados:")
                    lines.append("─" * 40)
                    for i, item in enumerate(self._search_results):
                        if i >= 5:
                            break
                        props = getattr(item, "properties", {}) or {}
                        lines += [
                            f"{self.ICON} Producto {i+1}:",
                            f"  ID:     {getattr(item, 'id', 'N/A')}",
                            f"  Título: {props.get('title', 'N/A')}",
                            f"  Fecha:  {props.get('date', props.get('startDate', 'N/A'))}",
                            f"  Tamaño: {props.get('size', 'N/A')}",
                            "",
                        ]
                    if total > 5:
                        lines.append(f"… y {total - 5} productos más.")
                else:
                    lines.append(
                        "⚠️ No se encontraron productos con los "
                        "criterios especificados.\n"
                        "Prueba ampliar el rango de fechas o revisar el Tile ID.")

                lines.append(
                    f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                self.after(0, self._set_result, "\n".join(lines))
                self.app.logger.info(
                    f"[{self.NAME}] Búsqueda completada: {total} resultado(s).")
                self.app.notify(
                    f"{self.ICON} [{self.NAME}] {total} producto(s) encontrados.",
                    level="success" if total > 0 else "warning")

            except Exception as exc:
                self.app.logger.error(
                    f"[{self.NAME}] Error en búsqueda: {exc}", exc_info=True)
                self.after(0, self._set_result,
                           f"❌ Error en la búsqueda:\n{exc}\n\n"
                           "Revisa tu conexión y credenciales.")
                self.app.notify(
                    f"❌ [{self.NAME}] Error de búsqueda: {exc}",
                    level="error")
            finally:
                self.after(0, self.search_btn.config, {"state": "normal"})

        threading.Thread(target=_run, daemon=True).start()

    # ── LÓGICA: DESCARGA ─────────────────────────────────────────────────────

    def _do_download(self):
        if not self._search_results:
            messagebox.showwarning(
                "Sin resultados",
                "Realiza una búsqueda primero.")
            return

        dl_dir = self.var_download_dir.get().strip()
        if not dl_dir:
            messagebox.showerror(
                "Carpeta requerida",
                "Selecciona una carpeta de descarga.")
            return

        self._cancel_event.clear()
        self._is_downloading = True
        self.download_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.dl_prog_lbl.config(text="⬇️ Iniciando descarga…")
        self.dl_prog_var.set(0)

        def _run():
            try:
                os.makedirs(dl_dir, exist_ok=True)
                self.app.logger.info(
                    f"[{self.NAME}] Descarga iniciada → {dl_dir}")
                self.app.notify(
                    f"⬇️ [{self.NAME}] Descarga iniciada en: {dl_dir}",
                    level="info")

                # La API HDA no expone callbacks de progreso, así que
                # simulamos con un pulso visual mientras descarga
                def _pulse():
                    if self._is_downloading and not self._cancel_event.is_set():
                        v = self.dl_prog_var.get()
                        # Pulso hasta 90 % (el 100 % lo ponemos al terminar)
                        self.dl_prog_var.set(min(v + 1, 90))
                        self.after(600, _pulse)
                self.after(0, _pulse)

                if self._cancel_event.is_set():
                    self.after(0, self._on_download_cancelled)
                    return

                self._search_results.download(dl_dir)

                # Recoger ficheros descargados
                exts = (".tif", ".tiff", ".zip", ".jpg", ".jpeg", ".png")
                self._downloaded_files = [
                    os.path.join(dl_dir, f)
                    for f in os.listdir(dl_dir)
                    if f.lower().endswith(exts)
                ]

                # Hook post-descarga (subclases pueden sobreescribir).
                # Permite reproyectar, recortar, renombrar, etc. cada archivo.
                # Si on_product_downloaded devuelve una ruta distinta, se
                # actualiza la lista para que la galería muestre el resultado.
                if callable(getattr(self, "on_product_downloaded", None)):
                    self._downloaded_files = [
                        self.on_product_downloaded(fp)
                        for fp in self._downloaded_files
                    ]

                self.app.logger.info(
                    f"[{self.NAME}] Descarga completada: "
                    f"{len(self._downloaded_files)} archivo(s).")
                self.after(0, self._on_download_complete)

            except Exception as exc:
                self.app.logger.error(
                    f"[{self.NAME}] Error en descarga: {exc}", exc_info=True)
                self.after(0, self._on_download_error, str(exc))

        threading.Thread(target=_run, daemon=True).start()

    def _do_cancel(self):
        """Señaliza la cancelación de la descarga en curso."""
        self._cancel_event.set()
        self.cancel_btn.config(state="disabled")
        self.dl_prog_lbl.config(text="⏹ Cancelando…",
                                fg=self.app.COLORS["warning"])
        self.app.logger.info(f"[{self.NAME}] Descarga cancelada por el usuario.")

    def _on_download_complete(self):
        self._is_downloading = False
        self.dl_prog_var.set(100)
        n = len(self._downloaded_files)
        self.dl_prog_lbl.config(
            text=f"✅ Descarga completada — {n} archivo(s)",
            fg=self.app.COLORS["success"])
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self._refresh_gallery()
        self._refresh_status()
        self.app.notify(
            f"✅ [{self.NAME}] {n} archivo(s) descargados en: "
            f"{self.var_download_dir.get()}",
            level="success")

    def _on_download_cancelled(self):
        self._is_downloading = False
        self.dl_prog_var.set(0)
        self.dl_prog_lbl.config(
            text="⏹ Descarga cancelada.", fg=self.app.COLORS["warning"])
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.app.notify(
            f"⏹ [{self.NAME}] Descarga cancelada por el usuario.",
            level="warning")

    def _on_download_error(self, msg: str):
        self._is_downloading = False
        self.dl_prog_var.set(0)
        self.dl_prog_lbl.config(
            text="❌ Error en la descarga.", fg=self.app.COLORS["error"])
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.app.notify(
            f"❌ [{self.NAME}] Error en descarga: {msg}",
            level="error", duration=8000)
        messagebox.showerror("Error de descarga", msg)

    # ── GALERÍA ───────────────────────────────────────────────────────────────

    def _refresh_gallery(self):
        C = self.app.COLORS
        for w in self.gallery_inner.winfo_children():
            w.destroy()

        if not self._downloaded_files:
            tk.Label(self.gallery_inner,
                     text="Aún no hay archivos descargados.",
                     font=("Segoe UI", 10),
                     bg=C["input_bg"], fg=C["fg_muted"]).pack(
                padx=20, pady=40)
            return

        cols = 4
        for i, fpath in enumerate(self._downloaded_files):
            if i % cols == 0:
                row_f = tk.Frame(self.gallery_inner, bg=C["input_bg"])
                row_f.pack(fill="x", padx=8, pady=4)

            card = tk.Frame(row_f, bg=C["card"],
                            padx=6, pady=6,
                            relief="flat", bd=1, cursor="hand2")
            card.pack(side="left", padx=4)

            # Miniatura
            try:
                from PIL import Image, ImageTk
                img = Image.open(fpath)
                img.thumbnail((140, 90))
                photo = ImageTk.PhotoImage(img)
                thumb = tk.Label(card, image=photo, bg=C["card"])
                thumb.image = photo
                thumb.pack()
            except Exception:
                tk.Label(card, text=self.ICON,
                         font=("Segoe UI", 24),
                         bg=C["card"], fg=C["fg_muted"],
                         width=10, height=3).pack()

            fname   = os.path.basename(fpath)
            size_kb = os.path.getsize(fpath) / 1024
            size_s  = (f"{size_kb/1024:.1f} MB"
                       if size_kb > 1024 else f"{size_kb:.0f} KB")
            tk.Label(card,
                     text=(fname[:18] + "…" if len(fname) > 18 else fname),
                     font=("Segoe UI", 7, "bold"),
                     bg=C["card"], fg=C["fg"],
                     wraplength=140).pack()
            tk.Label(card, text=size_s,
                     font=("Segoe UI", 7),
                     bg=C["card"], fg=C["fg_muted"]).pack()

            for w in [card] + card.winfo_children():
                w.bind("<Button-1>",
                       lambda e, p=fpath: self._show_image(p))

    def _show_image(self, fpath: str):
        C = self.app.COLORS
        for w in self.img_frame.winfo_children():
            w.destroy()
        try:
            from PIL import Image, ImageTk
            img = Image.open(fpath)
            img.thumbnail((720, 220))
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(self.img_frame, image=photo, bg=C["card"])
            lbl.image = photo
            lbl.pack(pady=4)
            size_mb = os.path.getsize(fpath) / (1024 ** 2)
            tk.Label(self.img_frame,
                     text=f"📸 {os.path.basename(fpath)}  ·  {size_mb:.2f} MB",
                     font=("Segoe UI", 8),
                     bg=C["card"], fg=C["fg_muted"]).pack()
        except Exception as exc:
            tk.Label(self.img_frame,
                     text=f"❌ No se puede mostrar la previsualización\n{exc}",
                     font=("Segoe UI", 9),
                     bg=C["card"], fg=C["fg_muted"]).pack(pady=20)

    def _open_download_dir(self):
        d = self.var_download_dir.get().strip()
        if d and os.path.isdir(d):
            import subprocess, platform
            if platform.system() == "Windows":
                os.startfile(d)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        else:
            self.app.notify(
                "⚠️ No hay carpeta de descarga seleccionada.",
                level="warning")

    # ── ESTADO DEL SISTEMA ────────────────────────────────────────────────────

    def _refresh_status(self):
        dl    = self.var_download_dir.get() or "No seleccionada"
        user  = self.var_user.get() or "No especificado"
        total = 0
        try:
            if self._search_results:
                total = len(list(self._search_results))
        except Exception:
            pass

        lines = [
            f"🖥️  ESTADO — {self.NAME}",
            "═" * 44,
            "",
            "🔌 CONEXIÓN HDA:",
            f"   Estado  : {'✅ Conectado' if self._hda_client else '❌ Sin conectar'}",
            f"   Usuario : {user}",
            f"   Keyring : {'✅ Disponible' if _KEYRING_OK else '⚠️ No instalado (pip install keyring)'}",
            "",
            "📁 ARCHIVOS:",
            f"   Carpeta de descarga : {dl}",
            f"   Productos en búsqueda: {total}",
            f"   Archivos descargados : {len(self._downloaded_files)}",
            "",
            "🧪 ENTORNO:",
            f"   Python : {__import__('sys').version.split()[0]}",
            f"   hda    : {'✅' if self._pkg_ok('hda') else '❌ pip install hda'}",
            f"   Pillow : {'✅' if self._pkg_ok('PIL') else '⚠️ pip install Pillow (previsualización)'}",
            "",
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        self._set_text(self.sys_text, "\n".join(lines))

    def _update_space_estimate(self, n_products: int = 0):
        """Muestra estimación de espacio basada en número de productos."""
        dl = self.var_download_dir.get().strip()
        parts = []
        if n_products > 0:
            # ~15 MB por producto (estimación conservadora para CLMS)
            est_mb = n_products * 15
            parts.append(
                f"⚠️ Espacio estimado: ~{est_mb} MB "
                f"({n_products} producto(s) × ~15 MB)")
        if dl and os.path.isdir(dl):
            try:
                import shutil
                free = shutil.disk_usage(dl).free / (1024 ** 3)
                parts.append(f"  Espacio libre: {free:.1f} GB")
            except Exception:
                pass
        self.space_lbl.config(text="  ".join(parts))

    @staticmethod
    def _pkg_ok(pkg: str) -> bool:
        try:
            __import__(pkg)
            return True
        except ImportError:
            return False

    # ── HELPERS DE UI ─────────────────────────────────────────────────────────

    def _section(self, parent, title: str):
        C = self.app.COLORS
        tk.Label(parent, text=title,
                 font=("Segoe UI", 10, "bold"),
                 bg=C["bg"], fg=C["accent"],
                 anchor="w").pack(fill="x", padx=16, pady=(14, 4))

    def _lbl(self, parent, text: str) -> tk.Label:
        C = self.app.COLORS
        return tk.Label(parent, text=text,
                        font=("Segoe UI", 9),
                        bg=C["card"], fg=C["fg_muted"])

    def _field(self, parent, label: str, var: tk.StringVar,
               row: int = 0, col: int = 0, colspan: int = 1,
               show: str = "", placeholder: str = ""):
        C = self.app.COLORS
        tk.Label(parent, text=label,
                 font=("Segoe UI", 9, "bold"),
                 bg=C["card"], fg=C["fg"],
                 anchor="w").grid(
            row=row * 2, column=col, columnspan=colspan,
            sticky="w", padx=(0, 8), pady=(8, 2))

        e = tk.Entry(parent, textvariable=var, show=show,
                     font=("Segoe UI", 10),
                     bg=C["input_bg"], fg=C["fg"],
                     insertbackground=C["fg"],
                     relief="flat", bd=0,
                     highlightthickness=1,
                     highlightbackground=C["border"],
                     highlightcolor=C["accent"])
        e.grid(row=row * 2 + 1, column=col, columnspan=colspan,
               sticky="ew", padx=(0, 8), pady=(0, 4), ipady=6)
        parent.columnconfigure(col, weight=1)

        if placeholder and not var.get():
            e.insert(0, placeholder)
            e.config(fg=C["fg_muted"])

            def _fi(ev, en=e, v=var, ph=placeholder):
                if en.get() == ph and not v.get():
                    en.delete(0, "end")
                    en.config(fg=C["fg"])

            def _fo(ev, en=e, v=var, ph=placeholder):
                if not en.get():
                    en.insert(0, ph)
                    en.config(fg=C["fg_muted"])

            e.bind("<FocusIn>",  _fi)
            e.bind("<FocusOut>", _fo)

        return e

    def _btn(self, parent, text: str, cmd, style: str = "primary"):
        C = self.app.COLORS
        palette = {
            "primary":   (C["accent"],      "white"),
            "success":   ("#2e7d32",        "white"),
            "secondary": (C["card_border"], C["fg"]),
            "danger":    ("#c53030",        "white"),
        }
        bg, fg = palette.get(style, palette["primary"])
        return tk.Button(parent, text=text, command=cmd,
                         font=("Segoe UI", 9, "bold"),
                         bg=bg, fg=fg,
                         activebackground=C["accent_dark"],
                         activeforeground="white",
                         relief="flat", bd=0,
                         padx=14, pady=7,
                         cursor="hand2")

    def _set_result(self, text: str):
        self._set_text(self.result_text, text)

    @staticmethod
    def _set_text(widget: tk.Text, text: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

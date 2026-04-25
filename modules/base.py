"""
base.py — Clase base para todos los módulos de la aplicación.
Cada módulo hereda de BaseModule e implementa build_ui().
"""
import tkinter as tk
from tkinter import ttk


class BaseModule(tk.Frame):
    """
    Interfaz común para todos los módulos.

    Uso:
        class MiModulo(BaseModule):
            NAME = "Mi Módulo"
            ICON = "🔧"

            def build_ui(self):
                ttk.Label(self, text="Hola").pack()
    """

    # Subclases deben definir estos atributos
    NAME: str = "Módulo sin nombre"
    ICON: str = "📦"

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, **kwargs)
        self.app = app          # Referencia al MainApp
        self.configure(bg=app.COLORS["bg"])
        self.build_ui()

    def build_ui(self):
        """Construye la interfaz del módulo. Debe sobreescribirse."""
        ttk.Label(self, text=f"Módulo: {self.NAME}").pack(padx=20, pady=20)

    def on_show(self):
        """Llamado cuando el módulo se hace visible. Opcional."""
        pass

    def on_hide(self):
        """Llamado cuando el módulo se oculta. Opcional."""
        pass

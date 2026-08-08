"""Arranca la página predeterminada con el motor de pruebas de Streamlit."""

from __future__ import annotations

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

os.environ.setdefault("CAME_DEV_MODE", "1")
root = Path(__file__).resolve().parents[1]
app = AppTest.from_file(str(root / "app.py"), default_timeout=30).run()
if app.exception:
    details = "\n".join(str(item.value) for item in app.exception)
    raise SystemExit(f"Smoke de Streamlit falló:\n{details}")
if not app.title or app.title[0].value != "Laboratorio CAME":
    raise SystemExit("La aplicación inició, pero no presentó el título esperado.")
print("Smoke de Streamlit: OK · módulo 1 navegable sin ejecutar consultas externas.")


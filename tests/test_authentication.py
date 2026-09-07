from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from came.config import AppSettings
from came.ui.components import passwords_match


def test_passwords_match_accepts_unicode() -> None:
    assert passwords_match("contraseña-segura-🔐", "contraseña-segura-🔐")
    assert not passwords_match("contraseña-segura", "contraseña-segura-🔐")


def test_settings_converts_numeric_password_to_text() -> None:
    settings = AppSettings.from_mapping({"ACCESS_PASSWORD": 123456})

    assert settings.access_password == "123456"
    assert passwords_match("123456", settings.access_password)


def test_streamlit_login_accepts_unicode_password(monkeypatch) -> None:
    monkeypatch.setenv("ACCESS_PASSWORD", "contraseña-segura-🔐")
    monkeypatch.setenv("ACCESS_VERSION", "test-v1")
    monkeypatch.setenv("CAME_DEV_MODE", "false")
    app_path = Path(__file__).resolve().parents[1] / "app.py"

    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    app.text_input[0].input("contraseña-segura-🔐")
    app.button[0].click()
    app.run()

    assert not app.exception
    assert app.header[0].value == "Introducción"

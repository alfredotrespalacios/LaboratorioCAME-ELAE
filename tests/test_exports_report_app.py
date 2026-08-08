from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from came.exports import build_excel, build_pdf
from came.report import build_executive_prompt, make_package


def test_excel_contains_standard_sheets_and_timezone_safe_dates() -> None:
    data = pd.DataFrame({"datetime": pd.date_range("2024-01-01", periods=2, tz="UTC"), "value": [1, 2]})
    content = build_excel(data=data, summary={"Promedio": 1.5}, methodology=["Prueba"])
    workbook = load_workbook(BytesIO(content), read_only=True)
    assert workbook.sheetnames[:5] == ["Datos", "Resumen", "Parámetros", "Metodología", "Cobertura"]


def test_pdf_is_generated() -> None:
    content = build_pdf(title="Prueba", subtitle="Cobertura", indicators={"Valor": 1}, tables={"Datos": pd.DataFrame({"a": [1]})})
    assert content.startswith(b"%PDF")
    assert len(content) > 1000


def test_executive_prompt_caps_news_and_questions_and_contains_packages() -> None:
    package = make_package(
        module="1",
        title="Precio",
        period="2024",
        source="XM",
        unit="COP/kWh",
        configuration={},
        indicators={"promedio": 100},
        methodology=["Promedio"],
    )
    prompt = build_executive_prompt(
        [package],
        audience="Directivos",
        tone="Ejecutivo",
        length="2 páginas",
        technical_level="Intermedio",
        news=[{"titulo": str(index)} for index in range(5)],
        questions=[f"Q{index}" for index in range(6)],
    )
    assert '"title": "Precio"' in prompt
    assert "Q3" in prompt
    assert "Q4" not in prompt
    assert '"titulo": "2"' in prompt
    assert '"titulo": "3"' not in prompt


def test_app_declares_all_19_numbered_pages() -> None:
    text = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    for number in range(1, 20):
        assert f'title="{number}.' in text


def test_streamlit_default_page_smoke(monkeypatch) -> None:
    monkeypatch.setenv("CAME_DEV_MODE", "1")
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Laboratorio CAME"
    assert app.header[0].value == "1. Precio de bolsa"

"""Exportaciones estandarizadas a Excel y PDF."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

EXCEL_ROW_LIMIT = 1_048_576


def _to_frame(value: Any, value_name: str = "Valor") -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, pd.Series):
        return value.rename(value_name).reset_index()
    if isinstance(value, dict):
        return pd.DataFrame(list(value.items()), columns=["Campo", value_name])
    if isinstance(value, list):
        return pd.DataFrame({value_name: value})
    return pd.DataFrame({value_name: [value]})


def build_excel(
    *,
    data: pd.DataFrame,
    summary: Any = None,
    parameters: Any = None,
    methodology: Any = None,
    coverage: Any = None,
    additional: dict[str, Any] | None = None,
) -> bytes:
    """Genera las hojas exigidas y aplica formato legible sin alterar los valores."""

    if len(data) + 1 > EXCEL_ROW_LIMIT:
        raise ValueError(
            f"Excel admite {EXCEL_ROW_LIMIT - 1:,} filas de datos por hoja; se recibieron {len(data):,}."
        )
    buffer = BytesIO()
    sheets: dict[str, pd.DataFrame] = {
        "Datos": _to_frame(data),
        "Resumen": _to_frame(summary),
        "Parámetros": _to_frame(parameters),
        "Metodología": _to_frame(methodology, "Descripción"),
        "Cobertura": _to_frame(coverage),
    }
    for name, value in (additional or {}).items():
        safe_name = str(name)[:31].replace("/", "-").replace("\\", "-")
        sheets[safe_name] = _to_frame(value)

    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="yyyy-mm-dd hh:mm") as writer:
        workbook = writer.book
        header_format = workbook.add_format(
            {"bold": True, "bg_color": "#1F4E79", "font_color": "#FFFFFF", "border": 0}
        )
        text_format = workbook.add_format({"text_wrap": True, "valign": "top"})
        number_format = workbook.add_format({"num_format": "0.0000"})
        for sheet_name, frame in sheets.items():
            frame = frame.copy()
            if len(frame.columns) == 0:
                frame = pd.DataFrame({"Información": ["Sin datos para esta sección"]})
            for column in frame.select_dtypes(include=["datetimetz"]).columns:
                frame[column] = frame[column].dt.tz_convert("UTC").dt.tz_localize(None)
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes(1, 0)
            worksheet.autofilter(0, 0, max(len(frame), 1), max(len(frame.columns) - 1, 0))
            for col_idx, column in enumerate(frame.columns):
                worksheet.write(0, col_idx, str(column), header_format)
                sample = frame[column].astype(str).head(300) if not frame.empty else pd.Series(dtype=str)
                width = min(max(len(str(column)) + 2, int(sample.str.len().quantile(0.90)) + 2 if not sample.empty else 10), 42)
                fmt = number_format if pd.api.types.is_numeric_dtype(frame[column]) else text_format
                worksheet.set_column(col_idx, col_idx, width, fmt)
            worksheet.set_row(0, 24)
    return buffer.getvalue()


def plotly_png(figure: Any, width: int = 1200, height: int = 650) -> bytes | None:
    try:
        return figure.to_image(format="png", width=width, height=height, scale=1.5)
    except Exception:
        return None


def _paragraph_text(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(
    *,
    title: str,
    subtitle: str,
    indicators: dict[str, Any] | None = None,
    tables: dict[str, pd.DataFrame] | None = None,
    methodology: list[str] | None = None,
    warnings: list[str] | None = None,
    figures: list[tuple[str, bytes | None]] | None = None,
) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.1 * cm,
        bottomMargin=1.1 * cm,
        title=title,
        author="ELAE — Alfredo Trespalacios",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CameTitle",
            parent=styles["Title"],
            textColor=colors.HexColor("#18324A"),
            alignment=TA_CENTER,
            fontSize=20,
            leading=24,
        )
    )
    story: list[Any] = [
        Paragraph(_paragraph_text(title), styles["CameTitle"]),
        Paragraph(_paragraph_text(subtitle), styles["Heading2"]),
        Spacer(1, 0.3 * cm),
    ]
    if indicators:
        table_data = [["Indicador", "Valor"]] + [
            [_paragraph_text(key), _paragraph_text(value)] for key, value in indicators.items()
        ]
        table = Table(table_data, colWidths=[8 * cm, 8 * cm], repeatRows=1)
        table.setStyle(_table_style())
        story.extend([table, Spacer(1, 0.4 * cm)])

    for name, frame in (tables or {}).items():
        story.append(Paragraph(_paragraph_text(name), styles["Heading2"]))
        preview = frame.head(35).copy()
        table_data = [[_paragraph_text(column) for column in preview.columns]]
        table_data += [
            [_paragraph_text(value) for value in row] for row in preview.astype(object).to_numpy()
        ]
        if table_data and table_data[0]:
            width = 25.5 * cm / len(table_data[0])
            table = Table(table_data, colWidths=[width] * len(table_data[0]), repeatRows=1)
            table.setStyle(_table_style(font_size=6.8))
            story.extend([table, Spacer(1, 0.4 * cm)])
        if len(frame) > len(preview):
            story.append(
                Paragraph(
                    f"La vista PDF presenta {len(preview)} de {len(frame)} filas; el Excel conserva la tabla completa.",
                    styles["Italic"],
                )
            )

    for figure_title, image_bytes in figures or []:
        if image_bytes:
            story.extend(
                [
                    PageBreak(),
                    Paragraph(_paragraph_text(figure_title), styles["Heading2"]),
                    Image(BytesIO(image_bytes), width=24.5 * cm, height=13.3 * cm),
                ]
            )

    if methodology:
        story.extend([PageBreak(), Paragraph("Metodología", styles["Heading1"])])
        for line in methodology:
            story.append(Paragraph("• " + _paragraph_text(line), styles["BodyText"]))
    if warnings:
        story.append(Paragraph("Advertencias", styles["Heading1"]))
        for line in warnings:
            story.append(Paragraph("• " + _paragraph_text(line), styles["BodyText"]))
    document.build(story)
    return buffer.getvalue()


def _table_style(font_size: float = 8.5) -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F4F7")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )

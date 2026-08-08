"""Gráficos Plotly coherentes para todos los módulos."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from came.config import COLORS

GRID_COLOR = "#CBD5E1"
ZERO_LINE_COLOR = "#98A2B3"


def configure_plotly_theme() -> None:
    """Aplica una cuadrícula legible incluso a figuras creadas fuera de este archivo."""

    pio.templates["came"] = go.layout.Template(
        layout=go.Layout(
            paper_bgcolor=COLORS["light"],
            plot_bgcolor=COLORS["light"],
            font=dict(color="#101828"),
            colorway=[COLORS["blue"], COLORS["gold"], COLORS["green"], COLORS["red"]],
            xaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=ZERO_LINE_COLOR),
            yaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=ZERO_LINE_COLOR),
        )
    )
    pio.templates.default = "came"
    px.defaults.template = "came"


def style_figure(figure: go.Figure, *, y_title: str = "", x_title: str = "") -> go.Figure:
    figure.update_layout(
        template="came",
        colorway=[COLORS["blue"], COLORS["gold"], COLORS["green"], COLORS["red"]],
        paper_bgcolor=COLORS["light"],
        plot_bgcolor=COLORS["light"],
        font=dict(color="#101828"),
        margin=dict(l=25, r=20, t=50, b=25),
        legend_title_text="",
        hovermode="x unified",
        xaxis_title=x_title,
        yaxis_title=y_title,
    )
    figure.update_xaxes(gridcolor=GRID_COLOR, zerolinecolor=ZERO_LINE_COLOR)
    figure.update_yaxes(gridcolor=GRID_COLOR, zerolinecolor=ZERO_LINE_COLOR)
    return figure


def line(frame: pd.DataFrame, y: str | list[str], *, title: str, unit: str) -> go.Figure:
    return style_figure(px.line(frame, x="datetime", y=y, title=title), y_title=unit)


def bars(
    frame: pd.DataFrame, x: str, y: str, *, color: str | None, title: str, unit: str
) -> go.Figure:
    return style_figure(px.bar(frame, x=x, y=y, color=color, title=title), y_title=unit)


def histogram(
    frame: pd.DataFrame,
    x: str,
    *,
    title: str,
    unit: str,
    bins: int = 35,
) -> go.Figure:
    return style_figure(px.histogram(frame, x=x, nbins=bins, title=title), x_title=unit)


def observed_estimated(frame: pd.DataFrame, *, title: str, unit: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame["datetime"], y=frame["observado"], name="Observado"))
    fig.add_trace(go.Scatter(x=frame["datetime"], y=frame["estimado"], name="Estimado"))
    if {"inferior_95", "superior_95"}.issubset(frame):
        fig.add_trace(
            go.Scatter(
                x=frame["datetime"], y=frame["superior_95"], line=dict(width=0), showlegend=False
            )
        )
        fig.add_trace(
            go.Scatter(
                x=frame["datetime"],
                y=frame["inferior_95"],
                fill="tonexty",
                line=dict(width=0),
                name="Intervalo 95 %",
                opacity=0.20,
            )
        )
    fig.update_layout(title=title)
    return style_figure(fig, y_title=unit)


def offer_curve(frame: pd.DataFrame, demand: float) -> go.Figure:
    fig = px.line(
        frame,
        x="Disponibilidad_acumulada_GWh_día",
        y="Precio_COP_kWh",
        color="Tecnología",
        title="Curva escalonada de oferta",
    )
    fig.update_traces(line_shape="hv", mode="lines+markers")
    fig.add_vline(x=demand, line_dash="dash", line_color=COLORS["red"], annotation_text="Demanda")
    return style_figure(fig, x_title="Disponibilidad acumulada (GWh-día)", y_title="COP/kWh")


def offer_curve_with_fits(result: object, demand: float) -> go.Figure:
    """Superpone la curva escalonada y los cuatro ajustes continuos válidos."""

    supply = result.supply
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=supply["Disponibilidad_acumulada_GWh_día"],
            y=supply["Precio_COP_kWh"],
            mode="lines+markers",
            line=dict(shape="hv", width=3, color=COLORS["navy"]),
            marker=dict(size=7),
            name="Oferta escalonada",
            text=supply["Tecnología"],
            hovertemplate="%{text}<br>%{x:.2f} GWh-día<br>%{y:.2f} COP/kWh<extra></extra>",
        )
    )
    upper = max(float(supply["Disponibilidad_acumulada_GWh_día"].max()), float(demand))
    grid = np.linspace(0.0, upper, 300)
    colors = [COLORS["blue"], COLORS["gold"], COLORS["green"], COLORS["red"]]
    for fit, color in zip(result.fits, colors, strict=False):
        if not fit.coefficients or fit.estimated_price is None:
            continue
        if fit.model == "Exponencial":
            values = fit.coefficients[0] * np.exp(fit.coefficients[1] * grid)
        else:
            values = np.polyval(fit.coefficients, grid)
        finite = np.isfinite(values)
        fig.add_trace(
            go.Scatter(
                x=grid[finite],
                y=values[finite],
                mode="lines",
                line=dict(width=2, dash="dash", color=color),
                name=fit.model,
                hovertemplate=f"{fit.model}<br>%{{x:.2f}} GWh-día<br>%{{y:.2f}} COP/kWh<extra></extra>",
            )
        )
    fig.add_vline(
        x=demand,
        line_dash="dot",
        line_color=COLORS["red"],
        annotation_text="Demanda",
        annotation_font_color=COLORS["red"],
    )
    fig.update_layout(title="Curva de oferta escalonada y ajustes continuos")
    return style_figure(
        fig,
        x_title="Disponibilidad acumulada (GWh-día)",
        y_title="COP/kWh",
    )

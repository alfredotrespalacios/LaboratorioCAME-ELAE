"""Gráficos Plotly coherentes para todos los módulos."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from came.config import COLORS


def style_figure(figure: go.Figure, *, y_title: str = "", x_title: str = "") -> go.Figure:
    figure.update_layout(
        template="plotly_white",
        colorway=[COLORS["blue"], COLORS["gold"], COLORS["green"], COLORS["red"]],
        margin=dict(l=25, r=20, t=50, b=25),
        legend_title_text="",
        hovermode="x unified",
        xaxis_title=x_title,
        yaxis_title=y_title,
    )
    return figure


def line(frame: pd.DataFrame, y: str | list[str], *, title: str, unit: str) -> go.Figure:
    return style_figure(px.line(frame, x="datetime", y=y, title=title), y_title=unit)


def bars(frame: pd.DataFrame, x: str, y: str, *, color: str | None, title: str, unit: str) -> go.Figure:
    return style_figure(px.bar(frame, x=x, y=y, color=color, title=title), y_title=unit)


def histogram(frame: pd.DataFrame, x: str, *, title: str, unit: str) -> go.Figure:
    return style_figure(px.histogram(frame, x=x, nbins=35, title=title), x_title=unit)


def observed_estimated(frame: pd.DataFrame, *, title: str, unit: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame["datetime"], y=frame["observado"], name="Observado"))
    fig.add_trace(go.Scatter(x=frame["datetime"], y=frame["estimado"], name="Estimado"))
    if {"inferior_95", "superior_95"}.issubset(frame):
        fig.add_trace(go.Scatter(x=frame["datetime"], y=frame["superior_95"], line=dict(width=0), showlegend=False))
        fig.add_trace(
            go.Scatter(
                x=frame["datetime"], y=frame["inferior_95"], fill="tonexty",
                line=dict(width=0), name="Intervalo 95 %", opacity=.20,
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

"""Módulo 1: precio de bolsa de Colombia."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from came.analytics.aggregation import add_change_columns, add_price_returns, summary_indicators
from came.data.monthly_store import load_default_metadata
from came.ui.charts import bars, histogram, line, style_figure
from came.ui.components import (
    date_range_controls,
    export_and_collect,
    page_header,
    show_indicators,
    unavailable,
)
from came.ui.loaders import xm_explore, xm_spot
from came.ui.monthly_access import published_series

PRICE_SERIES_ID = "col_precio_bolsa_cop_kwh"


def _published_price() -> pd.DataFrame:
    """Prepara el precio mensual ya guardado para usar las mismas métricas del módulo."""

    long = published_series("COL", [PRICE_SERIES_ID])
    if long.empty:
        raise ValueError("El Parquet de Colombia no contiene la serie de precio de bolsa.")
    data = long[["datetime", "value"]].copy()
    data = add_change_columns(data, frequency="monthly")
    return add_price_returns(data)


def _filter_period(data: pd.DataFrame, start: object, end: object) -> pd.DataFrame:
    dates = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    lower = pd.Timestamp(start, tz="UTC")
    upper = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return data[dates.ge(lower) & dates.lt(upper)].copy()


def _render_price_analysis(
    data: pd.DataFrame,
    *,
    frequency_label: str,
    source: str,
    key: str,
) -> None:
    if data.empty:
        st.warning("No hay observaciones del precio en el periodo seleccionado.")
        return

    indicators = summary_indicators(data)
    show_indicators(indicators)
    price_figure = line(data, "value", title="Precio de bolsa", unit="COP/kWh")
    st.plotly_chart(price_figure, use_container_width=True, key=f"{key}_price")

    left, right = st.columns(2)
    annual = (
        data.assign(Año=pd.to_datetime(data["datetime"], utc=True).dt.year)
        .groupby("Año", as_index=False)["value"]
        .mean()
    )
    left.plotly_chart(
        bars(annual, "Año", "value", color=None, title="Promedio anual", unit="COP/kWh"),
        use_container_width=True,
        key=f"{key}_annual",
    )
    right.plotly_chart(
        histogram(data, "value", title="Distribución", unit="COP/kWh"),
        use_container_width=True,
        key=f"{key}_distribution",
    )

    st.subheader("Rendimientos del precio de bolsa")
    latest = data.dropna(
        subset=["Variación_porcentual_pct", "Rendimiento_logarítmico_pct"], how="all"
    )
    if latest.empty:
        st.info("Se necesitan por lo menos dos observaciones para calcular rendimientos.")
    else:
        metric_columns = st.columns(2)
        metric_columns[0].metric(
            "Última variación porcentual",
            f"{latest['Variación_porcentual_pct'].iloc[-1]:,.2f} %",
        )
        metric_columns[1].metric(
            "Último rendimiento logarítmico",
            f"{latest['Rendimiento_logarítmico_pct'].iloc[-1]:,.2f} %",
        )
        returns_figure = line(
            data,
            ["Variación_porcentual_pct", "Rendimiento_logarítmico_pct"],
            title="Rendimiento entre observaciones consecutivas",
            unit="%",
        )
        st.plotly_chart(returns_figure, use_container_width=True, key=f"{key}_returns")
        st.caption(
            "Variación porcentual = (Pₜ/Pₜ₋₁ − 1) × 100. "
            "Rendimiento logarítmico = ln(Pₜ/Pₜ₋₁) × 100."
        )

    first = pd.to_datetime(data["datetime"], utc=True).min().date()
    last = pd.to_datetime(data["datetime"], utc=True).max().date()
    export_and_collect(
        module="1. Precio de bolsa",
        title="Precio de bolsa de Colombia",
        data=data,
        indicators=indicators,
        parameters={"Frecuencia": frequency_label, "Fuente de consulta": source},
        methodology=[
            "Promedio simple de las observaciones de precio en cada periodo.",
            "Variación porcentual = (Pₜ/Pₜ₋₁ − 1) × 100.",
            "Rendimiento logarítmico = ln(Pₜ/Pₜ₋₁) × 100; requiere precios positivos.",
        ],
        source=source,
        unit="COP/kWh; rendimientos en %",
        period=f"{first} a {last}",
        figure=price_figure,
        key=f"precio_bolsa_colombia_{key}",
    )


def _render_intraday(start: object, end: object, timeout: int) -> None:
    with st.expander("Perfil intradiario de los últimos 31 días del periodo"):
        if st.button("Cargar observaciones horarias", key="spot_hourly"):
            try:
                hourly_start = max(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=30))
                result = xm_explore("PrecBolsNaci", "Sistema", hourly_start, end, timeout)
                hourly = result.data[["datetime", "value"]].copy()
                local = hourly["datetime"].dt.tz_convert("America/Bogota")
                hourly["Hora"] = local.dt.hour
                st.session_state["spot_hourly_data"] = hourly
            except Exception as exc:
                unavailable(exc, source="XM")
        hourly = st.session_state.get("spot_hourly_data")
        if hourly is not None:
            figure = px.violin(hourly, x="Hora", y="value", box=True, title="Precio por hora")
            st.plotly_chart(
                style_figure(figure, y_title="COP/kWh"),
                use_container_width=True,
                key="spot_hourly_figure",
            )


def page_spot(timeout: int) -> None:
    page_header(
        1,
        "Precio de bolsa",
        "Evolución, rendimientos y distribución del precio nacional de bolsa.",
        "Base mensual precargada con datos XM · consulta directa a XM opcional",
    )
    published_tab, live_tab = st.tabs(
        ["Base precargada · mensual", "Consulta opcional a XM"]
    )

    with published_tab:
        st.caption(
            "Esta vista abre el Parquet publicado y no realiza una descarga nueva desde XM."
        )
        try:
            published = _published_price()
            metadata = load_default_metadata("COL")
        except (FileNotFoundError, OSError, ValueError) as exc:
            st.warning(str(exc))
            st.info(
                "Construya y publique Colombia desde **Mantenimiento → Mantenimiento de datos**."
            )
        else:
            min_date = pd.to_datetime(published["datetime"], utc=True).min().date()
            start, end = date_range_controls("spot_published", min_date=min_date)
            filtered = _filter_period(published, start, end)
            last_month = pd.to_datetime(published["datetime"], utc=True).max().date()
            st.info(
                f"Último mes completo disponible: **{last_month}**. "
                f"Paquete actualizado: {metadata.get('created_at_utc', 'sin fecha en el JSON')}."
            )
            _render_price_analysis(
                filtered,
                frequency_label="Mensual",
                source="Base mensual precargada · XM PrecBolsNaci",
                key="published",
            )

    with live_tab:
        st.info(
            "Use esta sección solo cuando necesite datos diarios o contrastar XM. "
            "La consulta puede tardar según el periodo."
        )
        start, end = date_range_controls("spot_live")
        frequency_label = st.radio(
            "Frecuencia XM",
            ["Mensual", "Diaria"],
            horizontal=True,
            key="spot_live_frequency",
        )
        frequency = "monthly" if frequency_label == "Mensual" else "daily"
        if st.button("Consultar precio directamente en XM", type="primary", key="spot_run"):
            try:
                with st.spinner("Consultando XM…"):
                    st.session_state["spot_result"] = xm_spot(start, end, frequency, timeout)
                    st.session_state["spot_query"] = (start, end, frequency_label)
            except Exception as exc:
                unavailable(exc, source="XM")
        data = st.session_state.get("spot_result")
        if data is None or data.empty:
            st.caption("No se ha ejecutado una consulta directa a XM en esta sesión.")
        else:
            query = st.session_state.get("spot_query", (start, end, frequency_label))
            _render_price_analysis(
                data,
                frequency_label=query[2],
                source="Consulta directa · XM PrecBolsNaci",
                key="xm",
            )
            _render_intraday(query[0], query[1], timeout)

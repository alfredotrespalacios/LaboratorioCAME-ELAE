"""Módulo 2: demanda nacional de Colombia."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from came.analytics.aggregation import add_change_columns, summary_indicators
from came.data.monthly_store import load_default_metadata
from came.ui.charts import line
from came.ui.components import (
    date_range_controls,
    export_and_collect,
    page_header,
    show_indicators,
    show_warnings,
    unavailable,
)
from came.ui.loaders import xm_demand, xm_unserved
from came.ui.monthly_access import published_series

DEMAND_SERIES = {
    "col_demanda_gwh_mes": "GWh_mes",
    "col_demanda_gwh_dia": "GWh_día",
}
UNSERVED_SERIES = {
    "col_demanda_no_atendida_gwh_mes": "GWh",
    "col_demanda_no_atendida_gwh_dia": "GWh_día",
}


def _wide_series(long: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    selected = long[long["series_id"].isin(mapping)].copy()
    if selected.empty:
        return pd.DataFrame(columns=["datetime", *mapping.values()])
    wide = selected.pivot(index="datetime", columns="series_id", values="value").reset_index()
    wide.columns.name = None
    return wide.rename(columns=mapping).sort_values("datetime").reset_index(drop=True)


def _published_demand() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lee demanda y DNA mensuales sin contactar nuevamente a XM."""

    series_ids = [*DEMAND_SERIES, *UNSERVED_SERIES]
    long = published_series("COL", series_ids)
    demand = _wide_series(long, DEMAND_SERIES)
    if demand.empty or "GWh_día" not in demand or demand["GWh_día"].dropna().empty:
        raise ValueError("El Parquet de Colombia no contiene la demanda nacional mensual.")
    demand["value"] = demand.get("GWh_mes", demand["GWh_día"])
    demand = add_change_columns(demand, value_column="GWh_día", frequency="monthly")
    unserved = _wide_series(long, UNSERVED_SERIES)
    return demand, unserved


def _filter_period(data: pd.DataFrame, start: object, end: object) -> pd.DataFrame:
    if data.empty:
        return data.copy()
    dates = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    lower = pd.Timestamp(start, tz="UTC")
    upper = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return data[dates.ge(lower) & dates.lt(upper)].copy()


def _show_completeness(demand: pd.DataFrame, frequency_label: str) -> None:
    last_complete = demand.attrs.get("last_complete_period")
    excluded = demand.attrs.get("excluded_incomplete_periods", [])
    if frequency_label == "Diaria" and last_complete is not None:
        st.info(f"Último día completo recibido de XM: **{pd.Timestamp(last_complete).date()}**.")
    if excluded:
        label = "días" if frequency_label == "Diaria" else "meses"
        formatted = ", ".join(str(pd.Timestamp(value).date()) for value in excluded[-5:])
        st.warning(
            f"Se ocultaron {len(excluded)} {label} incompletos para evitar mostrar una caída falsa. "
            f"Últimos periodos excluidos: {formatted}."
        )


def _render_demand_analysis(
    demand: pd.DataFrame,
    *,
    unserved: pd.DataFrame | None,
    audit: pd.DataFrame | None,
    warnings: list[str],
    frequency_label: str,
    source: str,
    key: str,
) -> None:
    if demand.empty:
        st.warning("No hay periodos completos de demanda dentro de la selección.")
        return

    _show_completeness(demand, frequency_label)
    indicators = summary_indicators(demand, "GWh_día")
    show_indicators(indicators)
    demand_figure = line(
        demand,
        "GWh_día",
        title="Demanda nacional promedio diaria",
        unit="GWh-día",
    )
    st.plotly_chart(demand_figure, use_container_width=True, key=f"{key}_demand")

    additional: dict[str, pd.DataFrame] = {}
    if unserved is not None and not unserved.empty:
        st.plotly_chart(
            line(unserved, "GWh_día", title="Demanda no atendida", unit="GWh-día"),
            use_container_width=True,
            key=f"{key}_unserved",
        )
        show_warnings(warnings)
        additional["Demanda no atendida"] = unserved
        if audit is not None and not audit.empty:
            additional["Auditoría jerárquica"] = audit
            with st.expander("Auditoría área/subárea"):
                st.dataframe(audit, use_container_width=True, hide_index=True)

    first = pd.to_datetime(demand["datetime"], utc=True).min().date()
    last = pd.to_datetime(demand["datetime"], utc=True).max().date()
    export_and_collect(
        module="2. Demanda nacional",
        title="Demanda nacional de Colombia",
        data=demand,
        indicators=indicators,
        parameters={
            "Frecuencia": frequency_label,
            "Incluye DNA": bool(unserved is not None and not unserved.empty),
            "Fuente de consulta": source,
        },
        methodology=[
            "Energía mensual = suma de intervalos; GWh-día = GWh del mes / días calendario.",
            "Los días con menos intervalos que los esperados se excluyen antes de agregar.",
            "Cuando área y subárea coexisten se usa área como total y subárea como verificación.",
        ],
        source=source,
        unit="GWh-día",
        period=f"{first} a {last}",
        warnings=warnings,
        figure=demand_figure,
        additional=additional,
        key=f"demanda_colombia_{key}",
    )


def page_demand(timeout: int) -> None:
    page_header(
        2,
        "Demanda nacional",
        "Demanda del SIN y demanda no atendida sin doble conteo entre área y subárea.",
        "Base mensual precargada con datos XM · consulta directa a XM opcional",
    )
    published_tab, live_tab = st.tabs(
        ["Base precargada · mensual", "Consulta opcional a XM"]
    )

    with published_tab:
        st.caption(
            "Esta vista abre el Parquet publicado y excluye el mes calendario aún incompleto."
        )
        try:
            demand, unserved = _published_demand()
            metadata = load_default_metadata("COL")
        except (FileNotFoundError, OSError, ValueError) as exc:
            st.warning(str(exc))
            st.info(
                "Construya y publique Colombia desde **Mantenimiento → Mantenimiento de datos**."
            )
        else:
            min_date = pd.to_datetime(demand["datetime"], utc=True).min().date()
            start, end = date_range_controls("demand_published", min_date=min_date)
            filtered_demand = _filter_period(demand, start, end)
            filtered_unserved = _filter_period(unserved, start, end)
            show_unserved = st.checkbox(
                "Mostrar demanda no atendida precargada",
                value=True,
                key="demand_published_unserved",
            )
            last_month = pd.to_datetime(demand["datetime"], utc=True).max().date()
            st.info(
                f"Último mes completo disponible: **{last_month}**. "
                f"Paquete actualizado: {metadata.get('created_at_utc', 'sin fecha en el JSON')}."
            )
            _render_demand_analysis(
                filtered_demand,
                unserved=filtered_unserved if show_unserved else None,
                audit=None,
                warnings=[],
                frequency_label="Mensual",
                source="Base mensual precargada · XM DemaSIN",
                key="published",
            )

    with live_tab:
        st.info(
            "Use esta sección para consultar días recientes o contrastar XM. "
            "La aplicación ocultará automáticamente cualquier día incompleto."
        )
        start, end = date_range_controls("demand_live")
        frequency_label = st.radio(
            "Frecuencia XM",
            ["Mensual", "Diaria"],
            horizontal=True,
            key="demand_live_frequency",
        )
        frequency = "monthly" if frequency_label == "Mensual" else "daily"
        include_unserved = st.checkbox(
            "Consultar también demanda no atendida",
            value=True,
            key="demand_live_unserved",
        )
        if st.button("Consultar demanda directamente en XM", type="primary", key="demand_run"):
            try:
                with st.spinner("Consultando XM…"):
                    demand = xm_demand(start, end, frequency, timeout)
                    state = {
                        "demand": demand,
                        "warnings": [],
                        "audit": pd.DataFrame(),
                        "frequency_label": frequency_label,
                    }
                    if include_unserved:
                        monthly, audit, warnings = xm_unserved(start, end, timeout)
                        if frequency == "monthly" and not demand.empty:
                            valid_months = pd.to_datetime(demand["datetime"], utc=True)
                            monthly_dates = pd.to_datetime(monthly["datetime"], utc=True)
                            monthly = monthly[monthly_dates.isin(valid_months)].copy()
                        state.update(
                            {"unserved": monthly, "audit": audit, "warnings": warnings}
                        )
                    st.session_state["demand_result"] = state
            except Exception as exc:
                unavailable(exc, source="XM")
        result = st.session_state.get("demand_result")
        if not result:
            st.caption("No se ha ejecutado una consulta directa a XM en esta sesión.")
        else:
            _render_demand_analysis(
                result["demand"],
                unserved=result.get("unserved"),
                audit=result.get("audit"),
                warnings=result.get("warnings", []),
                frequency_label=result.get("frequency_label", frequency_label),
                source="Consulta directa · XM DemaSIN",
                key="xm",
            )

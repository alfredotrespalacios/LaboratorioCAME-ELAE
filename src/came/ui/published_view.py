"""Vista reutilizable de un paquete mensual publicado."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from came.data.monthly_store import (
    PACKAGE_SPECS,
    load_default_metadata,
    load_default_monthly,
    series_options,
    to_wide,
)
from came.ui.components import export_and_collect, show_indicators


def render_published_country(country: str, *, key: str) -> bool:
    """Muestra un país; devuelve False cuando aún no existe su Parquet."""

    try:
        data = load_default_monthly(country)
        metadata = load_default_metadata(country)
    except FileNotFoundError as exc:
        st.warning(str(exc))
        return False
    except Exception as exc:
        st.error(f"No fue posible abrir el paquete mensual: {exc}")
        return False
    if data.empty:
        st.warning("El paquete mensual está vacío.")
        return False
    spec = PACKAGE_SPECS[country]
    options = series_options(data)
    st.caption(
        f"{spec.label} · último mes {data['datetime'].max().date()} · "
        f"actualizado {metadata.get('created_at_utc', 'sin JSON')}"
    )
    families = sorted(options["family"].astype(str).unique())
    selected_families = st.multiselect(
        "Familias de información", families, default=families, key=f"{key}_families"
    )
    visible = options[options["family"].isin(selected_families)]
    labels = {
        row.series_id: f"{row.series_name} · {row.unit} · {row.level}"
        for row in visible.itertuples()
    }
    selected = st.multiselect(
        "Series mensuales",
        list(labels),
        default=list(labels)[: min(5, len(labels))],
        format_func=lambda value: labels.get(value, value),
        max_selections=8,
        key=f"{key}_series",
    )
    if not selected:
        st.info("Seleccione una serie.")
        return True
    long = data[data["series_id"].isin(selected)].copy()
    figure = px.line(
        long,
        x="datetime",
        y="value",
        facet_row="series_name",
        facet_row_spacing=min(0.05, 0.25 / len(selected)),
        height=min(max(250 * len(selected), 420), 1800),
        title=f"Base mensual de {spec.label}",
    )
    figure.update_yaxes(matches=None, title_text="")
    figure.for_each_annotation(
        lambda annotation: annotation.update(text=annotation.text.split("=")[-1])
    )
    st.plotly_chart(figure, use_container_width=True)
    wide = to_wide(long, country)
    indicators = {
        "Meses": wide["datetime"].nunique(),
        "Series visibles": len(selected),
        "Series disponibles": len(options),
    }
    show_indicators(indicators)
    tabs = st.tabs(["Tabla mensual", "Catálogo"])
    tabs[0].dataframe(wide, use_container_width=True, hide_index=True)
    tabs[1].dataframe(
        options[options["series_id"].isin(selected)], use_container_width=True, hide_index=True
    )
    export_and_collect(
        module=f"Mercado de {spec.label}",
        title=f"Base mensual publicada de {spec.label}",
        data=wide,
        indicators=indicators,
        parameters={"Series": [labels[item] for item in selected]},
        methodology=[
            "Cada serie conserva la fuente, la unidad y la agregación descritas en su catálogo.",
            "No se completan valores faltantes de manera automática.",
        ],
        source=f"Paquete mensual validado de {spec.label}",
        unit="Una unidad por serie",
        period=f"{pd.to_datetime(long['datetime'], utc=True).min().date()} a {pd.to_datetime(long['datetime'], utc=True).max().date()}",
        figure=figure,
        additional={
            "Catálogo": options[options["series_id"].isin(selected)],
            "Formato largo": long,
        },
        key=f"{key}_published_export",
    )
    return True

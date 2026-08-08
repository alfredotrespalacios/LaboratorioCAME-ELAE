"""Acceso común de los módulos analíticos a las bases mensuales publicadas."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from came.data.monthly_store import PACKAGE_SPECS, load_default_monthly, series_options, to_wide


@dataclass
class ModelingData:
    country: str
    country_label: str
    wide: pd.DataFrame
    long: pd.DataFrame
    labels: dict[str, str]


@st.cache_data(show_spinner=False, ttl=300)
def _load_country(country: str) -> pd.DataFrame:
    return load_default_monthly(country)


def available_countries() -> dict[str, pd.DataFrame]:
    available: dict[str, pd.DataFrame] = {}
    for code in PACKAGE_SPECS:
        try:
            frame = _load_country(code)
        except (FileNotFoundError, OSError, ValueError):
            continue
        if not frame.empty:
            available[code] = frame
    return available


def modeling_data_or_message(*, key: str) -> ModelingData | None:
    """Selecciona un país y entrega una tabla ancha con nombres de columnas legibles."""

    countries = available_countries()
    if not countries:
        st.info(
            "No hay una base mensual publicada. Genere y publique el paquete desde "
            "**Mantenimiento → Mantenimiento de datos**. No es necesario abrir primero el módulo 6."
        )
        return None
    code = st.selectbox(
        "País de la serie histórica",
        list(countries),
        format_func=lambda value: PACKAGE_SPECS[value].label,
        key=f"{key}_country",
    )
    long = countries[code]
    options = series_options(long)
    labels: dict[str, str] = {}
    used: set[str] = set()
    for row in options.itertuples():
        base = f"{row.series_name} · {row.unit} · {row.level}"
        label = base if base not in used else f"{base} · {row.series_id}"
        used.add(label)
        labels[str(row.series_id)] = label
    wide = to_wide(long, code).rename(columns=labels)
    return ModelingData(code, PACKAGE_SPECS[code].label, wide, long, labels)

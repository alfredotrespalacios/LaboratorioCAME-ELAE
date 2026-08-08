"""Consultas almacenadas en caché; ninguna se ejecuta durante el arranque."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from came.analytics.generation import (
    GenerationMonthlyHistory,
    aggregate_generation_monthly_history,
)
from came.data.colombia import (
    agent_catalog,
    build_integrated_market,
    capacity_by_technology,
    generation_by_technology,
    generation_resources,
    national_demand,
    offers_by_technology,
    resource_catalog,
    spot_price,
    unserved_demand,
)
from came.data.providers.omie import OmieProvider
from came.data.providers.redata import REDataProvider
from came.data.providers.xm import XMProvider


@st.cache_data(show_spinner=False, ttl=3600)
def xm_spot(start: object, end: object, frequency: str, timeout: int) -> pd.DataFrame:
    return spot_price(XMProvider(timeout=timeout), start, end, frequency)


@st.cache_data(show_spinner=False, ttl=3600)
def xm_demand(start: object, end: object, frequency: str, timeout: int) -> pd.DataFrame:
    return national_demand(XMProvider(timeout=timeout), start, end, frequency)


@st.cache_data(show_spinner=False, ttl=3600)
def xm_unserved(
    start: object, end: object, timeout: int
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    result = unserved_demand(XMProvider(timeout=timeout), start, end)
    return result.monthly, result.hierarchy_audit, result.warnings


@st.cache_data(show_spinner=False, ttl=3600)
def xm_generation_technology(
    start: object, end: object, frequency: str, timeout: int
) -> pd.DataFrame:
    return generation_by_technology(XMProvider(timeout=timeout), start, end, frequency)


@st.cache_data(show_spinner=False, ttl=3600)
def xm_generation_resources(start: object, end: object, timeout: int) -> GenerationMonthlyHistory:
    provider = XMProvider(timeout=timeout)
    resources = resource_catalog(provider)
    data = generation_resources(provider, start, end, resources)
    agents = agent_catalog(provider)
    if "company_code" in data and "company_code" in agents:
        data = data.merge(
            agents[[column for column in ("company_code", "company_name") if column in agents]],
            on="company_code",
            how="left",
        )
    return aggregate_generation_monthly_history(data)


@st.cache_data(show_spinner=False, ttl=3600)
def xm_catalog(timeout: int) -> pd.DataFrame:
    return XMProvider(timeout=timeout).catalog()


@st.cache_data(show_spinner=False, ttl=3600)
def xm_explore(metric_id: str, entity: str, start: object, end: object, timeout: int):
    return XMProvider(timeout=timeout).fetch(metric_id, entity, start, end)


@st.cache_data(show_spinner=False, ttl=3600)
def xm_integrated(start: object, end: object, include_macro: bool, timeout: int):
    return build_integrated_market(
        XMProvider(timeout=timeout), start, end, include_macro=include_macro
    )


@st.cache_data(show_spinner=False, ttl=3600)
def xm_capacity(selected_date: object, timeout: int) -> tuple[pd.DataFrame, pd.Timestamp]:
    return capacity_by_technology(XMProvider(timeout=timeout), selected_date)


@st.cache_data(show_spinner=False, ttl=3600)
def xm_offers(start: object, end: object, timeout: int) -> pd.DataFrame:
    return offers_by_technology(XMProvider(timeout=timeout), start, end)


@st.cache_data(show_spinner=False, ttl=3600)
def redata_widget(
    category: str,
    widget: str,
    start: object,
    end: object,
    time_trunc: str,
    system: str,
    unit: str,
    timeout: int,
):
    return REDataProvider(timeout=timeout).fetch_widget(
        category, widget, start, end, time_trunc=time_trunc, system=system, unit=unit
    )


@st.cache_data(show_spinner=False, ttl=3600)
def omie_prices(start: object, end: object, timeout: int):
    return OmieProvider(timeout=timeout).fetch_prices(start, end)

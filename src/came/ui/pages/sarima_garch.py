"""Módulos 11–13: modelación, volatilidad y portafolios."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from came.analytics.volatility import fit_sarima, fit_sarima_garch
from came.ui.charts import line, observed_estimated
from came.ui.components import export_and_collect, page_header, show_indicators, show_warnings
from came.ui.monthly_access import ModelingData, modeling_data_or_message


def _integrated_or_message(*, key: str) -> ModelingData | None:
    return modeling_data_or_message(key=key)


def page_volatility() -> None:
    page_header(
        12,
        "Modelación de volatilidad SARIMA–GARCH",
        "SARIMA modela la media; GARCH modela la varianza condicional de sus residuales.",
        "Base mensual publicada del país seleccionado",
    )
    monthly = _integrated_or_message(key="volatility")
    if monthly is None:
        return
    data = monthly.wide
    numeric = [
        column
        for column in data.select_dtypes(include=np.number).columns
        if column not in {"Tiempo", "Niño", "Niña"}
    ]
    variable = st.selectbox("Serie mensual", numeric, key="vol_variable")
    series_frame = data[["datetime", variable]].dropna().copy()
    st.plotly_chart(
        line(
            series_frame.rename(columns={variable: "value"}),
            "value",
            title="Serie seleccionada",
            unit=variable,
        ),
        use_container_width=True,
    )
    st.subheader("Órdenes")
    cols = st.columns(7)
    p = cols[0].number_input("p", 0, 5, 1)
    d = cols[1].number_input("d", 0, 2, 1)
    q = cols[2].number_input("q", 0, 5, 1)
    seasonal_p = cols[3].number_input("P", 0, 3, 0)
    seasonal_d = cols[4].number_input("D", 0, 2, 1)
    seasonal_q = cols[5].number_input("Q", 0, 3, 1)
    seasonal_s = cols[6].number_input("s", 2, 24, 12)
    horizon = st.slider("Horizonte mensual", 1, 36, 12)
    use_garch = st.checkbox("Agregar GARCH", value=True)
    gcols = st.columns(3)
    garch_p = gcols[0].number_input("GARCH p", 1, 5, 1)
    garch_q = gcols[1].number_input("GARCH q", 1, 5, 1)
    distribution = gcols[2].selectbox("Distribución", ["normal", "t"])
    if st.button("Estimar volatilidad", type="primary", key="vol_run"):
        try:
            indexed = pd.Series(series_frame[variable].to_numpy(), index=series_frame["datetime"])
            if use_garch:
                result = fit_sarima_garch(
                    indexed,
                    sarima_order=(int(p), int(d), int(q)),
                    seasonal_order=(
                        int(seasonal_p),
                        int(seasonal_d),
                        int(seasonal_q),
                        int(seasonal_s),
                    ),
                    garch_order=(int(garch_p), int(garch_q)),
                    distribution=distribution,
                    horizon=horizon,
                )
            else:
                result = fit_sarima(
                    indexed,
                    order=(int(p), int(d), int(q)),
                    seasonal_order=(
                        int(seasonal_p),
                        int(seasonal_d),
                        int(seasonal_q),
                        int(seasonal_s),
                    ),
                    horizon=horizon,
                )
            st.session_state["vol_result"] = {
                "result": result,
                "garch": use_garch,
                "variable": variable,
                "series": series_frame,
                "orders": (
                    (p, d, q),
                    (seasonal_p, seasonal_d, seasonal_q, seasonal_s),
                    (garch_p, garch_q),
                    distribution,
                ),
            }
        except Exception as exc:
            st.error(str(exc))
    state = st.session_state.get("vol_result")
    if not state:
        st.info(
            "Para GARCH se requieren al menos 30 residuales útiles después del arranque estacional."
        )
        return
    result = state["result"]
    sarima = result.sarima if state["garch"] else result
    show_indicators({"AIC": sarima.aic, "BIC": sarima.bic})
    fitted = sarima.fitted.reset_index().rename(
        columns={sarima.fitted.index.name or "index": "datetime"}
    )
    if "datetime" not in fitted:
        fitted.insert(0, "datetime", state["series"]["datetime"].iloc[-len(fitted) :].to_numpy())
    fig = observed_estimated(fitted, title="Ajuste SARIMA", unit=state["variable"])
    st.plotly_chart(fig, use_container_width=True)
    forecast = result.combined_forecast if state["garch"] else sarima.forecast
    st.subheader("Pronóstico")
    st.dataframe(forecast, use_container_width=True, hide_index=True)
    st.subheader("Residuales originales y estandarizados")
    residuals = (
        result.standardized_residuals.reset_index()
        if state["garch"]
        else sarima.residuals.reset_index()
    )
    st.plotly_chart(
        px.line(
            residuals,
            y=[column for column in ("residual", "residual_estandarizado") if column in residuals],
            title="Diagnóstico de residuales",
        ),
        use_container_width=True,
    )
    warnings = (
        result.warnings
        if state["garch"]
        else ["Las bandas SARIMA provienen del modelo de la media y sus supuestos paramétricos."]
    )
    show_warnings(warnings)
    export_and_collect(
        module="12. SARIMA–GARCH",
        title=f"Volatilidad de {state['variable']}",
        data=forecast,
        indicators={"AIC": sarima.aic, "BIC": sarima.bic},
        parameters={"Órdenes": state["orders"], "GARCH": state["garch"]},
        methodology=[
            "SARIMA estima la media condicional.",
            "Cuando está habilitado, GARCH estima la varianza de los residuales SARIMA.",
        ],
        source=f"Base mensual publicada · {monthly.country_label}",
        unit=state["variable"],
        period=f"{state['series']['datetime'].min()} a {state['series']['datetime'].max()}",
        warnings=warnings,
        figure=fig,
        additional={"Ajuste": fitted, "Residuales": residuals},
        key="sarima_garch",
    )

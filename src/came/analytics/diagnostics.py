"""Diagnósticos pedagógicos comunes para residuales de modelos."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DIAGNOSTIC_EXPLANATIONS = {
    "Media residual": "Idealmente cercana a cero; un sesgo persistente indica errores sistemáticos.",
    "Jarque-Bera": "Contrasta si los residuales son compatibles con una distribución normal.",
    "Breusch-Pagan": "Contrasta si la varianza del residual cambia con las variables explicativas.",
    "Durbin-Watson": "Resume autocorrelación de primer orden; valores cercanos a 2 son deseables.",
    "Ljung-Box": "Contrasta en conjunto si quedan autocorrelaciones hasta el rezago seleccionado.",
    "ADF": "Contrasta raíz unitaria; un p-valor pequeño favorece residuales estacionarios.",
    "Cook máximo": "Señala observaciones con influencia elevada sobre una regresión lineal.",
    "Leverage máximo": "Identifica observaciones con combinaciones inusuales de explicativas.",
}


def residual_descriptive(residuals: object) -> pd.DataFrame:
    """Devuelve estadística descriptiva legible, incluida asimetría y curtosis."""

    values = pd.Series(residuals, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return pd.DataFrame(columns=["Estadístico", "Valor"])
    rows = {
        "Observaciones": float(values.size),
        "Media": float(values.mean()),
        "Desviación estándar": float(values.std(ddof=1)) if values.size > 1 else 0.0,
        "Mínimo": float(values.min()),
        "Percentil 25": float(values.quantile(0.25)),
        "Mediana": float(values.median()),
        "Percentil 75": float(values.quantile(0.75)),
        "Máximo": float(values.max()),
        "Asimetría": float(values.skew()) if values.size > 2 else np.nan,
        "Curtosis": float(values.kurtosis()) if values.size > 3 else np.nan,
    }
    return pd.DataFrame(rows.items(), columns=["Estadístico", "Valor"])


def correlation_diagnostics(residuals: object, nlags: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Calcula ACF y PACF con un número seguro de rezagos."""

    from statsmodels.tsa.stattools import acf, pacf

    values = pd.Series(residuals, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    if values.size < 4:
        empty = pd.DataFrame(columns=["Rezago", "Correlación"])
        return empty, empty.copy(), 0
    maximum = max(1, min(36, values.size // 2 - 1))
    used = maximum if nlags is None else max(1, min(int(nlags), maximum))
    acf_values = acf(values, nlags=used, fft=True, missing="drop")
    # ywm es estable y exige menos supuestos que la estimación OLS de la PACF.
    pacf_values = pacf(values, nlags=used, method="ywm")
    acf_frame = pd.DataFrame({"Rezago": np.arange(len(acf_values)), "Correlación": acf_values})
    pacf_frame = pd.DataFrame({"Rezago": np.arange(len(pacf_values)), "Correlación": pacf_values})
    return acf_frame, pacf_frame, used


def residual_diagnostics(
    residuals: object,
    *,
    exog: pd.DataFrame | np.ndarray | None = None,
    influence: Any | None = None,
    ljung_box_lag: int | None = None,
) -> pd.DataFrame:
    """Reúne pruebas estadísticas sin convertir sus p-valores en decisiones automáticas."""

    from scipy.stats import jarque_bera
    from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan
    from statsmodels.stats.stattools import durbin_watson
    from statsmodels.tsa.stattools import adfuller

    values = pd.Series(residuals, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    rows: list[dict[str, Any]] = []

    def add(test: str, statistic: float | None, p_value: float | None, result: str) -> None:
        rows.append(
            {
                "Prueba": test,
                "Estadístico": statistic,
                "p-valor": p_value,
                "Lectura breve": result,
                "Qué evalúa": DIAGNOSTIC_EXPLANATIONS.get(test, ""),
            }
        )

    if values.empty:
        return pd.DataFrame(rows, columns=["Prueba", "Estadístico", "p-valor", "Lectura breve", "Qué evalúa"])
    add("Media residual", float(values.mean()), None, "Revise si está suficientemente cerca de cero para la unidad analizada.")
    if values.size >= 3:
        jb = jarque_bera(values)
        add(
            "Jarque-Bera",
            float(jb.statistic),
            float(jb.pvalue),
            "No se rechaza normalidad." if jb.pvalue >= 0.05 else "Hay evidencia contra normalidad.",
        )
    add(
        "Durbin-Watson",
        float(durbin_watson(values)),
        None,
        "Un valor próximo a 2 sugiere poca autocorrelación de primer orden.",
    )
    if values.size >= 6:
        lag = min(ljung_box_lag or 12, max(1, values.size // 3))
        lb = acorr_ljungbox(values, lags=[lag], return_df=True).iloc[-1]
        add(
            "Ljung-Box",
            float(lb["lb_stat"]),
            float(lb["lb_pvalue"]),
            f"Resultado conjunto hasta el rezago {lag}.",
        )
    if values.size >= 8 and values.nunique() > 1:
        try:
            adf = adfuller(values, autolag="AIC")
            add(
                "ADF",
                float(adf[0]),
                float(adf[1]),
                "Favorece estacionariedad." if adf[1] < 0.05 else "No confirma estacionariedad.",
            )
        except (ValueError, np.linalg.LinAlgError):
            pass
    if exog is not None and values.size >= 5:
        try:
            matrix = np.asarray(exog, dtype=float)
            if matrix.shape[0] == values.size:
                bp = het_breuschpagan(values.to_numpy(), matrix)
                add(
                    "Breusch-Pagan",
                    float(bp[0]),
                    float(bp[1]),
                    "Varianza compatible con homocedasticidad." if bp[1] >= 0.05 else "Hay evidencia de heterocedasticidad.",
                )
        except (ValueError, np.linalg.LinAlgError):
            pass
    if influence is not None:
        try:
            cooks = np.asarray(influence.cooks_distance[0], dtype=float)
            leverage = np.asarray(influence.hat_matrix_diag, dtype=float)
            add("Cook máximo", float(np.nanmax(cooks)), None, "Compare con 4/n como referencia pedagógica.")
            add("Leverage máximo", float(np.nanmax(leverage)), None, "Compare con 2(k+1)/n como referencia pedagógica.")
        except (AttributeError, ValueError, np.linalg.LinAlgError):
            pass
    return pd.DataFrame(rows)

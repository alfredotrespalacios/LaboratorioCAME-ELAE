"""SARIMA para la media y GARCH para la varianza de sus residuales."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from came.errors import DataQualityError, ModelError


@dataclass
class SarimaResult:
    fitted_model: object
    fitted: pd.DataFrame
    forecast: pd.DataFrame
    residuals: pd.DataFrame
    aic: float
    bic: float


@dataclass
class SarimaGarchResult:
    sarima: SarimaResult
    garch_model: object
    volatility_history: pd.DataFrame
    volatility_forecast: pd.DataFrame
    standardized_residuals: pd.DataFrame
    combined_forecast: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def fit_sarima(
    series: pd.Series,
    *,
    order: tuple[int, int, int] = (1, 1, 1),
    seasonal_order: tuple[int, int, int, int] = (0, 1, 1, 12),
    horizon: int = 12,
) -> SarimaResult:
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if len(values) < max(20, seasonal_order[3] + 5):
        raise DataQualityError("La serie es demasiado corta para el SARIMA seleccionado.")
    try:
        model = SARIMAX(
            values,
            order=order,
            seasonal_order=seasonal_order,
            enforce_stationarity=False,
            enforce_invertibility=False,
        ).fit(disp=False)
    except Exception as exc:
        raise ModelError(f"SARIMA no pudo estimarse: {exc}") from exc
    prediction = model.get_forecast(steps=horizon)
    conf_95 = prediction.conf_int(alpha=0.05)
    conf_80 = prediction.conf_int(alpha=0.20)
    forecast_index = np.arange(len(values), len(values) + horizon)
    forecast = pd.DataFrame(
        {
            "paso": forecast_index,
            "media": np.asarray(prediction.predicted_mean, dtype=float),
            "inferior_80": conf_80.iloc[:, 0].to_numpy(dtype=float),
            "superior_80": conf_80.iloc[:, 1].to_numpy(dtype=float),
            "inferior_95": conf_95.iloc[:, 0].to_numpy(dtype=float),
            "superior_95": conf_95.iloc[:, 1].to_numpy(dtype=float),
        }
    )
    fitted_values = np.asarray(model.fittedvalues, dtype=float)
    observed = values.to_numpy(dtype=float)
    residual = observed - fitted_values
    residual_sd = float(np.nanstd(residual, ddof=1))
    residuals = pd.DataFrame(
        {
            "observado": observed,
            "estimado": fitted_values,
            "residual": residual,
            "residual_estandarizado": residual / residual_sd if residual_sd else np.nan,
        },
        index=values.index,
    )
    fitted = residuals[["observado", "estimado"]].copy()
    return SarimaResult(
        fitted_model=model,
        fitted=fitted,
        forecast=forecast,
        residuals=residuals,
        aic=float(model.aic),
        bic=float(model.bic),
    )


def fit_sarima_garch(
    series: pd.Series,
    *,
    sarima_order: tuple[int, int, int] = (1, 1, 1),
    seasonal_order: tuple[int, int, int, int] = (0, 1, 1, 12),
    garch_order: tuple[int, int] = (1, 1),
    distribution: str = "normal",
    horizon: int = 12,
) -> SarimaGarchResult:
    from arch import arch_model

    sarima = fit_sarima(
        series, order=sarima_order, seasonal_order=seasonal_order, horizon=horizon
    )
    residuals = sarima.residuals["residual"].replace([np.inf, -np.inf], np.nan).dropna()
    residuals = residuals.iloc[max(1, seasonal_order[3]) :]
    if len(residuals) < 30:
        raise DataQualityError("Quedan menos de 30 residuales útiles para estimar GARCH.")
    scale = float(residuals.std(ddof=1))
    if scale == 0 or not np.isfinite(scale):
        raise DataQualityError("Los residuales no tienen variación suficiente para GARCH.")
    dist = "t" if distribution.casefold() in {"t", "student", "student-t"} else "normal"
    p, q = garch_order
    try:
        model = arch_model(
            residuals / scale,
            mean="Zero",
            vol="GARCH",
            p=p,
            q=q,
            dist=dist,
            rescale=False,
        ).fit(disp="off")
        forecast = model.forecast(horizon=horizon, reindex=False)
    except Exception as exc:
        raise ModelError(f"GARCH no pudo estimarse: {exc}") from exc

    conditional_volatility = np.asarray(model.conditional_volatility, dtype=float) * scale
    standardized = residuals.to_numpy(dtype=float) / conditional_volatility
    variance_forecast = np.asarray(forecast.variance.iloc[-1], dtype=float) * scale**2
    volatility_forecast = np.sqrt(np.maximum(variance_forecast, 0))
    mean_forecast = sarima.forecast["media"].to_numpy(dtype=float)
    z80 = 1.2815515655446004
    z95 = 1.959963984540054
    combined = sarima.forecast[["paso", "media"]].copy()
    combined["volatilidad_condicional"] = volatility_forecast
    combined["inferior_80_garch"] = mean_forecast - z80 * volatility_forecast
    combined["superior_80_garch"] = mean_forecast + z80 * volatility_forecast
    combined["inferior_95_garch"] = mean_forecast - z95 * volatility_forecast
    combined["superior_95_garch"] = mean_forecast + z95 * volatility_forecast
    return SarimaGarchResult(
        sarima=sarima,
        garch_model=model,
        volatility_history=pd.DataFrame(
            {"volatilidad_condicional": conditional_volatility}, index=residuals.index
        ),
        volatility_forecast=pd.DataFrame(
            {"paso": np.arange(1, horizon + 1), "volatilidad_condicional": volatility_forecast}
        ),
        standardized_residuals=pd.DataFrame(
            {"residual": residuals.to_numpy(), "residual_estandarizado": standardized},
            index=residuals.index,
        ),
        combined_forecast=combined,
        warnings=[
            "SARIMA modela la media; GARCH modela la varianza de los residuales SARIMA.",
            "Las bandas GARCH combinan la media SARIMA con la volatilidad condicional estimada.",
        ],
    )


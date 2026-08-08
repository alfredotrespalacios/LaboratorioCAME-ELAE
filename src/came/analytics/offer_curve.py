"""Curva rápida de oferta y estimadores de precio de bolsa."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from came.errors import DataQualityError


@dataclass
class FitResult:
    model: str
    coefficients: list[float]
    equation: str
    r2: float | None
    estimated_price: float | None
    absolute_error: float | None
    percentage_error: float | None
    warning: str = ""


@dataclass
class OfferCurveResult:
    supply: pd.DataFrame
    fits: list[FitResult]
    marginal_discrete_price: float | None
    marginal_technology: str | None
    total_available_gwh_day: float
    demand_gwh_day: float
    deficit_gwh_day: float
    real_price: float | None


def offer_percentiles(
    frame: pd.DataFrame,
    *,
    technology_column: str = "Tecnología",
    price_column: str = "Precio_COP_kWh",
) -> pd.DataFrame:
    data = frame[[technology_column, price_column]].copy()
    data[price_column] = pd.to_numeric(data[price_column], errors="coerce")
    data = data.dropna(subset=[price_column])
    if data.empty:
        raise DataQualityError("No hay ofertas válidas para calcular percentiles.")
    grouped = data.groupby(technology_column)[price_column]
    result = grouped.quantile([0.05, 0.25, 0.50, 0.75, 0.95]).unstack()
    result.columns = ["P5", "P25", "P50", "P75", "P95"]
    result["Promedio"] = grouped.mean()
    result["n"] = grouped.size()
    return result.reset_index()


def _r2(y: np.ndarray, fitted: np.ndarray) -> float | None:
    denominator = float(np.sum((y - y.mean()) ** 2))
    if denominator == 0:
        return None
    return float(1 - np.sum((y - fitted) ** 2) / denominator)


def _errors(estimate: float | None, real: float | None) -> tuple[float | None, float | None]:
    if estimate is None or real is None or not np.isfinite(real):
        return None, None
    absolute = abs(estimate - real)
    percentage = absolute / abs(real) * 100 if real != 0 else None
    return float(absolute), float(percentage) if percentage is not None else None


def _poly_fit(
    x: np.ndarray,
    y: np.ndarray,
    degree: int,
    demand: float,
    real_price: float | None,
) -> FitResult:
    names = {1: "Lineal", 2: "Cuadrático", 3: "Cúbico"}
    if len(np.unique(x)) <= degree:
        return FitResult(
            names[degree], [], "", None, None, None, None, "Observaciones insuficientes"
        )
    coefficients = np.polyfit(x, y, degree)
    fitted = np.polyval(coefficients, x)
    estimate = float(np.polyval(coefficients, demand))
    absolute, percentage = _errors(estimate, real_price)
    terms: list[str] = []
    for index, coefficient in enumerate(coefficients):
        power = degree - index
        if power == 0:
            terms.append(f"{coefficient:.6g}")
        elif power == 1:
            terms.append(f"{coefficient:.6g}·x")
        else:
            terms.append(f"{coefficient:.6g}·x^{power}")
    return FitResult(
        model=names[degree],
        coefficients=[float(value) for value in coefficients],
        equation="P(x) = " + " + ".join(terms).replace("+ -", "- "),
        r2=_r2(y, fitted),
        estimated_price=estimate,
        absolute_error=absolute,
        percentage_error=percentage,
    )


def _exponential_fit(
    x: np.ndarray,
    y: np.ndarray,
    demand: float,
    real_price: float | None,
) -> FitResult:
    valid = y > 0
    if valid.sum() < 2 or len(np.unique(x[valid])) < 2:
        return FitResult(
            "Exponencial", [], "", None, None, None, None, "Requiere precios positivos"
        )
    alpha, log_a = np.polyfit(x[valid], np.log(y[valid]), 1)
    a = float(np.exp(log_a))
    fitted = a * np.exp(alpha * x[valid])
    estimate = float(a * np.exp(alpha * demand))
    absolute, percentage = _errors(estimate, real_price)
    return FitResult(
        model="Exponencial",
        coefficients=[a, float(alpha)],
        equation=f"P(x) = {a:.6g}·exp({alpha:.6g}·x)",
        r2=_r2(y[valid], fitted),
        estimated_price=estimate,
        absolute_error=absolute,
        percentage_error=percentage,
    )


def build_offer_curve(
    frame: pd.DataFrame,
    *,
    demand_gwh_day: float,
    real_price: float | None = None,
    include_hydraulic: bool = True,
    technology_column: str = "Tecnología",
    availability_column: str = "Disponibilidad_GWh_día",
    price_column: str = "Precio_COP_kWh",
) -> OfferCurveResult:
    required = {technology_column, availability_column, price_column}
    missing = required.difference(frame.columns)
    if missing:
        raise DataQualityError(f"Faltan columnas de la curva: {sorted(missing)}")
    if demand_gwh_day <= 0:
        raise DataQualityError("La demanda debe ser mayor que cero.")
    data = frame.copy()
    data[availability_column] = pd.to_numeric(data[availability_column], errors="coerce")
    data[price_column] = pd.to_numeric(data[price_column], errors="coerce")
    if data[[availability_column, price_column]].isna().any().any():
        raise DataQualityError("Disponibilidad y precio deben ser numéricos.")
    if (data[availability_column] < 0).any():
        raise DataQualityError("La disponibilidad no puede ser negativa.")

    data = data.sort_values([price_column, technology_column], kind="stable").reset_index(drop=True)
    data["Disponibilidad_acumulada_GWh_día"] = data[availability_column].cumsum()
    total = float(data[availability_column].sum())
    deficit = max(float(demand_gwh_day) - total, 0.0)
    marginal = data.loc[data["Disponibilidad_acumulada_GWh_día"] >= demand_gwh_day]
    marginal_price = float(marginal.iloc[0][price_column]) if not marginal.empty else None
    marginal_technology = str(marginal.iloc[0][technology_column]) if not marginal.empty else None

    fit_data = data[data[availability_column] > 0].copy()
    if not include_hydraulic:
        fit_data = fit_data[
            ~fit_data[technology_column].astype(str).str.contains("hidr", case=False, na=False)
        ]
        fit_data["x_fit"] = fit_data[availability_column].cumsum()
        x_column = "x_fit"
    else:
        x_column = "Disponibilidad_acumulada_GWh_día"

    fits: list[FitResult] = []
    if deficit > 0 or fit_data.empty:
        warning = "No existe equilibrio dentro de la oferta disponible."
        for name in ("Lineal", "Cuadrático", "Cúbico", "Exponencial"):
            fits.append(FitResult(name, [], "", None, None, None, None, warning))
    else:
        x = fit_data[x_column].to_numpy(dtype=float)
        y = fit_data[price_column].to_numpy(dtype=float)
        fits.extend(_poly_fit(x, y, degree, demand_gwh_day, real_price) for degree in (1, 2, 3))
        fits.append(_exponential_fit(x, y, demand_gwh_day, real_price))

    return OfferCurveResult(
        supply=data,
        fits=fits,
        marginal_discrete_price=marginal_price,
        marginal_technology=marginal_technology,
        total_available_gwh_day=total,
        demand_gwh_day=float(demand_gwh_day),
        deficit_gwh_day=deficit,
        real_price=float(real_price) if real_price is not None else None,
    )


def sensitivity_table(
    frame: pd.DataFrame,
    *,
    base_demand: float,
    changes_pct: tuple[float, ...] = (-10, -5, 0, 5, 10),
) -> pd.DataFrame:
    rows: list[dict[str, float | str | None]] = []
    for change in changes_pct:
        demand = base_demand * (1 + change / 100)
        result = build_offer_curve(frame, demand_gwh_day=demand)
        row: dict[str, float | str | None] = {
            "Cambio_demanda_pct": change,
            "Demanda_GWh_día": demand,
            "Marginal_discreto": result.marginal_discrete_price,
            "Déficit_GWh_día": result.deficit_gwh_day,
        }
        row.update({fit.model: fit.estimated_price for fit in result.fits})
        rows.append(row)
    return pd.DataFrame(rows)

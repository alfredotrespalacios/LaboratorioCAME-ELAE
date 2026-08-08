"""Generación por tecnología y factores de planta con unidades homogéneas."""

from __future__ import annotations

import numpy as np
import pandas as pd

from came.config import TECHNOLOGY_ORDER, canonical_technology
from came.errors import DataQualityError


def aggregate_generation_by_technology(
    frame: pd.DataFrame,
    *,
    datetime_column: str = "datetime",
    value_column: str = "value",
    technology_column: str = "technology",
    input_unit: str = "kWh",
    frequency: str = "daily",
) -> pd.DataFrame:
    multipliers = {"kWh": 1e-6, "MWh": 1e-3, "GWh": 1.0}
    if input_unit not in multipliers:
        raise ValueError(f"Unidad energética no soportada: {input_unit}")
    if not {datetime_column, value_column, technology_column}.issubset(frame.columns):
        raise DataQualityError("Faltan fecha, valor o tecnología en la generación.")
    data = frame.copy()
    data["datetime"] = pd.to_datetime(data[datetime_column], errors="coerce", utc=True)
    data["value_gwh"] = pd.to_numeric(data[value_column], errors="coerce") * multipliers[input_unit]
    data["technology"] = data[technology_column].map(canonical_technology)
    data = data.dropna(subset=["datetime", "value_gwh"])
    freq = {"daily": "D", "monthly": "MS"}.get(frequency)
    if freq is None:
        raise ValueError("La generación guiada admite frecuencia daily o monthly.")
    result = (
        data.groupby([pd.Grouper(key="datetime", freq=freq), "technology"], observed=True)[
            "value_gwh"
        ]
        .sum()
        .reset_index()
        .rename(columns={"value_gwh": "GWh"})
    )
    result["technology"] = pd.Categorical(
        result["technology"], categories=TECHNOLOGY_ORDER, ordered=True
    )
    if frequency == "monthly":
        result["GWh_día"] = result["GWh"] / result["datetime"].dt.days_in_month
    else:
        result["GWh_día"] = result["GWh"]
    totals = result.groupby("datetime")["GWh"].transform("sum")
    result["participación_pct"] = np.divide(
        result["GWh"], totals, out=np.zeros(len(result), dtype=float), where=totals.to_numpy() != 0
    ) * 100
    return result.sort_values(["datetime", "technology"]).reset_index(drop=True)


def historical_capacity_factor(
    generation_mwh: object,
    capacity_mw: object,
    hours: object,
) -> np.ndarray:
    generation = np.asarray(generation_mwh, dtype=float)
    capacity = np.asarray(capacity_mw, dtype=float)
    hours_values = np.asarray(hours, dtype=float)
    denominator = capacity * hours_values
    factor = np.divide(
        generation,
        denominator,
        out=np.full(np.broadcast_shapes(generation.shape, denominator.shape), np.nan),
        where=denominator > 0,
    )
    return factor


def capacity_factor_statistics(values: object) -> dict[str, float | int | None]:
    series = pd.Series(np.asarray(values, dtype=float)).replace([np.inf, -np.inf], np.nan).dropna()
    if series.empty:
        return {"promedio": None, "P5": None, "P50": None, "mínimo": None, "n": 0}
    return {
        "promedio": float(series.mean()),
        "P5": float(series.quantile(0.05)),
        "P50": float(series.quantile(0.50)),
        "mínimo": float(series.min()),
        "n": int(series.size),
    }


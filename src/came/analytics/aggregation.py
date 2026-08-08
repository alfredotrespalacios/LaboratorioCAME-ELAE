"""Agregación temporal, indicadores de cambio y unión de series."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from came.errors import DataQualityError
from came.quality import safe_divide

FREQUENCY_RULES = {
    "hourly": "h",
    "daily": "D",
    "monthly": "MS",
    "annual": "YS",
}


def aggregate_frame(
    frame: pd.DataFrame,
    *,
    frequency: str,
    rule: str,
    group_columns: Iterable[str] = ("variable_id", "entity_id", "entity_name"),
) -> pd.DataFrame:
    """Agrega observaciones respetando entidad y columnas canónicas disponibles."""

    if frequency not in FREQUENCY_RULES:
        raise ValueError(f"Frecuencia no soportada: {frequency}")
    if rule not in {"sum", "mean", "min", "max", "last"}:
        raise ValueError(f"Regla de agregación no soportada: {rule}")
    if frame.empty:
        return frame.copy()

    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data = data.dropna(subset=["datetime", "value"])
    if data.empty:
        raise DataQualityError("No hay observaciones válidas para agregar.")

    groups = [col for col in group_columns if col in data.columns]
    freq = FREQUENCY_RULES[frequency]
    grouper = pd.Grouper(key="datetime", freq=freq)
    by = groups + [grouper]
    result = data.groupby(by, dropna=False, observed=True)["value"].agg(rule).reset_index()

    preserved = [
        "country",
        "source",
        "dataset",
        "variable_name",
        "entity_type",
        "unit",
        "quality_status",
        "retrieved_at",
    ]
    for column in preserved:
        if column in data.columns and column not in result.columns:
            result[column] = data[column].dropna().iloc[0] if data[column].notna().any() else pd.NA
    result["frequency"] = frequency
    result["aggregation"] = rule
    return result.sort_values(groups + ["datetime"], kind="stable").reset_index(drop=True)


def add_change_columns(
    frame: pd.DataFrame,
    *,
    value_column: str = "value",
    frequency: str = "monthly",
) -> pd.DataFrame:
    """Añade cambios de un periodo y de un año sin mezclar frecuencias."""

    data = frame.sort_values("datetime").copy()
    prior_year = {"monthly": 12, "daily": 365, "hourly": 24 * 365, "annual": 1}.get(frequency, 12)
    values = pd.to_numeric(data[value_column], errors="coerce")
    data["cambio_periodo_nivel"] = values.diff(1)
    data["cambio_periodo_pct"] = values.pct_change(1, fill_method=None) * 100
    data["cambio_anual_nivel"] = values.diff(prior_year)
    data["cambio_anual_pct"] = values.pct_change(prior_year, fill_method=None) * 100
    return data


def add_price_returns(
    frame: pd.DataFrame,
    *,
    value_column: str = "value",
) -> pd.DataFrame:
    """Añade rendimiento simple y logarítmico entre observaciones consecutivas."""

    data = frame.sort_values("datetime").copy()
    prices = pd.to_numeric(data[value_column], errors="coerce")
    previous = prices.shift(1)
    data["Variación_porcentual_pct"] = prices.pct_change(fill_method=None) * 100
    valid_log = prices.gt(0) & previous.gt(0)
    data["Rendimiento_logarítmico_pct"] = np.nan
    data.loc[valid_log, "Rendimiento_logarítmico_pct"] = (
        np.log(prices[valid_log] / previous[valid_log]) * 100
    )
    return data


def summary_indicators(frame: pd.DataFrame, value_column: str = "value") -> dict[str, float | None]:
    values = pd.to_numeric(frame[value_column], errors="coerce").dropna()
    if values.empty:
        return {key: None for key in ("último", "promedio", "desviación", "mínimo", "máximo")}
    result: dict[str, float | None] = {
        "último": float(values.iloc[-1]),
        "promedio": float(values.mean()),
        "desviación": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        "mínimo": float(values.min()),
        "máximo": float(values.max()),
    }
    if len(values) > 1:
        result["variación_periodo_pct"] = (
            float((values.iloc[-1] / values.iloc[-2] - 1) * 100) if values.iloc[-2] else None
        )
    if len(values) > 12:
        result["variación_anual_pct"] = (
            float((values.iloc[-1] / values.iloc[-13] - 1) * 100) if values.iloc[-13] else None
        )
    return result


def canonical_to_wide(frames: Iterable[pd.DataFrame], names: Iterable[str]) -> pd.DataFrame:
    """Alinea series por fecha e informa faltantes mediante valores NaN visibles."""

    merged: pd.DataFrame | None = None
    for frame, name in zip(frames, names, strict=True):
        part = frame[["datetime", "value"]].copy()
        part["datetime"] = pd.to_datetime(part["datetime"], errors="coerce", utc=True)
        part = part.dropna(subset=["datetime"]).groupby("datetime", as_index=False)["value"].mean()
        part = part.rename(columns={"value": name})
        merged = part if merged is None else merged.merge(part, on="datetime", how="outer")
    if merged is None:
        return pd.DataFrame(columns=["datetime"])
    return merged.sort_values("datetime").reset_index(drop=True)


def add_time_and_enso(frame: pd.DataFrame, enso_column: str | None = None) -> pd.DataFrame:
    data = frame.sort_values("datetime").reset_index(drop=True).copy()
    data["Tiempo"] = np.arange(1, len(data) + 1)
    if enso_column and enso_column in data:
        enso = pd.to_numeric(data[enso_column], errors="coerce")
        data["Niño"] = (enso >= 0.5).astype("Int64")
        data["Niña"] = (enso <= -0.5).astype("Int64")
    return data


def generation_non_hydraulic(
    demand: pd.Series | np.ndarray,
    hydraulic_generation: pd.Series | np.ndarray,
) -> np.ndarray:
    """Demanda menos generación hidráulica, ambas en la misma unidad energética."""

    demand_values = np.asarray(demand, dtype=float)
    hydro_values = np.asarray(hydraulic_generation, dtype=float)
    if demand_values.shape != hydro_values.shape:
        raise ValueError("Demanda y generación hidráulica deben tener la misma forma.")
    return demand_values - hydro_values


def weighted_price(price: object, demand: object) -> float:
    prices = np.asarray(price, dtype=float)
    demands = np.asarray(demand, dtype=float)
    valid = np.isfinite(prices) & np.isfinite(demands) & (demands >= 0)
    if not valid.any() or demands[valid].sum() == 0:
        raise DataQualityError("No existe demanda válida para ponderar el precio.")
    return float(np.sum(prices[valid] * demands[valid]) / np.sum(demands[valid]))


def growth_rate(numerator: object, denominator: object) -> np.ndarray:
    return (safe_divide(numerator, denominator) - 1) * 100

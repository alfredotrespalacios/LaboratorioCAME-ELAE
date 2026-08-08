"""Balance energético rápido para Colombia."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from came.config import BALANCE_DEFAULTS, TECHNOLOGY_ORDER
from came.errors import DataQualityError


@dataclass
class BalanceResult:
    table: pd.DataFrame
    generation_available_gwh_day: float
    demand_gwh_day: float
    margin: float
    uncovered_demand_gwh_day: float
    uncovered_demand_pct: float
    generation_demand_ratio: float


def generation_available_gwh_day(capacity_mw: object, plant_factor: object) -> np.ndarray:
    capacity = np.asarray(capacity_mw, dtype=float)
    factor = np.asarray(plant_factor, dtype=float)
    return capacity * factor * 24 / 1000


def build_default_balance_table(capacity_by_technology: dict[str, float]) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    ordered = list(dict.fromkeys(TECHNOLOGY_ORDER + list(capacity_by_technology)))
    for technology in ordered:
        if technology not in capacity_by_technology:
            continue
        normal, nino = BALANCE_DEFAULTS.get(technology, (0.90, 0.90))
        rows.append(
            {
                "Tecnología": technology,
                "CEN_MW": float(capacity_by_technology[technology]),
                "FP_normal": normal,
                "FP_nino": nino,
            }
        )
    return pd.DataFrame(rows)


def calculate_balance(
    table: pd.DataFrame,
    *,
    demand_gwh_day: float,
    factor_column: str,
    capacity_column: str = "CEN_MW",
) -> BalanceResult:
    if demand_gwh_day <= 0:
        raise DataQualityError("La demanda debe ser mayor que cero.")
    required = {"Tecnología", capacity_column, factor_column}
    missing = required.difference(table.columns)
    if missing:
        raise DataQualityError(f"Faltan columnas del balance: {sorted(missing)}")
    data = table.copy()
    data[capacity_column] = pd.to_numeric(data[capacity_column], errors="coerce")
    data[factor_column] = pd.to_numeric(data[factor_column], errors="coerce")
    if data[[capacity_column, factor_column]].isna().any().any():
        raise DataQualityError("Capacidad y factor de planta deben ser numéricos.")
    if (data[capacity_column] < 0).any():
        raise DataQualityError("La capacidad no puede ser negativa.")
    if ((data[factor_column] < 0) | (data[factor_column] > 1)).any():
        raise DataQualityError("El factor de planta debe estar entre 0 y 1.")

    data["Generación_disponible_GWh_día"] = generation_available_gwh_day(
        data[capacity_column], data[factor_column]
    )
    total = float(data["Generación_disponible_GWh_día"].sum())
    margin = total / demand_gwh_day - 1
    uncovered = max(demand_gwh_day - total, 0.0)
    return BalanceResult(
        table=data,
        generation_available_gwh_day=total,
        demand_gwh_day=float(demand_gwh_day),
        margin=float(margin),
        uncovered_demand_gwh_day=float(uncovered),
        uncovered_demand_pct=float(uncovered / demand_gwh_day * 100),
        generation_demand_ratio=float(total / demand_gwh_day),
    )


def years_until_zero_margin(current_demand: float, available_generation: float, growth: float) -> float:
    if current_demand <= 0 or available_generation <= 0:
        raise DataQualityError("Demanda y generación deben ser positivas.")
    if current_demand >= available_generation:
        return 0.0
    if growth <= 0:
        return float("inf")
    return float(np.log(available_generation / current_demand) / np.log1p(growth))


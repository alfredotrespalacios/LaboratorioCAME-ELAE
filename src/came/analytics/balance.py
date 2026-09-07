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
    availability_gwh_day: float
    demand_gwh_day: float
    margin: float
    uncovered_demand_gwh_day: float
    uncovered_demand_pct: float
    generation_demand_ratio: float

    @property
    def generation_available_gwh_day(self) -> float:
        """Alias conservado para compatibilidad con resultados de versiones anteriores."""

        return self.availability_gwh_day


def generation_available_gwh_day(capacity_mw: object, plant_factor: object) -> np.ndarray:
    capacity = np.asarray(capacity_mw, dtype=float)
    factor = np.asarray(plant_factor, dtype=float)
    return capacity * factor * 24 / 1000


def weighted_plant_factor(capacity_mw: object, plant_factor: object) -> float:
    """Promedia el factor de planta ponderándolo por la CEN de cada tecnología."""

    capacity = np.asarray(capacity_mw, dtype=float)
    factor = np.asarray(plant_factor, dtype=float)
    total_capacity = float(np.nansum(capacity))
    if total_capacity <= 0:
        return 0.0
    return float(np.nansum(capacity * factor) / total_capacity)


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

    data["Disponibilidad_GWh_día"] = generation_available_gwh_day(
        data[capacity_column], data[factor_column]
    )
    total = float(data["Disponibilidad_GWh_día"].sum())
    margin = total / demand_gwh_day - 1
    uncovered = max(demand_gwh_day - total, 0.0)
    return BalanceResult(
        table=data,
        availability_gwh_day=total,
        demand_gwh_day=float(demand_gwh_day),
        margin=float(margin),
        uncovered_demand_gwh_day=float(uncovered),
        uncovered_demand_pct=float(uncovered / demand_gwh_day * 100),
        generation_demand_ratio=float(total / demand_gwh_day),
    )


def years_until_zero_margin(
    current_demand: float, available_generation: float, growth: float
) -> float:
    if current_demand <= 0 or available_generation <= 0:
        raise DataQualityError("Demanda y generación deben ser positivas.")
    if current_demand >= available_generation:
        return 0.0
    if growth <= 0:
        return float("inf")
    return float(np.log(available_generation / current_demand) / np.log1p(growth))


def build_balance_comparison(
    table: pd.DataFrame,
    *,
    first_name: str,
    first_demand_gwh_day: float,
    second_name: str,
    second_demand_gwh_day: float,
    first_factor_column: str = "FP_normal",
    second_factor_column: str = "FP_nino",
) -> pd.DataFrame:
    """Crea la tabla comparativa y agrega una fila total verificable."""

    first_name = str(first_name).strip() or "Escenario 1"
    second_name = str(second_name).strip() or "Escenario 2"
    first = calculate_balance(
        table,
        demand_gwh_day=first_demand_gwh_day,
        factor_column=first_factor_column,
    )
    second = calculate_balance(
        table,
        demand_gwh_day=second_demand_gwh_day,
        factor_column=second_factor_column,
    )
    capacity = pd.to_numeric(first.table["CEN_MW"], errors="coerce").fillna(0.0)
    first_availability = first.table["Disponibilidad_GWh_día"].astype(float)
    second_availability = second.table["Disponibilidad_GWh_día"].astype(float)
    first_factor = first.table[first_factor_column].astype(float)
    second_factor = second.table[second_factor_column].astype(float)

    first_fp_col = f"FP · {first_name}"
    first_availability_col = f"Disponibilidad · {first_name} (GWh-día)"
    first_share_col = f"Participación · {first_name} (%)"
    first_demand_col = f"Demanda · {first_name} (GWh-día)"
    second_fp_col = f"FP · {second_name}"
    second_availability_col = f"Disponibilidad · {second_name} (GWh-día)"
    second_share_col = f"Participación · {second_name} (%)"
    second_demand_col = f"Demanda · {second_name} (GWh-día)"

    comparison = pd.DataFrame(
        {
            "Tecnología": first.table["Tecnología"].astype(str),
            "CEN_MW": capacity,
            first_fp_col: first_factor,
            first_availability_col: first_availability,
            first_share_col: (
                first_availability / first.availability_gwh_day * 100
                if first.availability_gwh_day > 0
                else 0.0
            ),
            first_demand_col: float(first_demand_gwh_day),
            second_fp_col: second_factor,
            second_availability_col: second_availability,
            second_share_col: (
                second_availability / second.availability_gwh_day * 100
                if second.availability_gwh_day > 0
                else 0.0
            ),
            second_demand_col: float(second_demand_gwh_day),
        }
    )
    total = pd.DataFrame(
        [
            {
                "Tecnología": "Total",
                "CEN_MW": float(capacity.sum()),
                first_fp_col: weighted_plant_factor(capacity, first_factor),
                first_availability_col: first.availability_gwh_day,
                first_share_col: 100.0 if first.availability_gwh_day > 0 else 0.0,
                first_demand_col: float(first_demand_gwh_day),
                second_fp_col: weighted_plant_factor(capacity, second_factor),
                second_availability_col: second.availability_gwh_day,
                second_share_col: 100.0 if second.availability_gwh_day > 0 else 0.0,
                second_demand_col: float(second_demand_gwh_day),
            }
        ]
    )
    return pd.concat([comparison, total], ignore_index=True)

"""Demanda nacional y demanda no atendida sin doble conteo jerárquico."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from came.analytics.aggregation import add_change_columns
from came.errors import DataQualityError

ENERGY_TO_GWH = {
    "kWh": 1e-6,
    "MWh": 1e-3,
    "GWh": 1.0,
}


@dataclass
class UnservedDemandResult:
    monthly: pd.DataFrame
    hierarchy_audit: pd.DataFrame
    warnings: list[str]


def _normalize_level(value: object) -> str:
    text = str(value or "").casefold()
    if "sub" in text:
        return "subárea"
    if "area" in text or "área" in text:
        return "área"
    return "desconocido"


def deduplicate_unserved_demand(
    frame: pd.DataFrame,
    *,
    input_unit: str = "kWh",
    datetime_column: str = "datetime",
    value_column: str = "value",
    level_column: str = "level",
    type_column: str = "interruption_type",
    entity_column: str = "entity_name",
) -> UnservedDemandResult:
    """Prioriza el total de área y usa subáreas solo cuando el área no está publicada.

    Área y subárea son jerarquías alternativas del mismo fenómeno. Sumarlas entre sí duplicaría la
    energía. El reporte de auditoría conserva ambos totales cuando coexisten para que el usuario
    pueda revisar su diferencia.
    """

    if input_unit not in ENERGY_TO_GWH:
        raise ValueError(f"Unidad no soportada para demanda no atendida: {input_unit}")
    required = {datetime_column, value_column, level_column, type_column}
    missing = required.difference(frame.columns)
    if missing:
        raise DataQualityError(f"Faltan columnas para evitar doble conteo: {sorted(missing)}")

    data = frame.copy()
    data["datetime"] = pd.to_datetime(data[datetime_column], errors="coerce", utc=True)
    data["value"] = pd.to_numeric(data[value_column], errors="coerce")
    data["level"] = data[level_column].map(_normalize_level)
    data["interruption_type"] = data[type_column].fillna("sin clasificar").astype(str)
    if entity_column in data:
        data["entity_name"] = data[entity_column].fillna("sin entidad").astype(str)
    else:
        data["entity_name"] = "sin entidad"
    data = data.dropna(subset=["datetime", "value"])
    if data.empty:
        raise DataQualityError("No hay observaciones válidas de demanda no atendida.")

    before = len(data)
    data = data.drop_duplicates(
        subset=["datetime", "interruption_type", "level", "entity_name", "value"]
    )
    exact_duplicates = before - len(data)

    selected_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    for (timestamp, interruption_type), group in data.groupby(
        ["datetime", "interruption_type"], dropna=False, sort=True
    ):
        area = group.loc[group["level"] == "área", "value"]
        subarea = group.loc[group["level"] == "subárea", "value"]
        area_total = float(area.sum()) if not area.empty else np.nan
        subarea_total = float(subarea.sum()) if not subarea.empty else np.nan
        if not area.empty:
            selected = area_total
            hierarchy = "área"
        elif not subarea.empty:
            selected = subarea_total
            hierarchy = "subárea"
        else:
            selected = float(group["value"].sum())
            hierarchy = "desconocido"
        relative_gap = (
            abs(area_total - subarea_total) / abs(area_total)
            if np.isfinite(area_total) and np.isfinite(subarea_total) and area_total != 0
            else np.nan
        )
        selected_rows.append(
            {
                "datetime": timestamp,
                "interruption_type": interruption_type,
                "selected_value": selected,
                "selected_hierarchy": hierarchy,
            }
        )
        audit_rows.append(
            {
                "datetime": timestamp,
                "interruption_type": interruption_type,
                "area_total": area_total,
                "subarea_total": subarea_total,
                "selected_hierarchy": hierarchy,
                "relative_gap": relative_gap,
            }
        )

    selected = pd.DataFrame(selected_rows)
    selected["GWh"] = selected["selected_value"] * ENERGY_TO_GWH[input_unit]
    selected["month"] = (
        selected["datetime"]
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
        .dt.to_period("M")
        .dt.to_timestamp()
        .dt.tz_localize("UTC")
    )
    monthly = (
        selected.groupby("month", as_index=False)["GWh"].sum().rename(columns={"month": "datetime"})
    )
    monthly["días_calendario"] = monthly["datetime"].dt.days_in_month
    monthly["GWh_día"] = monthly["GWh"] / monthly["días_calendario"]
    monthly = add_change_columns(monthly, value_column="GWh_día", frequency="monthly")

    audit = pd.DataFrame(audit_rows)
    warnings: list[str] = []
    if exact_duplicates:
        warnings.append(f"Se excluyeron {exact_duplicates} registros exactamente duplicados.")
    both = audit["area_total"].notna() & audit["subarea_total"].notna()
    if both.any():
        warnings.append(
            "Área y subárea coexistían en parte de la historia; se usó área como total y subárea "
            "solo como verificación, evitando sumarlas entre sí."
        )
    large_gap = both & (audit["relative_gap"] > 0.05)
    if large_gap.any():
        warnings.append(
            f"En {int(large_gap.sum())} fechas la suma de subáreas difiere más de 5 % del total de área."
        )
    if (audit["selected_hierarchy"] == "desconocido").any():
        warnings.append(
            "Algunas observaciones no tenían jerarquía identificable; revise la auditoría."
        )
    return UnservedDemandResult(monthly=monthly, hierarchy_audit=audit, warnings=warnings)


def demand_served(demand_gwh_day: object, unserved_gwh_day: object) -> np.ndarray:
    demand = np.asarray(demand_gwh_day, dtype=float)
    unserved = np.asarray(unserved_gwh_day, dtype=float)
    return demand - unserved

"""Generación por tecnología y factores de planta con unidades homogéneas."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from came.config import TECHNOLOGY_ORDER, canonical_technology
from came.errors import DataQualityError


@dataclass
class GenerationMonthlyHistory:
    """Tablas mensuales completas derivadas de una misma consulta Gene/Recurso."""

    by_resource: pd.DataFrame
    by_company: pd.DataFrame
    by_technology: pd.DataFrame
    resource_catalog: pd.DataFrame
    validation: pd.DataFrame


def aggregate_generation_monthly_history(frame: pd.DataFrame) -> GenerationMonthlyHistory:
    """Reduce la generación horaria a meses sin perder recursos ni metadatos.

    La selección que se haga después en la interfaz no afecta estas tablas. Los recursos sin
    empresa o tecnología identificada se conservan en categorías explícitas para que los totales
    mensuales sean conciliables.
    """

    required = {"datetime", "value", "entity_id"}
    if not required.issubset(frame.columns):
        raise DataQualityError("Faltan fecha, valor o código de recurso en la generación.")

    optional_defaults = {
        "resource_name": frame.get("entity_name", frame["entity_id"]),
        "company_code": "NO_IDENTIFICADO",
        "company_name": "Sin agente identificado",
        "technology": "Otras",
    }
    columns = ["datetime", "value", "entity_id"] + [
        column for column in optional_defaults if column in frame.columns
    ]
    data = frame[columns].copy()
    for column, default in optional_defaults.items():
        if column not in data:
            data[column] = default

    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data = data.dropna(subset=["datetime", "value", "entity_id"])
    if data.empty:
        raise DataQualityError("La consulta no contiene generación útil para agregar mensualmente.")

    # El mes se define en la zona de operación de XM; la marca UTC resultante es solo una etiqueta.
    local_datetime = data["datetime"].dt.tz_convert("America/Bogota").dt.tz_localize(None)
    data["datetime"] = local_datetime.dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC")
    data["resource_code"] = data["entity_id"].astype("string").fillna("NO_IDENTIFICADO")
    for column, missing_label in (
        ("resource_name", "Sin nombre de recurso"),
        ("company_code", "NO_IDENTIFICADO"),
        ("company_name", "Sin agente identificado"),
        ("technology", "Otras"),
    ):
        data[column] = data[column].astype("string").fillna(missing_label).str.strip()
        data.loc[data[column].eq(""), column] = missing_label

    def aggregate(keys: list[str]) -> pd.DataFrame:
        result = (
            data.groupby(["datetime", *keys], as_index=False, observed=True, dropna=False)["value"]
            .sum()
            .rename(columns={"value": "GWh_mes"})
        )
        result["GWh_día"] = result["GWh_mes"] / result["datetime"].dt.days_in_month
        return result.sort_values(["datetime", *keys], kind="stable").reset_index(drop=True)

    by_resource = aggregate(
        [
            "resource_code",
            "resource_name",
            "company_code",
            "company_name",
            "technology",
        ]
    )
    by_company = aggregate(["company_code", "company_name"])
    by_technology = aggregate(["technology"])
    resource_catalog = (
        by_resource[
            [
                "resource_code",
                "resource_name",
                "company_code",
                "company_name",
                "technology",
            ]
        ]
        .drop_duplicates()
        .sort_values(["resource_name", "resource_code"], kind="stable")
        .reset_index(drop=True)
    )

    resource_totals = (
        by_resource.groupby("datetime", as_index=False)["GWh_mes"]
        .sum()
        .rename(columns={"GWh_mes": "GWh_recursos"})
    )
    company_totals = (
        by_company.groupby("datetime", as_index=False)["GWh_mes"]
        .sum()
        .rename(columns={"GWh_mes": "GWh_empresas"})
    )
    technology_totals = (
        by_technology.groupby("datetime", as_index=False)["GWh_mes"]
        .sum()
        .rename(columns={"GWh_mes": "GWh_tecnologías"})
    )
    validation = resource_totals.merge(company_totals, on="datetime", how="outer").merge(
        technology_totals, on="datetime", how="outer"
    )
    validation["Diferencia_empresas_GWh"] = validation["GWh_empresas"] - validation["GWh_recursos"]
    validation["Diferencia_tecnologías_GWh"] = (
        validation["GWh_tecnologías"] - validation["GWh_recursos"]
    )
    tolerance = validation["GWh_recursos"].abs().mul(1e-9).clip(lower=1e-9)
    validation["Estado"] = np.where(
        validation["Diferencia_empresas_GWh"].abs().le(tolerance)
        & validation["Diferencia_tecnologías_GWh"].abs().le(tolerance),
        "Conciliado",
        "Revisar",
    )

    return GenerationMonthlyHistory(
        by_resource=by_resource,
        by_company=by_company,
        by_technology=by_technology,
        resource_catalog=resource_catalog,
        validation=validation.sort_values("datetime").reset_index(drop=True),
    )


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
    result["participación_pct"] = (
        np.divide(
            result["GWh"],
            totals,
            out=np.zeros(len(result), dtype=float),
            where=totals.to_numpy() != 0,
        )
        * 100
    )
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

"""Servicios guiados de Colombia construidos sobre el catálogo vivo de XM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from came.analytics.aggregation import (
    add_change_columns,
    add_price_returns,
    add_time_and_enso,
    generation_non_hydraulic,
)
from came.analytics.demand import UnservedDemandResult, deduplicate_unserved_demand
from came.analytics.generation import aggregate_generation_by_technology
from came.config import canonical_technology
from came.data.providers.macro import MacroProvider
from came.data.providers.xm import XMProvider
from came.errors import SourceUnavailableError


@dataclass
class IntegratedMarketResult:
    data: pd.DataFrame
    status: pd.DataFrame
    methodologies: list[str]
    warnings: list[str] = field(default_factory=list)


def _local_period_start(values: pd.Series, frequency: str) -> pd.Series:
    """Convierte instantes UTC al inicio del día o mes civil de Colombia."""

    local = pd.to_datetime(values, errors="coerce", utc=True).dt.tz_convert("America/Bogota")
    naive = local.dt.tz_localize(None)
    if frequency == "daily":
        period = naive.dt.floor("D")
    elif frequency == "monthly":
        period = naive.dt.to_period("M").dt.to_timestamp()
    else:
        raise ValueError(f"Frecuencia local no soportada: {frequency}")
    return period.dt.tz_localize("UTC")


def resource_catalog(provider: XMProvider) -> pd.DataFrame:
    resources = provider.fetch_list("ListadoRecursos", "Sistema")
    if resources.empty:
        return pd.DataFrame(
            columns=[
                "resource_code",
                "resource_name",
                "technology",
                "company_code",
                "energy_source",
            ]
        )
    rename = {
        "Code": "resource_code",
        "code": "resource_code",
        "Name": "resource_name",
        "Value": "resource_name",
        "Type": "resource_type",
        "CompanyCode": "company_code",
        "EnerSource": "energy_source",
        "State": "state",
    }
    data = resources.rename(
        columns={key: value for key, value in rename.items() if key in resources}
    )
    if "resource_code" not in data:
        data["resource_code"] = data.get("Entity", pd.NA)
    if "resource_name" not in data:
        data["resource_name"] = data["resource_code"]
    if "energy_source" not in data:
        data["energy_source"] = data.get("resource_type", "")
    data["technology"] = data["energy_source"].map(canonical_technology)
    return data.drop_duplicates("resource_code").reset_index(drop=True)


def agent_catalog(provider: XMProvider) -> pd.DataFrame:
    agents = provider.fetch_list("ListadoAgentes", "Sistema")
    rename = {
        "Code": "company_code",
        "code": "company_code",
        "Name": "company_name",
        "Value": "company_name",
    }
    data = agents.rename(columns={key: value for key, value in rename.items() if key in agents})
    if "company_code" not in data:
        data["company_code"] = data.get("Entity", pd.NA)
    if "company_name" not in data:
        data["company_name"] = data["company_code"]
    return (
        data.dropna(subset=["company_code"]).drop_duplicates("company_code").reset_index(drop=True)
    )


def attach_resource_metadata(frame: pd.DataFrame, resources: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["entity_id"] = data["entity_id"].astype(str)
    merged = data.merge(resources, left_on="entity_id", right_on="resource_code", how="left")
    merged["resource_name"] = merged["resource_name"].fillna(merged["entity_id"])
    merged["entity_name"] = merged["resource_name"]
    merged["technology"] = merged["technology"].fillna("Otras")
    return merged


def spot_price(provider: XMProvider, start: object, end: object, frequency: str) -> pd.DataFrame:
    raw = provider.fetch("PrecBolsNaci", "Sistema", start, end)
    data = raw.data[["datetime", "value"]].copy()
    data["datetime"] = _local_period_start(data["datetime"], frequency)
    result = data.groupby("datetime", as_index=False)["value"].mean()
    result = add_change_columns(result, frequency=frequency)
    return add_price_returns(result)


def national_demand(
    provider: XMProvider, start: object, end: object, frequency: str
) -> pd.DataFrame:
    raw = provider.fetch("DemaSIN", "Sistema", start, end, target_unit="GWh")
    available_columns = [column for column in ("datetime", "value", "period") if column in raw.data]
    data = raw.data[available_columns].copy()
    local = pd.to_datetime(data["datetime"], errors="coerce", utc=True).dt.tz_convert(
        "America/Bogota"
    )
    data["día_local"] = local.dt.tz_localize(None).dt.floor("D")
    daily = (
        data.groupby("día_local", as_index=False)["value"]
        .agg(GWh_día="sum", intervalos_recibidos="count")
        .sort_values("día_local")
    )

    source_frequency = getattr(raw.meta, "frequency", "hourly")
    expected_intervals = 1
    if source_frequency == "hourly":
        maximum_period = (
            pd.to_numeric(data["period"], errors="coerce").max()
            if "period" in data
            else pd.NA
        )
        expected_intervals = max(24, int(maximum_period)) if pd.notna(maximum_period) else 24
    daily["intervalos_esperados"] = expected_intervals
    daily["día_completo"] = daily["intervalos_recibidos"].ge(expected_intervals)
    daily["datetime"] = pd.to_datetime(daily["día_local"]).dt.tz_localize("UTC")

    excluded_days = daily.loc[~daily["día_completo"], "datetime"].tolist()
    complete_daily = daily[daily["día_completo"]].copy()
    if frequency == "daily":
        result = complete_daily[
            ["datetime", "GWh_día", "intervalos_recibidos", "intervalos_esperados"]
        ].copy()
        result["value"] = result["GWh_día"]
    else:
        complete_daily["datetime"] = _local_period_start(complete_daily["datetime"], "monthly")
        monthly = complete_daily.groupby("datetime", as_index=False).agg(
            GWh_mes=("GWh_día", "sum"),
            días_recibidos=("día_local", "nunique"),
        )
        monthly["días_esperados"] = monthly["datetime"].dt.days_in_month
        complete_months = monthly["días_recibidos"].eq(monthly["días_esperados"])
        excluded_months = monthly.loc[~complete_months, "datetime"].tolist()
        result = monthly[complete_months].copy()
        result["GWh_día"] = result["GWh_mes"] / result["días_esperados"]
        result["value"] = result["GWh_mes"]
        excluded_days.extend(excluded_months)
    result = add_change_columns(result, value_column="GWh_día", frequency=frequency)
    result.attrs["excluded_incomplete_periods"] = excluded_days
    result.attrs["last_complete_period"] = (
        pd.to_datetime(result["datetime"], utc=True).max() if not result.empty else None
    )
    result.attrs["expected_intervals_per_day"] = expected_intervals
    return result


def generation_resources(
    provider: XMProvider,
    start: object,
    end: object,
    resources: pd.DataFrame | None = None,
) -> pd.DataFrame:
    resources = resource_catalog(provider) if resources is None else resources
    raw = provider.fetch("Gene", "Recurso", start, end, target_unit="GWh")
    return attach_resource_metadata(raw.data, resources)


def generation_by_technology(
    provider: XMProvider,
    start: object,
    end: object,
    frequency: str,
    resources: pd.DataFrame | None = None,
) -> pd.DataFrame:
    data = generation_resources(provider, start, end, resources)
    # Cada HourXX representa energía del intervalo; se suma por día/mes.
    return aggregate_generation_by_technology(
        data,
        datetime_column="datetime",
        value_column="value",
        technology_column="technology",
        input_unit="GWh",
        frequency=frequency,
    )


def capacity_by_technology(
    provider: XMProvider,
    selected_date: object,
    resources: pd.DataFrame | None = None,
    lookback_days: int = 45,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    resources = resource_catalog(provider) if resources is None else resources
    selected = pd.Timestamp(selected_date).normalize()
    selected_utc = (
        selected.tz_localize("UTC") if selected.tzinfo is None else selected.tz_convert("UTC")
    )
    raw = provider.fetch(
        "CapEfecNeta",
        "Recurso",
        selected - pd.Timedelta(days=lookback_days),
        selected,
        target_unit="MW",
    )
    if raw.data.empty:
        raise SourceUnavailableError("XM no publicó CEN dentro del periodo de búsqueda anterior.")
    dates = pd.to_datetime(raw.data["datetime"], utc=True).dt.normalize()
    effective = dates[dates <= selected_utc].max()
    selected_data = raw.data.loc[dates == effective].copy()
    selected_data = attach_resource_metadata(selected_data, resources)
    result = (
        selected_data.groupby("technology", as_index=False)["value"]
        .sum()
        .rename(columns={"technology": "Tecnología", "value": "CEN_MW"})
    )
    return result, pd.Timestamp(effective)


def unserved_demand(provider: XMProvider, start: object, end: object) -> UnservedDemandResult:
    frames: list[pd.DataFrame] = []
    for metric_id, interruption_type in (
        ("DemaNoAtenProg", "Programada"),
        ("DemaNoAtenNoProg", "No programada"),
    ):
        for entity, level in (("Area", "Área"), ("Subarea", "Subárea")):
            result = provider.fetch(metric_id, entity, start, end)
            part = result.data[["datetime", "value", "entity_name"]].copy()
            part["level"] = level
            part["interruption_type"] = interruption_type
            frames.append(part)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return deduplicate_unserved_demand(combined, input_unit="kWh")


def offers_by_technology(
    provider: XMProvider,
    start: object,
    end: object,
    resources: pd.DataFrame | None = None,
) -> pd.DataFrame:
    resources = resource_catalog(provider) if resources is None else resources
    raw = provider.fetch("PrecOferDesp", "Recurso", start, end)
    return attach_resource_metadata(raw.data, resources).rename(
        columns={"technology": "Tecnología", "value": "Precio_COP_kWh"}
    )


def build_integrated_market(
    provider: XMProvider,
    start: object,
    end: object,
    *,
    include_macro: bool = True,
    macro_provider: MacroProvider | None = None,
) -> IntegratedMarketResult:
    """Actualiza una canasta mensual tolerante a fallas y conserva el estado por columna."""

    series: list[pd.DataFrame] = []
    status_rows: list[dict[str, object]] = []
    methodologies: list[str] = []
    warnings: list[str] = []

    def add(name: str, unit: str, loader: Callable[[], pd.DataFrame], value_column: str) -> None:
        try:
            frame = loader()
            part = frame[["datetime", value_column]].rename(columns={value_column: name})
            part["datetime"] = pd.to_datetime(part["datetime"], utc=True)
            series.append(part)
            status_rows.append(
                {
                    "Variable": name,
                    "Estado": "Disponible",
                    "Unidad": unit,
                    "Observaciones": len(part),
                    "Inicio": part["datetime"].min(),
                    "Fin": part["datetime"].max(),
                }
            )
        except Exception as exc:
            status_rows.append(
                {"Variable": name, "Estado": "No disponible", "Unidad": unit, "Detalle": str(exc)}
            )
            warnings.append(f"{name}: {exc}")

    add(
        "Precio_bolsa_COP_kWh",
        "COP/kWh",
        lambda: spot_price(provider, start, end, "monthly"),
        "value",
    )
    add(
        "Demanda_GWh_día",
        "GWh-día",
        lambda: national_demand(provider, start, end, "monthly"),
        "GWh_día",
    )
    resources = resource_catalog(provider)
    generation = None
    try:
        generation = generation_by_technology(provider, start, end, "monthly", resources)
        for technology in sorted(generation["technology"].astype(str).unique()):
            part = generation[generation["technology"].astype(str) == technology][
                ["datetime", "GWh_día"]
            ].rename(columns={"GWh_día": f"Generación_{technology}_GWh_día"})
            series.append(part)
            status_rows.append(
                {
                    "Variable": f"Generación_{technology}_GWh_día",
                    "Estado": "Disponible",
                    "Unidad": "GWh-día",
                    "Observaciones": len(part),
                }
            )
    except Exception as exc:
        warnings.append(f"Generación por tecnología: {exc}")
        status_rows.append(
            {
                "Variable": "Generación por tecnología",
                "Estado": "No disponible",
                "Detalle": str(exc),
            }
        )
    for metric, name, unit in (
        ("PrecEsca", "Precio_escasez_COP_kWh", "COP/kWh"),
        ("PrecPromContRegu", "Precio_contrato_regulado_COP_kWh", "COP/kWh"),
        ("PrecPromContNoRegu", "Precio_contrato_no_regulado_COP_kWh", "COP/kWh"),
        ("RestSinAliv", "Restricciones_COP", "COP"),
        ("VoluUtilDiarEner", "Volumen_util_GWh", "GWh"),
    ):
        entity = "Sistema"

        def loader(
            metric_id: str = metric,
            target: str = unit,
            entity_name: str = entity,
        ) -> pd.DataFrame:
            target_unit = "GWh" if target == "GWh" else None
            raw = provider.fetch(metric_id, entity_name, start, end, target_unit=target_unit)
            frame = raw.data[["datetime", "value"]].copy()
            frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
            if metric_id == "VoluUtilDiarEner":
                rule = "last"
                frame = frame.sort_values("datetime")
            else:
                rule = "sum" if target == "COP" else "mean"
            return (
                frame.groupby(pd.Grouper(key="datetime", freq="MS"))["value"]
                .agg(rule)
                .reset_index()
            )

        add(name, unit, loader, "value")

    try:
        dna = unserved_demand(provider, start, end)
        part = dna.monthly[["datetime", "GWh_día"]].rename(
            columns={"GWh_día": "Demanda_no_atendida_GWh_día"}
        )
        series.append(part)
        status_rows.append(
            {
                "Variable": "Demanda_no_atendida_GWh_día",
                "Estado": "Disponible",
                "Unidad": "GWh-día",
                "Observaciones": len(part),
            }
        )
        warnings.extend(dna.warnings)
    except Exception as exc:
        warnings.append(f"Demanda no atendida: {exc}")

    if include_macro:
        macro = macro_provider or MacroProvider(timeout=provider.timeout)
        try:
            trm = macro.fetch_trm(start, end)
            trm = (
                trm.groupby(pd.Grouper(key="datetime", freq="MS"))["TRM_COP_USD"]
                .mean()
                .reset_index()
            )
            series.append(trm)
            status_rows.append(
                {
                    "Variable": "TRM_COP_USD",
                    "Estado": "Disponible",
                    "Unidad": "COP/USD",
                    "Observaciones": len(trm),
                }
            )
        except Exception as exc:
            warnings.append(f"TRM: {exc}")
        try:
            oni = macro.fetch_oni()
            start_utc = pd.Timestamp(start)
            end_utc = pd.Timestamp(end)
            start_utc = (
                start_utc.tz_localize("UTC")
                if start_utc.tzinfo is None
                else start_utc.tz_convert("UTC")
            )
            end_utc = (
                end_utc.tz_localize("UTC") if end_utc.tzinfo is None else end_utc.tz_convert("UTC")
            )
            oni = oni[
                (oni["datetime"] >= start_utc)
                & (oni["datetime"] <= end_utc + pd.offsets.MonthEnd())
            ]
            series.append(oni)
            status_rows.append(
                {
                    "Variable": "ENSO_ONI",
                    "Estado": "Disponible",
                    "Unidad": "°C",
                    "Observaciones": len(oni),
                }
            )
        except Exception as exc:
            warnings.append(f"ENSO: {exc}")

    if not series:
        return IntegratedMarketResult(
            pd.DataFrame(), pd.DataFrame(status_rows), methodologies, warnings
        )
    merged = series[0]
    for part in series[1:]:
        merged = merged.merge(part, on="datetime", how="outer")
    merged = merged.sort_values("datetime").reset_index(drop=True)
    demand_col = "Demanda_GWh_día"
    hydro_col = "Generación_Hidráulica_GWh_día"
    if demand_col in merged and hydro_col in merged:
        merged["Generación_no_hidráulica_GWh_día"] = generation_non_hydraulic(
            merged[demand_col], merged[hydro_col]
        )
        status_rows.append(
            {
                "Variable": "Generación_no_hidráulica_GWh_día",
                "Estado": "Calculada",
                "Unidad": "GWh-día",
                "Observaciones": int(merged["Generación_no_hidráulica_GWh_día"].notna().sum()),
            }
        )
        methodologies.append(
            "Generación no hidráulica = demanda nacional - generación hidráulica, ambas en GWh-día."
        )
    enso_column = "ENSO_ONI" if "ENSO_ONI" in merged else None
    merged = add_time_and_enso(merged, enso_column)
    methodologies.extend(
        [
            "Precio: promedio simple de observaciones horarias del mes.",
            "Energía mensual: suma de intervalos; GWh-día: total mensual dividido por días calendario.",
            "Volumen útil: último valor oficial disponible de cada mes.",
            "Tiempo se recalcula 1, 2, 3… después de ordenar la frecuencia mensual.",
        ]
    )
    return IntegratedMarketResult(
        data=merged,
        status=pd.DataFrame(status_rows),
        methodologies=methodologies,
        warnings=warnings,
    )

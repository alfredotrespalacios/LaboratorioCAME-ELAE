"""Motores reanudables para construir las bases mensuales desde fuentes oficiales."""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from came.analytics.aggregation import weighted_price
from came.analytics.generation import GenerationMonthlyHistory, aggregate_generation_monthly_history
from came.data.colombia import (
    agent_catalog,
    attach_resource_metadata,
    resource_catalog,
    unserved_demand,
)
from came.data.monthly_store import LONG_COLUMNS, last_complete_month, merge_monthly_data
from came.data.providers.chile import ChileProvider
from came.data.providers.macro import MacroProvider
from came.data.providers.omie import OmieProvider
from came.data.providers.redata import REDataProvider
from came.data.providers.xm import XMProvider

ProgressCallback = Callable[["ProgressEvent"], None]


@dataclass(frozen=True)
class ProgressEvent:
    source: str
    variable: str
    period: str
    current: int
    total: int
    status: str
    detail: str = ""


@dataclass
class BuildResult:
    country: str
    data: pd.DataFrame
    status: pd.DataFrame
    validation: pd.DataFrame = field(default_factory=pd.DataFrame)
    catalogs: dict[str, pd.DataFrame] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.data.empty


@dataclass(frozen=True)
class XMMonthlyTask:
    metric_id: str
    entity: str
    series_id: str
    series_name: str
    variable: str
    unit: str
    target_unit: str | None
    aggregation: str


COLOMBIA_TASKS = (
    XMMonthlyTask(
        "PrecBolsNaci",
        "Sistema",
        "col_precio_bolsa_cop_kwh",
        "Precio de bolsa nacional",
        "Precio de bolsa",
        "COP/kWh",
        None,
        "Promedio simple de las observaciones del mes",
    ),
    XMMonthlyTask(
        "PrecEsca",
        "Sistema",
        "col_precio_escasez_cop_kwh",
        "Precio de escasez",
        "Precio de escasez",
        "COP/kWh",
        None,
        "Promedio simple de las observaciones del mes",
    ),
    XMMonthlyTask(
        "PrecPromContRegu",
        "Sistema",
        "col_precio_contrato_regulado_cop_kwh",
        "Precio promedio de contratos regulados",
        "Precio de contratos regulados",
        "COP/kWh",
        None,
        "Promedio simple de las observaciones del mes",
    ),
    XMMonthlyTask(
        "PrecPromContNoRegu",
        "Sistema",
        "col_precio_contrato_no_regulado_cop_kwh",
        "Precio promedio de contratos no regulados",
        "Precio de contratos no regulados",
        "COP/kWh",
        None,
        "Promedio simple de las observaciones del mes",
    ),
    XMMonthlyTask(
        "RestSinAliv",
        "Sistema",
        "col_restricciones_cop_mes",
        "Costo mensual de restricciones",
        "Restricciones",
        "COP",
        None,
        "Suma de las observaciones del mes",
    ),
    XMMonthlyTask(
        "VoluUtilDiarEner",
        "Sistema",
        "col_volumen_util_gwh",
        "Volumen útil al cierre del mes",
        "Volumen útil",
        "GWh",
        "GWh",
        "Último valor oficial disponible del mes",
    ),
)


class CheckpointStore:
    """Conserva bloques mensuales ya aprobados en el disco temporal de la instancia."""

    def __init__(self, build_id: str) -> None:
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", build_id).strip("._")
        self.directory = Path(tempfile.gettempdir()) / "laboratorio_came" / safe_id
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", key).strip("._")
        return self.directory / f"{safe_key}.parquet"

    def get(self, key: str) -> pd.DataFrame | None:
        path = self._path(key)
        return pd.read_parquet(path) if path.exists() else None

    def put(self, key: str, frame: pd.DataFrame) -> None:
        frame.to_parquet(self._path(key), index=False, compression="zstd")

    def clear(self) -> None:
        if self.directory.exists():
            shutil.rmtree(self.directory)


def _month_start(values: pd.Series, timezone_name: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce", utc=True)
    local = dates.dt.tz_convert(timezone_name).dt.tz_localize(None)
    return local.dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC")


def _date_blocks(start: object, end: object, days: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    blocks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    current = first
    while current <= last:
        block_end = min(current + pd.Timedelta(days=days - 1), last)
        blocks.append((current, block_end))
        current = block_end + pd.Timedelta(days=1)
    return blocks


def _year_blocks(start: object, end: object) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    blocks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    current = first
    while current <= last:
        block_end = min(pd.Timestamp(current.year, 12, 31), last)
        blocks.append((current, block_end))
        current = block_end + pd.Timedelta(days=1)
    return blocks


def _emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    if callback:
        callback(event)


def _long_rows(
    frame: pd.DataFrame,
    *,
    country: str,
    family: str,
    level: str,
    entity_code: str | pd.Series,
    entity_name: str | pd.Series,
    variable: str,
    unit: str,
    value_column: str,
    source: str,
    dataset: str,
    aggregation: str,
    series_id: str | pd.Series,
    series_name: str | pd.Series,
    catalog_date: str = "",
) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "datetime": pd.to_datetime(frame["datetime"], utc=True),
            "country": country,
            "family": family,
            "level": level,
            "entity_code": entity_code,
            "entity_name": entity_name,
            "variable": variable,
            "unit": unit,
            "value": pd.to_numeric(frame[value_column], errors="coerce"),
            "source": source,
            "dataset": dataset,
            "aggregation": aggregation,
            "series_id": series_id,
            "series_name": series_name,
            "catalog_date": catalog_date,
        }
    )
    return result[list(LONG_COLUMNS)].dropna(subset=["datetime", "value"])


def _slug_series(values: pd.Series) -> pd.Series:
    return (
        values.astype("string")
        .fillna("no_identificado")
        .str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("ascii")
        .str.casefold()
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
        .replace("", "no_identificado")
    )


def _combine_partial_frames(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    valid = [frame for frame in frames if frame is not None and not frame.empty]
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()


class ColombiaMonthlyBuilder:
    """Construye Colombia por bloques y reutiliza cada bloque exitoso al reanudar."""

    def __init__(
        self,
        *,
        timeout: int = 45,
        build_id: str = "colombia",
        xm_provider: XMProvider | None = None,
        macro_provider: MacroProvider | None = None,
    ) -> None:
        self.xm = xm_provider or XMProvider(timeout=timeout)
        self.macro = macro_provider or MacroProvider(timeout=timeout)
        self.checkpoints = CheckpointStore(build_id)

    def clear_checkpoints(self) -> None:
        self.checkpoints.clear()

    def _cached_block(
        self,
        key: str,
        loader: Callable[[], pd.DataFrame],
    ) -> tuple[pd.DataFrame | None, str | None, bool]:
        cached = self.checkpoints.get(key)
        if cached is not None:
            return cached, None, True
        try:
            frame = loader()
            self.checkpoints.put(key, frame)
            return frame, None, False
        except Exception as exc:
            return None, str(exc), False

    def _system_task(
        self,
        task: XMMonthlyTask,
        start: object,
        end: object,
        callback: ProgressCallback | None,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
        blocks = _year_blocks(start, end)
        frames: list[pd.DataFrame] = []
        status: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, (block_start, block_end) in enumerate(blocks, start=1):
            key = f"xm_{task.metric_id}_{task.entity}_{block_start:%Y%m%d}_{block_end:%Y%m%d}"

            def load(
                current_start: pd.Timestamp = block_start,
                current_end: pd.Timestamp = block_end,
            ) -> pd.DataFrame:
                result = self.xm.fetch(
                    task.metric_id,
                    task.entity,
                    current_start,
                    current_end,
                    target_unit=task.target_unit,
                )
                return result.data[["datetime", "value"]].copy()

            frame, error, cached = self._cached_block(key, load)
            period = f"{block_start.date()} a {block_end.date()}"
            if error:
                message = f"XM · {task.metric_id} · {period}: {error}"
                errors.append(message)
                state = "Error"
            else:
                frames.append(frame if frame is not None else pd.DataFrame())
                state = "Reutilizado" if cached else "Aprobado"
            status.append(
                {
                    "Fuente": "XM",
                    "Variable": task.metric_id,
                    "Periodo": period,
                    "Estado": state,
                    "Detalle": error or "",
                }
            )
            _emit(
                callback,
                ProgressEvent("XM", task.metric_id, period, index, len(blocks), state, error or ""),
            )
        raw = _combine_partial_frames(frames)
        if raw.empty:
            if not errors:
                errors.append(f"XM · {task.metric_id}: no devolvió observaciones en el periodo.")
            return pd.DataFrame(columns=LONG_COLUMNS), status, errors
        raw["observed_at"] = pd.to_datetime(raw["datetime"], errors="coerce", utc=True)
        raw["datetime"] = _month_start(raw["observed_at"], "America/Bogota")
        if task.metric_id == "VoluUtilDiarEner":
            monthly = (
                raw.sort_values("observed_at", kind="stable")
                .groupby("datetime", as_index=False)["value"]
                .last()
            )
        elif task.unit == "COP" and task.metric_id == "RestSinAliv":
            monthly = raw.groupby("datetime", as_index=False)["value"].sum()
        else:
            monthly = raw.groupby("datetime", as_index=False)["value"].mean()
        rows = _long_rows(
            monthly,
            country="COL",
            family="Mercado",
            level="Sistema",
            entity_code="SIN",
            entity_name="Colombia",
            variable=task.variable,
            unit=task.unit,
            value_column="value",
            source="XM",
            dataset=f"{task.metric_id}/{task.entity}",
            aggregation=task.aggregation,
            series_id=task.series_id,
            series_name=task.series_name,
        )
        return rows, status, errors

    def _demand(
        self,
        start: object,
        end: object,
        callback: ProgressCallback | None,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
        blocks = _year_blocks(start, end)
        frames: list[pd.DataFrame] = []
        status: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, (block_start, block_end) in enumerate(blocks, start=1):
            key = f"xm_DemaSIN_Sistema_{block_start:%Y%m%d}_{block_end:%Y%m%d}"

            def load(
                current_start: pd.Timestamp = block_start,
                current_end: pd.Timestamp = block_end,
            ) -> pd.DataFrame:
                result = self.xm.fetch(
                    "DemaSIN", "Sistema", current_start, current_end, target_unit="GWh"
                )
                return result.data[["datetime", "value"]].copy()

            frame, error, cached = self._cached_block(key, load)
            period = f"{block_start.date()} a {block_end.date()}"
            state = "Error" if error else ("Reutilizado" if cached else "Aprobado")
            if error:
                errors.append(f"XM · DemaSIN · {period}: {error}")
            else:
                frames.append(frame if frame is not None else pd.DataFrame())
            status.append(
                {
                    "Fuente": "XM",
                    "Variable": "DemaSIN",
                    "Periodo": period,
                    "Estado": state,
                    "Detalle": error or "",
                }
            )
            _emit(
                callback,
                ProgressEvent("XM", "DemaSIN", period, index, len(blocks), state, error or ""),
            )
        raw = _combine_partial_frames(frames)
        if raw.empty:
            if not errors:
                errors.append("XM · DemaSIN: no devolvió observaciones en el periodo.")
            return pd.DataFrame(columns=LONG_COLUMNS), status, errors
        raw["datetime"] = _month_start(raw["datetime"], "America/Bogota")
        monthly = (
            raw.groupby("datetime", as_index=False)["value"]
            .sum()
            .rename(columns={"value": "GWh_mes"})
        )
        monthly["GWh_día"] = monthly["GWh_mes"] / monthly["datetime"].dt.days_in_month
        frames_long = [
            _long_rows(
                monthly,
                country="COL",
                family="Demanda",
                level="Sistema",
                entity_code="SIN",
                entity_name="Colombia",
                variable="Demanda mensual",
                unit="GWh",
                value_column="GWh_mes",
                source="XM",
                dataset="DemaSIN/Sistema",
                aggregation="Suma de energía del mes",
                series_id="col_demanda_gwh_mes",
                series_name="Demanda nacional mensual",
            ),
            _long_rows(
                monthly,
                country="COL",
                family="Demanda",
                level="Sistema",
                entity_code="SIN",
                entity_name="Colombia",
                variable="Demanda promedio diario",
                unit="GWh-día",
                value_column="GWh_día",
                source="XM",
                dataset="DemaSIN/Sistema",
                aggregation="GWh del mes dividido por días calendario",
                series_id="col_demanda_gwh_dia",
                series_name="Demanda nacional promedio diario",
            ),
        ]
        return pd.concat(frames_long, ignore_index=True), status, errors

    def _generation(
        self,
        start: object,
        end: object,
        callback: ProgressCallback | None,
    ) -> tuple[pd.DataFrame, GenerationMonthlyHistory | None, list[dict[str, Any]], list[str]]:
        try:
            resources = resource_catalog(self.xm)
            agents = agent_catalog(self.xm)
        except Exception as exc:
            return (
                pd.DataFrame(columns=LONG_COLUMNS),
                None,
                [],
                [f"Catálogos de generación XM: {exc}"],
            )
        blocks = _date_blocks(start, end, 14)
        partials: list[pd.DataFrame] = []
        status: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, (block_start, block_end) in enumerate(blocks, start=1):
            key = f"xm_Gene_Recurso_{block_start:%Y%m%d}_{block_end:%Y%m%d}"

            def load(
                current_start: pd.Timestamp = block_start,
                current_end: pd.Timestamp = block_end,
            ) -> pd.DataFrame:
                raw = self.xm.fetch(
                    "Gene", "Recurso", current_start, current_end, target_unit="GWh"
                ).data
                attached = attach_resource_metadata(raw, resources)
                if "company_code" in attached and "company_code" in agents:
                    columns = [
                        column for column in ("company_code", "company_name") if column in agents
                    ]
                    attached = attached.merge(
                        agents[columns].drop_duplicates("company_code"),
                        on="company_code",
                        how="left",
                    )
                attached["datetime"] = _month_start(attached["datetime"], "America/Bogota")
                group_columns = [
                    "datetime",
                    "entity_id",
                    "resource_name",
                    "company_code",
                    "company_name",
                    "technology",
                ]
                for column, default in (
                    ("company_code", "NO_IDENTIFICADO"),
                    ("company_name", "Sin agente identificado"),
                    ("technology", "Otras"),
                ):
                    if column not in attached:
                        attached[column] = default
                    attached[column] = attached[column].fillna(default)
                return attached.groupby(group_columns, as_index=False, dropna=False, observed=True)[
                    "value"
                ].sum()

            frame, error, cached = self._cached_block(key, load)
            period = f"{block_start.date()} a {block_end.date()}"
            state = "Error" if error else ("Reutilizado" if cached else "Aprobado")
            if error:
                errors.append(f"XM · Gene/Recurso · {period}: {error}")
            else:
                partials.append(frame if frame is not None else pd.DataFrame())
            status.append(
                {
                    "Fuente": "XM",
                    "Variable": "Gene/Recurso",
                    "Periodo": period,
                    "Estado": state,
                    "Detalle": error or "",
                }
            )
            _emit(
                callback,
                ProgressEvent("XM", "Gene/Recurso", period, index, len(blocks), state, error or ""),
            )
        combined = _combine_partial_frames(partials)
        if combined.empty:
            if not errors:
                errors.append("XM · Gene/Recurso: no devolvió observaciones en el periodo.")
            return pd.DataFrame(columns=LONG_COLUMNS), None, status, errors
        history = aggregate_generation_monthly_history(combined)
        catalog_date = datetime.now(timezone.utc).date().isoformat()
        long_frames: list[pd.DataFrame] = []

        def add_level(
            table: pd.DataFrame,
            level: str,
            code_column: str,
            name_column: str,
        ) -> None:
            base_slug = _slug_series(table[code_column])
            for value_column, unit, suffix, variable, label in (
                ("GWh_mes", "GWh", "gwh_mes", "Generación mensual", "mensual"),
                ("GWh_día", "GWh-día", "gwh_dia", "Generación promedio diario", "promedio diario"),
            ):
                long_frames.append(
                    _long_rows(
                        table,
                        country="COL",
                        family="Generación",
                        level=level,
                        entity_code=table[code_column],
                        entity_name=table[name_column],
                        variable=variable,
                        unit=unit,
                        value_column=value_column,
                        source="XM",
                        dataset="Gene/Recurso + ListadoRecursos + ListadoAgentes",
                        aggregation="Suma de Gene/Recurso; asociación según catálogo XM consultado",
                        series_id="col_generacion_"
                        + level.casefold().replace("í", "i")
                        + "_"
                        + base_slug
                        + "_"
                        + suffix,
                        series_name="Generación "
                        + label
                        + " · "
                        + table[name_column].astype("string"),
                        catalog_date=catalog_date,
                    )
                )

        add_level(history.by_resource, "Recurso", "resource_code", "resource_name")
        add_level(history.by_company, "Empresa", "company_code", "company_name")
        technology = history.by_technology.assign(
            technology_code=_slug_series(history.by_technology["technology"])
        )
        add_level(technology, "Tecnología", "technology_code", "technology")
        totals = history.by_resource.groupby("datetime", as_index=False)[
            ["GWh_mes", "GWh_día"]
        ].sum()
        for value_column, unit, suffix, variable, label in (
            ("GWh_mes", "GWh", "gwh_mes", "Generación mensual", "Generación nacional mensual"),
            (
                "GWh_día",
                "GWh-día",
                "gwh_dia",
                "Generación promedio diario",
                "Generación nacional promedio diario",
            ),
        ):
            long_frames.append(
                _long_rows(
                    totals,
                    country="COL",
                    family="Generación",
                    level="Sistema",
                    entity_code="SIN",
                    entity_name="Colombia",
                    variable=variable,
                    unit=unit,
                    value_column=value_column,
                    source="XM",
                    dataset="Gene/Recurso",
                    aggregation="Suma de todos los recursos del mes",
                    series_id=f"col_generacion_total_{suffix}",
                    series_name=label,
                    catalog_date=catalog_date,
                )
            )
        return pd.concat(long_frames, ignore_index=True), history, status, errors

    def _unserved(
        self,
        start: object,
        end: object,
        callback: ProgressCallback | None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]], list[str], list[str]]:
        blocks = _year_blocks(start, end)
        monthly_frames: list[pd.DataFrame] = []
        audits: list[pd.DataFrame] = []
        status: list[dict[str, Any]] = []
        errors: list[str] = []
        warnings: list[str] = []
        for index, (block_start, block_end) in enumerate(blocks, start=1):
            key = f"xm_DNA_{block_start:%Y%m%d}_{block_end:%Y%m%d}"

            def load(
                current_start: pd.Timestamp = block_start,
                current_end: pd.Timestamp = block_end,
            ) -> pd.DataFrame:
                result = unserved_demand(self.xm, current_start, current_end)
                monthly = result.monthly.copy()
                monthly["_kind"] = "monthly"
                audit = result.hierarchy_audit.copy()
                audit["_kind"] = "audit"
                return pd.concat([monthly, audit], ignore_index=True, sort=False)

            frame, error, cached = self._cached_block(key, load)
            period = f"{block_start.date()} a {block_end.date()}"
            state = "Error" if error else ("Reutilizado" if cached else "Aprobado")
            if error:
                errors.append(f"XM · demanda no atendida · {period}: {error}")
            elif frame is not None:
                monthly_frames.append(frame[frame["_kind"].eq("monthly")].drop(columns="_kind"))
                audits.append(frame[frame["_kind"].eq("audit")].drop(columns="_kind"))
            status.append(
                {
                    "Fuente": "XM",
                    "Variable": "Demanda no atendida",
                    "Periodo": period,
                    "Estado": state,
                    "Detalle": error or "",
                }
            )
            _emit(
                callback,
                ProgressEvent(
                    "XM", "Demanda no atendida", period, index, len(blocks), state, error or ""
                ),
            )
        monthly = _combine_partial_frames(monthly_frames)
        if monthly.empty:
            if not errors:
                errors.append("XM · demanda no atendida: no devolvió observaciones en el periodo.")
            return (
                pd.DataFrame(columns=LONG_COLUMNS),
                _combine_partial_frames(audits),
                status,
                errors,
                warnings,
            )
        monthly["datetime"] = pd.to_datetime(monthly["datetime"], utc=True)
        monthly = monthly.groupby("datetime", as_index=False)[["GWh", "GWh_día"]].sum()
        frames = [
            _long_rows(
                monthly,
                country="COL",
                family="Demanda no atendida",
                level="Sistema",
                entity_code="SIN",
                entity_name="Colombia",
                variable="Demanda no atendida mensual",
                unit="GWh",
                value_column="GWh",
                source="XM",
                dataset="DemaNoAtenProg + DemaNoAtenNoProg",
                aggregation="Suma mensual sin doble conteo entre área y subárea",
                series_id="col_demanda_no_atendida_gwh_mes",
                series_name="Demanda no atendida mensual",
            ),
            _long_rows(
                monthly,
                country="COL",
                family="Demanda no atendida",
                level="Sistema",
                entity_code="SIN",
                entity_name="Colombia",
                variable="Demanda no atendida promedio diario",
                unit="GWh-día",
                value_column="GWh_día",
                source="XM",
                dataset="DemaNoAtenProg + DemaNoAtenNoProg",
                aggregation="GWh del mes dividido por días calendario; sin doble conteo jerárquico",
                series_id="col_demanda_no_atendida_gwh_dia",
                series_name="Demanda no atendida promedio diario",
            ),
        ]
        return (
            pd.concat(frames, ignore_index=True),
            _combine_partial_frames(audits),
            status,
            errors,
            warnings,
        )

    def _macro(
        self,
        start: object,
        end: object,
        callback: ProgressCallback | None,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str]]:
        frames: list[pd.DataFrame] = []
        status: list[dict[str, Any]] = []
        errors: list[str] = []
        period = f"{pd.Timestamp(start).date()} a {pd.Timestamp(end).date()}"

        trm, error, cached = self._cached_block(
            f"macro_TRM_{pd.Timestamp(start):%Y%m%d}_{pd.Timestamp(end):%Y%m%d}",
            lambda: self.macro.fetch_trm(start, end),
        )
        state = "Error" if error else ("Reutilizado" if cached else "Aprobado")
        if error:
            errors.append(f"TRM · {period}: {error}")
        elif trm is not None and not trm.empty:
            trm = trm.copy()
            trm["datetime"] = _month_start(trm["datetime"], "America/Bogota")
            trm = trm.groupby("datetime", as_index=False)["TRM_COP_USD"].mean()
            frames.append(
                _long_rows(
                    trm,
                    country="COL",
                    family="Macroeconomía",
                    level="Sistema",
                    entity_code="COL",
                    entity_name="Colombia",
                    variable="TRM",
                    unit="COP/USD",
                    value_column="TRM_COP_USD",
                    source="Banco de la República / datos.gov.co",
                    dataset="TRM oficial",
                    aggregation="Promedio de valores diarios del mes",
                    series_id="col_trm_cop_usd",
                    series_name="TRM promedio mensual",
                )
            )
        else:
            errors.append(f"TRM · {period}: la fuente no devolvió observaciones.")
        status.append(
            {
                "Fuente": "datos.gov.co",
                "Variable": "TRM",
                "Periodo": period,
                "Estado": state,
                "Detalle": error or "",
            }
        )
        _emit(callback, ProgressEvent("datos.gov.co", "TRM", period, 1, 2, state, error or ""))

        oni, error, cached = self._cached_block("macro_ONI_completo", self.macro.fetch_oni)
        state = "Error" if error else ("Reutilizado" if cached else "Aprobado")
        if error:
            errors.append(f"ONI · NOAA: {error}")
        elif oni is not None and not oni.empty:
            filtered = oni[
                pd.to_datetime(oni["datetime"], utc=True).between(
                    pd.Timestamp(start, tz="UTC")
                    if pd.Timestamp(start).tzinfo is None
                    else pd.Timestamp(start).tz_convert("UTC"),
                    pd.Timestamp(end, tz="UTC")
                    if pd.Timestamp(end).tzinfo is None
                    else pd.Timestamp(end).tz_convert("UTC"),
                )
            ].copy()
            for column, unit, series_id, name in (
                ("ENSO_ONI", "°C", "col_enso_oni", "Índice ONI"),
                ("Niño", "Indicador 0/1", "col_enso_nino", "Indicador El Niño"),
                ("Niña", "Indicador 0/1", "col_enso_nina", "Indicador La Niña"),
            ):
                frames.append(
                    _long_rows(
                        filtered,
                        country="COL",
                        family="Clima",
                        level="Sistema",
                        entity_code="ENSO",
                        entity_name="Pacífico ecuatorial",
                        variable=name,
                        unit=unit,
                        value_column=column,
                        source="NOAA/CPC",
                        dataset="ONI",
                        aggregation="Valor mensual oficial",
                        series_id=series_id,
                        series_name=name,
                    )
                )
            if filtered.empty:
                errors.append(
                    f"ONI · {period}: no hay observaciones dentro del periodo solicitado."
                )
        else:
            errors.append("ONI · NOAA: la fuente no devolvió observaciones.")
        status.append(
            {
                "Fuente": "NOAA/CPC",
                "Variable": "ONI",
                "Periodo": period,
                "Estado": state,
                "Detalle": error or "",
            }
        )
        _emit(callback, ProgressEvent("NOAA/CPC", "ONI", period, 2, 2, state, error or ""))
        return _combine_partial_frames(frames), status, errors

    @staticmethod
    def _add_non_hydraulic(data: pd.DataFrame) -> pd.DataFrame:
        demand = data[data["series_id"].eq("col_demanda_gwh_dia")][["datetime", "value"]].rename(
            columns={"value": "demand"}
        )
        hydro = data[
            data["series_id"].str.contains(
                "col_generacion_tecnologia_hidraulica_gwh_dia", regex=False
            )
        ][["datetime", "value"]].rename(columns={"value": "hydro"})
        merged = demand.merge(hydro, on="datetime", how="inner")
        if merged.empty:
            return data
        merged["value"] = merged["demand"] - merged["hydro"]
        derived = _long_rows(
            merged,
            country="COL",
            family="Generación",
            level="Calculada",
            entity_code="NO_HIDRAULICA",
            entity_name="Generación no hidráulica",
            variable="Generación no hidráulica promedio diario",
            unit="GWh-día",
            value_column="value",
            source="Cálculo CAME con datos XM",
            dataset="DemaSIN - Gene/Recurso hidráulica",
            aggregation="Demanda nacional menos generación hidráulica",
            series_id="col_generacion_no_hidraulica_gwh_dia",
            series_name="Generación no hidráulica promedio diario",
        )
        return merge_monthly_data(data, derived)

    def build(
        self,
        start: object,
        end: object,
        *,
        existing: pd.DataFrame | None = None,
        replace_start: object | None = None,
        replace_end: object | None = None,
        include_macro: bool = True,
        callback: ProgressCallback | None = None,
    ) -> BuildResult:
        first = pd.Timestamp(start).normalize()
        final = pd.Timestamp(end).normalize()
        allowed_end = last_complete_month() + pd.offsets.MonthEnd()
        allowed_end = allowed_end.tz_localize(None) if allowed_end.tzinfo else allowed_end
        final = min(final, allowed_end)
        if first > final:
            return BuildResult(
                "COL",
                pd.DataFrame(columns=LONG_COLUMNS),
                pd.DataFrame(),
                errors=["El periodo no contiene meses completos."],
            )

        long_frames: list[pd.DataFrame] = []
        statuses: list[dict[str, Any]] = []
        errors: list[str] = []
        warnings: list[str] = []

        demand, task_status, task_errors = self._demand(first, final, callback)
        long_frames.append(demand)
        statuses.extend(task_status)
        errors.extend(task_errors)
        for task in COLOMBIA_TASKS:
            rows, task_status, task_errors = self._system_task(task, first, final, callback)
            long_frames.append(rows)
            statuses.extend(task_status)
            errors.extend(task_errors)
        generation, history, task_status, task_errors = self._generation(first, final, callback)
        long_frames.append(generation)
        statuses.extend(task_status)
        errors.extend(task_errors)
        dna, dna_audit, task_status, task_errors, task_warnings = self._unserved(
            first, final, callback
        )
        long_frames.append(dna)
        statuses.extend(task_status)
        errors.extend(task_errors)
        warnings.extend(task_warnings)
        if include_macro:
            macro, task_status, task_errors = self._macro(first, final, callback)
            long_frames.append(macro)
            statuses.extend(task_status)
            errors.extend(task_errors)

        incoming = _combine_partial_frames(long_frames)
        base = existing.copy() if existing is not None else pd.DataFrame(columns=LONG_COLUMNS)
        if replace_start is not None and replace_end is not None and not base.empty:
            dates = pd.to_datetime(base["datetime"], utc=True)
            lower = pd.Timestamp(replace_start)
            upper = pd.Timestamp(replace_end) + pd.offsets.MonthEnd()
            lower = lower.tz_localize("UTC") if lower.tzinfo is None else lower.tz_convert("UTC")
            upper = upper.tz_localize("UTC") if upper.tzinfo is None else upper.tz_convert("UTC")
            base = base[~dates.between(lower, upper)]
        data = merge_monthly_data(base, incoming)
        data = self._add_non_hydraulic(data)
        catalogs: dict[str, pd.DataFrame] = {"Auditoría DNA": dna_audit}
        validation = pd.DataFrame()
        if history is not None:
            catalogs["Recursos XM"] = history.resource_catalog
            validation = history.validation
        return BuildResult(
            country="COL",
            data=data,
            status=pd.DataFrame(statuses),
            validation=validation,
            catalogs=catalogs,
            warnings=warnings,
            errors=errors,
        )


class SpainMonthlyBuilder:
    """Construye la canasta española con REData y precio diario de OMIE."""

    WIDGETS = (
        ("demanda", "evolucion", "MWh", "Demanda"),
        ("generacion", "estructura-generacion", "MWh", "Generación"),
    )

    def __init__(self, *, timeout: int = 45, build_id: str = "espana") -> None:
        self.redata = REDataProvider(timeout=timeout)
        self.omie = OmieProvider(timeout=timeout)
        self.checkpoints = CheckpointStore(build_id)

    def clear_checkpoints(self) -> None:
        self.checkpoints.clear()

    def _cached_block(
        self, key: str, loader: Callable[[], pd.DataFrame]
    ) -> tuple[pd.DataFrame | None, str | None, bool]:
        cached = self.checkpoints.get(key)
        if cached is not None:
            return cached, None, True
        try:
            frame = loader()
            self.checkpoints.put(key, frame)
            return frame, None, False
        except Exception as exc:
            return None, str(exc), False

    def build(
        self,
        start: object,
        end: object,
        *,
        include_omie: bool = True,
        callback: ProgressCallback | None = None,
    ) -> BuildResult:
        frames: list[pd.DataFrame] = []
        statuses: list[dict[str, Any]] = []
        errors: list[str] = []
        redata_blocks = _year_blocks(start, end)
        omie_periods = list(pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M"))
        tasks_total = len(self.WIDGETS) * len(redata_blocks) + (
            len(omie_periods) if include_omie else 0
        )
        task_number = 0
        for category, widget, unit, family in self.WIDGETS:
            widget_frames: list[pd.DataFrame] = []
            for block_start, block_end in redata_blocks:
                task_number += 1
                key = f"redata_{category}_{widget}_{block_start:%Y%m%d}_{block_end:%Y%m%d}"

                def load(
                    current_start: pd.Timestamp = block_start,
                    current_end: pd.Timestamp = block_end,
                    current_category: str = category,
                    current_widget: str = widget,
                    current_unit: str = unit,
                ) -> pd.DataFrame:
                    return self.redata.fetch_widget(
                        current_category,
                        current_widget,
                        current_start,
                        current_end,
                        time_trunc="month",
                        system="Península",
                        unit=current_unit,
                    ).data

                data, error, cached = self._cached_block(key, load)
                period = f"{block_start.date()} a {block_end.date()}"
                state = "Error" if error else ("Reutilizado" if cached else "Aprobado")
                if error:
                    errors.append(f"REData · {widget} · {period}: {error}")
                elif data is not None:
                    widget_frames.append(data)
                statuses.append(
                    {
                        "Fuente": "REData",
                        "Variable": widget,
                        "Periodo": period,
                        "Estado": state,
                        "Detalle": error or "",
                    }
                )
                _emit(
                    callback,
                    ProgressEvent(
                        "REData", widget, period, task_number, tasks_total, state, error or ""
                    ),
                )
            data = _combine_partial_frames(widget_frames)
            if not data.empty:
                data["datetime"] = _month_start(data["datetime"], "Europe/Madrid")
                slug = _slug_series(
                    data["entity_id"].astype("string") + "_" + data["entity_name"].astype("string")
                )
                frames.append(
                    _long_rows(
                        data,
                        country="ESP",
                        family=family,
                        level="Indicador",
                        entity_code=data["entity_id"],
                        entity_name=data["entity_name"],
                        variable=family,
                        unit=unit,
                        value_column="value",
                        source="REData — Red Eléctrica",
                        dataset=f"{category}/{widget}",
                        aggregation="Valor mensual publicado por REData",
                        series_id="esp_" + category + "_" + slug,
                        series_name=data["entity_name"].astype("string"),
                    )
                )

        if include_omie:
            omie_months: list[pd.DataFrame] = []
            omie_errors: list[str] = []
            for month in omie_periods:
                task_number += 1
                month_start = month.start_time
                month_end = min(month.end_time.normalize(), pd.Timestamp(end).normalize())
                key = f"omie_precio_{month_start:%Y%m}"

                def load_omie(
                    current_start: pd.Timestamp = month_start,
                    current_end: pd.Timestamp = month_end,
                ) -> pd.DataFrame:
                    return self.omie.fetch_prices(current_start, current_end).data

                part, error, cached = self._cached_block(key, load_omie)
                period = str(month)
                state = "Error" if error else ("Reutilizado" if cached else "Aprobado")
                if error:
                    omie_errors.append(f"{month}: {error}")
                elif part is not None:
                    part = part.copy()
                    part["datetime"] = _month_start(part["datetime"], "Europe/Madrid")
                    omie_months.append(part.groupby("datetime", as_index=False)["value"].mean())
                statuses.append(
                    {
                        "Fuente": "OMIE",
                        "Variable": "Precio diario",
                        "Periodo": period,
                        "Estado": state,
                        "Detalle": error or "",
                    }
                )
                _emit(
                    callback,
                    ProgressEvent(
                        "OMIE",
                        "Precio diario",
                        period,
                        task_number,
                        tasks_total,
                        state,
                        error or "",
                    ),
                )
            if omie_months:
                omie_data = pd.concat(omie_months, ignore_index=True)
                frames.append(
                    _long_rows(
                        omie_data,
                        country="ESP",
                        family="Mercado",
                        level="Sistema",
                        entity_code="ES",
                        entity_name="España",
                        variable="Precio mercado diario",
                        unit="EUR/MWh",
                        value_column="value",
                        source="OMIE",
                        dataset="marginalpdbc",
                        aggregation="Promedio simple de periodos del mes",
                        series_id="esp_precio_omie_eur_mwh",
                        series_name="Precio mensual del mercado diario",
                    )
                )
            if omie_errors:
                errors.extend(f"OMIE · {message}" for message in omie_errors)
        return BuildResult(
            "ESP", _combine_partial_frames(frames), pd.DataFrame(statuses), errors=errors
        )


class ChileMonthlyBuilder:
    """Construye Chile a partir de los dos archivos oficiales validados."""

    def __init__(self, *, timeout: int = 45) -> None:
        self.provider = ChileProvider(timeout=timeout)

    def build_from_files(
        self,
        costs_content: bytes,
        costs_filename: str,
        demand_content: bytes,
        demand_filename: str,
        generation_content: bytes,
        generation_filename: str,
        *,
        callback: ProgressCallback | None = None,
    ) -> BuildResult:
        try:
            costs = self.provider.parse_marginal_cost(costs_content, costs_filename)
            demand = self.provider.parse_demand(demand_content, demand_filename)
            generation = self.provider.parse_generation(generation_content, generation_filename)
            _, by_time = self.provider.national_weighted_price(costs, demand)
            by_time["datetime"] = _month_start(by_time["datetime"], "America/Santiago")
            monthly = (
                by_time.groupby("datetime", as_index=False)
                .apply(
                    lambda group: pd.Series(
                        {
                            "price_usd_mwh": weighted_price(
                                group["price_usd_mwh"], group["demand_mwh"]
                            ),
                            "demand_mwh": group["demand_mwh"].sum(),
                            "bars": group["bars"].max(),
                        }
                    ),
                    include_groups=False,
                )
                .reset_index(drop=True)
            )
            generation["datetime"] = _month_start(generation["datetime"], "America/Santiago")
            generation_monthly = generation.groupby(
                ["datetime", "technology"], as_index=False, observed=True
            )["generation_mwh"].sum()
            generation_monthly["GWh_mes"] = generation_monthly["generation_mwh"] / 1000
            generation_monthly["technology_code"] = _slug_series(generation_monthly["technology"])
            frames = [
                _long_rows(
                    monthly,
                    country="CHL",
                    family="Mercado",
                    level="Sistema",
                    entity_code="SEN",
                    entity_name="Chile",
                    variable="Costo marginal nacional ponderado",
                    unit="USD/MWh",
                    value_column="price_usd_mwh",
                    source="Coordinador Eléctrico Nacional",
                    dataset=costs_filename,
                    aggregation="Promedio mensual de precios por intervalo ponderados por demanda",
                    series_id="chl_precio_nacional_usd_mwh",
                    series_name="Costo marginal nacional ponderado",
                ),
                _long_rows(
                    monthly,
                    country="CHL",
                    family="Demanda",
                    level="Sistema",
                    entity_code="SEN",
                    entity_name="Chile",
                    variable="Demanda mensual de barras coincidentes",
                    unit="MWh",
                    value_column="demand_mwh",
                    source="Coordinador Eléctrico Nacional",
                    dataset=demand_filename,
                    aggregation="Suma mensual de demanda en barras coincidentes",
                    series_id="chl_demanda_mwh_mes",
                    series_name="Demanda mensual de barras coincidentes",
                ),
                _long_rows(
                    generation_monthly,
                    country="CHL",
                    family="Generación",
                    level="Tecnología",
                    entity_code=generation_monthly["technology_code"],
                    entity_name=generation_monthly["technology"],
                    variable="Generación mensual",
                    unit="GWh",
                    value_column="GWh_mes",
                    source="Coordinador Eléctrico Nacional",
                    dataset=generation_filename,
                    aggregation="Suma mensual por tecnología de la exportación oficial",
                    series_id="chl_generacion_tecnologia_"
                    + generation_monthly["technology_code"]
                    + "_gwh_mes",
                    series_name="Generación mensual · "
                    + generation_monthly["technology"].astype("string"),
                ),
            ]
            status = pd.DataFrame(
                [
                    {
                        "Fuente": "Coordinador",
                        "Variable": "Costo y demanda",
                        "Periodo": "Cobertura de archivos",
                        "Estado": "Aprobado",
                        "Detalle": "",
                    }
                ]
            )
            _emit(
                callback,
                ProgressEvent(
                    "Coordinador", "Costo y demanda", "Cobertura de archivos", 1, 1, "Aprobado"
                ),
            )
            return BuildResult(
                "CHL",
                pd.concat(frames, ignore_index=True),
                status,
                catalogs={
                    "Costos por barra": costs,
                    "Demanda por barra": demand,
                    "Generación tecnología": generation,
                },
            )
        except Exception as exc:
            return BuildResult(
                "CHL",
                pd.DataFrame(columns=LONG_COLUMNS),
                pd.DataFrame(
                    [
                        {
                            "Fuente": "Coordinador",
                            "Variable": "Costo y demanda",
                            "Periodo": "Cobertura de archivos",
                            "Estado": "Error",
                            "Detalle": str(exc),
                        }
                    ]
                ),
                errors=[str(exc)],
            )

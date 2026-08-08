"""Esquema canónico compartido por conectores, análisis y exportaciones."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from came.errors import SourceContractError

CANONICAL_COLUMNS = [
    "country",
    "source",
    "dataset",
    "variable_id",
    "variable_name",
    "entity_type",
    "entity_id",
    "entity_name",
    "datetime",
    "value",
    "unit",
    "frequency",
    "aggregation",
    "quality_status",
    "retrieved_at",
]


@dataclass(frozen=True)
class Coverage:
    requested_start: str | None = None
    requested_end: str | None = None
    received_start: str | None = None
    received_end: str | None = None
    observations: int = 0
    missing_expected: int | None = None
    duplicates: int = 0
    excluded: int = 0
    completeness_pct: float | None = None


@dataclass(frozen=True)
class SeriesMeta:
    country: str
    source: str
    dataset: str
    variable_id: str
    variable_name: str
    unit: str
    frequency: str
    aggregation: str
    entity_type: str = "Sistema"
    timezone: str | None = None
    methodology: str = ""
    source_url: str | None = None
    retrieved_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class DataResult:
    data: pd.DataFrame
    meta: SeriesMeta
    coverage: Coverage | None = None
    warnings: list[str] = field(default_factory=list)
    raw_columns: list[str] = field(default_factory=list)

    def canonical(self) -> pd.DataFrame:
        return ensure_canonical(self.data, self.meta)


@dataclass
class AnalysisPackage:
    package_id: str
    module: str
    title: str
    created_at: str
    period: str
    source: str
    unit: str
    configuration: dict[str, Any]
    indicators: dict[str, Any]
    methodology: list[str]
    warnings: list[str] = field(default_factory=list)
    table_preview: list[dict[str, Any]] = field(default_factory=list)
    additional_tables_preview: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    user_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_canonical() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_COLUMNS)


def ensure_canonical(frame: pd.DataFrame, meta: SeriesMeta | None = None) -> pd.DataFrame:
    """Completa el contrato canónico sin ocultar columnas originales relevantes."""

    if frame is None:
        raise SourceContractError("La fuente no devolvió una tabla.")
    data = frame.copy()
    if "datetime" not in data.columns or "value" not in data.columns:
        if meta is None:
            raise SourceContractError("Faltan las columnas canónicas datetime y value.")
        raise SourceContractError(
            f"{meta.source}/{meta.dataset} no produjo columnas datetime y value."
        )

    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data = data.dropna(subset=["datetime", "value"]).copy()

    if meta is not None:
        defaults = {
            "country": meta.country,
            "source": meta.source,
            "dataset": meta.dataset,
            "variable_id": meta.variable_id,
            "variable_name": meta.variable_name,
            "entity_type": meta.entity_type,
            "entity_id": "Sistema",
            "entity_name": "Sistema",
            "unit": meta.unit,
            "frequency": meta.frequency,
            "aggregation": meta.aggregation,
            "quality_status": "observado",
            "retrieved_at": meta.retrieved_at,
        }
        for column, value in defaults.items():
            if column not in data.columns:
                data[column] = value

    for column in CANONICAL_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
    ordered = CANONICAL_COLUMNS + [col for col in data.columns if col not in CANONICAL_COLUMNS]
    return (
        data[ordered].sort_values(["datetime", "entity_name"], kind="stable").reset_index(drop=True)
    )

"""Lectura, validación y empaquetado de las bases mensuales por defecto.

El archivo Parquet usa formato largo. Las páginas que necesitan una tabla ancha la
obtienen con :func:`to_wide`, sin duplicar el archivo publicado en GitHub.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd

SCHEMA_VERSION = "2.0"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = PROJECT_ROOT / "datos_por_defecto"

LONG_COLUMNS = (
    "datetime",
    "country",
    "family",
    "level",
    "entity_code",
    "entity_name",
    "variable",
    "unit",
    "value",
    "source",
    "dataset",
    "aggregation",
    "series_id",
    "series_name",
    "catalog_date",
)

SERIES_KEY = ("datetime", "country", "series_id")


@dataclass(frozen=True)
class CountryPackageSpec:
    code: str
    label: str
    directory: str
    parquet_name: str
    catalog_name: str
    metadata_name: str

    @property
    def relative_directory(self) -> Path:
        return Path("datos_por_defecto") / self.directory

    @property
    def absolute_directory(self) -> Path:
        return DEFAULT_DATA_ROOT / self.directory


PACKAGE_SPECS = {
    "COL": CountryPackageSpec(
        "COL",
        "Colombia",
        "colombia",
        "Base_integrada_mensual.parquet",
        "Catalogo_Base_integrada.xlsx",
        "Fecha_actualizacion_Base_integrada.json",
    ),
    "ESP": CountryPackageSpec(
        "ESP",
        "España",
        "espana",
        "Base_integrada_mensual_Espana.parquet",
        "Catalogo_Base_integrada_Espana.xlsx",
        "Fecha_actualizacion_Espana.json",
    ),
    "CHL": CountryPackageSpec(
        "CHL",
        "Chile",
        "chile",
        "Base_integrada_mensual_Chile.parquet",
        "Catalogo_Base_integrada_Chile.xlsx",
        "Fecha_actualizacion_Chile.json",
    ),
}


@dataclass
class ValidationResult:
    ok: bool
    issues: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def as_frame(self) -> pd.DataFrame:
        rows = [{"Control": key, "Resultado": value} for key, value in self.summary.items()]
        rows.extend({"Control": "Incidencia", "Resultado": issue} for issue in self.issues)
        return pd.DataFrame(rows)


@dataclass
class MonthlyPackage:
    spec: CountryPackageSpec
    data: pd.DataFrame
    catalog: pd.DataFrame
    metadata: dict[str, Any]
    validation: ValidationResult
    parquet_bytes: bytes
    catalog_bytes: bytes
    metadata_bytes: bytes
    zip_bytes: bytes


def get_package_spec(country: str) -> CountryPackageSpec:
    code = str(country).upper()
    if code not in PACKAGE_SPECS:
        raise ValueError(f"País no soportado: {country}.")
    return PACKAGE_SPECS[code]


def last_complete_month(reference: object | None = None) -> pd.Timestamp:
    """Devuelve el primer día UTC del último mes calendario completo."""

    current = pd.Timestamp(reference or datetime.now(timezone.utc))
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    current_naive = current.tz_localize(None)
    return (current_naive.to_period("M").to_timestamp() - pd.offsets.MonthBegin()).tz_localize(
        "UTC"
    )


def normalize_monthly_data(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza tipos y orden sin rellenar valores faltantes."""

    data = frame.copy()
    for column in LONG_COLUMNS:
        if column not in data:
            data[column] = pd.NA
    data = data[list(LONG_COLUMNS)]
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    local = data["datetime"].dt.tz_convert("UTC").dt.tz_localize(None)
    data["datetime"] = local.dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC")
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    text_columns = [column for column in LONG_COLUMNS if column not in {"datetime", "value"}]
    for column in text_columns:
        data[column] = data[column].astype("string").fillna("").str.strip()
    data = data.dropna(subset=["datetime", "value"])
    data = data[np.isfinite(data["value"])]
    return data.sort_values(list(SERIES_KEY), kind="stable").reset_index(drop=True)


def validate_monthly_data(
    frame: pd.DataFrame,
    country: str,
    *,
    reference: object | None = None,
) -> ValidationResult:
    """Aplica controles estructurales antes de permitir la descarga del paquete."""

    code = get_package_spec(country).code
    issues: list[str] = []
    missing = sorted(set(LONG_COLUMNS).difference(frame.columns))
    if missing:
        issues.append(f"Faltan columnas obligatorias: {', '.join(missing)}.")
        return ValidationResult(False, issues, {"Filas": len(frame), "País": code})

    data = normalize_monthly_data(frame)
    if data.empty:
        issues.append("La base mensual no contiene observaciones válidas.")
    unexpected_countries = sorted(set(data["country"].dropna().astype(str)).difference({code}))
    if unexpected_countries:
        issues.append(f"Se encontraron otros países: {', '.join(unexpected_countries)}.")
    blank_columns = [
        column
        for column in ("family", "level", "variable", "unit", "source", "series_id", "series_name")
        if data[column].eq("").any()
    ]
    if blank_columns:
        issues.append(f"Hay campos de trazabilidad vacíos en: {', '.join(blank_columns)}.")
    duplicates = int(data.duplicated(list(SERIES_KEY), keep=False).sum())
    if duplicates:
        issues.append(f"Hay {duplicates} filas involucradas en claves mensuales duplicadas.")
    future_rows = data[data["datetime"] > last_complete_month(reference)]
    if not future_rows.empty:
        issues.append("La base contiene el mes actual incompleto o meses futuros.")
    invalid_months = data[data["datetime"].dt.day.ne(1)]
    if not invalid_months.empty:
        issues.append("Todas las fechas deben representar el primer día de su mes.")

    summary = {
        "Estado": "Aprobado" if not issues else "Revisar",
        "País": code,
        "Filas": len(data),
        "Series": int(data["series_id"].nunique()),
        "Meses": int(data["datetime"].nunique()),
        "Primer mes": data["datetime"].min() if not data.empty else None,
        "Último mes": data["datetime"].max() if not data.empty else None,
        "Duplicados": duplicates,
    }
    return ValidationResult(not issues, issues, summary)


def build_series_catalog(frame: pd.DataFrame) -> pd.DataFrame:
    data = normalize_monthly_data(frame)
    if data.empty:
        return pd.DataFrame()
    group_columns = [
        "country",
        "family",
        "level",
        "entity_code",
        "entity_name",
        "variable",
        "unit",
        "source",
        "dataset",
        "aggregation",
        "series_id",
        "series_name",
        "catalog_date",
    ]
    return (
        data.groupby(group_columns, as_index=False, dropna=False, observed=True)
        .agg(
            Inicio=("datetime", "min"),
            Fin=("datetime", "max"),
            Observaciones=("value", "count"),
            Meses_disponibles=("datetime", "nunique"),
        )
        .sort_values(["family", "level", "series_name"], kind="stable")
        .reset_index(drop=True)
    )


def _excel_bytes(
    catalog: pd.DataFrame,
    coverage: pd.DataFrame,
    validation: ValidationResult,
    additional_sheets: dict[str, pd.DataFrame] | None,
) -> bytes:
    buffer = BytesIO()
    sheets = {
        "Catálogo de series": catalog,
        "Cobertura mensual": coverage,
        "Validación paquete": validation.as_frame(),
    }
    sheets.update(additional_sheets or {})
    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
        workbook = writer.book
        header = workbook.add_format({"bold": True, "bg_color": "#1F4E79", "font_color": "#FFFFFF"})
        for raw_name, raw_frame in sheets.items():
            name = re.sub(r"[\\/*?:\[\]]", "-", str(raw_name))[:31]
            frame = raw_frame.copy()
            if frame.empty and len(frame.columns) == 0:
                frame = pd.DataFrame({"Información": ["Sin datos"]})
            for column in frame.select_dtypes(include=["datetimetz"]).columns:
                frame[column] = frame[column].dt.tz_convert("UTC").dt.tz_localize(None)
            for column in frame.columns:
                if pd.api.types.is_object_dtype(frame[column].dtype):
                    frame[column] = frame[column].map(
                        lambda value: (
                            value.tz_convert("UTC").tz_localize(None)
                            if isinstance(value, pd.Timestamp) and value.tzinfo is not None
                            else value
                        )
                    )
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes(1, 0)
            for index, column in enumerate(frame.columns):
                sheet.write(0, index, str(column), header)
                sample = frame[column].dropna().astype(str).head(250)
                width = max(
                    len(str(column)) + 2,
                    int(sample.str.len().quantile(0.9)) + 2 if not sample.empty else 10,
                )
                sheet.set_column(index, index, min(width, 44))
    return buffer.getvalue()


def _coverage_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = normalize_monthly_data(frame)
    if data.empty:
        return pd.DataFrame()
    return (
        data.groupby(["family", "level", "source"], as_index=False, observed=True)
        .agg(
            Series=("series_id", "nunique"),
            Observaciones=("value", "count"),
            Inicio=("datetime", "min"),
            Fin=("datetime", "max"),
        )
        .sort_values(["family", "level", "source"], kind="stable")
        .reset_index(drop=True)
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def create_monthly_package(
    frame: pd.DataFrame,
    country: str,
    *,
    additional_sheets: dict[str, pd.DataFrame] | None = None,
    build_notes: list[str] | None = None,
    reference: object | None = None,
) -> MonthlyPackage:
    """Valida y crea Parquet, catálogo, metadatos y ZIP en memoria."""

    spec = get_package_spec(country)
    data = normalize_monthly_data(frame)
    validation = validate_monthly_data(data, spec.code, reference=reference)
    if not validation.ok:
        raise ValueError("No se creó el paquete: " + " ".join(validation.issues))
    catalog = build_series_catalog(data)
    coverage = _coverage_frame(data)
    parquet_buffer = BytesIO()
    data.to_parquet(parquet_buffer, index=False, compression="zstd")
    parquet_bytes = parquet_buffer.getvalue()
    catalog_bytes = _excel_bytes(catalog, coverage, validation, additional_sheets)
    created_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "country": spec.code,
        "country_name": spec.label,
        "created_at_utc": created_at,
        "last_complete_month": data["datetime"].max().date().isoformat(),
        "first_month": data["datetime"].min().date().isoformat(),
        "rows": len(data),
        "series": int(data["series_id"].nunique()),
        "sources": sorted(data["source"].dropna().astype(str).unique()),
        "notes": build_notes or [],
        "files": {
            spec.parquet_name: {"sha256": _sha256(parquet_bytes), "bytes": len(parquet_bytes)},
            spec.catalog_name: {"sha256": _sha256(catalog_bytes), "bytes": len(catalog_bytes)},
        },
    }
    metadata_bytes = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, "w", ZIP_DEFLATED) as archive:
        root = spec.relative_directory.as_posix()
        archive.writestr(f"{root}/{spec.parquet_name}", parquet_bytes)
        archive.writestr(f"{root}/{spec.catalog_name}", catalog_bytes)
        archive.writestr(f"{root}/{spec.metadata_name}", metadata_bytes)
    return MonthlyPackage(
        spec=spec,
        data=data,
        catalog=catalog,
        metadata=metadata,
        validation=validation,
        parquet_bytes=parquet_bytes,
        catalog_bytes=catalog_bytes,
        metadata_bytes=metadata_bytes,
        zip_bytes=zip_buffer.getvalue(),
    )


def default_file_paths(country: str) -> dict[str, Path]:
    spec = get_package_spec(country)
    return {
        "parquet": spec.absolute_directory / spec.parquet_name,
        "catalog": spec.absolute_directory / spec.catalog_name,
        "metadata": spec.absolute_directory / spec.metadata_name,
    }


def load_default_monthly(country: str) -> pd.DataFrame:
    path = default_file_paths(country)["parquet"]
    if not path.exists():
        raise FileNotFoundError(
            f"No existe {path.relative_to(PROJECT_ROOT)}. Genere el paquete en Mantenimiento de datos."
        )
    return normalize_monthly_data(pd.read_parquet(path))


def load_default_metadata(country: str) -> dict[str, Any]:
    path = default_file_paths(country)["metadata"]
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def merge_monthly_data(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    """Une una actualización y deja la fila entrante en cualquier clave repetida."""

    frames = [frame for frame in (existing, incoming) if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=LONG_COLUMNS)
    combined = pd.concat(frames, ignore_index=True)
    combined = normalize_monthly_data(combined)
    return combined.drop_duplicates(list(SERIES_KEY), keep="last").reset_index(drop=True)


def to_wide(frame: pd.DataFrame, country: str | None = None) -> pd.DataFrame:
    """Convierte las series mensuales seleccionadas a una fila por mes."""

    data = normalize_monthly_data(frame)
    if country:
        data = data[data["country"].eq(str(country).upper())]
    if data.empty:
        return pd.DataFrame(columns=["datetime"])
    wide = data.pivot(index="datetime", columns="series_id", values="value").reset_index()
    wide.columns.name = None
    return wide.sort_values("datetime").reset_index(drop=True)


def series_options(frame: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una fila legible por serie para selectores de Streamlit."""

    catalog = build_series_catalog(frame)
    if catalog.empty:
        return pd.DataFrame(columns=["series_id", "series_name", "unit", "level", "family"])
    return catalog[["series_id", "series_name", "unit", "level", "family", "Inicio", "Fin"]]

"""Lectura, validación y empaquetado de las bases mensuales por defecto.

El archivo Parquet usa formato largo. Las páginas que necesitan una tabla ancha la
obtienen con :func:`to_wide`, sin duplicar el archivo publicado en GitHub.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable
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
PackageProgressCallback = Callable[[str], None]


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


@dataclass(frozen=True)
class StoredMonthlyPackage:
    """Rutas de un paquete ya escrito en el almacenamiento de ejecución."""

    spec: CountryPackageSpec
    directory: Path
    zip_path: Path
    parquet_path: Path
    catalog_path: Path
    metadata_path: Path
    manifest_path: Path
    metadata: dict[str, Any]
    validation: ValidationResult
    created_at_utc: str


def get_package_spec(country: str) -> CountryPackageSpec:
    code = str(country).upper()
    if code not in PACKAGE_SPECS:
        raise ValueError(f"País no soportado: {country}.")
    return PACKAGE_SPECS[code]


def runtime_storage_root(*, create: bool = False) -> Path:
    """Devuelve una ruta ajena al repositorio para avances y descargas recuperables.

    Streamlit vuelve a ejecutar el código con frecuencia. La ubicación es estable durante la
    vida de la instancia y evita que los archivos generados activen el observador del código.
    Community Cloud sigue siendo un almacenamiento efímero: un reinicio total puede borrarlo.
    """

    configured = os.getenv("CAME_RUNTIME_STORAGE")
    preferred = Path(configured).expanduser() if configured else Path.home() / ".cache" / "came"
    fallback = Path(tempfile.gettempdir()) / "laboratorio_came_runtime"
    candidates = (preferred, fallback)
    if not create:
        return preferred if preferred.exists() or not fallback.exists() else fallback
    last_error: OSError | None = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError as exc:
            last_error = exc
    raise OSError("No fue posible crear el almacenamiento de ejecución.") from last_error


def allocate_ready_package_directory(country: str, build_id: str) -> Path:
    """Reserva un directorio único para publicar un paquete terminado."""

    spec = get_package_spec(country)
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", build_id).strip("._") or "construccion"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}_{safe_id}_{uuid.uuid4().hex[:8]}"
    return runtime_storage_root(create=True) / "ready" / spec.code / name


def _legacy_package_manifests() -> list[Path]:
    legacy_root = Path(tempfile.gettempdir()) / "laboratorio_came"
    if not legacy_root.exists():
        return []
    return list(legacy_root.glob("*/package/Paquete_listo.json"))


def discover_ready_monthly_package(country: str) -> StoredMonthlyPackage | None:
    """Encuentra el paquete más reciente incluso si se perdió ``session_state``."""

    spec = get_package_spec(country)
    manifests: list[Path] = []
    ready_root = runtime_storage_root() / "ready" / spec.code
    if ready_root.exists():
        manifests.extend(ready_root.glob("*/Paquete_listo.json"))
    manifests.extend(_legacy_package_manifests())

    candidates: list[tuple[float, StoredMonthlyPackage]] = []
    for manifest_path in manifests:
        try:
            package = load_stored_monthly_package(manifest_path.parent, spec.code, required=True)
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if package is not None:
            candidates.append((manifest_path.stat().st_mtime, package))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


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


def _write_excel_catalog(
    destination: str | Path | BytesIO,
    catalog: pd.DataFrame,
    coverage: pd.DataFrame,
    validation: ValidationResult,
    additional_sheets: dict[str, pd.DataFrame] | None,
) -> None:
    sheets = {
        "Catálogo de series": catalog,
        "Cobertura mensual": coverage,
        "Validación paquete": validation.as_frame(),
    }
    sheets.update(additional_sheets or {})
    with pd.ExcelWriter(destination, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as writer:
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


def _excel_bytes(
    catalog: pd.DataFrame,
    coverage: pd.DataFrame,
    validation: ValidationResult,
    additional_sheets: dict[str, pd.DataFrame] | None,
) -> bytes:
    buffer = BytesIO()
    _write_excel_catalog(buffer, catalog, coverage, validation, additional_sheets)
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_progress(callback: PackageProgressCallback | None, message: str) -> None:
    if callback:
        callback(message)


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


def create_stored_monthly_package(
    frame: pd.DataFrame,
    country: str,
    directory: str | Path,
    *,
    additional_sheets: dict[str, pd.DataFrame] | None = None,
    build_notes: list[str] | None = None,
    reference: object | None = None,
    progress: PackageProgressCallback | None = None,
) -> StoredMonthlyPackage:
    """Valida y escribe un paquete sin conservar Parquet, Excel y ZIP duplicados en RAM.

    El directorio definitivo se publica únicamente cuando los cuatro archivos y el manifiesto
    están completos. Así una recarga de Streamlit nunca descubre un paquete a medio construir.
    """

    output = Path(directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"El directorio de salida ya existe: {output}")
    staging = output.with_name(f".{output.name}.building-{uuid.uuid4().hex[:8]}")
    staging.mkdir(parents=True, exist_ok=False)
    spec = get_package_spec(country)

    try:
        _package_progress(progress, "1/5 · Validando la estructura y la cobertura mensual…")
        data = normalize_monthly_data(frame)
        validation = validate_monthly_data(data, spec.code, reference=reference)
        if not validation.ok:
            raise ValueError("No se creó el paquete: " + " ".join(validation.issues))

        parquet_path = staging / spec.parquet_name
        catalog_path = staging / spec.catalog_name
        metadata_path = staging / spec.metadata_name
        zip_name = f"Base_mensual_{spec.label}.zip"
        zip_path = staging / zip_name
        manifest_path = staging / "Paquete_listo.json"

        _package_progress(progress, "2/5 · Escribiendo el Parquet mensual en disco…")
        data.to_parquet(parquet_path, index=False, compression="zstd")

        _package_progress(progress, "3/5 · Construyendo el catálogo Excel…")
        catalog = build_series_catalog(data)
        coverage = _coverage_frame(data)
        _write_excel_catalog(
            catalog_path,
            catalog,
            coverage,
            validation,
            additional_sheets,
        )
        del catalog, coverage

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
                spec.parquet_name: {
                    "sha256": _sha256_file(parquet_path),
                    "bytes": parquet_path.stat().st_size,
                },
                spec.catalog_name: {
                    "sha256": _sha256_file(catalog_path),
                    "bytes": catalog_path.stat().st_size,
                },
            },
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _package_progress(progress, "4/5 · Comprimiendo el ZIP descargable…")
        root = spec.relative_directory.as_posix()
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
            archive.write(parquet_path, f"{root}/{spec.parquet_name}")
            archive.write(catalog_path, f"{root}/{spec.catalog_name}")
            archive.write(metadata_path, f"{root}/{spec.metadata_name}")

        _package_progress(progress, "5/5 · Publicando el paquete terminado…")
        manifest = {
            "country": spec.code,
            "created_at_utc": created_at,
            "zip_name": zip_name,
            "parquet_name": spec.parquet_name,
            "catalog_name": spec.catalog_name,
            "metadata_name": spec.metadata_name,
            "validation_ok": validation.ok,
            "validation_issues": validation.issues,
            "validation_summary": validation.summary,
            "sizes": {
                zip_name: zip_path.stat().st_size,
                spec.parquet_name: parquet_path.stat().st_size,
                spec.catalog_name: catalog_path.stat().st_size,
                spec.metadata_name: metadata_path.stat().st_size,
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        staging.replace(output)
        package = load_stored_monthly_package(output, spec.code, required=True)
        if package is None:  # pragma: no cover - ``required`` ya obliga una excepción.
            raise FileNotFoundError("El paquete se publicó, pero no pudo abrirse.")
        return package
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _write_bytes_atomically(path: Path, content: bytes) -> None:
    """Escribe primero un temporal y publica el archivo solo cuando está completo."""

    temporary = path.with_name(f".{path.name}.tmp")
    for attempt in range(2):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
            return
        except OSError:
            if attempt == 1:
                raise
        finally:
            temporary.unlink(missing_ok=True)


def store_monthly_package(
    package: MonthlyPackage,
    directory: str | Path,
) -> StoredMonthlyPackage:
    """Guarda el paquete y un manifiesto recuperable después de un rerun de Streamlit."""

    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    spec = package.spec
    zip_name = f"Base_mensual_{spec.label}.zip"
    zip_path = output / zip_name
    parquet_path = output / spec.parquet_name
    catalog_path = output / spec.catalog_name
    metadata_path = output / spec.metadata_name
    manifest_path = output / "Paquete_listo.json"

    _write_bytes_atomically(parquet_path, package.parquet_bytes)
    _write_bytes_atomically(catalog_path, package.catalog_bytes)
    _write_bytes_atomically(metadata_path, package.metadata_bytes)
    _write_bytes_atomically(zip_path, package.zip_bytes)

    created_at = str(package.metadata.get("created_at_utc", datetime.now(timezone.utc).isoformat()))
    manifest = {
        "country": spec.code,
        "created_at_utc": created_at,
        "zip_name": zip_name,
        "parquet_name": spec.parquet_name,
        "catalog_name": spec.catalog_name,
        "metadata_name": spec.metadata_name,
        "validation_ok": package.validation.ok,
        "validation_issues": package.validation.issues,
        "validation_summary": package.validation.summary,
        "sizes": {
            zip_name: len(package.zip_bytes),
            spec.parquet_name: len(package.parquet_bytes),
            spec.catalog_name: len(package.catalog_bytes),
            spec.metadata_name: len(package.metadata_bytes),
        },
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    _write_bytes_atomically(manifest_path, manifest_bytes)
    return load_stored_monthly_package(output, spec.code, required=True)


def load_stored_monthly_package(
    directory: str | Path,
    country: str,
    *,
    required: bool = False,
) -> StoredMonthlyPackage | None:
    """Recupera las descargas listas sin reconstruir el paquete en memoria."""

    output = Path(directory)
    manifest_path = output / "Paquete_listo.json"
    if not manifest_path.exists():
        if required:
            raise FileNotFoundError(f"No existe el manifiesto del paquete en {output}.")
        return None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spec = get_package_spec(country)
    if manifest.get("country") != spec.code:
        raise ValueError(
            f"El paquete guardado corresponde a {manifest.get('country')}, no a {spec.code}."
        )
    zip_path = output / str(manifest["zip_name"])
    parquet_path = output / str(manifest["parquet_name"])
    catalog_path = output / str(manifest["catalog_name"])
    metadata_path = output / str(manifest["metadata_name"])
    paths = (zip_path, parquet_path, catalog_path, metadata_path)
    missing = [path.name for path in paths if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise FileNotFoundError(
            "El paquete guardado está incompleto. Faltan: " + ", ".join(missing) + "."
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    validation = ValidationResult(
        ok=bool(manifest.get("validation_ok")),
        issues=list(manifest.get("validation_issues", [])),
        summary=dict(manifest.get("validation_summary", {})),
    )
    return StoredMonthlyPackage(
        spec=spec,
        directory=output,
        zip_path=zip_path,
        parquet_path=parquet_path,
        catalog_path=catalog_path,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        metadata=metadata,
        validation=validation,
        created_at_utc=str(manifest.get("created_at_utc", "")),
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

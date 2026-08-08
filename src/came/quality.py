"""Controles de calidad y cobertura que acompañan cada resultado."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from came.schema import Coverage


@dataclass
class QualityReport:
    coverage: Coverage
    warnings: list[str] = field(default_factory=list)
    unexpected_negative: int = 0
    non_numeric: int = 0
    null_datetimes: int = 0


def expected_index(start: pd.Timestamp, end: pd.Timestamp, frequency: str) -> pd.DatetimeIndex | None:
    mapping = {"hourly": "h", "daily": "D", "monthly": "MS", "annual": "YS"}
    freq = mapping.get(frequency)
    if freq is None:
        return None
    return pd.date_range(start=start, end=end, freq=freq, tz=start.tz)


def inspect_quality(
    frame: pd.DataFrame,
    *,
    requested_start: object | None = None,
    requested_end: object | None = None,
    frequency: str = "daily",
    allow_negative: bool = True,
    duplicate_keys: tuple[str, ...] = ("datetime", "entity_id", "variable_id"),
) -> QualityReport:
    data = frame.copy()
    datetimes = pd.to_datetime(data.get("datetime"), errors="coerce", utc=True)
    values = pd.to_numeric(data.get("value"), errors="coerce")
    null_datetimes = int(datetimes.isna().sum())
    non_numeric = int(values.isna().sum())
    existing_keys = [key for key in duplicate_keys if key in data.columns]
    duplicates = int(data.duplicated(existing_keys).sum()) if existing_keys else 0
    unexpected_negative = int((values < 0).sum()) if not allow_negative else 0

    valid_dt = datetimes.dropna()
    received_start = valid_dt.min() if not valid_dt.empty else None
    received_end = valid_dt.max() if not valid_dt.empty else None
    req_start = pd.to_datetime(requested_start, utc=True) if requested_start is not None else received_start
    req_end = pd.to_datetime(requested_end, utc=True) if requested_end is not None else received_end

    missing_expected: int | None = None
    completeness_pct: float | None = None
    if req_start is not None and req_end is not None:
        expected = expected_index(req_start, req_end, frequency)
        if expected is not None and len(expected):
            observed = pd.DatetimeIndex(valid_dt.dt.floor("h") if frequency == "hourly" else valid_dt.dt.normalize())
            if frequency == "monthly":
                observed = observed.to_period("M").to_timestamp().tz_localize("UTC")
            missing_expected = max(len(expected.difference(observed.unique())), 0)
            completeness_pct = 100 * (len(expected) - missing_expected) / len(expected)

    coverage = Coverage(
        requested_start=req_start.isoformat() if req_start is not None else None,
        requested_end=req_end.isoformat() if req_end is not None else None,
        received_start=received_start.isoformat() if received_start is not None else None,
        received_end=received_end.isoformat() if received_end is not None else None,
        observations=int((~datetimes.isna() & ~values.isna()).sum()),
        missing_expected=missing_expected,
        duplicates=duplicates,
        excluded=null_datetimes + non_numeric,
        completeness_pct=round(completeness_pct, 3) if completeness_pct is not None else None,
    )

    warnings: list[str] = []
    if null_datetimes:
        warnings.append(f"Se excluyeron {null_datetimes} filas sin fecha válida.")
    if non_numeric:
        warnings.append(f"Se excluyeron {non_numeric} filas sin valor numérico válido.")
    if duplicates:
        warnings.append(f"Se detectaron {duplicates} duplicados según la clave canónica.")
    if unexpected_negative:
        warnings.append(f"Se detectaron {unexpected_negative} valores negativos inesperados.")
    if missing_expected:
        warnings.append(f"Faltan {missing_expected} periodos esperados dentro del rango solicitado.")

    return QualityReport(
        coverage=coverage,
        warnings=warnings,
        unexpected_negative=unexpected_negative,
        non_numeric=non_numeric,
        null_datetimes=null_datetimes,
    )


def safe_divide(numerator: object, denominator: object) -> np.ndarray:
    num = np.asarray(numerator, dtype=float)
    den = np.asarray(denominator, dtype=float)
    return np.divide(num, den, out=np.full(np.broadcast_shapes(num.shape, den.shape), np.nan), where=den != 0)


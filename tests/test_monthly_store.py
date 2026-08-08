from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pandas as pd
import pytest

from came.data.maintenance import COLOMBIA_TASKS, ColombiaMonthlyBuilder
from came.data.monthly_store import (
    LONG_COLUMNS,
    create_monthly_package,
    load_stored_monthly_package,
    merge_monthly_data,
    store_monthly_package,
    to_wide,
    validate_monthly_data,
)
from came.errors import SourceUnavailableError
from came.schema import DataResult


def monthly_row(month: str, value: float, series_id: str = "col_test") -> dict[str, object]:
    return {
        "datetime": pd.Timestamp(month, tz="UTC"),
        "country": "COL",
        "family": "Mercado",
        "level": "Sistema",
        "entity_code": "SIN",
        "entity_name": "Colombia",
        "variable": "Prueba",
        "unit": "GWh",
        "value": value,
        "source": "XM",
        "dataset": "Prueba/Sistema",
        "aggregation": "Último valor del mes",
        "series_id": series_id,
        "series_name": "Serie de prueba",
        "catalog_date": "2026-08-08",
    }


def test_monthly_package_contains_the_three_publishable_files() -> None:
    data = pd.DataFrame([monthly_row("2024-01-01", 1.0), monthly_row("2024-02-01", 2.0)])
    package = create_monthly_package(data, "COL", reference="2024-03-15")

    assert package.validation.ok
    assert package.metadata["last_complete_month"] == "2024-02-01"
    with ZipFile(BytesIO(package.zip_bytes)) as archive:
        assert set(archive.namelist()) == {
            "datos_por_defecto/colombia/Base_integrada_mensual.parquet",
            "datos_por_defecto/colombia/Catalogo_Base_integrada.xlsx",
            "datos_por_defecto/colombia/Fecha_actualizacion_Base_integrada.json",
        }


def test_monthly_package_is_recoverable_from_disk_after_a_rerun(tmp_path) -> None:
    data = pd.DataFrame([monthly_row("2024-01-01", 1.0), monthly_row("2024-02-01", 2.0)])
    package = create_monthly_package(data, "COL", reference="2024-03-15")

    stored = store_monthly_package(package, tmp_path / "package")
    recovered = load_stored_monthly_package(tmp_path / "package", "COL")

    assert recovered is not None
    assert recovered.zip_path == stored.zip_path
    assert recovered.zip_path.read_bytes() == package.zip_bytes
    assert recovered.parquet_path.read_bytes() == package.parquet_bytes
    assert recovered.catalog_path.read_bytes() == package.catalog_bytes
    assert recovered.metadata_path.read_bytes() == package.metadata_bytes
    assert recovered.validation.ok


def test_validation_rejects_duplicates_and_incomplete_month() -> None:
    data = pd.DataFrame([monthly_row("2024-03-01", 1.0), monthly_row("2024-03-01", 2.0)])
    result = validate_monthly_data(data, "COL", reference="2024-03-15")
    assert not result.ok
    assert any("duplic" in issue.casefold() for issue in result.issues)
    assert any("incompleto" in issue.casefold() for issue in result.issues)


def test_merge_replaces_same_series_and_month_and_wide_keeps_series() -> None:
    existing = pd.DataFrame([monthly_row("2024-01-01", 1.0)])
    incoming = pd.DataFrame([monthly_row("2024-01-01", 3.0)])
    merged = merge_monthly_data(existing, incoming)
    assert len(merged) == 1
    assert merged.loc[0, "value"] == pytest.approx(3.0)
    assert to_wide(merged, "COL").loc[0, "col_test"] == pytest.approx(3.0)


class FakeXM:
    def fetch(self, *args, **kwargs):
        data = pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2024-01-02", "2024-01-31"], utc=True),
                "value": [10.0, 20.0],
            }
        )
        return DataResult(data=data, meta=None, coverage=None, warnings=[])


class FlakyDemandXM:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, *args, **kwargs):
        self.calls += 1
        if self.calls < 3:
            raise SourceUnavailableError("XM respondió 502")
        data = pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2024-01-01", "2024-01-31"], utc=True),
                "value": [10.0, 20.0],
            }
        )
        return DataResult(data=data, meta=None, coverage=None, warnings=[])


def test_colombia_builder_retries_a_temporarily_failed_block(tmp_path) -> None:
    provider = FlakyDemandXM()
    builder = ColombiaMonthlyBuilder(xm_provider=provider, build_id="retry-demand")
    builder.checkpoints.directory = tmp_path
    rows, status, errors = builder._demand("2024-01-01", "2024-01-31", callback=None)
    assert provider.calls == 3
    assert not rows.empty
    assert not errors
    assert status[0]["Estado"] == "Aprobado"


def test_volume_uses_last_observation_of_month(tmp_path, monkeypatch) -> None:
    builder = ColombiaMonthlyBuilder(xm_provider=FakeXM(), build_id="test-volume")
    builder.checkpoints.directory = tmp_path
    volume_task = next(task for task in COLOMBIA_TASKS if task.metric_id == "VoluUtilDiarEner")
    rows, _, errors = builder._system_task(volume_task, "2024-01-01", "2024-01-31", callback=None)
    assert not errors
    assert list(rows.columns) == list(LONG_COLUMNS)
    assert rows.loc[0, "value"] == pytest.approx(20.0)


class CompleteFakeXM:
    def fetch_list(self, metric_id: str, entity: str = "Sistema") -> pd.DataFrame:
        if metric_id == "ListadoRecursos":
            return pd.DataFrame(
                {
                    "Code": ["R1"],
                    "Name": ["Planta 1"],
                    "CompanyCode": ["A1"],
                    "EnerSource": ["Agua"],
                }
            )
        return pd.DataFrame({"Code": ["A1"], "Name": ["Empresa 1"]})

    def fetch(self, metric_id, entity, start, end, *, target_unit=None, **kwargs):
        start_ts = pd.Timestamp(start, tz="UTC")
        if metric_id == "Gene":
            data = pd.DataFrame(
                {
                    "datetime": [start_ts],
                    "value": [1.0],
                    "entity_id": ["R1"],
                    "entity_name": ["R1"],
                }
            )
        elif metric_id in {"DemaNoAtenProg", "DemaNoAtenNoProg"}:
            data = pd.DataFrame(
                {
                    "datetime": [start_ts],
                    "value": [1000.0 if entity == "Area" else 500.0],
                    "entity_name": [entity],
                }
            )
        else:
            data = pd.DataFrame(
                {
                    "datetime": [start_ts, pd.Timestamp(end, tz="UTC")],
                    "value": [10.0, 20.0],
                    "entity_name": [entity, entity],
                }
            )
        return DataResult(data=data, meta=None, coverage=None, warnings=[])


class CompleteFakeMacro:
    def fetch_trm(self, start, end):
        return pd.DataFrame({"datetime": [pd.Timestamp(start, tz="UTC")], "TRM_COP_USD": [4000.0]})

    def fetch_oni(self):
        return pd.DataFrame(
            {
                "datetime": [pd.Timestamp("2024-01-01", tz="UTC")],
                "ENSO_ONI": [0.7],
                "Niño": [1],
                "Niña": [0],
            }
        )


def test_colombia_builder_creates_system_resource_company_and_technology_series(tmp_path) -> None:
    builder = ColombiaMonthlyBuilder(
        xm_provider=CompleteFakeXM(),
        macro_provider=CompleteFakeMacro(),
        build_id="complete-fake",
    )
    builder.checkpoints.directory = tmp_path
    result = builder.build("2024-01-01", "2024-01-31")

    assert result.ok
    assert not result.validation.empty
    assert result.validation["Estado"].eq("Conciliado").all()
    assert {"Sistema", "Recurso", "Empresa", "Tecnología"}.issubset(set(result.data["level"]))
    assert "col_generacion_no_hidraulica_gwh_dia" in set(result.data["series_id"])
    assert not result.data.duplicated(["datetime", "country", "series_id"]).any()

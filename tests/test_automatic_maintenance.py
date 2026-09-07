from __future__ import annotations

import pandas as pd

import came.data.automatic_maintenance as automatic
from came.data.maintenance import BuildResult


def _row(series_id: str, variable: str) -> dict[str, object]:
    return {
        "datetime": pd.Timestamp("2024-01-01", tz="UTC"),
        "country": "COL",
        "family": "Mercado",
        "level": "Sistema",
        "entity_code": "SIN",
        "entity_name": "Colombia",
        "variable": variable,
        "unit": "unidad",
        "value": 1.0,
        "source": "Prueba",
        "dataset": "Prueba/Sistema",
        "aggregation": "Mensual",
        "series_id": series_id,
        "series_name": variable,
        "catalog_date": "2026-09-07",
    }


def test_reads_selection_from_version_150_notes() -> None:
    metadata = {"notes": ["Variables seleccionadas: demand, spot_price."]}
    assert automatic.selected_options_from_metadata(metadata) == {"demand", "spot_price"}


def test_complete_selection_is_divided_into_automatic_stages() -> None:
    stages = automatic.planned_stages(
        {
            "demand",
            "spot_price",
            "generation_national",
            "generation_technology",
        }
    )
    assert [stage.key for stage in stages] == ["demand", "spot_price", "generation"]
    assert set(stages[-1].options) == {"generation_national", "generation_technology"}


def test_automatic_builder_reuses_completed_stages(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CAME_RUNTIME_STORAGE", str(tmp_path / "runtime"))
    calls: list[set[str]] = []

    class FakeBuilder:
        def __init__(self, *args, **kwargs):
            pass

        def clear_checkpoints(self) -> None:
            pass

        def build(self, *args, **kwargs) -> BuildResult:
            selected = set(kwargs["selected_options"])
            calls.append(selected)
            option = sorted(selected)[0]
            return BuildResult(
                country="COL",
                data=pd.DataFrame([_row(f"col_test_{option}", option)]),
                status=pd.DataFrame(
                    [{"Fuente": "Prueba", "Variable": option, "Estado": "Aprobado"}]
                ),
            )

        @staticmethod
        def _add_non_hydraulic(data: pd.DataFrame) -> pd.DataFrame:
            return data

        @staticmethod
        def _add_reference_derivatives(data: pd.DataFrame) -> pd.DataFrame:
            return data

    monkeypatch.setattr(automatic, "ColombiaMonthlyBuilder", FakeBuilder)
    first = automatic.ColombiaAutomaticBuilder(build_id="automatic-test").build(
        "2024-01-01",
        "2024-01-31",
        selected_options={"demand", "spot_price"},
    )
    assert not first.result.errors
    assert calls == [{"demand"}, {"spot_price"}]
    assert set(first.result.data["series_id"]) == {"col_test_demand", "col_test_spot_price"}

    second = automatic.ColombiaAutomaticBuilder(build_id="automatic-test").build(
        "2024-01-01",
        "2024-01-31",
        selected_options={"demand", "spot_price"},
    )
    assert not second.result.errors
    assert calls == [{"demand"}, {"spot_price"}]


def test_published_demand_is_reused_when_price_is_added(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CAME_RUNTIME_STORAGE", str(tmp_path / "runtime"))
    calls: list[set[str]] = []

    class FakeBuilder:
        def __init__(self, *args, **kwargs):
            pass

        def clear_checkpoints(self) -> None:
            pass

        def build(self, *args, **kwargs) -> BuildResult:
            selected = set(kwargs["selected_options"])
            calls.append(selected)
            return BuildResult(
                country="COL",
                data=pd.DataFrame([_row("col_precio_bolsa_cop_kwh", "Precio")]),
                status=pd.DataFrame(
                    [{"Fuente": "XM", "Variable": "Precio", "Estado": "Aprobado"}]
                ),
            )

        @staticmethod
        def _add_non_hydraulic(data: pd.DataFrame) -> pd.DataFrame:
            return data

        @staticmethod
        def _add_reference_derivatives(data: pd.DataFrame) -> pd.DataFrame:
            return data

    monkeypatch.setattr(automatic, "ColombiaMonthlyBuilder", FakeBuilder)
    existing = pd.DataFrame([_row("col_demanda_gwh_mes", "Demanda")])
    outcome = automatic.ColombiaAutomaticBuilder(build_id="published-test").build(
        "2024-01-01",
        "2024-01-31",
        existing=existing,
        selected_options={"demand", "spot_price"},
        completed_options={"demand"},
        existing_option_series={"demand": ["col_demanda_gwh_mes"]},
    )
    assert calls == [{"spot_price"}]
    assert "Demanda nacional" in outcome.reused_published
    assert set(outcome.result.data["series_id"]) == {
        "col_demanda_gwh_mes",
        "col_precio_bolsa_cop_kwh",
    }


def test_partial_published_demand_continues_from_next_month(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CAME_RUNTIME_STORAGE", str(tmp_path / "runtime"))
    starts: list[pd.Timestamp] = []

    class FakeBuilder:
        def __init__(self, *args, **kwargs):
            pass

        def clear_checkpoints(self) -> None:
            pass

        def build(self, start, *args, **kwargs) -> BuildResult:
            starts.append(pd.Timestamp(start))
            row = _row("col_demanda_gwh_mes", "Demanda")
            row["datetime"] = pd.Timestamp("2024-02-01", tz="UTC")
            return BuildResult(country="COL", data=pd.DataFrame([row]), status=pd.DataFrame())

        @staticmethod
        def _add_non_hydraulic(data: pd.DataFrame) -> pd.DataFrame:
            return data

        @staticmethod
        def _add_reference_derivatives(data: pd.DataFrame) -> pd.DataFrame:
            return data

    monkeypatch.setattr(automatic, "ColombiaMonthlyBuilder", FakeBuilder)
    existing = pd.DataFrame([_row("col_demanda_gwh_mes", "Demanda")])
    outcome = automatic.ColombiaAutomaticBuilder(build_id="partial-test").build(
        "2024-01-01",
        "2024-02-29",
        existing=existing,
        selected_options={"demand"},
        repair_coverage=True,
    )

    assert starts == [pd.Timestamp("2024-02-01")]
    assert set(pd.to_datetime(outcome.result.data["datetime"]).dt.month) == {1, 2}

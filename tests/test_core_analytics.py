from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from came.analytics.aggregation import add_price_returns, generation_non_hydraulic, weighted_price
from came.analytics.demand import deduplicate_unserved_demand
from came.analytics.generation import aggregate_generation_monthly_history
from came.analytics.modeling import fit_supervised, prepare_model_matrix
from came.data.colombia import national_demand
from came.errors import DataQualityError
from came.schema import DataResult, SeriesMeta


def test_generation_non_hydraulic_is_demand_minus_hydro() -> None:
    result = generation_non_hydraulic(np.array([230.0, 240.0]), np.array([150.0, 145.0]))
    assert result.tolist() == [80.0, 95.0]


def test_weighted_price() -> None:
    assert weighted_price([10, 20], [1, 3]) == pytest.approx(17.5)


def test_price_returns_include_simple_and_logarithmic_definitions() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=2, freq="MS", tz="UTC"),
            "value": [100.0, 110.0],
        }
    )
    result = add_price_returns(frame)
    assert result.loc[1, "Variación_porcentual_pct"] == pytest.approx(10.0)
    assert result.loc[1, "Rendimiento_logarítmico_pct"] == pytest.approx(np.log(1.1) * 100)


class IncompleteDemandProvider:
    def fetch(self, *args, **kwargs):
        first_day = pd.date_range("2026-08-01 05:00", periods=24, freq="h", tz="UTC")
        incomplete_day = pd.date_range("2026-08-02 05:00", periods=6, freq="h", tz="UTC")
        dates = first_day.append(incomplete_day)
        data = pd.DataFrame(
            {
                "datetime": dates,
                "value": 1.0,
                "period": [*range(1, 25), *range(1, 7)],
            }
        )
        meta = SeriesMeta(
            country="COL",
            source="XM",
            dataset="DemaSIN",
            variable_id="DemaSIN",
            variable_name="Demanda",
            unit="GWh",
            frequency="hourly",
            aggregation="original",
        )
        return DataResult(data=data, meta=meta)


def test_daily_demand_hides_the_last_incomplete_day() -> None:
    result = national_demand(
        IncompleteDemandProvider(), "2026-08-01", "2026-08-02", frequency="daily"
    )
    assert len(result) == 1
    assert result.loc[0, "GWh_día"] == pytest.approx(24.0)
    assert result.loc[0, "intervalos_recibidos"] == 24
    assert pd.Timestamp(result.attrs["last_complete_period"]).date().isoformat() == "2026-08-01"
    assert len(result.attrs["excluded_incomplete_periods"]) == 1


def test_demand_hierarchy_uses_area_not_area_plus_subarea() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01"] * 3, utc=True),
            "value": [1000, 400, 600],
            "level": ["Área", "Subárea", "Subárea"],
            "interruption_type": ["Programada"] * 3,
            "entity_name": ["Total", "A", "B"],
        }
    )
    result = deduplicate_unserved_demand(frame, input_unit="kWh")
    assert result.monthly.loc[0, "GWh"] == pytest.approx(0.001)
    assert result.hierarchy_audit.loc[0, "selected_hierarchy"] == "área"
    assert result.warnings


def test_chronological_model_pipeline_with_selected_lags() -> None:
    dates = pd.date_range("2018-01-01", periods=72, freq="MS", tz="UTC")
    x = np.arange(72, dtype=float)
    frame = pd.DataFrame({"datetime": dates, "target": 2 * x + 5, "driver": x})
    matrix, columns = prepare_model_matrix(
        frame,
        target="target",
        features=["driver"],
        selected_lags=["anterior", "un_ano"],
        lagged_features=["target"],
        include_time=True,
        frequency="monthly",
    )
    result = fit_supervised(matrix, target="target", feature_columns=columns, model="linear")
    assert result.predictions["datetime"].min() > matrix["datetime"].min()
    assert result.metrics["R2"] > 0.99
    assert {"residual", "residual_estandarizado"}.issubset(result.residuals)


def test_model_rejects_too_little_complete_data() -> None:
    frame = pd.DataFrame(
        {"datetime": pd.date_range("2024-01-01", periods=4), "y": range(4), "x": range(4)}
    )
    with pytest.raises(DataQualityError):
        prepare_model_matrix(frame, target="y", features=["x"])


def test_generation_history_keeps_all_resources_and_reconciles_levels() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                [
                    "2024-01-01 05:00",
                    "2024-01-01 06:00",
                    "2024-01-01 05:00",
                    "2024-02-01 05:00",
                ],
                utc=True,
            ),
            "value": [1.0, 2.0, 4.0, 6.0],
            "entity_id": ["R1", "R1", "R2", "R2"],
            "resource_name": ["Planta 1", "Planta 1", "Planta 2", "Planta 2"],
            "company_code": ["A1", "A1", "A2", "A2"],
            "company_name": ["Empresa 1", "Empresa 1", "Empresa 2", "Empresa 2"],
            "technology": ["Hidráulica", "Hidráulica", "Gas", "Gas"],
        }
    )

    result = aggregate_generation_monthly_history(frame)

    assert set(result.by_resource["resource_code"]) == {"R1", "R2"}
    assert result.by_resource["GWh_mes"].sum() == pytest.approx(13.0)
    january = result.by_resource[result.by_resource["datetime"].dt.month == 1]
    assert january["GWh_día"].sum() == pytest.approx(7.0 / 31.0)
    assert result.validation["Estado"].eq("Conciliado").all()
    assert result.validation["Diferencia_empresas_GWh"].abs().max() == pytest.approx(0.0)
    assert result.validation["Diferencia_tecnologías_GWh"].abs().max() == pytest.approx(0.0)


def test_generation_history_keeps_unmapped_resources_in_explicit_groups() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01"], utc=True),
            "value": [5.0],
            "entity_id": ["R1"],
        }
    )

    result = aggregate_generation_monthly_history(frame)

    assert result.by_company.loc[0, "company_name"] == "Sin agente identificado"
    assert result.by_technology.loc[0, "technology"] == "Otras"
    assert result.validation.loc[0, "Estado"] == "Conciliado"

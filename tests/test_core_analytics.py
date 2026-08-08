from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from came.analytics.aggregation import generation_non_hydraulic, weighted_price
from came.analytics.demand import deduplicate_unserved_demand
from came.analytics.modeling import fit_supervised, prepare_model_matrix
from came.errors import DataQualityError


def test_generation_non_hydraulic_is_demand_minus_hydro() -> None:
    result = generation_non_hydraulic(np.array([230.0, 240.0]), np.array([150.0, 145.0]))
    assert result.tolist() == [80.0, 95.0]


def test_weighted_price() -> None:
    assert weighted_price([10, 20], [1, 3]) == pytest.approx(17.5)


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
    frame = pd.DataFrame({"datetime": pd.date_range("2024-01-01", periods=4), "y": range(4), "x": range(4)})
    with pytest.raises(DataQualityError):
        prepare_model_matrix(frame, target="y", features=["x"])


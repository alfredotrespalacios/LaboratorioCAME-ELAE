from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from came.analytics.balance import (
    build_balance_comparison,
    calculate_balance,
    weighted_plant_factor,
    years_until_zero_margin,
)
from came.analytics.modeling import (
    evaluation_split_index,
    fit_supervised,
    prepare_model_matrix,
    select_historical_window,
)
from came.exports import plotly_png
from came.ui.pages.energy_balance import _availability_demand_figure, _scenario_summary
from came.ui.pages.modeling_forecast import _fit_time_series_state


def _balance_inputs() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Tecnología": ["Hidráulica", "Gas"],
            "CEN_MW": [10_000.0, 2_000.0],
            "FP_normal": [0.50, 0.80],
            "FP_nino": [0.30, 0.90],
        }
    )


def test_balance_uses_availability_names_and_weighted_total() -> None:
    table = _balance_inputs()
    normal = calculate_balance(table, demand_gwh_day=150.0, factor_column="FP_normal")
    nino = calculate_balance(table, demand_gwh_day=145.0, factor_column="FP_nino")
    comparison = build_balance_comparison(
        table,
        first_name="Operación normal 2026",
        first_demand_gwh_day=150.0,
        second_name="El Niño fuerte 2027",
        second_demand_gwh_day=145.0,
    )

    assert "Disponibilidad_GWh_día" in normal.table
    assert "Generación_disponible_GWh_día" not in normal.table
    total = comparison.iloc[-1]
    assert total["Tecnología"] == "Total"
    assert total["CEN_MW"] == pytest.approx(12_000.0)
    assert total["FP · Operación normal 2026"] == pytest.approx(
        weighted_plant_factor(table["CEN_MW"], table["FP_normal"])
    )
    assert total["Disponibilidad · Operación normal 2026 (GWh-día)"] == pytest.approx(
        normal.availability_gwh_day
    )
    assert total["Participación · Operación normal 2026 (%)"] == pytest.approx(100.0)
    assert total["Demanda · Operación normal 2026 (GWh-día)"] == pytest.approx(150.0)
    assert total["Disponibilidad · El Niño fuerte 2027 (GWh-día)"] == pytest.approx(
        nino.availability_gwh_day
    )


def test_balance_summary_contains_each_scenario_demand_and_zero_margin_years() -> None:
    table = _balance_inputs()
    summary, scenario_rows = _scenario_summary(
        table,
        first_name="Normal personalizado",
        first_demand=150.0,
        second_name="Niño personalizado",
        second_demand=145.0,
        growth=0.025,
    )

    assert list(summary["Escenario"]) == ["Normal personalizado", "Niño personalizado"]
    assert list(summary["Demanda_GWh_día"]) == [150.0, 145.0]
    assert "Disponibilidad_GWh_día" in summary
    assert "Generación_GWh_día" not in summary
    assert summary["Años_hasta_margen_cero"].notna().all()
    assert set(scenario_rows["Escenario"]) == {"Normal personalizado", "Niño personalizado"}


def test_balance_chart_has_two_editable_demand_lines() -> None:
    _, rows = _scenario_summary(
        _balance_inputs(),
        first_name="Caso A",
        first_demand=150.0,
        second_name="Caso B",
        second_demand=145.0,
        growth=0.025,
    )
    figure = _availability_demand_figure(
        rows,
        [("Caso A", 150.0), ("Caso B", 145.0)],
    )

    names = {trace.name for trace in figure.data}
    assert {"Demanda · Caso A", "Demanda · Caso B"}.issubset(names)
    assert {trace.legendgroup for trace in figure.data if trace.name.startswith("Demanda ·")} == {
        "demanda"
    }


def test_zero_margin_equation_matches_compound_demand_identity() -> None:
    demand = 230.0
    availability = 275.0
    growth = 0.025
    years = years_until_zero_margin(demand, availability, growth)
    assert demand * (1 + growth) ** years - availability == pytest.approx(0.0)


def test_modeling_historical_window_and_test_split_are_chronological() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2018-01-01", periods=84, freq="MS", tz="UTC"),
            "y": np.arange(84, dtype=float),
        }
    )
    selected = select_historical_window(frame, date(2020, 1, 1), date(2024, 12, 31))
    split_by_periods = evaluation_split_index(selected["datetime"], test_periods=12)
    split_by_date = evaluation_split_index(
        selected["datetime"], test_start=selected["datetime"].iloc[-12]
    )

    assert selected["datetime"].min() == pd.Timestamp("2020-01-01", tz="UTC")
    assert selected["datetime"].max() == pd.Timestamp("2024-12-01", tz="UTC")
    assert split_by_periods == split_by_date == len(selected) - 12


def test_supervised_evaluation_and_final_calibration_are_separate() -> None:
    time = np.arange(72, dtype=float)
    data = pd.DataFrame(
        {
            "datetime": pd.date_range("2019-01-01", periods=72, freq="MS", tz="UTC"),
            "y": 100 + 0.8 * time + np.sin(time),
            "x": 20 + 0.3 * time,
        }
    )
    matrix, features = prepare_model_matrix(data, target="y", features=["x"])
    evaluation = fit_supervised(
        matrix,
        target="y",
        feature_columns=features,
        model="linear",
        reserve_test=True,
        split_index=60,
    )
    final = fit_supervised(
        matrix,
        target="y",
        feature_columns=features,
        model="linear",
        reserve_test=False,
    )

    assert evaluation.configuration["observations_calibration"] == 60
    assert evaluation.configuration["observations_test"] == 12
    assert len(evaluation.test_predictions) == 12
    assert final.configuration["observations_calibration"] == 72
    assert final.configuration["observations_test"] == 0
    assert final.test_predictions.empty
    assert evaluation.statsmodels_summary
    assert final.statsmodels_summary


def test_arima_keeps_evaluation_and_final_statsmodels_reports() -> None:
    time = np.arange(72, dtype=float)
    series = pd.DataFrame(
        {
            "datetime": pd.date_range("2019-01-01", periods=72, freq="MS", tz="UTC"),
            "demanda": 200 + 0.4 * time + 3 * np.sin(2 * np.pi * time / 12),
        }
    )
    state = _fit_time_series_state(
        series,
        "demanda",
        "ARIMA",
        4,
        True,
        0.80,
        "none",
        (1, 1, 0),
        (0, 0, 0, 0),
        12,
        split_index=60,
    )

    assert state["parameters"]["Observaciones calibración final"] == 72
    assert state["parameters"]["Observaciones de prueba"] == 12
    assert state["evaluation_summary_text"]
    assert state["summary_text"]
    assert not state["evaluation_parameter_table"].empty
    assert not state["final_parameter_table"].empty
    assert set(state["residuals"]["muestra"]) == {"Residuales del modelo"}
    assert set(state["evaluation_errors"]["muestra"]) == {"Errores de prueba"}


def test_plotly_figures_render_for_pdf() -> None:
    figure = _availability_demand_figure(
        pd.DataFrame(
            {
                "Escenario": ["Normal", "El Niño"],
                "Tecnología": ["Hidráulica", "Hidráulica"],
                "Disponibilidad_GWh_día": [250.0, 210.0],
            }
        ),
        [("Normal", 230.0), ("El Niño", 235.0)],
    )
    image = plotly_png(figure, width=700, height=400)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_version_is_150() -> None:
    from came import __version__
    from came.config import APP_VERSION

    assert APP_VERSION == "1.5.0"
    assert __version__ == "1.5.0"

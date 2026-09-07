from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from came.analytics.modeling import (
    fit_supervised,
    forecast_supervised,
    prepare_model_matrix,
    seasonal_future_defaults,
)
from came.analytics.portfolio import (
    PortfolioInputs,
    sensitivity_contract_correlation,
    sensitivity_contract_price,
    sensitivity_contract_share,
)
from came.data.colombia_selection import (
    DEFAULT_SELECTION,
    is_recommended_series,
    selection_catalog,
)
from came.data.maintenance import ColombiaMonthlyBuilder
from came.errors import DataQualityError
from came.ui.pages.modeling_forecast import _rolling_origin_evaluation


def _model_data(length: int = 84) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    time = np.arange(length, dtype=float)
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2018-01-01", periods=length, freq="MS", tz="UTC"),
            "y": 100 + 0.8 * time + 4 * np.sin(time * 2 * np.pi / 12) + rng.normal(0, 0.5, length),
            "x": 30 + 0.3 * time,
        }
    )


def _portfolio_inputs() -> PortfolioInputs:
    return PortfolioInputs(
        generation_mean_gwh=100,
        generation_sd_gwh=18,
        generation_max_gwh=180,
        price_mean_cop_kwh=250,
        price_sd_cop_kwh=75,
        target_correlation=-0.2,
        contract_share=0.7,
        contract_price_cop_kwh=260,
        iterations=400,
        seed=42,
    )


def test_transformations_are_selected_per_variable_and_return_original_target() -> None:
    data = _model_data()
    matrix, features = prepare_model_matrix(
        data,
        target="y",
        features=["x"],
        selected_lags=["anterior"],
        lagged_features=["y"],
        transformations={"y": "difference", "x": "log"},
    )
    result = fit_supervised(
        matrix,
        target="y",
        feature_columns=features,
        model="linear",
    )

    assert result.configuration["transformations"] == {"y": "difference", "x": "log"}
    assert result.predictions["observado"].mean() > 100
    assert result.statsmodels_summary
    assert {"MSE", "U_Theil"}.issubset(result.metrics)


def test_log_transformation_rejects_nonpositive_values() -> None:
    data = _model_data()
    data.loc[5, "x"] = 0
    with pytest.raises(DataQualityError, match="iguales o menores que cero"):
        prepare_model_matrix(
            data,
            target="y",
            features=["x"],
            transformations={"x": "log"},
        )


def test_model_can_use_all_data_without_test_and_labels_metrics_as_adjustment() -> None:
    data = _model_data()
    matrix, features = prepare_model_matrix(data, target="y", features=["x"])
    result = fit_supervised(
        matrix,
        target="y",
        feature_columns=features,
        model="linear",
        reserve_test=False,
    )

    assert result.test_predictions.empty
    assert result.predictions["muestra"].eq("Ajuste con 100 %").all()
    assert any("dentro de muestra" in warning for warning in result.warnings)


def test_random_forest_reports_two_importance_methods_and_uses_seed() -> None:
    data = _model_data()
    matrix, features = prepare_model_matrix(data, target="y", features=["x"], include_time=True)
    result = fit_supervised(
        matrix,
        target="y",
        feature_columns=features,
        model="random_forest",
        random_state=17,
        n_estimators=50,
    )

    assert "importancia_interna" in result.feature_effects
    assert "importancia_permutación" in result.permutation_importance
    assert result.configuration["random_state"] == 17


def test_supervised_future_uses_seasonal_defaults_and_recursive_target_lag() -> None:
    data = _model_data()
    matrix, features = prepare_model_matrix(
        data,
        target="y",
        features=["x"],
        selected_lags=["anterior"],
        lagged_features=["y"],
    )
    result = fit_supervised(matrix, target="y", feature_columns=features, model="linear")
    defaults = seasonal_future_defaults(
        data.iloc[:60], ["x"], 4, start_after=data["datetime"].max()
    )
    forecast = forecast_supervised(result, data, defaults)

    assert len(forecast) == 4
    assert forecast["datetime"].min() > data["datetime"].max()
    assert {"pronóstico", "inferior_95", "superior_95"}.issubset(forecast)


def test_contract_share_sensitivity_has_ten_rows_and_m_cvar() -> None:
    frame = sensitivity_contract_share(_portfolio_inputs(), np.linspace(-2, 2, 10))
    assert len(frame) == 10
    assert "M-CVaR" in frame
    assert frame["Porcentaje contratado"].min() == pytest.approx(-2)
    assert frame["Porcentaje contratado"].max() == pytest.approx(2)


def test_joint_sensitivities_have_fifty_combinations() -> None:
    inputs = _portfolio_inputs()
    shares = np.linspace(0, 1, 10)
    correlations = np.linspace(-0.7, 0.7, 5)
    prices = np.linspace(220, 300, 5)

    by_correlation = sensitivity_contract_correlation(inputs, shares, correlations)
    by_price = sensitivity_contract_price(inputs, shares, prices)

    assert len(by_correlation) == 50
    assert len(by_price) == 50
    assert by_correlation["Correlación"].nunique() == 5
    assert by_price["Precio contrato COP/kWh"].nunique() == 5


def test_colombia_catalog_preselects_priority_series_without_mandatory_variables() -> None:
    catalog = selection_catalog()
    assert {"demand", "spot_price", "generation_national"}.issubset(DEFAULT_SELECTION)
    assert not catalog["Obligatoria"].any()
    assert is_recommended_series("col_generacion_empresa_epmg_gwh_mes", "Empresa", "EPMG")
    assert is_recommended_series("col_generacion_recurso_gtpe_gwh_mes", "Recurso", "GTPE")
    assert not is_recommended_series("col_generacion_recurso_otra_gwh_mes", "Recurso", "OTRA")


def test_demand_only_build_does_not_query_generation_or_other_sources(monkeypatch) -> None:
    builder = ColombiaMonthlyBuilder(xm_provider=SimpleNamespace())
    demand = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2024-01-01", tz="UTC"),
                "country": "COL",
                "family": "Demanda",
                "level": "Sistema",
                "entity_code": "SIN",
                "entity_name": "Colombia",
                "variable": "Demanda mensual",
                "unit": "GWh",
                "value": 7_000.0,
                "source": "XM",
                "dataset": "DemaSIN/Sistema",
                "aggregation": "Suma de energía del mes",
                "series_id": "col_demanda_gwh_mes",
                "series_name": "Demanda nacional mensual",
                "catalog_date": "2026-08-08",
            }
        ]
    )
    monkeypatch.setattr(
        builder,
        "_demand",
        lambda *_args, **_kwargs: (
            demand,
            [{"Fuente": "XM", "Variable": "DemaSIN", "Estado": "Aprobado"}],
            [],
        ),
    )

    def unexpected_query(*_args, **_kwargs):
        raise AssertionError("No debía consultarse una fuente no seleccionada")

    monkeypatch.setattr(builder, "_generation", unexpected_query)
    monkeypatch.setattr(builder, "_system_task", unexpected_query)
    monkeypatch.setattr(builder, "_capacity", unexpected_query)
    monkeypatch.setattr(builder, "_fuel_offer_prices", unexpected_query)
    monkeypatch.setattr(builder, "_unserved", unexpected_query)
    monkeypatch.setattr(builder, "_macro", unexpected_query)

    result = builder.build(
        "2024-01-01",
        "2024-01-31",
        selected_options={"demand"},
        include_macro=True,
    )

    assert not result.errors
    assert result.data["series_id"].str.startswith("col_generacion").sum() == 0
    assert result.data["series_id"].eq("col_demanda_gwh_mes").any()
    assert set(result.status["Variable"]) == {"DemaSIN"}


def test_rolling_origin_evaluation_preserves_chronology() -> None:
    data = _model_data()
    original = pd.Series(
        data["y"].to_numpy(),
        index=pd.DatetimeIndex(data["datetime"]),
    )
    evaluation, metrics = _rolling_origin_evaluation(
        original,
        original,
        model_label="Ingenuo estacional",
        transformation="none",
        order=(0, 0, 0),
        seasonal_order=(0, 0, 0, 0),
        origins=4,
        diagnostic_lags=12,
    )

    assert len(evaluation) == 4
    assert evaluation["Origen"].lt(evaluation["Fecha"]).all()
    assert {"RMSE", "MASE"}.issubset(metrics)


def test_maintenance_generation_does_not_shift_month_when_localizing(monkeypatch) -> None:
    class FakeXM:
        @staticmethod
        def fetch_list(dataset: str, _entity: str) -> pd.DataFrame:
            if dataset == "ListadoRecursos":
                return pd.DataFrame(
                    {
                        "Code": ["GTPE"],
                        "Name": ["Guatapé"],
                        "CompanyCode": ["EPMG"],
                        "EnerSource": ["HIDRAULICA"],
                    }
                )
            return pd.DataFrame({"Code": ["EPMG"], "Name": ["EPM"]})

        @staticmethod
        def fetch(*_args, **_kwargs) -> SimpleNamespace:
            return SimpleNamespace(
                data=pd.DataFrame(
                    {
                        "datetime": [pd.Timestamp("2024-01-15T05:00:00Z")],
                        "entity_id": ["GTPE"],
                        "value": [10.0],
                    }
                )
            )

    builder = ColombiaMonthlyBuilder(xm_provider=FakeXM())
    monkeypatch.setattr(
        builder,
        "_cached_block",
        lambda _key, loader: (loader(), None, False),
    )
    data, *_ = builder._generation(
        "2024-01-15",
        "2024-01-15",
        None,
        selected_options={"generation_national", "generation_resources"},
    )
    total = data[data["series_id"].eq("col_generacion_total_gwh_mes")]

    assert total["datetime"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")
    assert total["value"].iloc[0] == pytest.approx(10.0)


def test_modeling_page_estimates_default_supervised_flow() -> None:
    script = """
import numpy as np
import pandas as pd
import came.ui.pages.modeling_forecast as page
from came.ui.monthly_access import ModelingData

n = 84
time = np.arange(n, dtype=float)
wide = pd.DataFrame({
    "datetime": pd.date_range("2018-01-01", periods=n, freq="MS", tz="UTC"),
    "Demanda": 200 + 0.7 * time + 5 * np.sin(2 * np.pi * time / 12),
    "Precio": 250 + 0.4 * time + 8 * np.cos(2 * np.pi * time / 12),
})
monthly = ModelingData("COL", "Colombia", wide, pd.DataFrame(), {})
page._integrated_or_message = lambda **_kwargs: monthly
page.page_modeling()
"""
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    estimate = next(button for button in app.button if button.label == "Estimar y evaluar")
    app = estimate.click().run()

    assert not app.exception
    assert any(metric.label.casefold() == "mae" for metric in app.metric)

    family = next(radio for radio in app.radio if radio.label == "Familia de modelos")
    app = family.set_value("Series temporales").run()
    forecast = next(button for button in app.button if button.label == "Validar y pronosticar")
    app = forecast.click().run()

    assert not app.exception
    assert any(metric.label.casefold() == "mase" for metric in app.metric)

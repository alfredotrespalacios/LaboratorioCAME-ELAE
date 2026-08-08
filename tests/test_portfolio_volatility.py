from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from came.analytics.portfolio import PortfolioInputs, lognormal_parameters, simulate_portfolio
from came.analytics.volatility import fit_sarima, fit_sarima_garch


def test_lognormal_parameters_reproduce_mean_and_sd() -> None:
    mu, sigma = lognormal_parameters(250, 90)
    reproduced_mean = np.exp(mu + sigma**2 / 2)
    reproduced_variance = (np.exp(sigma**2) - 1) * np.exp(2 * mu + sigma**2)
    assert reproduced_mean == pytest.approx(250)
    assert np.sqrt(reproduced_variance) == pytest.approx(90)


def test_portfolio_uses_bounded_generation_and_common_draws() -> None:
    inputs = PortfolioInputs(
        generation_mean_gwh=100,
        generation_sd_gwh=20,
        generation_max_gwh=180,
        price_mean_cop_kwh=250,
        price_sd_cop_kwh=80,
        target_correlation=-0.25,
        contract_share=0.7,
        contract_price_cop_kwh=260,
        iterations=2500,
        seed=7,
    )
    result = simulate_portfolio(inputs)
    assert len(result.simulations) == 2500
    assert result.simulations["Generación_GWh"].between(0, 180).all()
    assert result.realized_correlation == pytest.approx(-0.25, abs=0.04)
    unhedged = result.simulations["Precio_bolsa_COP_kWh"] * result.simulations["Generación_GWh"]
    assert np.allclose(unhedged, result.simulations["Ventas_sin_cobertura_millones_COP"])
    assert {"VaR_1_pct", "CVaR_1_pct", "VaR_5_pct", "CVaR_5_pct"}.issubset(result.performance)


def _synthetic_series(length: int = 144) -> pd.Series:
    rng = np.random.default_rng(42)
    index = pd.date_range("2012-01-01", periods=length, freq="MS")
    values = 100 + 0.2 * np.arange(length) + 8 * np.sin(np.arange(length) * 2 * np.pi / 12) + rng.normal(0, 2, length)
    return pd.Series(values, index=index)


def test_sarima_returns_original_and_standardized_residuals() -> None:
    result = fit_sarima(
        _synthetic_series(), order=(1, 0, 0), seasonal_order=(0, 0, 0, 12), horizon=6
    )
    assert len(result.forecast) == 6
    assert {"residual", "residual_estandarizado"}.issubset(result.residuals)
    assert np.isfinite(result.aic)


def test_sarima_garch_returns_conditional_bands() -> None:
    result = fit_sarima_garch(
        _synthetic_series(180),
        sarima_order=(1, 0, 0),
        seasonal_order=(0, 0, 0, 12),
        garch_order=(1, 1),
        horizon=4,
    )
    assert len(result.combined_forecast) == 4
    assert {"inferior_95_garch", "superior_95_garch"}.issubset(result.combined_forecast)
    assert "residual_estandarizado" in result.standardized_residuals


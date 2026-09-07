"""Simulación mensual de un portafolio de generación con cobertura."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import kurtosis, skew

from came.errors import DataQualityError

MAX_ITERATIONS = 1_000_000


@dataclass(frozen=True)
class PortfolioInputs:
    generation_mean_gwh: float
    generation_sd_gwh: float
    generation_max_gwh: float
    price_mean_cop_kwh: float
    price_sd_cop_kwh: float
    target_correlation: float = 0.0
    contract_share: float = 0.70
    contract_price_cop_kwh: float = 0.0
    iterations: int = 1_000
    trm_cop_usd: float = 4_000.0
    seed: int | None = 42
    contracted_generation_gwh: float | None = None


@dataclass
class PortfolioResult:
    simulations: pd.DataFrame
    summary: pd.DataFrame
    percentiles: pd.DataFrame
    performance: pd.DataFrame
    latent_correlation: float
    realized_correlation: float
    excluded_nonpositive_prices: int = 0


SENSITIVITY_METRICS = ("Media", "Desviación estándar", "VaR", "CVaR", "M-CVaR")


def lognormal_parameters(mean: float, sd: float) -> tuple[float, float]:
    if mean <= 0 or sd < 0:
        raise DataQualityError("La media del precio debe ser positiva y su desviación no negativa.")
    variance_ratio = (sd / mean) ** 2
    sigma = float(np.sqrt(np.log1p(variance_ratio)))
    mu = float(np.log(mean) - 0.5 * sigma**2)
    return mu, sigma


def _validate_inputs(inputs: PortfolioInputs) -> None:
    if not 1 <= inputs.iterations <= MAX_ITERATIONS:
        raise DataQualityError(f"Las iteraciones deben estar entre 1 y {MAX_ITERATIONS:,}.")
    if inputs.generation_sd_gwh <= 0:
        raise DataQualityError("La desviación de generación debe ser mayor que cero.")
    if inputs.generation_max_gwh <= 0:
        raise DataQualityError("El máximo de generación debe ser mayor que cero.")
    if not 0 <= inputs.generation_mean_gwh <= inputs.generation_max_gwh:
        raise DataQualityError("La media de generación debe estar entre cero y su máximo.")
    if not -0.99 <= inputs.target_correlation <= 0.99:
        raise DataQualityError("La correlación objetivo debe estar entre -0,99 y 0,99.")
    if inputs.trm_cop_usd <= 0:
        raise DataQualityError("La TRM debe ser positiva.")
    if not -2 <= inputs.contract_share <= 2:
        raise DataQualityError("El porcentaje contratado debe estar entre -200 % y 200 %.")


def _pilot_realized_correlation(
    latent: float,
    z_generation: np.ndarray,
    z_independent: np.ndarray,
    inputs: PortfolioInputs,
    price_mu: float,
    price_sigma: float,
) -> float:
    generation = inputs.generation_mean_gwh + inputs.generation_sd_gwh * z_generation
    accepted = (generation >= 0) & (generation <= inputs.generation_max_gwh)
    if accepted.sum() < 100:
        return np.nan
    z_price = latent * z_generation + np.sqrt(max(1 - latent**2, 0)) * z_independent
    price = np.exp(price_mu + price_sigma * z_price)
    return float(np.corrcoef(generation[accepted], price[accepted])[0, 1])


def calibrate_latent_correlation(inputs: PortfolioInputs, pilot_size: int = 80_000) -> float:
    price_mu, price_sigma = lognormal_parameters(inputs.price_mean_cop_kwh, inputs.price_sd_cop_kwh)
    rng = np.random.default_rng(inputs.seed)
    z_generation = rng.standard_normal(pilot_size)
    z_independent = rng.standard_normal(pilot_size)

    def objective(latent: float) -> float:
        realized = _pilot_realized_correlation(
            latent, z_generation, z_independent, inputs, price_mu, price_sigma
        )
        return realized - inputs.target_correlation

    low_value = objective(-0.999)
    high_value = objective(0.999)
    if not np.isfinite(low_value) or not np.isfinite(high_value):
        raise DataQualityError("No fue posible calibrar la correlación con estos parámetros.")
    if low_value * high_value > 0:
        return -0.999 if abs(low_value) < abs(high_value) else 0.999
    return float(brentq(objective, -0.999, 0.999, xtol=1e-5, maxiter=80))


def _draw_rejection_pairs(
    inputs: PortfolioInputs,
    latent: float,
    price_mu: float,
    price_sigma: float,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(inputs.seed)
    generation_parts: list[np.ndarray] = []
    price_parts: list[np.ndarray] = []
    accepted_total = 0
    attempts = 0
    while accepted_total < inputs.iterations:
        remaining = inputs.iterations - accepted_total
        batch = min(max(int(remaining * 1.8), 10_000), 400_000)
        z_generation = rng.standard_normal(batch)
        z_independent = rng.standard_normal(batch)
        generation = inputs.generation_mean_gwh + inputs.generation_sd_gwh * z_generation
        accepted = (generation >= 0) & (generation <= inputs.generation_max_gwh)
        if accepted.any():
            z_price = latent * z_generation + np.sqrt(max(1 - latent**2, 0)) * z_independent
            price = np.exp(price_mu + price_sigma * z_price)
            take = min(remaining, int(accepted.sum()))
            generation_parts.append(generation[accepted][:take])
            price_parts.append(price[accepted][:take])
            accepted_total += take
        attempts += batch
        if attempts > max(inputs.iterations * 500, 2_000_000):
            raise DataQualityError(
                "La normal propuesta casi nunca cae entre cero y el máximo; revise media, desviación y máximo."
            )
    return np.concatenate(generation_parts), np.concatenate(price_parts)


def _distribution_summary(values: np.ndarray, name: str) -> dict[str, float | str]:
    return {
        "Escenario": name,
        "Promedio": float(np.mean(values)),
        "Desviación": float(np.std(values, ddof=1)),
        "Sesgo": float(skew(values, bias=False)),
        "Curtosis": float(kurtosis(values, fisher=False, bias=False)),
        "Mínimo": float(np.min(values)),
        "Máximo": float(np.max(values)),
        "Probabilidad_ventas_negativas_pct": float(np.mean(values < 0) * 100),
    }


def _risk_metrics(values: np.ndarray, name: str) -> dict[str, float | str]:
    var_1 = float(np.quantile(values, 0.01))
    var_5 = float(np.quantile(values, 0.05))
    cvar_1 = float(values[values <= var_1].mean())
    cvar_5 = float(values[values <= var_5].mean())
    mean = float(values.mean())
    return {
        "Escenario": name,
        "Promedio": mean,
        "VaR_1_pct": var_1,
        "CVaR_1_pct": cvar_1,
        "VaR_5_pct": var_5,
        "CVaR_5_pct": cvar_5,
        "M-CVaR_5_pct": mean - cvar_5,
    }


def simulate_portfolio(inputs: PortfolioInputs) -> PortfolioResult:
    _validate_inputs(inputs)
    price_mu, price_sigma = lognormal_parameters(inputs.price_mean_cop_kwh, inputs.price_sd_cop_kwh)
    latent = calibrate_latent_correlation(inputs)
    generation, price = _draw_rejection_pairs(inputs, latent, price_mu, price_sigma)
    realized = float(np.corrcoef(generation, price)[0, 1])
    contracted_generation = (
        float(inputs.contracted_generation_gwh)
        if inputs.contracted_generation_gwh is not None
        else float(inputs.generation_mean_gwh)
    )
    sales_unhedged = price * generation
    sales_hedged = sales_unhedged + (
        inputs.contract_share * contracted_generation * (inputs.contract_price_cop_kwh - price)
    )
    simulations = pd.DataFrame(
        {
            "Generación_GWh": generation,
            "Precio_bolsa_COP_kWh": price,
            "Ventas_sin_cobertura_millones_COP": sales_unhedged,
            "Ventas_con_cobertura_millones_COP": sales_hedged,
        }
    )
    simulations["Ventas_sin_cobertura_millones_USD"] = sales_unhedged / inputs.trm_cop_usd
    simulations["Ventas_con_cobertura_millones_USD"] = sales_hedged / inputs.trm_cop_usd

    summary = pd.DataFrame(
        [
            _distribution_summary(sales_unhedged, "Sin cobertura"),
            _distribution_summary(sales_hedged, "Con cobertura"),
        ]
    )
    quantiles = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
    percentiles = pd.DataFrame(
        {
            "Percentil": [int(value * 100) for value in quantiles],
            "Sin_cobertura_millones_COP": np.quantile(sales_unhedged, quantiles),
            "Con_cobertura_millones_COP": np.quantile(sales_hedged, quantiles),
        }
    )
    performance = pd.DataFrame(
        [
            _risk_metrics(sales_unhedged, "Sin cobertura"),
            _risk_metrics(sales_hedged, "Con cobertura"),
        ]
    )
    return PortfolioResult(
        simulations=simulations,
        summary=summary,
        percentiles=percentiles,
        performance=performance,
        latent_correlation=latent,
        realized_correlation=realized,
    )


def _outcome_metrics(values: np.ndarray) -> dict[str, float]:
    """Métricas de resultado financiero; VaR y CVaR conservan su signo."""

    var = float(np.quantile(values, 0.05))
    cvar = float(values[values <= var].mean())
    mean = float(np.mean(values))
    return {
        "Media": mean,
        "Desviación estándar": float(np.std(values, ddof=1)),
        "VaR": var,
        "CVaR": cvar,
        "M-CVaR": mean - cvar,
    }


def _contracted_sales(
    simulations: pd.DataFrame,
    *,
    share: float,
    expected_generation_gwh: float,
    contract_price_cop_kwh: float,
) -> np.ndarray:
    generation = simulations["Generación_GWh"].to_numpy(dtype=float)
    price = simulations["Precio_bolsa_COP_kWh"].to_numpy(dtype=float)
    return price * generation + share * expected_generation_gwh * (contract_price_cop_kwh - price)


def sensitivity_contract_share(
    inputs: PortfolioInputs,
    shares: object,
) -> pd.DataFrame:
    """Sensibilidad a contratación con correlación y precio fijos."""

    base = simulate_portfolio(inputs)
    rows = []
    for share in np.asarray(shares, dtype=float):
        if not -2 <= share <= 2:
            raise DataQualityError("Todos los porcentajes deben estar entre -200 % y 200 %.")
        values = _contracted_sales(
            base.simulations,
            share=float(share),
            expected_generation_gwh=inputs.generation_mean_gwh,
            contract_price_cop_kwh=inputs.contract_price_cop_kwh,
        )
        rows.append(
            {
                "Porcentaje contratado": float(share),
                "Correlación": inputs.target_correlation,
                "Precio contrato COP/kWh": inputs.contract_price_cop_kwh,
                **_outcome_metrics(values),
            }
        )
    return pd.DataFrame(rows)


def sensitivity_contract_correlation(
    inputs: PortfolioInputs,
    shares: object,
    correlations: object,
) -> pd.DataFrame:
    """Sensibilidad 10×5; cada correlación reutiliza los mismos normales base por semilla."""

    rows: list[dict[str, float]] = []
    shares_array = np.asarray(shares, dtype=float)
    correlations_array = np.asarray(correlations, dtype=float)
    for correlation in correlations_array:
        if not -0.99 <= correlation <= 0.99:
            raise DataQualityError("Las correlaciones deben estar entre -0,99 y 0,99.")
        correlated_inputs = PortfolioInputs(**({**vars(inputs), "target_correlation": float(correlation)}))
        simulations = simulate_portfolio(correlated_inputs).simulations
        for share in shares_array:
            values = _contracted_sales(
                simulations,
                share=float(share),
                expected_generation_gwh=inputs.generation_mean_gwh,
                contract_price_cop_kwh=inputs.contract_price_cop_kwh,
            )
            rows.append(
                {
                    "Porcentaje contratado": float(share),
                    "Correlación": float(correlation),
                    "Precio contrato COP/kWh": inputs.contract_price_cop_kwh,
                    **_outcome_metrics(values),
                }
            )
    return pd.DataFrame(rows)


def sensitivity_contract_price(
    inputs: PortfolioInputs,
    shares: object,
    contract_prices: object,
) -> pd.DataFrame:
    """Sensibilidad 10×5 a contratación y precio con correlación fija."""

    simulations = simulate_portfolio(inputs).simulations
    rows: list[dict[str, float]] = []
    for price in np.asarray(contract_prices, dtype=float):
        if price < 0:
            raise DataQualityError("Los precios contractuales no pueden ser negativos.")
        for share in np.asarray(shares, dtype=float):
            values = _contracted_sales(
                simulations,
                share=float(share),
                expected_generation_gwh=inputs.generation_mean_gwh,
                contract_price_cop_kwh=float(price),
            )
            rows.append(
                {
                    "Porcentaje contratado": float(share),
                    "Correlación": inputs.target_correlation,
                    "Precio contrato COP/kWh": float(price),
                    **_outcome_metrics(values),
                }
            )
    return pd.DataFrame(rows)


def historical_portfolio_parameters(
    generation: pd.Series,
    price: pd.Series,
    *,
    minimum_observations: int = 8,
) -> dict[str, float | int]:
    generation_values = pd.to_numeric(generation, errors="coerce").dropna()
    price_values = pd.to_numeric(price, errors="coerce")
    nonpositive = int((price_values <= 0).sum())
    price_values = price_values[price_values > 0].dropna()
    if min(len(generation_values), len(price_values)) < minimum_observations:
        raise DataQualityError(
            f"Se requieren al menos {minimum_observations} observaciones válidas del mismo mes."
        )
    return {
        "generation_mean_gwh": float(generation_values.mean()),
        "generation_sd_gwh": float(generation_values.std(ddof=1)),
        "price_mean_cop_kwh": float(price_values.mean()),
        "price_sd_cop_kwh": float(price_values.std(ddof=1)),
        "excluded_nonpositive_prices": nonpositive,
    }

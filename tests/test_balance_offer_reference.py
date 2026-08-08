"""Contraste reproducible contra los dos Excel pedagógicos entregados."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from came.analytics.balance import calculate_balance
from came.analytics.offer_curve import build_offer_curve
from came.ui.pages.offer_curve import _calculated_offer_table, _scenario_inputs


def test_balance_matches_reference_workbook_normal_and_nino() -> None:
    # Valores de las filas 17:27 de “Modelo rápido 2026 03”.
    table = pd.DataFrame(
        {
            "Tecnología": [
                "Hidráulica",
                "Gas",
                "Carbón",
                "ACPM",
                "Combustóleo",
                "Bagazo",
                "Solar",
                "GLP",
                "Jet-A1",
                "Eólica",
                "Biogás",
            ],
            "CEN_MW": [13211.467, 3145.19, 1652.9, 818, 266, 200.29, 1906.01203, 52, 48, 0, 14.65],
            "FP_normal": [0.52, 0.9, 0.9, 0.9, 0.9, 0.9, 0.17, 0.9, 0.9, 0.25, 0.9],
            "FP_nino": [0.35, 0.9, 0.9, 0.9, 0.9, 0.9, 0.17, 0.9, 0.9, 0.25, 0.9],
        }
    )
    normal = calculate_balance(table, demand_gwh_day=235, factor_column="FP_normal")
    nino = calculate_balance(table, demand_gwh_day=237.35, factor_column="FP_nino")
    assert normal.generation_available_gwh_day == pytest.approx(306.51148524240006)
    assert normal.margin == pytest.approx(0.3043041925208514)
    assert nino.generation_available_gwh_day == pytest.approx(252.6086998824)
    assert nino.margin == pytest.approx(0.06428776019549187)
    assert normal.uncovered_demand_gwh_day == 0
    assert nino.uncovered_demand_gwh_day == 0


def test_offer_curve_matches_reference_availability_and_marginal_unit() -> None:
    # Filas 26:36 de “Modelo rápido Un Periodo”.
    capacity = [13220.207, 3135.39, 1654.9, 903, 266, 200.29, 1303.62636, 52, 50, 0, 11.05]
    factor = [0.4954044862403434, 0.9, 0.9, 0.9, 0.9, 0.9, 0.17, 0.9, 0.9, 0.25, 0.9]
    table = pd.DataFrame(
        {
            "Tecnología": [
                "Hidráulica",
                "Gas",
                "Carbón",
                "ACPM",
                "Combustóleo",
                "Bagazo",
                "Solar",
                "GLP",
                "Jet-A1",
                "Eólica",
                "Biogás",
            ],
            "Disponibilidad_GWh_día": [
                value * fp * 24 / 1000 for value, fp in zip(capacity, factor, strict=True)
            ],
            "Precio_COP_kWh": [95, 450, 230, 600, 620, 96, 94, 450, 700, 93, 400],
        }
    )
    result = build_offer_curve(table, demand_gwh_day=240.83315642)
    assert result.total_available_gwh_day == pytest.approx(297.99200011262377)
    assert result.marginal_discrete_price == 450
    assert result.marginal_technology == "Gas"
    assert result.deficit_gwh_day == 0
    assert all(math.isfinite(fit.estimated_price) for fit in result.fits if not fit.warning)


def test_offer_curve_does_not_extrapolate_a_deficit() -> None:
    table = pd.DataFrame(
        {"Tecnología": ["Solar"], "Disponibilidad_GWh_día": [10.0], "Precio_COP_kWh": [80.0]}
    )
    result = build_offer_curve(table, demand_gwh_day=12.0)
    assert result.deficit_gwh_day == 2.0
    assert result.marginal_discrete_price is None
    assert all(fit.estimated_price is None for fit in result.fits)


def test_offer_scenarios_show_cen_factor_availability_and_price() -> None:
    seed = pd.DataFrame(
        {
            "Tecnología": ["Hidráulica"],
            "CEN_MW": [10_000.0],
            "FP_normal": [0.52],
            "FP_nino": [0.35],
            "Precio_COP_kWh": [95.0],
        }
    )

    normal = _calculated_offer_table(_scenario_inputs(seed, nino=False))
    nino = _calculated_offer_table(_scenario_inputs(seed, nino=True))

    expected_columns = {
        "CEN_MW",
        "Factor_planta",
        "Disponibilidad_GWh_día",
        "Precio_COP_kWh",
    }
    assert expected_columns.issubset(normal.columns)
    assert normal.loc[0, "Disponibilidad_GWh_día"] == pytest.approx(124.8)
    assert nino.loc[0, "Disponibilidad_GWh_día"] == pytest.approx(84.0)

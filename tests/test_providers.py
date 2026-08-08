from __future__ import annotations

import pandas as pd
import pytest

from came.data.providers.chile import ChileProvider
from came.data.providers.omie import OmieProvider
from came.data.providers.redata import REDataProvider
from came.data.providers.xm import XMProvider


def test_xm_hourly_parser_supports_quarter_hours() -> None:
    values = {f"Hour{period:02d}": period for period in range(1, 97)}
    payload = {
        "Items": [{"Date": "2026-08-07", "HourlyEntities": [{"Id": "Sistema", "Values": values}]}]
    }
    frame = XMProvider._parse_items([payload], container="HourlyEntities", frequency="hourly")
    assert len(frame) == 96
    assert frame["datetime"].iloc[-1] - frame["datetime"].iloc[0] == pd.Timedelta(
        hours=23, minutes=45
    )


def test_omie_parser_supports_quarter_hours() -> None:
    text = "\n".join(f"2026;8;7;{period};50.5;48.2;" for period in range(1, 97))
    frame = OmieProvider.parse_price_file(text)
    assert len(frame) == 96
    assert frame["price_spain"].iloc[0] == 50.5


def test_redata_flattens_nested_balance_payload() -> None:
    nested = [
        {
            "id": "group",
            "attributes": {
                "content": [
                    {
                        "id": "hydro",
                        "attributes": {
                            "title": "Hidráulica",
                            "values": [{"datetime": "2024-01-01", "value": 10}],
                        },
                    }
                ]
            },
        }
    ]
    flattened = REDataProvider._flatten_included(nested)
    assert flattened[0]["id"] == "hydro"


def test_chile_parsers_and_national_weighted_price() -> None:
    costs = b"Fecha;Hora;Barra;Costo Marginal USD/MWh\n01/01/2024;1;A;10\n01/01/2024;1;B;30\n"
    demand = b"Fecha;Hora;Barra;Demanda MWh\n01/01/2024;1;A;1\n01/01/2024;1;B;3\n"
    cost_frame = ChileProvider.parse_marginal_cost(costs, "costos.csv")
    demand_frame = ChileProvider.parse_demand(demand, "demanda.csv")
    national, by_time = ChileProvider.national_weighted_price(cost_frame, demand_frame)
    assert national == pytest.approx(25)
    assert by_time.loc[0, "bars"] == 2


def test_chile_generation_parser_recognizes_technology() -> None:
    content = (
        b"Fecha;Hora;Tecnologia;Generacion MWh\n01/01/2024;1;Solar;10\n01/01/2024;2;Solar;12\n"
    )
    frame = ChileProvider.parse_generation(content, "generacion.csv")
    assert frame["generation_mwh"].sum() == pytest.approx(22)
    assert frame["technology"].unique().tolist() == ["Solar"]

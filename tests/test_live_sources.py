from __future__ import annotations

import pytest

from came.data.providers.omie import OmieProvider
from came.data.providers.redata import REDataProvider
from came.data.providers.xm import XMProvider

pytestmark = pytest.mark.live


def test_xm_live_contract() -> None:
    status = XMProvider(timeout=30).healthcheck()
    assert status["ok"]
    assert status["sample_unit"] == "GWh"


def test_redata_live_contract() -> None:
    assert REDataProvider(timeout=30).healthcheck()["ok"]


def test_omie_live_contract() -> None:
    assert OmieProvider(timeout=30).healthcheck()["ok"]

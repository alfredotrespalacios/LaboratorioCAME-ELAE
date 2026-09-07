"""Series macroclimáticas oficiales usadas en la base integrada."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pandas as pd

from came.data.providers.base import DataProvider
from came.errors import SourceContractError, SourceUnavailableError


class MacroProvider(DataProvider):
    source_name = "Fuentes macroclimáticas oficiales"
    trm_url = "https://www.datos.gov.co/resource/32sa-8pi3.json"
    oni_url = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

    def fetch_trm(self, start: object, end: object) -> pd.DataFrame:
        params = {
            "$limit": 50000,
            "$where": (
                f"vigenciadesde >= '{pd.Timestamp(start):%Y-%m-%dT00:00:00.000}' AND "
                f"vigenciadesde <= '{pd.Timestamp(end):%Y-%m-%dT23:59:59.999}'"
            ),
            "$order": "vigenciadesde",
        }
        try:
            response = self.session.get(self.trm_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceUnavailableError(f"No fue posible consultar la TRM oficial: {exc}") from exc
        data = pd.DataFrame(payload)
        if data.empty:
            return pd.DataFrame(columns=["datetime", "TRM_COP_USD"])
        date_col = "vigenciadesde" if "vigenciadesde" in data else data.columns[0]
        value_candidates = [column for column in data if "valor" in column.casefold()]
        if not value_candidates:
            raise SourceContractError(f"La fuente TRM cambió de columnas: {list(data.columns)}")
        result = pd.DataFrame(
            {
                "datetime": pd.to_datetime(data[date_col], errors="coerce", utc=True),
                "TRM_COP_USD": pd.to_numeric(data[value_candidates[0]], errors="coerce"),
            }
        )
        return result.dropna().sort_values("datetime").reset_index(drop=True)

    def fetch_oni(self) -> pd.DataFrame:
        try:
            response = self.session.get(self.oni_url, timeout=self.timeout)
            response.raise_for_status()
        except Exception as exc:
            raise SourceUnavailableError(f"No fue posible consultar ONI de NOAA: {exc}") from exc
        try:
            raw = pd.read_fwf(StringIO(response.text))
        except Exception as exc:
            raise SourceContractError(f"No fue posible leer ONI: {exc}") from exc
        columns = {str(column).casefold(): column for column in raw.columns}
        year_col = columns.get("year") or columns.get("yr")
        season_col = columns.get("seas") or columns.get("season")
        oni_col = columns.get("anom") or columns.get("oni")
        if not all((year_col, season_col, oni_col)):
            raise SourceContractError(f"NOAA cambió la tabla ONI: {list(raw.columns)}")
        season_month = {
            "DJF": 1,
            "JFM": 2,
            "FMA": 3,
            "MAM": 4,
            "AMJ": 5,
            "MJJ": 6,
            "JJA": 7,
            "JAS": 8,
            "ASO": 9,
            "SON": 10,
            "OND": 11,
            "NDJ": 12,
        }
        result = pd.DataFrame(
            {
                "year": pd.to_numeric(raw[year_col], errors="coerce"),
                "month": raw[season_col].astype(str).str.upper().map(season_month),
                "ENSO_ONI": pd.to_numeric(raw[oni_col], errors="coerce"),
            }
        ).dropna()
        result["datetime"] = pd.to_datetime(
            dict(year=result["year"].astype(int), month=result["month"].astype(int), day=1),
            utc=True,
        )
        result["Niño"] = (result["ENSO_ONI"] >= 0.5).astype(int)
        result["Niña"] = (result["ENSO_ONI"] <= -0.5).astype(int)
        return result[["datetime", "ENSO_ONI", "Niño", "Niña"]].reset_index(drop=True)

    def healthcheck(self) -> dict[str, Any]:
        oni = self.fetch_oni()
        return {"source": self.source_name, "ok": not oni.empty, "oni_rows": len(oni)}

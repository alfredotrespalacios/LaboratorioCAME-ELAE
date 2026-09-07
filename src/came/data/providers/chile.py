"""Parser de descargas oficiales del Coordinador Eléctrico Nacional de Chile."""

from __future__ import annotations

from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from came.analytics.aggregation import weighted_price
from came.data.providers.base import DataProvider
from came.errors import SourceContractError, SourceUnavailableError


class ChileProvider(DataProvider):
    source_name = "Coordinador Eléctrico Nacional de Chile"
    costs_url = "https://www.coordinador.cl/costos-marginales/"
    demand_url = "https://www.coordinador.cl/operacion/graficos/operacion-real/demanda-real/"

    @staticmethod
    def _read_file(content: bytes, filename: str) -> pd.DataFrame:
        suffix = Path(filename).suffix.casefold()
        if suffix in {".xlsx", ".xls"}:
            try:
                return pd.read_excel(BytesIO(content))
            except Exception as exc:
                raise SourceContractError(
                    f"No fue posible leer el Excel oficial de Chile: {exc}"
                ) from exc
        decoded = content.decode("utf-8-sig", errors="replace")
        for separator in ("\t", ";", ","):
            frame = pd.read_csv(StringIO(decoded), sep=separator)
            if len(frame.columns) > 1:
                return frame
        raise SourceContractError("El archivo chileno no tiene una estructura tabular reconocible.")

    @staticmethod
    def _find_column(frame: pd.DataFrame, words: tuple[str, ...]) -> str | None:
        normalized = {column: str(column).casefold() for column in frame.columns}
        for column, text in normalized.items():
            if all(word in text for word in words):
                return str(column)
        return None

    @classmethod
    def parse_marginal_cost(cls, content: bytes, filename: str) -> pd.DataFrame:
        raw = cls._read_file(content, filename)
        date_col = cls._find_column(raw, ("fecha",))
        hour_col = cls._find_column(raw, ("hora",)) or cls._find_column(raw, ("period",))
        bar_col = cls._find_column(raw, ("barra",))
        cost_col = (
            cls._find_column(raw, ("costo", "marginal"))
            or cls._find_column(raw, ("cmg",))
            or cls._find_column(raw, ("usd", "mwh"))
        )
        if not all((date_col, bar_col, cost_col)):
            raise SourceContractError(
                f"No se identificaron fecha, barra y costo marginal. Columnas: {list(raw.columns)}"
            )
        timestamp = pd.to_datetime(raw[date_col], errors="coerce", dayfirst=True)
        if hour_col:
            hour = pd.to_numeric(raw[hour_col], errors="coerce").fillna(1)
            timestamp = timestamp + pd.to_timedelta(hour.clip(lower=1) - 1, unit="h")
        result = pd.DataFrame(
            {
                "datetime": timestamp,
                "bar": raw[bar_col].astype(str),
                "marginal_cost_usd_mwh": pd.to_numeric(raw[cost_col], errors="coerce"),
            }
        ).dropna(subset=["datetime", "marginal_cost_usd_mwh"])
        result["datetime"] = (
            result["datetime"]
            .dt.tz_localize("America/Santiago", ambiguous="NaT", nonexistent="shift_forward")
            .dt.tz_convert("UTC")
        )
        return result.reset_index(drop=True)

    @classmethod
    def parse_demand(cls, content: bytes, filename: str) -> pd.DataFrame:
        raw = cls._read_file(content, filename)
        date_col = cls._find_column(raw, ("fecha",))
        hour_col = cls._find_column(raw, ("hora",)) or cls._find_column(raw, ("period",))
        bar_col = cls._find_column(raw, ("barra",))
        demand_col = cls._find_column(raw, ("demanda",)) or cls._find_column(raw, ("retiro",))
        if not date_col or not demand_col:
            raise SourceContractError(
                f"No se identificaron fecha y demanda. Columnas: {list(raw.columns)}"
            )
        timestamp = pd.to_datetime(raw[date_col], errors="coerce", dayfirst=True)
        if hour_col:
            hour = pd.to_numeric(raw[hour_col], errors="coerce").fillna(1)
            timestamp = timestamp + pd.to_timedelta(hour.clip(lower=1) - 1, unit="h")
        result = pd.DataFrame(
            {
                "datetime": timestamp,
                "bar": raw[bar_col].astype(str) if bar_col else "Sistema",
                "demand_mwh": pd.to_numeric(raw[demand_col], errors="coerce"),
            }
        ).dropna(subset=["datetime", "demand_mwh"])
        result["datetime"] = (
            result["datetime"]
            .dt.tz_localize("America/Santiago", ambiguous="NaT", nonexistent="shift_forward")
            .dt.tz_convert("UTC")
        )
        return result.reset_index(drop=True)

    @classmethod
    def parse_generation(cls, content: bytes, filename: str) -> pd.DataFrame:
        """Lee una exportación oficial de generación real por tecnología o fuente."""

        raw = cls._read_file(content, filename)
        date_col = cls._find_column(raw, ("fecha",))
        hour_col = cls._find_column(raw, ("hora",)) or cls._find_column(raw, ("period",))
        technology_col = (
            cls._find_column(raw, ("tecnolog",))
            or cls._find_column(raw, ("fuente",))
            or cls._find_column(raw, ("combustible",))
            or cls._find_column(raw, ("tipo", "gener"))
        )
        generation_col = (
            cls._find_column(raw, ("generacion",))
            or cls._find_column(raw, ("generación",))
            or cls._find_column(raw, ("energia",))
            or cls._find_column(raw, ("energía",))
        )
        if not date_col or not generation_col:
            raise SourceContractError(
                f"No se identificaron fecha y generación. Columnas: {list(raw.columns)}"
            )
        timestamp = pd.to_datetime(raw[date_col], errors="coerce", dayfirst=True)
        if hour_col:
            hour = pd.to_numeric(raw[hour_col], errors="coerce").fillna(1)
            timestamp = timestamp + pd.to_timedelta(hour.clip(lower=1) - 1, unit="h")
        result = pd.DataFrame(
            {
                "datetime": timestamp,
                "technology": raw[technology_col].astype(str)
                if technology_col
                else "Sin tecnología identificada",
                "generation_mwh": pd.to_numeric(raw[generation_col], errors="coerce"),
            }
        ).dropna(subset=["datetime", "generation_mwh"])
        result["datetime"] = (
            result["datetime"]
            .dt.tz_localize("America/Santiago", ambiguous="NaT", nonexistent="shift_forward")
            .dt.tz_convert("UTC")
        )
        return result.dropna(subset=["datetime"]).reset_index(drop=True)

    @staticmethod
    def national_weighted_price(
        costs: pd.DataFrame, demand: pd.DataFrame
    ) -> tuple[float, pd.DataFrame]:
        merged = costs.merge(demand, on=["datetime", "bar"], how="inner")
        if merged.empty:
            raise SourceContractError("Costo y demanda no coinciden por fecha y barra.")
        national = weighted_price(merged["marginal_cost_usd_mwh"], merged["demand_mwh"])
        by_time = (
            merged.groupby("datetime", as_index=False)
            .apply(
                lambda group: pd.Series(
                    {
                        "price_usd_mwh": weighted_price(
                            group["marginal_cost_usd_mwh"], group["demand_mwh"]
                        ),
                        "demand_mwh": group["demand_mwh"].sum(),
                        "bars": group["bar"].nunique(),
                    }
                ),
                include_groups=False,
            )
            .reset_index(drop=True)
        )
        return national, by_time

    def fetch_configured_url(self, url: str, filename: str | None = None) -> bytes:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            raise SourceUnavailableError(
                f"No fue posible descargar el archivo oficial de Chile: {exc}"
            ) from exc

    def healthcheck(self) -> dict[str, Any]:
        try:
            response = self.session.get(self.costs_url, timeout=self.timeout)
            ok = response.status_code == 200
        except Exception:
            ok = False
        return {
            "source": self.source_name,
            "ok": ok,
            "mode": "descarga oficial TSV/XLSX; carga manual cuando Cloudflare/Qlik impide automatizar",
        }

"""Descarga y parser de precios públicos del mercado diario OMIE."""

from __future__ import annotations

from typing import Any

import pandas as pd

from came.data.providers.base import DataProvider
from came.errors import SourceContractError, SourceUnavailableError
from came.quality import inspect_quality
from came.schema import DataResult, SeriesMeta, ensure_canonical


class OmieProvider(DataProvider):
    source_name = "OMIE"
    download_url = "https://www.omie.es/en/file-download"
    source_url = "https://www.omie.es/en/file-access-list"

    @staticmethod
    def parse_price_file(text: str) -> pd.DataFrame:
        lines = [line.strip() for line in text.replace("\ufeff", "").splitlines() if line.strip()]
        rows: list[list[str]] = []
        for line in lines:
            parts = [part.strip() for part in line.split(";")]
            if len(parts) >= 7 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
                rows.append(parts[:7])
        if not rows:
            raise SourceContractError("El archivo OMIE no contiene filas de precios reconocibles.")
        data = pd.DataFrame(
            rows,
            columns=["year", "month", "day", "period", "price_spain", "price_portugal", "empty"],
        )
        for column in ("year", "month", "day", "period", "price_spain", "price_portugal"):
            data[column] = pd.to_numeric(data[column], errors="coerce")
        data = data.dropna(subset=["year", "month", "day", "period", "price_spain"])
        base_date = pd.to_datetime(
            dict(
                year=data["year"].astype(int),
                month=data["month"].astype(int),
                day=data["day"].astype(int),
            )
        )
        max_period = int(data["period"].max())
        minutes = 15 if max_period > 30 else 60
        data["datetime"] = base_date + pd.to_timedelta((data["period"] - 1) * minutes, unit="m")
        data["datetime"] = (
            data["datetime"]
            .dt.tz_localize("Europe/Madrid", ambiguous="NaT", nonexistent="shift_forward")
            .dt.tz_convert("UTC")
        )
        return data.drop(columns="empty").reset_index(drop=True)

    def fetch_day(self, day: object) -> pd.DataFrame:
        timestamp = pd.Timestamp(day)
        filename = f"marginalpdbc_{timestamp:%Y%m%d}.1"
        try:
            response = self.session.get(
                self.download_url,
                params={"filename": filename, "parents": "marginalpdbc"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except Exception as exc:
            raise SourceUnavailableError(f"OMIE no pudo descargar {filename}: {exc}") from exc
        return self.parse_price_file(response.content.decode("latin-1", errors="replace"))

    def fetch_prices(self, start: object, end: object) -> DataResult:
        days = pd.date_range(
            pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D"
        )
        frames: list[pd.DataFrame] = []
        warnings: list[str] = []
        for day in days:
            try:
                frames.append(self.fetch_day(day))
            except SourceUnavailableError as exc:
                warnings.append(str(exc))
        if not frames:
            raise SourceUnavailableError(
                "OMIE no devolvió ningún archivo en el periodo solicitado."
            )
        raw = pd.concat(frames, ignore_index=True)
        data = pd.DataFrame(
            {
                "datetime": raw["datetime"],
                "value": raw["price_spain"],
                "entity_id": "ES",
                "entity_name": "España",
                "entity_type": "Zona de precio",
                "period": raw["period"],
                "price_portugal": raw["price_portugal"],
            }
        )
        meta = SeriesMeta(
            country="ESP",
            source="OMIE",
            dataset="marginalpdbc",
            variable_id="day_ahead_price_spain",
            variable_name="Precio horario del mercado diario — España",
            unit="EUR/MWh",
            frequency="hourly" if raw["period"].max() <= 30 else "quarter-hourly",
            aggregation="original",
            entity_type="Zona de precio",
            timezone="Europe/Madrid",
            methodology="Ficheros diarios públicos marginalpdbc; precio español de cada periodo.",
            source_url=self.source_url,
        )
        canonical = ensure_canonical(data, meta)
        report = inspect_quality(
            canonical,
            requested_start=start,
            requested_end=end,
            frequency="hourly" if meta.frequency == "hourly" else "quarter-hourly",
            allow_negative=True,
        )
        return DataResult(
            canonical,
            meta,
            report.coverage,
            warnings + report.warnings,
            raw_columns=list(raw.columns),
        )

    def healthcheck(self) -> dict[str, Any]:
        frame = self.fetch_day("2026-08-07")
        return {
            "source": self.source_name,
            "ok": len(frame) in {24, 25, 92, 96, 100},
            "sample_rows": len(frame),
        }

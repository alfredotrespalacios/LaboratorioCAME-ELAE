"""Conector a la API oficial REData de Red Eléctrica."""

from __future__ import annotations

from typing import Any

import pandas as pd

from came.config import REDATA_SYSTEMS
from came.data.providers.base import DataProvider
from came.errors import SourceContractError, SourceUnavailableError
from came.quality import inspect_quality
from came.schema import DataResult, SeriesMeta, ensure_canonical


class REDataProvider(DataProvider):
    source_name = "Red Eléctrica — REData"
    base_url = "https://apidatos.ree.es/es/datos/{category}/{widget}"
    documentation_url = "https://www.ree.es/es/datos/apidatos"

    @staticmethod
    def _flatten_included(included: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for item in included:
            attributes = item.get("attributes") or {}
            content = attributes.get("content")
            if isinstance(content, list):
                flattened.extend(REDataProvider._flatten_included(content))
            if isinstance(attributes.get("values"), list):
                flattened.append(item)
        return flattened

    def fetch_widget(
        self,
        category: str,
        widget: str,
        start: object,
        end: object,
        *,
        time_trunc: str = "day",
        system: str = "Península",
        unit: str = "MWh",
    ) -> DataResult:
        params = {
            "start_date": pd.Timestamp(start).strftime("%Y-%m-%dT00:00"),
            "end_date": pd.Timestamp(end).strftime("%Y-%m-%dT23:59"),
            "time_trunc": time_trunc,
        }
        if system != "Península":
            geo_limit, geo_id = REDATA_SYSTEMS[system]
            params.update(
                {"geo_trunc": "electric_system", "geo_limit": geo_limit, "geo_ids": geo_id}
            )
        url = self.base_url.format(category=category, widget=widget)
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceUnavailableError(f"REData no respondió para {widget}: {exc}") from exc
        if payload.get("errors"):
            details = "; ".join(error.get("detail", "error") for error in payload["errors"])
            raise SourceUnavailableError(f"REData informó: {details}")
        items = self._flatten_included(payload.get("included", []))
        rows: list[dict[str, Any]] = []
        for item in items:
            attributes = item.get("attributes") or {}
            title = attributes.get("title") or item.get("type") or item.get("id")
            for value in attributes.get("values", []):
                rows.append(
                    {
                        "datetime": value.get("datetime"),
                        "value": value.get("value"),
                        "percentage": value.get("percentage"),
                        "entity_id": str(item.get("id") or title),
                        "entity_name": str(title),
                        "entity_type": str(attributes.get("type") or item.get("groupId") or "Indicador"),
                        "group": item.get("groupId"),
                    }
                )
        data = pd.DataFrame(rows)
        if data.empty:
            raise SourceContractError(f"REData no devolvió valores para {widget} en el periodo.")
        meta = SeriesMeta(
            country="ESP",
            source="REData — Red Eléctrica",
            dataset=f"{category}/{widget}",
            variable_id=widget,
            variable_name=str(payload.get("data", {}).get("attributes", {}).get("title") or widget),
            unit=unit,
            frequency={"hour": "hourly", "day": "daily", "month": "monthly", "year": "annual"}[time_trunc],
            aggregation="publicada por REData",
            entity_type="Indicador",
            timezone="Europe/Madrid",
            methodology=f"API REST oficial REData; sistema {system}; agregación {time_trunc}.",
            source_url=self.documentation_url,
        )
        canonical = ensure_canonical(data, meta)
        report = inspect_quality(
            canonical,
            requested_start=start,
            requested_end=end,
            frequency=meta.frequency,
            allow_negative=True,
        )
        return DataResult(
            canonical, meta, report.coverage, report.warnings, raw_columns=list(data.columns)
        )

    def healthcheck(self) -> dict[str, Any]:
        result = self.fetch_widget(
            "demanda", "evolucion", "2024-01-01", "2024-01-03", time_trunc="day"
        )
        return {"source": self.source_name, "ok": len(result.data) == 3, "sample_rows": len(result.data)}


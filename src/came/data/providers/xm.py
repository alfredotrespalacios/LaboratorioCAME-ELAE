"""Conector síncrono a la API pública de XM con descarga mensual por lotes."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from came.data.providers.base import DataProvider
from came.errors import SourceContractError, SourceUnavailableError
from came.quality import inspect_quality
from came.schema import DataResult, SeriesMeta, ensure_canonical


class XMProvider(DataProvider):
    source_name = "XM"
    lists_url = "https://servapibi.xm.com.co/Lists"
    base_url = "https://servapibi.xm.com.co/{period}"
    source_url = "https://sinergox.xm.com.co/"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._catalog: pd.DataFrame | None = None

    def catalog(self, refresh: bool = False) -> pd.DataFrame:
        if self._catalog is not None and not refresh:
            return self._catalog.copy()
        try:
            response = self.session.post(
                self.lists_url,
                json={"MetricId": "ListadoMetricas"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceUnavailableError(
                f"No fue posible consultar el catálogo de XM: {exc}"
            ) from exc
        rows: list[dict[str, Any]] = []
        for item in payload.get("Items", []):
            for entity in item.get("ListEntities", []):
                row = {"Id": entity.get("Id"), "Date": item.get("Date")}
                row.update(entity.get("Values", {}))
                rows.append(row)
        catalog = pd.DataFrame(rows)
        required = {"MetricId", "MetricName", "Entity", "Type", "MetricUnits"}
        if catalog.empty or not required.issubset(catalog.columns):
            raise SourceContractError(
                "El catálogo de XM cambió y no contiene las columnas esperadas."
            )
        catalog["MaxDays"] = pd.to_numeric(catalog.get("MaxDays"), errors="coerce")
        self._catalog = catalog
        return catalog.copy()

    def metric_info(self, metric_id: str, entity: str) -> pd.Series:
        catalog = self.catalog()
        match = catalog[(catalog["MetricId"] == metric_id) & (catalog["Entity"] == entity)]
        if match.empty:
            raise SourceContractError(f"XM no publica {metric_id} para la entidad {entity}.")
        return match.iloc[0]

    @staticmethod
    def _period_info(entity_type: str) -> tuple[str, str]:
        mapping = {
            "HourlyEntities": ("hourly", "HourlyEntities"),
            "DailyEntities": ("daily", "DailyEntities"),
            "MonthlyEntities": ("monthly", "MonthlyEntities"),
            "AnnualEntities": ("annual", "AnnualEntities"),
            "ListsEntities": ("lists", "ListEntities"),
        }
        if entity_type not in mapping:
            raise SourceContractError(f"Tipo de entidad XM no soportado: {entity_type}")
        return mapping[entity_type]

    @staticmethod
    def _chunks(
        start: object, end: object, max_days: int
    ) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        if start_ts > end_ts:
            raise ValueError("La fecha inicial no puede ser posterior a la final.")
        chunks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
        current = start_ts
        while current <= end_ts:
            chunk_end = min(current + pd.Timedelta(days=max_days - 1), end_ts)
            chunks.append((current, chunk_end))
            current = chunk_end + pd.Timedelta(days=1)
        return chunks

    def _post_data(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url.format(period=endpoint)
        try:
            response = self.session.post(url, json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceUnavailableError(
                f"XM no respondió para {body.get('MetricId')} ({body.get('StartDate')} a {body.get('EndDate')}): {exc}"
            ) from exc
        if "Items" not in payload:
            raise SourceContractError("La respuesta de XM no contiene Items.")
        return payload

    @staticmethod
    def _parse_items(
        payloads: list[dict[str, Any]],
        *,
        container: str,
        frequency: str,
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for payload in payloads:
            for item in payload.get("Items", []):
                day = pd.Timestamp(item.get("Date"))
                entities = item.get(container, [])
                for entity in entities:
                    entity_type = entity.get("Id") or "Sistema"
                    values = entity.get("Values") or {}
                    code = (
                        entity.get("Code")
                        or values.get("code")
                        or values.get("Code")
                        or entity_type
                    )
                    if frequency == "hourly":
                        value_items = []
                        for key, value in values.items():
                            if str(key).lower().startswith("hour"):
                                digits = "".join(
                                    character for character in str(key) if character.isdigit()
                                )
                                if digits:
                                    value_items.append((int(digits), value))
                        max_period = max((period for period, _ in value_items), default=24)
                        minutes = 15 if max_period > 30 else 60
                        for period, value in value_items:
                            rows.append(
                                {
                                    "datetime": day + pd.Timedelta(minutes=(period - 1) * minutes),
                                    "value": value,
                                    "entity_type": entity_type,
                                    "entity_id": code,
                                    "entity_name": code,
                                    "period": period,
                                }
                            )
                    else:
                        value = entity.get("Value")
                        if value is None:
                            value = values.get("Value") or values.get("value")
                        rows.append(
                            {
                                "datetime": day,
                                "value": value,
                                "entity_type": entity_type,
                                "entity_id": code,
                                "entity_name": code,
                            }
                        )
        data = pd.DataFrame(rows)
        if data.empty:
            return pd.DataFrame(
                columns=["datetime", "value", "entity_type", "entity_id", "entity_name"]
            )
        data["datetime"] = (
            pd.to_datetime(data["datetime"], errors="coerce")
            .dt.tz_localize("America/Bogota")
            .dt.tz_convert("UTC")
        )
        data["value"] = pd.to_numeric(data["value"], errors="coerce")
        return data.dropna(subset=["datetime", "value"]).reset_index(drop=True)

    def fetch(
        self,
        metric_id: str,
        entity: str,
        start: object,
        end: object,
        *,
        filters: list[str] | None = None,
        target_unit: str | None = None,
    ) -> DataResult:
        info = self.metric_info(metric_id, entity)
        endpoint, container = self._period_info(str(info["Type"]))
        if endpoint == "lists":
            raise SourceContractError("Use fetch_list para una colección de listas.")
        max_days = int(info.get("MaxDays") or 31)
        payloads: list[dict[str, Any]] = []
        for chunk_start, chunk_end in self._chunks(start, end, max(max_days, 1)):
            body = {
                "MetricId": metric_id,
                "StartDate": chunk_start.date().isoformat(),
                "EndDate": chunk_end.date().isoformat(),
                "Entity": entity,
                "Filter": filters or [],
            }
            payloads.append(self._post_data(endpoint, body))
        data = self._parse_items(payloads, container=container, frequency=endpoint)
        original_unit = str(info.get("MetricUnits") or "")
        unit = original_unit
        conversion = 1.0
        if target_unit:
            conversions = {
                ("kWh", "MWh"): 1e-3,
                ("kWh", "GWh"): 1e-6,
                ("MWh", "GWh"): 1e-3,
                ("kW", "MW"): 1e-3,
            }
            conversion = conversions.get((original_unit, target_unit), 1.0)
            if (original_unit, target_unit) not in conversions and original_unit != target_unit:
                raise SourceContractError(
                    f"No se definió conversión segura de {original_unit} a {target_unit}."
                )
            data["value"] = data["value"] * conversion
            unit = target_unit
        meta = SeriesMeta(
            country="COL",
            source="XM",
            dataset=metric_id,
            variable_id=metric_id,
            variable_name=str(info["MetricName"]),
            unit=unit,
            frequency=endpoint,
            aggregation="original",
            entity_type=entity,
            timezone="America/Bogota",
            methodology=(
                f"Consulta pública XM por lotes de máximo {max_days} días. "
                f"Conversión aplicada: factor {conversion:g}."
            ),
            source_url=self.source_url,
        )
        canonical = ensure_canonical(data, meta)
        report = inspect_quality(
            canonical,
            requested_start=start,
            requested_end=end,
            frequency=endpoint,
            allow_negative=original_unit in {"COP", "COP/kWh"},
        )
        return DataResult(
            data=canonical,
            meta=meta,
            coverage=report.coverage,
            warnings=report.warnings,
            raw_columns=list(data.columns),
        )

    def fetch_list(self, metric_id: str, entity: str = "Sistema") -> pd.DataFrame:
        info = self.metric_info(metric_id, entity)
        endpoint, container = self._period_info(str(info["Type"]))
        if endpoint != "lists":
            raise SourceContractError(f"{metric_id}/{entity} no es una colección de listas.")
        payload = self._post_data("lists", {"MetricId": metric_id, "Entity": entity})
        rows: list[dict[str, Any]] = []
        for item in payload.get("Items", []):
            for list_entity in item.get(container, []):
                row = {"Date": item.get("Date"), "Entity": list_entity.get("Id")}
                row.update(list_entity.get("Values") or {})
                rows.append(row)
        return pd.DataFrame(rows)

    def healthcheck(self) -> dict[str, Any]:
        catalog = self.catalog(refresh=True)
        sample = self.fetch(
            "DemaSIN", "Sistema", date(2024, 1, 1), date(2024, 1, 2), target_unit="GWh"
        )
        return {
            "source": self.source_name,
            "ok": len(catalog) > 0 and len(sample.data) == 2,
            "catalog_rows": len(catalog),
            "sample_rows": len(sample.data),
            "sample_unit": sample.meta.unit,
        }

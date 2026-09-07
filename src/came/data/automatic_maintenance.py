"""Construcción automática y reanudable de la base mensual colombiana.

La página de Streamlit entrega una sola selección. Este módulo la divide en etapas
pequeñas, conserva cada resultado en disco y recompone un único paquete al final.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import pandas as pd

from came.data.colombia_selection import selection_catalog
from came.data.maintenance import (
    BuildResult,
    ColombiaMonthlyBuilder,
    ProgressCallback,
    XMMonthlyTask,
)
from came.data.monthly_store import (
    LONG_COLUMNS,
    merge_monthly_data,
    normalize_monthly_data,
    runtime_storage_root,
)

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


@dataclass(frozen=True)
class AutomaticStage:
    """Etapa operativa que puede completarse y recuperarse de forma independiente."""

    key: str
    label: str
    options: tuple[str, ...]


@dataclass(frozen=True)
class AutomaticStageEvent:
    """Avance global de una construcción automática."""

    current: int
    total: int
    label: str
    status: str


AutomaticStageCallback = Callable[[AutomaticStageEvent], None]


@dataclass
class AutomaticBuildOutcome:
    """Resultado final y trazabilidad necesaria para futuras actualizaciones."""

    result: BuildResult
    selected_options: list[str]
    option_series: dict[str, list[str]] = field(default_factory=dict)
    completed_stages: list[str] = field(default_factory=list)
    reused_published: list[str] = field(default_factory=list)
    pending_stages: list[str] = field(default_factory=list)
    failed_stages: list[str] = field(default_factory=list)
    run_complete: bool = False
    processed_this_run: int = 0
    run_ledger: list[dict[str, object]] = field(default_factory=list)


AutomaticCheckpointCallback = Callable[[AutomaticBuildOutcome], None]


BASE_STAGES = (
    AutomaticStage("demand", "Demanda nacional", ("demand",)),
    AutomaticStage("spot_price", "Precio de bolsa nacional", ("spot_price",)),
    AutomaticStage("contract_regulated", "Contratos regulados", ("contract_regulated",)),
    AutomaticStage(
        "contract_nonregulated",
        "Contratos no regulados",
        ("contract_nonregulated",),
    ),
    AutomaticStage("scarcity_price", "Precio de escasez", ("scarcity_price",)),
    AutomaticStage("restrictions", "Restricciones", ("restrictions",)),
    AutomaticStage("reservoir", "Volumen útil de embalse", ("reservoir",)),
    AutomaticStage("inflows", "Aportes hídricos", ("inflows",)),
    AutomaticStage("contract_mc", "Índice MC", ("contract_mc",)),
    AutomaticStage("availability", "Disponibilidad de generación", ("availability",)),
    AutomaticStage(
        "imports_exports",
        "Importaciones y exportaciones",
        ("imports_exports",),
    ),
    AutomaticStage("market_exposure", "Exposición y compras en bolsa", ("market_exposure",)),
    AutomaticStage("capacity", "Capacidad efectiva neta", ("capacity",)),
    AutomaticStage("fuel_offers", "Ofertas de gas y carbón", ("fuel_offers",)),
    AutomaticStage("unserved", "Demanda no atendida", ("unserved",)),
    AutomaticStage("macro", "TRM y ciclo ENSO", ("trm", "enso")),
    AutomaticStage(
        "generation",
        "Generación nacional, tecnologías, empresas y plantas",
        (
            "generation_national",
            "generation_technology",
            "generation_companies",
            "generation_resources",
        ),
    ),
)

CALENDAR_SERIES = {
    "col_dias_mes",
    "col_tiempo",
    "col_trimestre_1",
    "col_trimestre_2",
    "col_trimestre_3",
}


def selected_options_from_metadata(metadata: dict[str, object]) -> set[str]:
    """Lee la selección estructurada o recupera la nota creada por versiones anteriores."""

    selected = metadata.get("target_options") or metadata.get("selected_options")
    if isinstance(selected, list):
        return {str(value) for value in selected if str(value).strip()}
    for note in metadata.get("notes", []) if isinstance(metadata.get("notes"), list) else []:
        match = re.search(r"Variables seleccionadas:\s*(.+?)\.?$", str(note))
        if match:
            return {
                value.strip()
                for value in match.group(1).split(",")
                if value.strip()
            }
    return set()


def option_series_from_metadata(metadata: dict[str, object]) -> dict[str, list[str]]:
    """Recupera el mapa opción-serie escrito por una construcción automática."""

    raw = metadata.get("option_series")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[str]] = {}
    for option, series in raw.items():
        if isinstance(series, list):
            result[str(option)] = sorted({str(value) for value in series if str(value).strip()})
    return result


def _series_for_option(series_ids: set[str], option: str) -> list[str]:
    exact: dict[str, set[str]] = {
        "demand": {"col_demanda_gwh_mes", "col_demanda_gwh_dia"},
        "spot_price": {"col_precio_bolsa_cop_kwh"},
        "contract_regulated": {"col_precio_contrato_regulado_cop_kwh"},
        "contract_nonregulated": {"col_precio_contrato_no_regulado_cop_kwh"},
        "scarcity_price": {"col_precio_escasez_cop_kwh"},
        "restrictions": {"col_restricciones_cop_mes"},
        "reservoir": {"col_volumen_util_gwh"},
        "inflows": {"col_aportes_hidricos_gwh_mes", "col_aportes_hidricos_gwh_dia"},
        "contract_mc": {"col_precio_mc_cop_kwh"},
        "capacity": {"col_cen_total_mw"},
        "unserved": {
            "col_demanda_no_atendida_gwh_mes",
            "col_demanda_no_atendida_gwh_dia",
        },
        "trm": {"col_trm_cop_usd"},
        "enso": {"col_enso_oni", "col_enso_nino", "col_enso_nina"},
    }
    prefixes: dict[str, tuple[str, ...]] = {
        "generation_national": (
            "col_generacion_total_",
            "col_generacion_tecnologia_nacional_",
            "col_generacion_no_hidraulica_",
        ),
        "generation_technology": ("col_generacion_tecnologia_",),
        "generation_companies": ("col_generacion_empresa_",),
        "generation_resources": ("col_generacion_recurso_",),
        "fuel_offers": ("col_precio_oferta_",),
        "availability": ("col_availability_",),
        "imports_exports": ("col_imports_exports_", "col_import", "col_export"),
        "market_exposure": ("col_market_exposure_", "col_expos", "col_compras_netas"),
    }
    matches = set(exact.get(option, set())).intersection(series_ids)
    matches.update(
        series_id
        for series_id in series_ids
        if any(series_id.startswith(prefix) for prefix in prefixes.get(option, ()))
    )
    return sorted(matches)


def infer_option_series(
    data: pd.DataFrame,
    selected_options: Iterable[str],
) -> dict[str, list[str]]:
    """Infiere trazabilidad para paquetes 1.5.0 que todavía no tenían mapa estructurado."""

    if data.empty or "series_id" not in data:
        return {}
    series_ids = set(data["series_id"].dropna().astype(str)) - CALENDAR_SERIES
    return {
        option: matches
        for option in selected_options
        if (matches := _series_for_option(series_ids, str(option)))
    }


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._") or "stage"


def _frame_or_empty(frame: pd.DataFrame | None) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _plain_timestamp(value: object) -> pd.Timestamp:
    """Normaliza fechas de control sin zona horaria para compararlas de forma segura."""

    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp


class AutomaticStageStore:
    """Conserva resultados de etapas completas fuera del repositorio observado."""

    def __init__(self, build_id: str) -> None:
        self.root = runtime_storage_root(create=True) / "automatic" / "COL" / _safe_name(build_id)
        self.root.mkdir(parents=True, exist_ok=True)

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def run_path(self) -> Path:
        return self.root / "run.json"

    def load_run(self) -> dict[str, object]:
        if not self.run_path.is_file():
            return {}
        try:
            value = json.loads(self.run_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}

    def save_run(self, value: dict[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.run_path.with_name(f".{self.run_path.name}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(self.run_path)

    @staticmethod
    def signature(
        stage: AutomaticStage,
        start: object,
        end: object,
        extra_tasks: list[XMMonthlyTask] | None = None,
    ) -> str:
        payload = {
            "stage": stage.key,
            "options": list(stage.options),
            "start": str(pd.Timestamp(start).date()),
            "end": str(pd.Timestamp(end).date()),
            "extra": [
                [task.metric_id, task.entity, task.series_id, task.aggregation_mode]
                for task in (extra_tasks or [])
            ],
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return f"{_safe_name(stage.key)}_{digest}"

    def _directory(self, signature: str) -> Path:
        return self.root / "stages" / signature

    def load(self, signature: str) -> BuildResult | None:
        directory = self._directory(signature)
        manifest_path = directory / "stage.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            data = pd.read_parquet(directory / "data.parquet")
            status = (
                pd.read_parquet(directory / "status.parquet")
                if manifest.get("has_status")
                else pd.DataFrame()
            )
            validation = (
                pd.read_parquet(directory / "validation.parquet")
                if manifest.get("has_validation")
                else pd.DataFrame()
            )
            catalogs = {
                name: pd.read_parquet(directory / filename)
                for name, filename in manifest.get("catalogs", {}).items()
            }
            return BuildResult(
                country="COL",
                data=normalize_monthly_data(data),
                status=status,
                validation=validation,
                catalogs=catalogs,
                warnings=[str(value) for value in manifest.get("warnings", [])],
                errors=[],
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def save(self, signature: str, result: BuildResult) -> None:
        if result.errors:
            raise ValueError("No se guarda como terminada una etapa con errores bloqueantes.")
        destination = self._directory(signature)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        staging = destination.with_name(f".{destination.name}.building-{uuid.uuid4().hex[:8]}")
        staging.mkdir(parents=True, exist_ok=False)
        try:
            normalize_monthly_data(result.data).to_parquet(
                staging / "data.parquet", index=False, compression="zstd"
            )
            has_status = not _frame_or_empty(result.status).empty
            has_validation = not _frame_or_empty(result.validation).empty
            if has_status:
                result.status.to_parquet(
                    staging / "status.parquet", index=False, compression="zstd"
                )
            if has_validation:
                result.validation.to_parquet(
                    staging / "validation.parquet", index=False, compression="zstd"
                )
            catalog_files: dict[str, str] = {}
            for index, (name, frame) in enumerate(result.catalogs.items(), start=1):
                if frame.empty:
                    continue
                filename = f"catalog_{index:02d}.parquet"
                frame.to_parquet(staging / filename, index=False, compression="zstd")
                catalog_files[str(name)] = filename
            (staging / "stage.json").write_text(
                json.dumps(
                    {
                        "warnings": list(result.warnings),
                        "catalogs": catalog_files,
                        "has_status": has_status,
                        "has_validation": has_validation,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            staging.replace(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def planned_stages(
    selected_options: set[str],
    extra_tasks: list[XMMonthlyTask] | None = None,
) -> list[AutomaticStage]:
    """Crea una cola estable; las familias que comparten fuente se procesan juntas."""

    stages: list[AutomaticStage] = []
    for definition in BASE_STAGES:
        options = tuple(option for option in definition.options if option in selected_options)
        if options:
            stages.append(AutomaticStage(definition.key, definition.label, options))
    if extra_tasks:
        stages.append(AutomaticStage("xm_extra", "Variables adicionales de XM", ()))
    return stages


def _merge_catalogs(results: list[BuildResult], selected_options: set[str]) -> dict[str, pd.DataFrame]:
    catalogs: dict[str, list[pd.DataFrame]] = {}
    for result in results:
        for name, frame in result.catalogs.items():
            if name == "Selección de variables" or frame.empty:
                continue
            catalogs.setdefault(name, []).append(frame)
    merged: dict[str, pd.DataFrame] = {
        "Selección de variables": selection_catalog().assign(
            Seleccionada=lambda frame: frame["Clave"].isin(selected_options)
        )
    }
    for name, frames in catalogs.items():
        combined = pd.concat(frames, ignore_index=True)
        merged[name] = combined.drop_duplicates().reset_index(drop=True)
    return merged


class ColombiaAutomaticBuilder:
    """Orquesta toda la selección sin pedir ejecuciones manuales por variable."""

    def __init__(self, *, timeout: int = 45, build_id: str = "colombia_automatic") -> None:
        self.build_id = build_id
        self.builder = ColombiaMonthlyBuilder(timeout=timeout, build_id=build_id)
        self.stages = AutomaticStageStore(build_id)

    def clear(self) -> None:
        self.builder.clear_checkpoints()
        self.stages.clear()

    @staticmethod
    def _stage_period(
        stage: AutomaticStage,
        default_start: object,
        end: object,
        existing: pd.DataFrame,
        option_series: dict[str, list[str]],
        repair_coverage: bool,
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        first = pd.Timestamp(default_start).normalize()
        final = pd.Timestamp(end).normalize()
        if not repair_coverage or existing.empty:
            return first, final
        identifiers = {
            series_id
            for option in stage.options
            for series_id in option_series.get(option, [])
        }
        if not identifiers:
            return first, final
        subset = existing[existing["series_id"].astype(str).isin(identifiers)].copy()
        if subset.empty:
            return first, final
        datetimes = pd.to_datetime(subset["datetime"], utc=True)
        grouped = datetimes.groupby(subset["series_id"].astype(str))
        earliest = grouped.min()
        latest = grouped.max()
        if latest.empty:
            return first, final
        # Si el paquete parcial comienza después del inicio solicitado, todavía falta la historia
        # anterior y la etapa debe reconstruirse desde el principio. En cambio, cuando ya cubre el
        # inicio, se continúa exactamente desde el mes posterior a su dato más reciente.
        earliest_option = earliest.min().tz_localize(None).normalize()
        if earliest_option > first:
            return first, final
        # Algunas opciones producen series por planta o empresa que terminan legítimamente cuando
        # sale un recurso. La cobertura de la opción se mide por su observación más reciente, no por
        # la serie individual más antigua, para no reconstruir años completos en cada actualización.
        latest_option = latest.max().tz_localize(None).normalize()
        current_month = pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M").to_timestamp()
        if final.to_period("M") == current_month.to_period("M") and latest_option >= current_month:
            # El mes en curso se conserva como parcial y puede volver a consultarse en una
            # actualización posterior. Los puntos de avance locales evitan repetirlo dentro de
            # la misma ejecución reanudable.
            return max(first, current_month), final
        option_next = latest_option + pd.offsets.MonthBegin()
        return option_next.normalize(), final

    def build(
        self,
        start: object,
        end: object,
        *,
        existing: pd.DataFrame | None = None,
        selected_options: set[str],
        extra_tasks: list[XMMonthlyTask] | None = None,
        completed_options: set[str] | None = None,
        existing_option_series: dict[str, list[str]] | None = None,
        repair_coverage: bool = False,
        source_callback: ProgressCallback | None = None,
        stage_callback: AutomaticStageCallback | None = None,
        checkpoint_callback: AutomaticCheckpointCallback | None = None,
        max_new_stages: int | None = None,
        time_budget_seconds: float | None = None,
        existing_ledger: list[dict[str, object]] | None = None,
    ) -> AutomaticBuildOutcome:
        base = normalize_monthly_data(
            existing if existing is not None else pd.DataFrame(columns=LONG_COLUMNS)
        )
        selected = set(selected_options)
        completed_published = set(completed_options or set())
        option_series = dict(existing_option_series or {})
        # La versión 1.5.0 solo guardaba la selección en una nota. Inferir contra toda la selección
        # permite aprovechar una variable parcial y continuarla, aunque todavía no cubra el periodo
        # completo solicitado.
        inferred = infer_option_series(base, selected.union(completed_published))
        for option, series in inferred.items():
            option_series.setdefault(option, series)

        queue = planned_stages(selected, extra_tasks)
        results: list[BuildResult] = []
        completed_labels: list[str] = []
        reused_published: list[str] = []
        failed_labels: list[str] = []
        blocking_errors: list[str] = []
        failed_statuses: list[pd.DataFrame] = []
        synthetic_status: list[dict[str, object]] = []
        processed_this_run = 0
        started_at = monotonic()
        ledger_by_stage = {
            str(
                entry.get("ledger_id")
                or (
                    f"{entry.get('stage_key')}:{entry.get('period_start')}:"
                    f"{entry.get('period_end')}"
                )
            ): dict(entry)
            for entry in (existing_ledger or [])
            if isinstance(entry, dict) and entry.get("stage_key")
        }
        local_run = self.stages.load_run()
        for entry in local_run.get("run_ledger", []) if isinstance(local_run, dict) else []:
            if isinstance(entry, dict) and entry.get("stage_key"):
                ledger_id = str(
                    entry.get("ledger_id")
                    or (
                        f"{entry.get('stage_key')}:{entry.get('period_start')}:"
                        f"{entry.get('period_end')}"
                    )
                )
                ledger_by_stage[ledger_id] = dict(entry)

        def compose(pending: list[str]) -> AutomaticBuildOutcome:
            data = base.copy()
            for approved in results:
                data = merge_monthly_data(data, approved.data)
            data = ColombiaMonthlyBuilder._add_non_hydraulic(data)
            data = ColombiaMonthlyBuilder._add_reference_derivatives(data)

            status_frames = [result.status for result in results if not result.status.empty]
            status_frames.extend(frame for frame in failed_statuses if not frame.empty)
            if synthetic_status:
                status_frames.insert(0, pd.DataFrame(synthetic_status))
            validations = [result.validation for result in results if not result.validation.empty]
            final = BuildResult(
                country="COL",
                data=data,
                status=(
                    pd.concat(status_frames, ignore_index=True)
                    if status_frames
                    else pd.DataFrame()
                ),
                validation=(
                    pd.concat(validations, ignore_index=True)
                    .drop_duplicates()
                    .reset_index(drop=True)
                    if validations
                    else pd.DataFrame()
                ),
                catalogs=_merge_catalogs(results, selected),
                warnings=[warning for result in results for warning in result.warnings],
                errors=list(blocking_errors),
            )
            outcome = AutomaticBuildOutcome(
                final,
                sorted(selected),
                option_series,
                completed_labels,
                reused_published,
                pending,
                failed_labels,
                not pending and not failed_labels,
                processed_this_run,
                sorted(
                    ledger_by_stage.values(),
                    key=lambda entry: (
                        str(entry.get("stage_key")),
                        str(entry.get("period_start")),
                        str(entry.get("period_end")),
                    ),
                ),
            )
            self.stages.save_run(
                {
                    "build_id": self.build_id,
                    "updated_at_utc": datetime.now(UTC).isoformat(),
                    "requested_start": str(pd.Timestamp(start).date()),
                    "requested_end": str(pd.Timestamp(end).date()),
                    "target_options": sorted(selected),
                    "completed_stages": completed_labels,
                    "reused_published": reused_published,
                    "pending_stages": pending,
                    "failed_stages": failed_labels,
                    "run_complete": outcome.run_complete,
                    "run_ledger": outcome.run_ledger,
                }
            )
            return outcome

        def checkpoint(outcome: AutomaticBuildOutcome) -> None:
            if checkpoint_callback is None or outcome.result.data.empty:
                return
            try:
                checkpoint_callback(outcome)
            except Exception:
                LOGGER.exception(
                    "CAME mantenimiento no pudo publicar el punto de avance build_id=%s",
                    self.build_id,
                )

        for index, stage in enumerate(queue, start=1):
            if stage.options and set(stage.options).issubset(completed_published):
                reused_published.append(stage.label)
                synthetic_status.append(
                    {
                        "Fuente": "Base publicada",
                        "Variable": stage.label,
                        "Periodo": f"{pd.Timestamp(start).date()} a {pd.Timestamp(end).date()}",
                        "Estado": "Reutilizado",
                        "Detalle": "Cobertura completa detectada en el paquete publicado.",
                    }
                )
                if stage_callback:
                    stage_callback(
                        AutomaticStageEvent(index, len(queue), stage.label, "Reutilizado")
                    )
                continue

            stage_start, stage_end = self._stage_period(
                stage,
                start,
                end,
                base,
                option_series,
                repair_coverage,
            )
            if stage_start > stage_end:
                reused_published.append(stage.label)
                synthetic_status.append(
                    {
                        "Fuente": "Base publicada",
                        "Variable": stage.label,
                        "Periodo": str(stage_end.date()),
                        "Estado": "Al día",
                        "Detalle": "No se detectaron meses pendientes para esta etapa.",
                    }
                )
                if stage_callback:
                    stage_callback(
                        AutomaticStageEvent(index, len(queue), stage.label, "Al día")
                    )
                continue
            stage_start_plain = _plain_timestamp(stage_start)
            stage_end_plain = _plain_timestamp(stage_end)
            current_month_start = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize().replace(
                day=1
            )

            confirmed_no_data: dict[str, object] | None = None
            for entry in ledger_by_stage.values():
                if entry.get("stage_key") != stage.key or entry.get("status") != "no_data":
                    continue
                try:
                    recorded_start = _plain_timestamp(entry.get("period_start"))
                    recorded_end = _plain_timestamp(entry.get("period_end"))
                except (TypeError, ValueError):
                    continue
                if (
                    recorded_start <= stage_start_plain
                    and recorded_end >= stage_end_plain
                    and stage_end_plain < current_month_start
                ):
                    confirmed_no_data = entry
                    break
            if confirmed_no_data is not None:
                reused_published.append(stage.label)
                synthetic_status.append(
                    {
                        "Fuente": "Registro de actualización",
                        "Variable": stage.label,
                        "Periodo": f"{stage_start.date()} a {stage_end.date()}",
                        "Estado": "Sin datos confirmado",
                        "Detalle": (
                            "El periodo ya fue consultado correctamente y la fuente no "
                            "publicó observaciones."
                        ),
                    }
                )
                if stage_callback:
                    stage_callback(
                        AutomaticStageEvent(
                            index,
                            len(queue),
                            stage.label,
                            "Sin datos confirmado",
                        )
                    )
                continue
            signature = self.stages.signature(
                stage,
                stage_start,
                stage_end,
                extra_tasks if stage.key == "xm_extra" else None,
            )
            # El mes actual es parcial y puede cambiar entre ejecuciones. Nunca se da por
            # definitivo un resultado local que lo incluya.
            result = (
                None
                if stage_end_plain >= current_month_start
                else self.stages.load(signature)
            )
            if result is not None:
                status_label = "Reutilizado"
            else:
                reached_count_limit = (
                    max_new_stages is not None and processed_this_run >= max_new_stages
                )
                reached_time_limit = (
                    time_budget_seconds is not None
                    and processed_this_run > 0
                    and monotonic() - started_at >= time_budget_seconds
                )
                if reached_count_limit or reached_time_limit:
                    pending = [item.label for item in queue[index - 1 :]]
                    LOGGER.info(
                        "CAME mantenimiento pausa controlada build_id=%s procesadas=%s pendientes=%s",
                        self.build_id,
                        processed_this_run,
                        len(pending),
                    )
                    return compose(pending)
                status_label = "Procesando"
                processed_this_run += 1
                if stage_callback:
                    stage_callback(
                        AutomaticStageEvent(index, len(queue), stage.label, status_label)
                    )
                try:
                    LOGGER.info(
                        "CAME mantenimiento inicia etapa build_id=%s etapa=%s periodo=%s/%s intento=%s",
                        self.build_id,
                        stage.key,
                        stage_start.date(),
                        stage_end.date(),
                        processed_this_run,
                    )
                    result = self.builder.build(
                        stage_start,
                        stage_end,
                        selected_options=set(stage.options),
                        extra_tasks=extra_tasks if stage.key == "xm_extra" else None,
                        include_macro=bool({"trm", "enso"}.intersection(stage.options)),
                        callback=source_callback,
                    )
                except Exception as exc:
                    LOGGER.exception(
                        "CAME mantenimiento excepción etapa build_id=%s etapa=%s periodo=%s/%s",
                        self.build_id,
                        stage.key,
                        stage_start.date(),
                        stage_end.date(),
                    )
                    result = BuildResult(
                        country="COL",
                        data=pd.DataFrame(columns=LONG_COLUMNS),
                        status=pd.DataFrame(),
                        errors=[f"{stage.label}: {exc}"],
                    )
                if result.errors:
                    failed_labels.append(stage.label)
                    blocking_errors.extend(result.errors)
                    failed_statuses.append(result.status)
                    ledger_id = f"{stage.key}:{stage_start.date()}:{stage_end.date()}"
                    ledger_by_stage[ledger_id] = {
                        "ledger_id": ledger_id,
                        "stage_key": stage.key,
                        "stage": stage.label,
                        "period_start": str(stage_start.date()),
                        "period_end": str(stage_end.date()),
                        "status": "failed",
                        "attempts": 3,
                        "updated_at_utc": datetime.now(UTC).isoformat(),
                        "error": " | ".join(result.errors),
                    }
                    LOGGER.error(
                        "CAME mantenimiento etapa fallida build_id=%s etapa=%s errores=%s",
                        self.build_id,
                        stage.key,
                        " | ".join(result.errors),
                    )
                    pending = [stage.label] + [item.label for item in queue[index:]]
                    outcome = compose(pending)
                    checkpoint(outcome)
                    return outcome
                try:
                    self.stages.save(signature, result)
                except Exception as exc:
                    LOGGER.exception(
                        "CAME mantenimiento no pudo guardar etapa build_id=%s etapa=%s",
                        self.build_id,
                        stage.key,
                    )
                    failed_labels.append(stage.label)
                    blocking_errors.append(
                        f"No fue posible guardar la etapa {stage.label}: {exc}"
                    )
                    failed_statuses.append(result.status)
                    pending = [stage.label] + [item.label for item in queue[index:]]
                    outcome = compose(pending)
                    checkpoint(outcome)
                    return outcome

            results.append(result)
            completed_labels.append(stage.label)
            produced = sorted(
                set(result.data.get("series_id", pd.Series(dtype="string")).dropna().astype(str))
                - CALENDAR_SERIES
            )
            for option in stage.options:
                option_series[option] = produced
            current_month = pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M")
            stage_state = (
                "partial"
                if stage_end_plain.to_period("M") == current_month
                else ("no_data" if not produced else "completed")
            )
            ledger_id = f"{stage.key}:{stage_start.date()}:{stage_end.date()}"
            ledger_by_stage[ledger_id] = {
                "ledger_id": ledger_id,
                "stage_key": stage.key,
                "stage": stage.label,
                "period_start": str(stage_start.date()),
                "period_end": str(stage_end.date()),
                "status": stage_state,
                "attempts": 1,
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "error": "",
            }
            LOGGER.info(
                "CAME mantenimiento termina etapa build_id=%s etapa=%s estado=%s filas=%s",
                self.build_id,
                stage.key,
                stage_state,
                len(result.data),
            )
            if stage_callback:
                final_status = "Completado" if status_label == "Procesando" else status_label
                stage_callback(
                    AutomaticStageEvent(index, len(queue), stage.label, final_status)
                )
            pending = [item.label for item in queue[index:]]
            checkpoint(compose(pending))

        return compose([])

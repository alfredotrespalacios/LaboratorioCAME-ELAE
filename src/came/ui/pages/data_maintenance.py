"""Página técnica para construir y publicar las bases mensuales por defecto."""

from __future__ import annotations

import logging
import re
from datetime import date

import pandas as pd
import streamlit as st

from came.config import APP_VERSION
from came.data.automatic_maintenance import (
    AutomaticStageEvent,
    ColombiaAutomaticBuilder,
    option_series_from_metadata,
    selected_options_from_metadata,
)
from came.data.colombia_selection import DEFAULT_SELECTION, selection_catalog
from came.data.maintenance import (
    BuildResult,
    ChileMonthlyBuilder,
    ProgressEvent,
    SpainMonthlyBuilder,
    XMMonthlyTask,
)
from came.data.monthly_store import (
    LONG_COLUMNS,
    StoredMonthlyPackage,
    allocate_ready_package_directory,
    create_stored_monthly_package,
    discover_ready_monthly_package,
    get_package_spec,
    load_default_metadata,
    load_default_monthly,
    load_stored_monthly_package,
    merge_monthly_data,
)
from came.data.providers.xm import XMProvider

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

OPERATION_UPDATE = "Agregar meses y variables faltantes"
OPERATION_BUILD = "Construir la primera base"
OPERATION_RECALCULATE = "Recalcular un periodo"
EARLIEST_MAINTENANCE_DATE = date(1990, 1, 1)
MAX_PERIOD_MONTHS = 60
MAX_NEW_STAGES_PER_EXECUTION = 3
EXECUTION_TIME_BUDGET_SECONDS = 180

PACKAGE_PHASES = (
    "1/5 · Validando la estructura y la cobertura mensual…",
    "2/5 · Escribiendo el Parquet mensual en disco…",
    "3/5 · Construyendo el catálogo Excel…",
    "4/5 · Comprimiendo el ZIP descargable…",
    "5/5 · Publicando el paquete terminado…",
)


def _load_existing(country: str) -> tuple[pd.DataFrame, dict[str, object], str | None]:
    try:
        data = load_default_monthly(country)
        return data, load_default_metadata(country), None
    except FileNotFoundError as exc:
        return pd.DataFrame(columns=LONG_COLUMNS), {}, str(exc)
    except Exception as exc:
        return (
            pd.DataFrame(columns=LONG_COLUMNS),
            {},
            f"No fue posible leer el paquete publicado: {exc}",
        )


def _progress_callback(container: st.delta_generator.DeltaGenerator):
    bar = container.progress(0.0)
    detail = container.empty()

    def update(event: ProgressEvent) -> None:
        progress = event.current / max(event.total, 1)
        bar.progress(min(max(progress, 0.0), 1.0))
        message = (
            f"{event.source} · {event.variable} · {event.period} · {event.status} "
            f"({event.current}/{event.total})"
        )
        if event.detail:
            LOGGER.error("%s · Detalle: %s", message, event.detail)
            detail.error(f"{message}\n\nDetalle: {event.detail}")
        else:
            LOGGER.info(message)
            detail.caption(message)

    return update


def _show_current_state(country: str, data: pd.DataFrame, metadata: dict[str, object]) -> None:
    spec = get_package_spec(country)
    st.markdown(f"**Archivos publicados de {spec.label}**")
    if data.empty:
        st.warning("Todavía no existe una base mensual publicada para este país.")
        return
    columns = st.columns(4)
    columns[0].metric(
        "Último dato",
        str(metadata.get("last_available_month") or pd.to_datetime(data["datetime"], utc=True).max().date()),
    )
    columns[1].metric("Series", f"{data['series_id'].nunique():,}")
    columns[2].metric("Filas", f"{len(data):,}")
    columns[3].metric("Versión", str(metadata.get("schema_version", "Sin JSON")))
    if metadata.get("partial_month"):
        st.caption(
            f"El mes {metadata['partial_month']} está marcado como parcial y podrá actualizarse "
            "nuevamente cuando XM publique más información."
        )


def _result_for_session(
    result: BuildResult,
    package: StoredMonthlyPackage | None,
) -> dict[str, object]:
    """Conserva solo un resumen pequeño; la base y el ZIP permanecen en disco."""

    package_metadata = package.metadata if package else {}
    return {
        "status": result.status,
        "warnings": list(result.warnings),
        "errors": list(result.errors),
        "package_directory": str(package.directory) if package else None,
        "country": result.country,
        "recovered": False,
        "run_complete": bool(package_metadata.get("run_complete", not result.errors)),
        "pending_stages": list(package_metadata.get("pending_stages", [])),
        "failed_stages": list(package_metadata.get("failed_stages", [])),
    }


def _package_from_state(state: dict[str, object]) -> StoredMonthlyPackage | None:
    directory = state.get("package_directory")
    country = state.get("country")
    if not directory or not country:
        return None
    package = load_stored_monthly_package(str(directory), str(country))
    return package or discover_ready_monthly_package(str(country))


def _state_or_latest(session_key: str, country: str) -> dict[str, object] | None:
    """Recupera la última descarga aunque Streamlit haya creado una sesión nueva."""

    state = st.session_state.get(session_key)
    if isinstance(state, dict):
        return state
    package = discover_ready_monthly_package(country)
    if package is None:
        return None
    state = {
        "status": pd.DataFrame(),
        "warnings": list(package.metadata.get("warnings", [])),
        "errors": list(package.metadata.get("errors", [])),
        "package_directory": str(package.directory),
        "country": country,
        "recovered": True,
        "run_complete": bool(package.metadata.get("run_complete", True)),
        "pending_stages": list(package.metadata.get("pending_stages", [])),
        "failed_stages": list(package.metadata.get("failed_stages", [])),
    }
    st.session_state[session_key] = state
    return state


def _download_file(
    label: str,
    path,
    *,
    file_name: str,
    mime: str,
    key: str,
    primary: bool = False,
) -> None:
    with path.open("rb") as content:
        st.download_button(
            label,
            data=content,
            file_name=file_name,
            mime=mime,
            type="primary" if primary else "secondary",
            key=key,
            width="stretch",
        )


def _show_result(state: dict[str, object], key: str) -> None:
    st.subheader("Resultado de la ejecución")
    status = state.get("status")
    warnings = list(state.get("warnings", []))
    errors = list(state.get("errors", []))
    if isinstance(status, pd.DataFrame) and not status.empty:
        st.dataframe(status, width="stretch", hide_index=True)
    if warnings:
        for warning in warnings:
            st.warning(warning)
    if errors:
        st.warning(
            f"La corrida encontró {len(errors)} error(es). El ZIP disponible conserva los datos "
            "aprobados y registra lo pendiente para continuar después."
        )
        with st.expander("Errores que deben resolverse", expanded=True):
            for error in errors:
                st.write(f"- {error}")
    try:
        package = _package_from_state(state)
    except Exception as exc:
        st.error(
            "La construcción terminó, pero los archivos de descarga no pudieron recuperarse. "
            f"Detalle: {exc}"
        )
        return
    if package is None:
        st.error("No fue posible recuperar un ZIP de avance de esta corrida.")
        return
    run_complete = bool(package.metadata.get("run_complete", state.get("run_complete", True)))
    pending = list(package.metadata.get("pending_stages", state.get("pending_stages", [])))
    failed = list(package.metadata.get("failed_stages", state.get("failed_stages", [])))
    if run_complete:
        st.success("Actualización terminada. El ZIP completo está listo para descargar.")
    else:
        st.info(
            "ZIP de avance listo. Contiene todo lo aprobado hasta este punto y puede publicarse "
            "en GitHub para conservar el progreso."
        )
        if pending:
            st.write(f"**Etapas pendientes:** {len(pending)}. Próxima: {pending[0]}.")
        if failed:
            st.write("**Etapas con error:** " + ", ".join(failed) + ".")
    if state.get("recovered"):
        st.caption(
            "La descarga se recuperó automáticamente de la ejecución más reciente; "
            "no depende de la memoria de esta sesión."
        )
    st.dataframe(package.validation.as_frame(), width="stretch", hide_index=True)
    spec = package.spec
    metrics = st.columns(3)
    metrics[0].metric("Tamaño del ZIP", f"{package.zip_path.stat().st_size / 1_048_576:.1f} MB")
    metrics[1].metric("Series", f"{int(package.metadata.get('series', 0)):,}")
    metrics[2].metric(
        "Último dato",
        str(package.metadata.get("last_available_month") or package.metadata.get("last_complete_month", "")),
    )
    st.info(
        "Para conservar este avance, descomprima el ZIP y copie sus tres archivos en esta carpeta exacta "
        f"del repositorio: `{spec.relative_directory.as_posix()}/`. "
        "Reemplace los tres juntos, conserve sus nombres y espere el nuevo despliegue de Streamlit."
    )
    _download_file(
        "Descargar ZIP completo para GitHub" if run_complete else "Descargar ZIP de avance para GitHub",
        package.zip_path,
        file_name=f"Base_mensual_{spec.label}.zip",
        mime="application/zip",
        key=f"{key}_zip",
        primary=True,
    )
    if key == "maintenance_col" and not run_complete:
        st.button(
            "Continuar con las etapas pendientes",
            type="primary",
            key=f"{key}_continue",
            on_click=lambda: st.session_state.__setitem__("maintenance_col_continue", True),
            width="stretch",
        )
    if st.checkbox("Necesito descargar también un archivo individual", key=f"{key}_individual"):
        files = {
            spec.parquet_name: (package.parquet_path, "application/octet-stream"),
            spec.catalog_name: (
                package.catalog_path,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            spec.metadata_name: (package.metadata_path, "application/json"),
        }
        selected = st.selectbox(
            "Archivo individual",
            list(files),
            key=f"{key}_individual_file",
        )
        selected_path, selected_mime = files[selected]
        _download_file(
            f"Descargar {selected}",
            selected_path,
            file_name=selected,
            mime=selected_mime,
            key=f"{key}_individual_download",
        )


def _create_download_package(
    result: BuildResult,
    *,
    country: str,
    build_id: str,
    additional_sheets: dict[str, pd.DataFrame],
    build_notes: list[str],
    metadata_extra: dict[str, object] | None = None,
    allow_partial: bool = False,
) -> StoredMonthlyPackage | None:
    """Empaqueta en disco y deja un registro visible de todo el cierre."""

    phase = st.container(border=True)
    phase.markdown("**Cierre de la construcción**")
    phase.write("0/5 · Las consultas terminaron. Comprobando si el paquete puede crearse…")
    phase_slots = [phase.empty() for _ in PACKAGE_PHASES]
    for slot, label in zip(phase_slots, PACKAGE_PHASES, strict=True):
        slot.caption(label + " · Pendiente")

    current_phase = 0

    def show_phase(message: str) -> None:
        nonlocal current_phase
        try:
            current_phase = int(message.split("/", maxsplit=1)[0])
        except (TypeError, ValueError):
            phase.write(message)
            return
        if 1 <= current_phase <= len(phase_slots):
            phase_slots[current_phase - 1].info(message)

    if result.errors and not allow_partial:
        phase.error(
            f"El empaquetado NO comenzó: quedaron {len(result.errors)} error(es) bloqueante(s). "
            "Los avances aprobados se conservaron para reintentar solo lo pendiente."
        )
        return None
    if result.errors:
        phase.warning(
            "Se construirá un ZIP de avance con los datos aprobados. Los errores y las etapas "
            "pendientes quedarán identificados en el JSON y en el catálogo."
        )
    if result.data.empty:
        result.errors.append("La consulta terminó sin observaciones válidas para empaquetar.")
        phase.error("El empaquetado NO comenzó porque la base resultante está vacía.")
        return None
    try:
        package = _write_download_package(
            result.data,
            country,
            build_id,
            additional_sheets=additional_sheets,
            build_notes=build_notes,
            metadata_extra=metadata_extra,
            progress=show_phase,
        )
        result.data = pd.DataFrame(columns=LONG_COLUMNS)
        for slot, label in zip(phase_slots, PACKAGE_PHASES, strict=True):
            slot.success(label + " · Completado")
        phase.success("5/5 · Paquete terminado y verificado. El botón de descarga está debajo.")
        return package
    except Exception as exc:
        result.errors.append(f"Empaquetado final: {exc}")
        if 1 <= current_phase <= len(phase_slots):
            phase_slots[current_phase - 1].error(
                PACKAGE_PHASES[current_phase - 1] + f" · Error: {exc}"
            )
        phase.error("La consulta terminó, pero el empaquetado final falló.")
        return None


def _write_download_package(
    data: pd.DataFrame,
    country: str,
    build_id: str,
    *,
    additional_sheets: dict[str, pd.DataFrame],
    build_notes: list[str],
    metadata_extra: dict[str, object] | None = None,
    progress=None,
) -> StoredMonthlyPackage:
    """Escribe un paquete verificable, con o sin elementos pendientes."""

    output = allocate_ready_package_directory(country, build_id)
    LOGGER.info(
        "CAME mantenimiento inicia ZIP build_id=%s país=%s filas=%s",
        build_id,
        country,
        len(data),
    )
    package = create_stored_monthly_package(
        data,
        country,
        output,
        additional_sheets=additional_sheets,
        build_notes=build_notes,
        metadata_extra=metadata_extra,
        progress=progress,
        allow_current_month=country == "COL",
    )
    LOGGER.info(
        "CAME mantenimiento termina ZIP build_id=%s país=%s ruta=%s",
        build_id,
        country,
        package.zip_path,
    )
    return package


def _period_controls(
    country: str,
    operation: str,
    existing: pd.DataFrame,
    *,
    default_start: date,
    key: str,
    plan_metadata: dict[str, object] | None = None,
) -> tuple[date, date, pd.DataFrame | None, date | None, date | None] | None:
    today = date.today()
    plan_metadata = plan_metadata or {}

    def planned_date(field: str, fallback: date) -> date:
        parsed = pd.to_datetime(plan_metadata.get(field), errors="coerce")
        if pd.isna(parsed):
            return fallback
        value = parsed.date()
        return min(max(value, EARLIEST_MAINTENANCE_DATE), today)

    if operation == OPERATION_BUILD:
        initial = planned_date("requested_start", max(default_start, EARLIEST_MAINTENANCE_DATE))
        start = st.date_input(
            "Fecha inicial de la historia",
            value=initial,
            min_value=EARLIEST_MAINTENANCE_DATE,
            max_value=today,
            key=f"{key}_start_build",
        )
        suggested_end = min(today, date(min(start.year + 4, today.year), 12, 31))
        suggested_end = max(suggested_end, start)
        end = st.date_input(
            "Último día a consultar",
            value=planned_date("requested_end", suggested_end),
            min_value=EARLIEST_MAINTENANCE_DATE,
            max_value=today,
            key=f"{key}_end_build",
        )
        return start, end, None, None, None
    if operation == OPERATION_UPDATE:
        if existing.empty:
            st.info("No existe un Parquet publicado. Seleccione **Construir la primera base**.")
            return None
        current_last = pd.to_datetime(existing["datetime"], utc=True).max()
        current_month = pd.Timestamp(today).to_period("M").to_timestamp()
        current_last_naive = current_last.tz_localize(None)
        suggested_start = (
            current_month
            if current_last_naive.to_period("M") >= current_month.to_period("M")
            else current_last_naive + pd.offsets.MonthBegin()
        ).date()
        columns = st.columns(2)
        start = columns[0].date_input(
            "Fecha inicial de la actualización",
            value=planned_date("requested_start", suggested_start),
            min_value=EARLIEST_MAINTENANCE_DATE,
            max_value=today,
            key=f"{key}_start_update",
        )
        end = columns[1].date_input(
            "Último día a consultar",
            value=planned_date("requested_end", today),
            min_value=EARLIEST_MAINTENANCE_DATE,
            max_value=today,
            key=f"{key}_end_update",
        )
        st.caption(
            "La aplicación leerá la cobertura publicada por variable y mes. Los datos completos "
            "se reutilizan; el mes actual puede consultarse nuevamente por ser parcial."
        )
        return start, end, existing, None, None
    columns = st.columns(2)
    start = columns[0].date_input(
        "Primer mes que se reemplazará",
        value=planned_date("requested_start", max(default_start, EARLIEST_MAINTENANCE_DATE)),
        min_value=EARLIEST_MAINTENANCE_DATE,
        max_value=today,
        key=f"{key}_start_recalc",
    )
    end = columns[1].date_input(
        "Último mes que se reemplazará",
        value=planned_date("requested_end", today),
        min_value=EARLIEST_MAINTENANCE_DATE,
        max_value=today,
        key=f"{key}_end_recalc",
    )
    if existing.empty:
        st.info("No existe una versión publicada sobre la cual reemplazar meses.")
        return None
    return start, end, existing, start, end


def _period_months(start: date, end: date) -> int:
    first = pd.Timestamp(start).to_period("M")
    last = pd.Timestamp(end).to_period("M")
    return (last.year - first.year) * 12 + last.month - first.month + 1


def _additional_sheets(result: BuildResult) -> dict[str, pd.DataFrame]:
    sheets = {"Estado de fuentes": result.status}
    if not result.validation.empty:
        sheets["Conciliación generación"] = result.validation
    sheets.update(result.catalogs)
    return sheets


def _colombia_section(timeout: int) -> None:
    existing, metadata, load_error = _load_existing("COL")
    _show_current_state("COL", existing, metadata)
    if load_error:
        st.caption(load_error)

    plan_metadata = metadata
    local_package = discover_ready_monthly_package("COL")
    if (
        local_package is not None
        and not bool(local_package.metadata.get("run_complete", True))
        and local_package.metadata.get("requested_start")
    ):
        plan_metadata = local_package.metadata
        st.info(
            "Se recuperó un avance local que todavía tiene etapas pendientes. Los controles se "
            "cargaron con el periodo y la canasta de esa corrida."
        )

    partial_seed = metadata.get("build_mode") == "partial_seed"
    operations = [OPERATION_UPDATE, OPERATION_BUILD, OPERATION_RECALCULATE]
    saved_operation = plan_metadata.get("operation")
    default_operation = (
        str(saved_operation)
        if saved_operation in operations and not bool(plan_metadata.get("run_complete", True))
        else (OPERATION_BUILD if partial_seed else OPERATION_UPDATE)
    )
    operation = st.radio(
        "Operación para Colombia",
        operations,
        index=operations.index(default_operation),
        key="maintenance_col_operation",
    )
    period = _period_controls(
        "COL",
        operation,
        existing,
        default_start=EARLIEST_MAINTENANCE_DATE,
        key="maintenance_col",
        plan_metadata=plan_metadata,
    )
    st.subheader("Variables que se incorporarán")
    catalog = selection_catalog()
    labels = {
        row.Clave: f"{row.Grupo} · {row.Variable} · {row.Fuente}"
        for row in catalog.itertuples()
    }
    published_selection = selected_options_from_metadata(plan_metadata)
    if operation == OPERATION_UPDATE and published_selection:
        selected = set(published_selection)
        st.success(
            "La actualización usará automáticamente la misma canasta de la base publicada: "
            f"{len(selected)} variable(s). No necesita seleccionarlas de nuevo."
        )
    else:
        scope = st.radio(
            "Alcance de la construcción",
            ["Canasta CAME completa (recomendado)", "Selección personalizada"],
            key="maintenance_col_scope",
        )
        if scope == "Canasta CAME completa (recomendado)":
            selected = set(DEFAULT_SELECTION)
            st.success(
                f"Se procesarán automáticamente las {len(selected)} variables de la canasta CAME. "
                "La aplicación las dividirá en etapas y reutilizará los avances aprobados."
            )
        else:
            selected = set(
                st.multiselect(
                    "Variables de la canasta CAME",
                    list(labels),
                    default=[key for key in labels if key in DEFAULT_SELECTION],
                    format_func=lambda value: labels[value],
                    key="maintenance_col_selection",
                )
            )
            st.caption(
                "Solo se consultarán y guardarán las variables seleccionadas. "
                "La ejecución seguirá siendo automática por etapas."
            )
    st.dataframe(
        catalog.assign(Seleccionada=catalog["Clave"].isin(selected)).drop(
            columns="Obligatoria", errors="ignore"
        ),
        hide_index=True,
        width="stretch",
    )

    with st.expander("Catálogo avanzado: todas las variables publicadas por XM"):
        st.write(
            "Consulte el catálogo vivo y seleccione métricas adicionales. Estas quedan inicialmente "
            "desmarcadas y se agregan con una regla mensual explícita."
        )
        if st.button("Consultar catálogo vivo de XM", key="maintenance_xm_catalog_load"):
            try:
                st.session_state["maintenance_xm_catalog"] = XMProvider(timeout=timeout).catalog()
            except Exception as exc:
                st.error(f"XM no pudo entregar el catálogo en este momento: {exc}")
        live_catalog = st.session_state.get("maintenance_xm_catalog")
        selected_live: list[str] = []
        if isinstance(live_catalog, pd.DataFrame) and not live_catalog.empty:
            columns = [
                column
                for column in ("MetricId", "MetricName", "Entity", "Type", "MetricUnits", "MaxDays")
                if column in live_catalog
            ]
            st.dataframe(live_catalog[columns], hide_index=True, width="stretch")
            live_catalog = live_catalog.copy()
            live_catalog["_key"] = (
                live_catalog["MetricId"].astype(str) + "|" + live_catalog["Entity"].astype(str)
            )
            live_labels = {
                str(row["_key"]): (
                    f"{row.get('MetricName', row['MetricId'])} · "
                    f"{row['MetricId']}/{row['Entity']} · {row.get('MetricUnits', '')}"
                )
                for _, row in live_catalog.iterrows()
            }
            selected_live = st.multiselect(
                "Variables XM adicionales",
                list(live_labels),
                default=[],
                format_func=lambda value: live_labels[value],
                key="maintenance_xm_extra_selection",
            )
    extra_tasks: list[XMMonthlyTask] = []
    live_catalog = st.session_state.get("maintenance_xm_catalog")
    if isinstance(live_catalog, pd.DataFrame) and not live_catalog.empty:
        live_catalog = live_catalog.copy()
        live_catalog["_key"] = live_catalog["MetricId"].astype(str) + "|" + live_catalog["Entity"].astype(str)
        for selected_key in selected_live:
            row = live_catalog[live_catalog["_key"].eq(selected_key)].iloc[0]
            metric = str(row["MetricId"])
            entity = str(row["Entity"])
            unit = str(row.get("MetricUnits") or "Unidad XM")
            slug = re.sub(r"[^a-z0-9]+", "_", (metric + "_" + entity).casefold()).strip("_")
            aggregation_mode = "sum" if unit in {"kWh", "MWh", "GWh"} else "mean"
            extra_tasks.append(
                XMMonthlyTask(
                    metric,
                    entity,
                    f"col_xm_catalogo_{slug}",
                    str(row.get("MetricName") or metric),
                    str(row.get("MetricName") or metric),
                    unit,
                    None,
                    "Suma mensual" if aggregation_mode == "sum" else "Promedio simple mensual",
                    aggregation_mode,
                    "Catálogo XM",
                )
            )
    has_selection = bool(selected or extra_tasks)
    if not has_selection:
        st.warning("Seleccione al menos una variable antes de iniciar la construcción.")
    else:
        st.caption(
            "La construcción consultará exclusivamente las fuentes requeridas por la selección anterior."
        )
    period_allowed = period is not None
    if period:
        period_start, period_end, *_ = period
        if period_start > period_end:
            st.error("La fecha inicial no puede ser posterior a la fecha final.")
            period_allowed = False
        elif _period_months(period_start, period_end) > MAX_PERIOD_MONTHS:
            st.error(
                f"Seleccione como máximo {MAX_PERIOD_MONTHS} meses por corrida. Termine y publique "
                "ese avance antes de continuar con el siguiente intervalo."
            )
            period_allowed = False
        else:
            st.caption(
                f"Periodo seleccionado: {_period_months(period_start, period_end)} mes(es). "
                "Cada ejecución procesa hasta tres etapas nuevas y entrega un ZIP de avance."
            )

    confirm = st.checkbox(
        "Entiendo que debo mantener abierta esta pestaña hasta que aparezca el ZIP de avance.",
        key="maintenance_col_confirm",
    )
    clear = st.checkbox(
        "Borrar los avances temporales de este periodo y volver a consultar sus bloques",
        value=False,
        key="maintenance_col_clear",
    )
    clear_confirmed = True
    if clear:
        st.warning(
            "Esta opción elimina únicamente los avances temporales de la operación y el periodo "
            "seleccionados. No elimina los archivos publicados en GitHub."
        )
        clear_confirmed = st.checkbox(
            "Confirmo que deseo borrar esos avances temporales.",
            key="maintenance_col_clear_confirm",
        )
    st.caption(
        "La aplicación compara la canasta con el Parquet publicado, reutiliza la información "
        "completa y consulta lo pendiente. Cada bloque tiene tres intentos. Si algo falla, el ZIP "
        "conservará lo aprobado y dejará identificado lo que debe reintentarse."
    )
    button_label = (
        "Construir o continuar por etapas"
        if operation != OPERATION_UPDATE
        else "Actualizar o continuar por etapas"
    )
    continue_requested = bool(st.session_state.pop("maintenance_col_continue", False))
    run_clicked = st.button(
        button_label,
        type="primary",
        disabled=not (
            confirm and has_selection and period_allowed and clear_confirmed
        ),
        key="maintenance_col_run",
    )
    if period and period_allowed and (run_clicked or continue_requested):
        start, end, base, _replace_start, _replace_end = period
        build_id = f"COL_{operation}_{start}_{end}"
        builder = ColombiaAutomaticBuilder(timeout=timeout, build_id=build_id)
        if clear and run_clicked:
            builder.clear()
        progress = st.container()
        global_bar = progress.progress(0.0)
        global_detail = progress.empty()
        source_progress = progress.container()

        def show_stage(event: AutomaticStageEvent) -> None:
            completed = event.current if event.status != "Procesando" else event.current - 1
            global_bar.progress(min(max(completed / max(event.total, 1), 0.0), 1.0))
            global_detail.info(
                f"Etapa {event.current}/{event.total} · {event.label} · {event.status}"
            )

        def outcome_metadata(outcome) -> dict[str, object]:
            return {
                "build_mode": "incremental_checkpoint_152",
                "operation": operation,
                "requested_start": str(start),
                "requested_end": str(end),
                "selected_options": outcome.selected_options,
                "target_options": outcome.selected_options,
                "option_series": outcome.option_series,
                "completed_stages": outcome.completed_stages,
                "reused_published": outcome.reused_published,
                "pending_stages": outcome.pending_stages,
                "failed_stages": outcome.failed_stages,
                "run_complete": outcome.run_complete,
                "processed_this_run": outcome.processed_this_run,
                "run_ledger": outcome.run_ledger,
                "warnings": list(outcome.result.warnings),
                "errors": list(outcome.result.errors),
            }

        build_notes = [
            f"Operación: {operation}.",
            f"Construcción incremental recuperable · Laboratorio CAME {APP_VERSION}.",
            "La asociación recurso–empresa se conserva por mes; el catálogo documenta los cambios observados y las empresas involucradas.",
            "Variables objetivo: " + ", ".join(sorted(selected)) + ".",
            "El mes actual, cuando está presente, se identifica como parcial y puede actualizarse nuevamente.",
        ]
        latest_checkpoint: StoredMonthlyPackage | None = None

        def save_checkpoint(outcome) -> None:
            nonlocal latest_checkpoint
            if outcome.result.data.empty:
                return
            global_detail.info("Guardando un ZIP recuperable con el avance aprobado…")
            latest_checkpoint = _write_download_package(
                outcome.result.data,
                "COL",
                build_id,
                additional_sheets=_additional_sheets(outcome.result),
                build_notes=build_notes,
                metadata_extra=outcome_metadata(outcome),
            )
            st.session_state["maintenance_col_result"] = _result_for_session(
                outcome.result,
                latest_checkpoint,
            )

        with st.spinner("Procesando automáticamente la canasta por etapas…"):
            outcome = builder.build(
                start,
                end,
                existing=existing if not existing.empty else base,
                selected_options=selected,
                extra_tasks=extra_tasks,
                completed_options=set(),
                existing_option_series=option_series_from_metadata(plan_metadata),
                repair_coverage=(
                    operation in {OPERATION_UPDATE, OPERATION_BUILD} and not existing.empty
                ),
                source_callback=_progress_callback(source_progress),
                stage_callback=show_stage,
                checkpoint_callback=save_checkpoint,
                max_new_stages=MAX_NEW_STAGES_PER_EXECUTION,
                time_budget_seconds=EXECUTION_TIME_BUDGET_SECONDS,
                existing_ledger=(
                    list(plan_metadata.get("run_ledger", []))
                    if isinstance(plan_metadata.get("run_ledger"), list)
                    else []
                ),
            )
        result = outcome.result
        if outcome.run_complete:
            global_bar.progress(1.0)
            global_detail.success(
                "Todas las etapas del periodo quedaron procesadas o reutilizadas."
            )
        elif result.errors:
            global_detail.warning(
                "La corrida se detuvo en una etapa con error. El avance anterior permanece "
                "descargable y el error quedó registrado."
            )
        else:
            global_detail.info(
                f"Pausa controlada: se procesaron {outcome.processed_this_run} etapa(s) nueva(s). "
                "Descargue el ZIP o continúe con el siguiente grupo."
            )

        package = latest_checkpoint
        if package is None:
            package = _create_download_package(
                result,
                country="COL",
                build_id=build_id,
                additional_sheets=_additional_sheets(result),
                build_notes=build_notes,
                metadata_extra=outcome_metadata(outcome),
                allow_partial=True,
            )
        st.session_state["maintenance_col_result"] = _result_for_session(result, package)
    state = _state_or_latest("maintenance_col_result", "COL")
    if isinstance(state, dict):
        _show_result(state, "maintenance_col")


def _spain_section(timeout: int) -> None:
    existing, metadata, load_error = _load_existing("ESP")
    _show_current_state("ESP", existing, metadata)
    if load_error:
        st.caption(load_error)
    operation = st.radio(
        "Operación para España",
        [OPERATION_UPDATE, OPERATION_BUILD, OPERATION_RECALCULATE],
        key="maintenance_esp_operation",
    )
    period = _period_controls(
        "ESP", operation, existing, default_start=date(2014, 1, 1), key="maintenance_esp"
    )
    st.caption("La construcción completa incluye REData y el precio diario de OMIE.")
    confirm = st.checkbox(
        "Entiendo que REData y OMIE se procesarán de manera independiente.",
        key="maintenance_esp_confirm",
    )
    if period and st.button(
        "Construir o actualizar España",
        type="primary",
        disabled=not confirm,
        key="maintenance_esp_run",
    ):
        start, end, base, replace_start, replace_end = period
        progress = st.container()
        build_id = f"ESP_{operation}_{start}_{end}"
        builder = SpainMonthlyBuilder(timeout=timeout, build_id=build_id)
        with st.spinner("Consultando fuentes oficiales de España…"):
            result = builder.build(
                start, end, include_omie=True, callback=_progress_callback(progress)
            )
        if result.ok:
            if base is not None and replace_start is not None and replace_end is not None:
                dates = pd.to_datetime(base["datetime"], utc=True)
                lower = pd.Timestamp(replace_start, tz="UTC")
                upper = pd.Timestamp(replace_end, tz="UTC") + pd.offsets.MonthEnd()
                base = base[~dates.between(lower, upper)]
            result.data = merge_monthly_data(base, result.data)
        package = _create_download_package(
            result,
            country="ESP",
            build_id=build_id,
            additional_sheets=_additional_sheets(result),
            build_notes=[f"Operación: {operation}."],
        )
        st.session_state["maintenance_esp_result"] = _result_for_session(result, package)
    state = _state_or_latest("maintenance_esp_result", "ESP")
    if isinstance(state, dict):
        _show_result(state, "maintenance_esp")


def _chile_section(timeout: int) -> None:
    existing, metadata, load_error = _load_existing("CHL")
    _show_current_state("CHL", existing, metadata)
    if load_error:
        st.caption(load_error)
    st.info(
        "El portal del Coordinador puede bloquear la descarga automática. Para mantener datos "
        "oficiales y trazables, cargue aquí las dos exportaciones de la misma cobertura."
    )
    costs = st.file_uploader(
        "Archivo oficial de costos marginales",
        type=["xlsx", "xls", "csv", "tsv", "txt"],
        key="maintenance_chl_costs",
    )
    demand = st.file_uploader(
        "Archivo oficial de demanda por barra",
        type=["xlsx", "xls", "csv", "tsv", "txt"],
        key="maintenance_chl_demand",
    )
    generation = st.file_uploader(
        "Archivo oficial de generación por tecnología",
        type=["xlsx", "xls", "csv", "tsv", "txt"],
        key="maintenance_chl_generation",
    )
    confirm = st.checkbox(
        "Confirmo que los tres archivos provienen del Coordinador y cubren el mismo periodo.",
        key="maintenance_chl_confirm",
    )
    if st.button(
        "Procesar y actualizar Chile",
        type="primary",
        disabled=not (confirm and costs and demand and generation),
        key="maintenance_chl_run",
    ):
        progress = st.container()
        result = ChileMonthlyBuilder(timeout=timeout).build_from_files(
            costs.getvalue(),
            costs.name,
            demand.getvalue(),
            demand.name,
            generation.getvalue(),
            generation.name,
            callback=_progress_callback(progress),
        )
        if result.ok and not existing.empty:
            first = pd.to_datetime(result.data["datetime"], utc=True).min()
            last = pd.to_datetime(result.data["datetime"], utc=True).max() + pd.offsets.MonthEnd()
            dates = pd.to_datetime(existing["datetime"], utc=True)
            result.data = merge_monthly_data(existing[~dates.between(first, last)], result.data)
        package = _create_download_package(
            result,
            country="CHL",
            build_id="CHL_archivos",
            additional_sheets=_additional_sheets(result),
            build_notes=[
                "Actualización construida desde exportaciones oficiales cargadas por el usuario."
            ],
        )
        st.session_state["maintenance_chl_result"] = _result_for_session(result, package)
    state = _state_or_latest("maintenance_chl_result", "CHL")
    if isinstance(state, dict):
        _show_result(state, "maintenance_chl")


def _publication_guide() -> None:
    st.subheader("Cómo actualizar y publicar los datos")
    st.info(
        "La aplicación lee automáticamente los archivos que ya están publicados, conserva los "
        "datos completos y consulta solo los periodos o variables pendientes. El ZIP incorpora "
        "la ruta correcta para reemplazar los archivos en GitHub."
    )
    st.markdown(
        "1. Revise la cobertura que aparece en **Archivos publicados**.\n"
        "2. Elija la operación y un periodo de máximo cinco años, entre 1990 y la fecha actual.\n"
        "3. Inicie la corrida. Cada ejecución procesa un grupo corto de etapas y genera un "
        "**ZIP completo** o un **ZIP de avance**.\n"
        "4. Descargue el ZIP. Si quedan etapas pendientes, puede publicarlo para asegurar el "
        "avance o pulsar **Continuar con las etapas pendientes**.\n"
        "5. Descomprima el ZIP y abra en GitHub la carpeta exacta incluida en él.\n"
        "6. Reemplace juntos el Parquet, el catálogo Excel y el JSON, sin cambiar sus nombres.\n"
        "7. Confirme los tres archivos en un mismo *commit*. Streamlit nunca modifica GitHub "
        "automáticamente.\n"
        "8. Espere el despliegue y compruebe la cobertura. La siguiente corrida leerá el JSON y "
        "el Parquet publicados para reutilizar lo completo y continuar con lo pendiente."
    )
    rows = []
    for country in ("COL", "ESP", "CHL"):
        spec = get_package_spec(country)
        rows.append(
            {
                "País": spec.label,
                "Carpeta GitHub": spec.relative_directory.as_posix() + "/",
                "Parquet": spec.parquet_name,
                "Catálogo": spec.catalog_name,
                "Actualización": spec.metadata_name,
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def page_data_maintenance(timeout: int = 45) -> None:
    """Construye, valida y permite descargar paquetes mensuales independientes."""

    st.header("Mantenimiento de datos")
    st.write(
        "Página técnica para crear o actualizar las bases mensuales que utilizan los módulos. "
        "No se necesita durante la consulta normal del Laboratorio."
    )
    st.warning(
        "**No usar durante la operación normal.** Trabaje con intervalos de máximo cinco años. "
        "Mantenga abierta la pestaña hasta que aparezca el ZIP de avance; así cada corrida termina "
        "de forma controlada y puede continuarse sin perder lo aprobado.",
        icon="⚠️",
    )
    st.info(
        "No existen perfiles diferentes: cualquier usuario puede construir y descargar. "
        "Publicar requiere permiso sobre GitHub; la aplicación nunca lo reemplaza automáticamente.",
        icon="ℹ️",
    )
    _publication_guide()
    tabs = st.tabs(["Colombia", "España", "Chile"])
    with tabs[0]:
        _colombia_section(timeout)
    with tabs[1]:
        _spain_section(timeout)
    with tabs[2]:
        _chile_section(timeout)

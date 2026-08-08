"""Página técnica para construir y publicar las bases mensuales por defecto."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from came.data.maintenance import (
    BuildResult,
    ChileMonthlyBuilder,
    ColombiaMonthlyBuilder,
    ProgressEvent,
    SpainMonthlyBuilder,
)
from came.data.monthly_store import (
    LONG_COLUMNS,
    StoredMonthlyPackage,
    allocate_ready_package_directory,
    create_stored_monthly_package,
    discover_ready_monthly_package,
    get_package_spec,
    last_complete_month,
    load_default_metadata,
    load_default_monthly,
    load_stored_monthly_package,
    merge_monthly_data,
)

OPERATION_UPDATE = "Agregar meses faltantes"
OPERATION_BUILD = "Construir la primera base"
OPERATION_RECALCULATE = "Recalcular un periodo"

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
            detail.error(f"{message}\n\nDetalle: {event.detail}")
        else:
            detail.caption(message)

    return update


def _show_current_state(country: str, data: pd.DataFrame, metadata: dict[str, object]) -> None:
    spec = get_package_spec(country)
    st.markdown(f"**Archivos publicados de {spec.label}**")
    if data.empty:
        st.warning("Todavía no existe una base mensual publicada para este país.")
        return
    columns = st.columns(4)
    columns[0].metric("Último mes", str(pd.to_datetime(data["datetime"], utc=True).max().date()))
    columns[1].metric("Series", f"{data['series_id'].nunique():,}")
    columns[2].metric("Filas", f"{len(data):,}")
    columns[3].metric("Versión", str(metadata.get("schema_version", "Sin JSON")))


def _result_for_session(
    result: BuildResult,
    package: StoredMonthlyPackage | None,
) -> dict[str, object]:
    """Conserva solo un resumen pequeño; la base y el ZIP permanecen en disco."""

    return {
        "status": result.status,
        "warnings": list(result.warnings),
        "errors": list(result.errors),
        "package_directory": str(package.directory) if package else None,
        "country": result.country,
        "recovered": False,
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
        "warnings": [],
        "errors": [],
        "package_directory": str(package.directory),
        "country": country,
        "recovered": True,
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
        st.error(
            f"La ejecución terminó, pero NO se creó el ZIP: quedaron {len(errors)} "
            "error(es) bloqueante(s). "
            "Los bloques aprobados quedaron guardados "
            "temporalmente. Pulse de nuevo con la misma operación y el mismo periodo: "
            "la aplicación reutilizará los bloques aprobados y reintentará únicamente los pendientes."
        )
        with st.expander("Errores que deben resolverse", expanded=True):
            for error in errors:
                st.write(f"- {error}")
        return
    try:
        package = _package_from_state(state)
    except Exception as exc:
        st.error(
            "La construcción terminó, pero los archivos de descarga no pudieron recuperarse. "
            f"Detalle: {exc}"
        )
        return
    if package is None:
        st.error(
            "La construcción terminó sin errores de fuente, pero no quedó un paquete guardado. "
            "Ejecute nuevamente la misma operación; los bloques aprobados se reutilizarán."
        )
        return
    st.success("Paquete listo. El ZIP quedó guardado y ya puede descargarlo.")
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
    metrics[2].metric("Último mes", str(package.metadata.get("last_complete_month", "")))
    st.info(
        "Después de descomprimir el ZIP, copie sus tres archivos en esta carpeta exacta "
        f"del repositorio: `{spec.relative_directory.as_posix()}/`. "
        "Reemplace los tres juntos y conserve sus nombres."
    )
    _download_file(
        "Descargar ZIP listo para GitHub",
        package.zip_path,
        file_name=f"Base_mensual_{spec.label}.zip",
        mime="application/zip",
        key=f"{key}_zip",
        primary=True,
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

    if result.errors:
        phase.error(
            f"El empaquetado NO comenzó: quedaron {len(result.errors)} error(es) bloqueante(s). "
            "Los avances aprobados se conservaron para reintentar solo lo pendiente."
        )
        return None
    if result.data.empty:
        result.errors.append("La consulta terminó sin observaciones válidas para empaquetar.")
        phase.error("El empaquetado NO comenzó porque la base resultante está vacía.")
        return None
    try:
        output = allocate_ready_package_directory(country, build_id)
        package = create_stored_monthly_package(
            result.data,
            country,
            output,
            additional_sheets=additional_sheets,
            build_notes=build_notes,
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


def _period_controls(
    country: str,
    operation: str,
    existing: pd.DataFrame,
    *,
    default_start: date,
    key: str,
) -> tuple[date, date, pd.DataFrame | None, date | None, date | None] | None:
    complete = last_complete_month().date()
    complete_end = (last_complete_month() + pd.offsets.MonthEnd()).date()
    if operation == OPERATION_BUILD:
        start = st.date_input(
            "Fecha inicial de la historia", value=default_start, key=f"{key}_start_build"
        )
        end = st.date_input(
            "Último día a consultar",
            value=complete_end,
            max_value=complete_end,
            key=f"{key}_end_build",
        )
        return start, end, None, None, None
    if operation == OPERATION_UPDATE:
        if existing.empty:
            st.info("No existe un Parquet publicado. Seleccione **Construir la primera base**.")
            return None
        current_last = pd.to_datetime(existing["datetime"], utc=True).max()
        start_ts = current_last + pd.offsets.MonthBegin()
        if start_ts.date() > complete:
            st.success("La base publicada ya contiene el último mes calendario completo.")
            return None
        start = start_ts.date()
        st.write(f"Se descargarán únicamente los meses entre **{start}** y **{complete_end}**.")
        return start, complete_end, existing, None, None
    columns = st.columns(2)
    start = columns[0].date_input(
        "Primer mes que se reemplazará", value=default_start, key=f"{key}_start_recalc"
    )
    end = columns[1].date_input(
        "Último mes que se reemplazará",
        value=complete_end,
        max_value=complete_end,
        key=f"{key}_end_recalc",
    )
    if existing.empty:
        st.info("No existe una versión publicada sobre la cual reemplazar meses.")
        return None
    return start, end, existing, start, end


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
    operation = st.radio(
        "Operación para Colombia",
        [OPERATION_UPDATE, OPERATION_BUILD, OPERATION_RECALCULATE],
        key="maintenance_col_operation",
    )
    period = _period_controls(
        "COL", operation, existing, default_start=date(2000, 1, 1), key="maintenance_col"
    )
    st.caption("La construcción completa incluye XM, TRM y ONI automáticamente.")
    confirm = st.checkbox(
        "Entiendo que la operación puede tardar y mantendré abierta esta pestaña.",
        key="maintenance_col_confirm",
    )
    clear = st.checkbox(
        "Ignorar avances temporales y volver a consultar todos los bloques",
        value=False,
        key="maintenance_col_clear",
    )
    st.caption(
        "Si aparece un error como `XM · DemaSIN · 2004...`, no marque la opción anterior. "
        "Ejecute de nuevo la misma operación: los años aprobados se reutilizan y el año fallido "
        "se intenta nuevamente. Cada bloque tiene tres intentos automáticos."
    )
    button_label = (
        "Reanudar o iniciar construcción"
        if operation != OPERATION_UPDATE
        else "Actualizar meses faltantes"
    )
    if period and st.button(
        button_label, type="primary", disabled=not confirm, key="maintenance_col_run"
    ):
        start, end, base, replace_start, replace_end = period
        build_id = f"COL_{operation}_{start}_{end}"
        builder = ColombiaMonthlyBuilder(timeout=timeout, build_id=build_id)
        if clear:
            builder.clear_checkpoints()
        progress = st.container()
        with st.spinner("Procesando fuentes oficiales por bloques…"):
            result = builder.build(
                start,
                end,
                existing=base,
                replace_start=replace_start,
                replace_end=replace_end,
                include_macro=True,
                callback=_progress_callback(progress),
            )
        package = _create_download_package(
            result,
            country="COL",
            build_id=build_id,
            additional_sheets=_additional_sheets(result),
            build_notes=[
                f"Operación: {operation}.",
                "La asociación histórica recurso–empresa corresponde al catálogo XM usado en la consulta.",
            ],
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
    st.subheader("Cómo publicar una actualización")
    st.info(
        "El ZIP ya contiene la ruta correcta. Dentro del repositorio del Laboratorio CAME, "
        "los archivos deben quedar en `datos_por_defecto/colombia/`, "
        "`datos_por_defecto/espana/` o `datos_por_defecto/chile/`, según el país."
    )
    st.markdown(
        "1. Construya o actualice un país y espere el mensaje **Paquete listo**.\n"
        "2. Descargue el ZIP; no publique archivos de una ejecución con errores.\n"
        "3. Descomprímalo y abra en GitHub la carpeta exacta incluida en el ZIP.\n"
        "4. Reemplace juntos el Parquet, el catálogo Excel y el JSON, sin cambiar sus nombres.\n"
        "5. Confirme el cambio mediante un *commit*. Solo una persona con permiso de GitHub "
        "puede publicarlo; Streamlit nunca modifica el repositorio automáticamente.\n"
        "6. Espere el nuevo despliegue y compruebe el último mes desde **Base integrada**."
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
        "**No usar durante la operación normal.** Una construcción histórica consulta muchas "
        "observaciones y puede tardar. Mantenga abierta la pestaña y no actualice archivos en "
        "GitHub hasta que aparezca **Descargar ZIP listo para GitHub**.",
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

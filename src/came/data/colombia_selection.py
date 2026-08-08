"""Canasta recomendada y prioridades de la base mensual colombiana."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ColombiaVariableOption:
    key: str
    group: str
    label: str
    source: str
    description: str
    default: bool = True
    required: bool = False


PRIORITY_COMPANIES = {
    "epm": ("EPM", ("EPMG",)),
    "aes_chivor": ("AES Colombia–Chivor", ("CHVG",)),
    "enel": ("Enel Colombia", ("ENDG",)),
    "isagen": ("ISAGEN", ("ISGG",)),
    "termoemcali": ("Termoemcali", ("TEMG",)),
    "termobarranquilla": ("Termobarranquilla", ("TBSG",)),
    "termotasajero": ("Termotasajero", ("TRMG", "TERG")),
    "celsia": ("Celsia", ("EPSG",)),
    "gecelca": ("Gecelca", ("GECG",)),
}

PRIORITY_RESOURCES = {
    "GTPE": "Guatapé",
    "PRC3": "Porce III",
    "SNCR": "San Carlos",
    "TSR1": "Termosierra",
    "TRM1": "Termocentro",
}

THERMAL_TECHNOLOGIES = {"Gas", "Carbón", "ACPM", "Combustóleo", "Jet-A1", "GLP"}


COLOMBIA_VARIABLE_OPTIONS = (
    ColombiaVariableOption("demand", "Base CAME", "Demanda nacional", "XM · DemaSIN", "Total mensual y promedio diario."),
    ColombiaVariableOption("spot_price", "Base CAME", "Precio de bolsa nacional", "XM · PrecBolsNaci", "Promedio simple mensual."),
    ColombiaVariableOption("generation_national", "Base CAME", "Generación nacional", "XM · Gene/Recurso", "Total, hidráulica, térmica y otras."),
    ColombiaVariableOption("generation_technology", "Generación", "Generación por tecnología", "XM · Gene/Recurso", "Totales mensuales nacionales por tecnología."),
    ColombiaVariableOption("generation_companies", "Generación", "Empresas prioritarias", "XM · Gene/Recurso", "EPM, AES–Chivor, Enel, ISAGEN, Termoemcali, Termobarranquilla, Termotasajero, Celsia y Gecelca."),
    ColombiaVariableOption("generation_resources", "Generación", "Plantas prioritarias", "XM · Gene/Recurso", "Guatapé, Porce III, San Carlos, Termosierra y Termocentro."),
    ColombiaVariableOption("contract_mc", "Precios", "Índice MC", "XM", "Costo promedio ponderado de convocatorias para mercado regulado."),
    ColombiaVariableOption("contract_regulated", "Precios", "Contratos regulados", "XM · PrecPromContRegu", "Precio promedio mensual del mercado regulado."),
    ColombiaVariableOption("contract_nonregulated", "Precios", "Contratos no regulados", "XM · PrecPromContNoRegu", "Precio promedio mensual del mercado no regulado."),
    ColombiaVariableOption("scarcity_price", "Precios", "Precios de escasez", "XM · PrecEsca", "Precio de escasez mensual."),
    ColombiaVariableOption("fuel_offers", "Precios", "Ofertas de gas y carbón", "XM · PrecOferDesp + CapEfecNeta", "Promedio simple y promedio ponderado por capacidad instalada."),
    ColombiaVariableOption("inflows", "Sistema", "Aportes hídricos", "XM · AporEner", "Total mensual y promedio diario."),
    ColombiaVariableOption("capacity", "Sistema", "Capacidad efectiva neta", "XM · CapEfecNeta", "CEN total mensual en MW."),
    ColombiaVariableOption("reservoir", "Sistema", "Nivel o volumen útil de embalse", "XM · VoluUtilDiarEner", "Último valor oficial de cada mes."),
    ColombiaVariableOption("availability", "Sistema", "Disponibilidad de generación", "XM · catálogo vivo", "Serie oficial disponible para el periodo."),
    ColombiaVariableOption("imports_exports", "Sistema", "Importaciones y exportaciones", "XM · catálogo vivo", "Intercambios de electricidad publicados por XM."),
    ColombiaVariableOption("unserved", "Sistema", "Demanda no atendida", "XM · área/subárea", "Programada y no programada, sin doble conteo."),
    ColombiaVariableOption("restrictions", "Sistema", "Restricciones", "XM · RestSinAliv", "Costo mensual de restricciones."),
    ColombiaVariableOption("market_exposure", "Sistema", "Exposición y compras netas en bolsa", "XM · catálogo vivo", "Variables comerciales disponibles para el periodo."),
    ColombiaVariableOption("trm", "Macro", "TRM", "datos.gov.co", "Promedio mensual COP/USD."),
    ColombiaVariableOption("enso", "Macro", "ONI, El Niño y La Niña", "NOAA/CPC", "Indicadores climáticos mensuales."),
)


DEFAULT_SELECTION = {option.key for option in COLOMBIA_VARIABLE_OPTIONS if option.default}


def selection_catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Clave": option.key,
                "Grupo": option.group,
                "Variable": option.label,
                "Fuente": option.source,
                "Descripción": option.description,
                "Preseleccionada": option.default,
                "Obligatoria": option.required,
            }
            for option in COLOMBIA_VARIABLE_OPTIONS
        ]
    )


def is_recommended_series(series_id: object, level: object = "", entity_code: object = "") -> bool:
    """Marca la canasta inicial incluso al leer un paquete 1.3.x con series más amplias."""

    sid = str(series_id).casefold()
    code = str(entity_code).upper()
    lvl = str(level).casefold()
    base_prefixes = (
        "col_demanda_",
        "col_precio_",
        "col_generacion_total_",
        "col_generacion_nacional_",
        "col_aportes_",
        "col_cen_",
        "col_volumen_util_",
        "col_dna_",
        "col_trm_",
        "col_enso_",
        "col_restricciones_",
        "col_import",
        "col_export",
        "col_dispon",
        "col_expos",
        "col_compras_netas",
    )
    if sid.startswith(base_prefixes):
        return True
    if "tecnologia" in sid or "empresa_grupo" in sid:
        return True
    if lvl == "empresa" and code in {code for _, codes in PRIORITY_COMPANIES.values() for code in codes}:
        return True
    return lvl == "recurso" and code in PRIORITY_RESOURCES

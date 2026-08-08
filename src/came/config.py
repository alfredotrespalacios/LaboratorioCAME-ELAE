"""Configuración central, catálogos guiados y valores pedagógicos."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

APP_TITLE = "Laboratorio CAME"
APP_SUBTITLE = "Plataforma ELAE de análisis de mercados eléctricos"
APP_VERSION = "1.2.1"

COLORS = {
    "navy": "#18324A",
    "blue": "#1F4E79",
    "mid_blue": "#2E74B5",
    "sky": "#EAF2F8",
    "gold": "#C69214",
    "green": "#237A57",
    "red": "#9B1C1C",
    "gray": "#667085",
    "light": "#F7F9FC",
}

TECHNOLOGY_ORDER = [
    "Hidráulica",
    "Gas",
    "Carbón",
    "ACPM",
    "Combustóleo",
    "Bagazo",
    "Solar",
    "GLP",
    "Jet-A1",
    "Eólica",
    "Biogás",
    "Cogeneración",
    "Biomasa",
    "Otras",
]

TECHNOLOGY_ALIASES = {
    "agua": "Hidráulica",
    "hidraulica": "Hidráulica",
    "hidráulica": "Hidráulica",
    "hydro": "Hidráulica",
    "gas": "Gas",
    "carbon": "Carbón",
    "carbón": "Carbón",
    "acpm": "ACPM",
    "diesel": "ACPM",
    "diésel": "ACPM",
    "combustoleo": "Combustóleo",
    "combustóleo": "Combustóleo",
    "fuel oil": "Combustóleo",
    "bagazo": "Bagazo",
    "solar": "Solar",
    "glp": "GLP",
    "jet-a1": "Jet-A1",
    "jet a1": "Jet-A1",
    "viento": "Eólica",
    "eolica": "Eólica",
    "eólica": "Eólica",
    "wind": "Eólica",
    "biogas": "Biogás",
    "biogás": "Biogás",
    "cogeneracion": "Cogeneración",
    "cogeneración": "Cogeneración",
    "biomasa": "Biomasa",
}

BALANCE_DEFAULTS = {
    "Hidráulica": (0.52, 0.35),
    "Gas": (0.90, 0.90),
    "Carbón": (0.90, 0.90),
    "ACPM": (0.90, 0.90),
    "Combustóleo": (0.90, 0.90),
    "Bagazo": (0.90, 0.90),
    "Solar": (0.17, 0.17),
    "GLP": (0.90, 0.90),
    "Jet-A1": (0.90, 0.90),
    "Eólica": (0.25, 0.25),
    "Biogás": (0.90, 0.90),
    "Otras": (0.90, 0.90),
}

OFFER_STAT_DEFAULTS = {
    "Hidráulica": "P5",
    "Solar": "P5",
    "Eólica": "P5",
}

REDATA_SYSTEMS = {
    "Península": ("peninsular", 8741),
    "Canarias": ("canarias", 8742),
    "Baleares": ("baleares", 8743),
    "Ceuta": ("ceuta", 8744),
    "Melilla": ("melilla", 8745),
}

REDATA_WIDGETS = {
    "Demanda": ("demanda", "evolucion", "MWh"),
    "Balance eléctrico": ("balance", "balance-electrico", "MWh"),
    "Generación por tecnología": ("generacion", "estructura-generacion", "MWh"),
    "Potencia instalada": ("generacion", "potencia-instalada", "MW"),
    "Intercambios físicos": ("intercambios", "todas-fronteras-fisicos", "MWh"),
}

# Mapeos guiados. El explorador siempre usa el catálogo vivo y no depende de esta lista.
XM_METRIC_CANDIDATES = {
    "spot_price": [("PrecBolsNaci", "Sistema")],
    "demand": [("DemaSIN", "Sistema")],
    "generation": [("Gene", "Sistema"), ("Gene", "Recurso")],
    "capacity": [("CapEfecNeta", "Recurso"), ("CEN", "Recurso")],
    "reservoir": [("VoluUtilDiarEner", "Embalse"), ("VoluUtil", "Embalse")],
    "inflows": [("AporEner", "Sistema"), ("AporEner", "Rio")],
}


@dataclass(frozen=True)
class AppSettings:
    """Configuración segura leída de secretos o variables de entorno."""

    access_password: str | None = None
    access_version: str = "local"
    dev_mode: bool = False
    cache_ttl_seconds: int = 3600
    request_timeout_seconds: int = 45
    chile_costs_url: str | None = None
    chile_demand_url: str | None = None

    @property
    def authentication_required(self) -> bool:
        return not self.dev_mode

    @classmethod
    def from_mapping(cls, secrets: Mapping[str, Any] | None = None) -> AppSettings:
        values: Mapping[str, Any] = secrets or {}

        def read(name: str, default: Any = None) -> Any:
            if name in values:
                return values[name]
            return os.getenv(name, default)

        dev_raw = read("CAME_DEV_MODE", "false")
        dev_mode = (
            dev_raw if isinstance(dev_raw, bool) else str(dev_raw).lower() in {"1", "true", "yes"}
        )
        password_raw = read("ACCESS_PASSWORD")
        return cls(
            access_password=str(password_raw) if password_raw is not None else None,
            access_version=str(read("ACCESS_VERSION", "local")),
            dev_mode=dev_mode,
            cache_ttl_seconds=int(read("CACHE_TTL_SECONDS", 3600)),
            request_timeout_seconds=int(read("REQUEST_TIMEOUT_SECONDS", 45)),
            chile_costs_url=read("CHILE_COSTS_URL", read("CHILE_DOWNLOAD_URL")),
            chile_demand_url=read("CHILE_DEMAND_URL"),
        )


def canonical_technology(value: object) -> str:
    """Homologa una etiqueta conocida y deja trazable lo no clasificado como Otras."""

    text = str(value or "").strip()
    lowered = text.casefold()
    for alias, canonical in TECHNOLOGY_ALIASES.items():
        if alias in lowered:
            return canonical
    return "Otras"


def default_offer_stat(technology: str) -> str:
    return OFFER_STAT_DEFAULTS.get(technology, "P50")

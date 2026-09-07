"""Canasta de resultados y constructor del prompt del Informe ejecutivo."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from came.schema import AnalysisPackage


def _table_preview(table: pd.DataFrame | None, rows: int = 20) -> list[dict[str, Any]]:
    if table is None:
        return []
    safe = table.head(rows).copy()
    for column in safe.select_dtypes(include=["datetimetz"]).columns:
        safe[column] = safe[column].astype(str)
    return json.loads(safe.to_json(orient="records", date_format="iso"))


def make_package(
    *,
    module: str,
    title: str,
    period: str,
    source: str,
    unit: str,
    configuration: dict[str, Any],
    indicators: dict[str, Any],
    methodology: list[str],
    warnings: list[str] | None = None,
    table: pd.DataFrame | None = None,
    additional_tables: dict[str, Any] | None = None,
    user_note: str = "",
    package_id: str | None = None,
) -> AnalysisPackage:
    additional_preview = {
        str(name): _table_preview(value if isinstance(value, pd.DataFrame) else pd.DataFrame(value))
        for name, value in (additional_tables or {}).items()
        if value is not None
    }
    return AnalysisPackage(
        package_id=package_id or uuid.uuid4().hex[:12],
        module=module,
        title=title,
        created_at=datetime.now(UTC).isoformat(),
        period=period,
        source=source,
        unit=unit,
        configuration=configuration,
        indicators=indicators,
        methodology=methodology,
        warnings=warnings or [],
        table_preview=_table_preview(table),
        additional_tables_preview=additional_preview,
        user_note=user_note,
    )


def build_executive_prompt(
    packages: list[AnalysisPackage | dict[str, Any]],
    *,
    audience: str,
    tone: str,
    length: str,
    technical_level: str,
    news: list[dict[str, str]] | None = None,
    questions: list[str] | None = None,
) -> str:
    normalized = [
        package.to_dict() if isinstance(package, AnalysisPackage) else package
        for package in packages
    ]
    questions = [question.strip() for question in (questions or []) if question.strip()][:4]
    news = [item for item in (news or []) if any(str(value).strip() for value in item.values())][:3]
    payload = json.dumps(normalized, ensure_ascii=False, indent=2, default=str)
    news_text = json.dumps(news, ensure_ascii=False, indent=2)
    questions_text = (
        "\n".join(f"{index + 1}. {question}" for index, question in enumerate(questions))
        or "No se formularon preguntas específicas."
    )
    return f"""Actúa como analista senior de mercados eléctricos y redacta un informe ejecutivo.

## Propósito y audiencia

- Audiencia: {audience}
- Tono: {tone}
- Extensión: {length}
- Nivel técnico: {technical_level}

## Reglas obligatorias

1. Usa únicamente las cifras suministradas en los paquetes de resultados.
2. No inventes datos, causas, fuentes ni resultados no incluidos.
3. Distingue expresamente datos observados, resultados calculados y supuestos del usuario.
4. Cada cifra debe conservar su unidad, periodo y fuente.
5. Explica las advertencias y limitaciones materiales.
6. Si una pregunta no puede responderse con la evidencia suministrada, indícalo con claridad.
7. Estructura el informe con: resumen ejecutivo, hallazgos, metodología, riesgos o limitaciones, respuestas clave y conclusiones.

## Preguntas del usuario

{questions_text}

## Noticias aportadas por el usuario

Estas referencias pueden orientar contexto, pero no sustituyen los datos. Consulta una URL solo si tienes acceso a internet y diferencia lo encontrado de los resultados de la aplicación.

{news_text}

## Paquetes estructurados de resultados

```json
{payload}
```
"""

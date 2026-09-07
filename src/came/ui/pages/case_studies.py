"""Módulos 14–18: casos de estudio del curso."""

from __future__ import annotations

import streamlit as st

from came.ui.components import page_header

CASE_STUDY_TITLES = {
    14: "Caso de estudio 1",
    15: "Caso de estudio 2",
    16: "Caso de estudio 3",
    17: "Caso de estudio 4",
    18: "Caso de estudio 5",
}


def page_case_study(number: int) -> None:
    """Muestra el espacio reservado para un caso de estudio aprobado por ELAE."""

    page_header(
        number,
        CASE_STUDY_TITLES[number],
        "Espacio reservado para el caso de estudio, sus datos, instrucciones y rúbrica.",
        "Contenido académico por publicar",
    )
    st.info("Próximamente disponible")
    st.write(
        "El módulo está incorporado en la navegación definitiva y no presenta casos "
        "ficticios. Se activará cuando ELAE publique el contenido académico aprobado."
    )

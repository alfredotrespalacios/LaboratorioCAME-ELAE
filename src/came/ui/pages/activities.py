"""Módulos 14–19: actividades académicas e informe ejecutivo."""

from __future__ import annotations

import streamlit as st

from came.ui.components import page_header

ACTIVITY_TITLES = {
    14: "Actividad académica 1",
    15: "Actividad académica 2",
    16: "Actividad académica 3",
    17: "Actividad académica 4",
    18: "Actividad académica 5",
}


def page_activity(number: int) -> None:
    page_header(
        number,
        ACTIVITY_TITLES[number],
        "Espacio reservado para el caso de estudio, sus datos, instrucciones y rúbrica.",
        "Contenido académico por publicar",
    )
    st.info("Próximamente disponible")
    st.write(
        "El módulo está incorporado en la navegación definitiva y no presenta ejercicios ficticios. "
        "Se activará cuando ELAE entregue el contenido académico aprobado."
    )

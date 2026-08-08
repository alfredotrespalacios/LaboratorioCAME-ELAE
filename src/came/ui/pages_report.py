"""Módulos 14–19: actividades académicas e informe ejecutivo."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from came.report import build_executive_prompt
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


def page_report() -> None:
    page_header(
        19,
        "Informe ejecutivo",
        "Combina resultados seleccionados y genera un prompt TXT verificable para redactar el informe.",
        "Canasta de resultados de esta sesión",
    )
    packages = st.session_state.setdefault("report_packages", [])
    if not packages:
        st.info("Use “Añadir al informe” en cualquier módulo con resultados para construir la canasta.")
    else:
        overview = pd.DataFrame(
            [
                {
                    "Seleccionar": True,
                    "Módulo": item.get("module"),
                    "Título": item.get("title"),
                    "Periodo": item.get("period"),
                    "Fuente": item.get("source"),
                    "ID": item.get("package_id"),
                }
                for item in packages
            ]
        )
        edited = st.data_editor(
            overview,
            hide_index=True,
            use_container_width=True,
            key="report_selector",
            disabled=["Módulo", "Título", "Periodo", "Fuente", "ID"],
        )
        selected_ids = set(edited.loc[edited["Seleccionar"], "ID"])
        packages = [item for item in packages if item.get("package_id") in selected_ids]
        if st.button("Eliminar de la canasta los no seleccionados", key="remove_unselected"):
            st.session_state["report_packages"] = packages
            st.rerun()

    col1, col2 = st.columns(2)
    audience = col1.text_input("Audiencia", value="Dirección académica y participantes ELAE")
    tone = col2.selectbox("Tono", ["Ejecutivo y claro", "Académico", "Técnico", "Divulgativo"])
    col1, col2 = st.columns(2)
    length = col1.selectbox("Extensión", ["2–3 páginas", "1 página", "4–6 páginas"])
    technical_level = col2.selectbox("Nivel técnico", ["Intermedio", "Básico", "Avanzado"])
    with st.expander("Hasta tres noticias o referencias aportadas por el usuario"):
        news = []
        for index in range(3):
            left, right = st.columns(2)
            news.append(
                {
                    "titulo": left.text_input(f"Título {index + 1}", key=f"news_title_{index}"),
                    "url": right.text_input(f"URL {index + 1}", key=f"news_url_{index}"),
                }
            )
    with st.expander("Hasta cuatro preguntas que debe responder el informe"):
        questions = [st.text_input(f"Pregunta {index + 1}", key=f"report_question_{index}") for index in range(4)]
    prompt = build_executive_prompt(
        packages,
        audience=audience,
        tone=tone,
        length=length,
        technical_level=technical_level,
        news=news,
        questions=questions,
    )
    st.download_button(
        "Descargar prompt ejecutivo TXT",
        prompt.encode("utf-8"),
        file_name="prompt_informe_ejecutivo_came.txt",
        mime="text/plain",
        type="primary",
        use_container_width=True,
    )
    with st.expander("Vista previa del prompt"):
        st.code(prompt, language="markdown")
    if st.button("Nuevo informe", key="new_report"):
        st.session_state["report_packages"] = []
        for index in range(3):
            st.session_state.pop(f"news_title_{index}", None)
            st.session_state.pop(f"news_url_{index}", None)
        for index in range(4):
            st.session_state.pop(f"report_question_{index}", None)
        st.rerun()

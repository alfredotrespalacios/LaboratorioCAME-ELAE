"""Página inicial y condiciones de uso académico del Laboratorio CAME."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def page_introduction() -> None:
    """Presenta el alcance, la navegación y las reglas de uso de la aplicación."""

    st.header("Introducción")
    st.write(
        "El **Laboratorio CAME** es una aplicación académica de **ELAE — Escuela "
        "Latinoamericana de Administración y Emprendimiento** para apoyar el aprendizaje "
        "del análisis de mercados eléctricos. Reúne datos oficiales, visualizaciones, "
        "modelación, casos de estudio y herramientas para preparar informes ejecutivos."
    )

    st.info(
        "Esta aplicación es propiedad de ELAE. Su uso está autorizado únicamente a los "
        "participantes del curso durante el periodo de formación y bajo las condiciones "
        "definidas por ELAE."
    )

    st.subheader("¿Qué encontrará en la aplicación?")
    modules = pd.DataFrame(
        [
            {
                "Sección": "Colombia",
                "Contenido": "Módulos 1–8",
                "Propósito": "Consultar y analizar precio, demanda, generación y mercado XM.",
            },
            {
                "Sección": "Otros mercados",
                "Contenido": "Módulos 9–10",
                "Propósito": "Explorar información oficial de España y Chile.",
            },
            {
                "Sección": "Análisis y modelación",
                "Contenido": "Módulos 11–12",
                "Propósito": "Construir pronósticos y estudiar series y volatilidad.",
            },
            {
                "Sección": "Estructuración de portafolios",
                "Contenido": "Módulo 13",
                "Propósito": "Simular portafolios de generación mediante Monte Carlo.",
            },
            {
                "Sección": "Casos de estudio",
                "Contenido": "Módulos 14–18",
                "Propósito": "Aplicar los conceptos del curso en situaciones guiadas.",
            },
            {
                "Sección": "Informe",
                "Contenido": "Módulo 19",
                "Propósito": "Reunir resultados elegidos y preparar un informe ejecutivo.",
            },
        ]
    )
    st.dataframe(modules, hide_index=True, width="stretch")

    st.subheader("Ruta recomendada")
    st.markdown(
        """
        1. Seleccione un módulo en el menú lateral.
        2. Revise la fuente, el periodo, la unidad y las advertencias del resultado.
        3. Ajuste los parámetros y contraste los resultados con el contenido del curso.
        4. Descargue las tablas o gráficos que necesite.
        5. Pulse **Guardar resultado para el informe ejecutivo** únicamente cuando quiera
           conservar ese resultado durante la sesión.
        """
    )
    st.caption(
        "Mantenimiento de datos es una herramienta técnica para actualizar los paquetes "
        "publicados; no hace parte de la ruta normal del estudiante."
    )

    st.subheader("Condiciones y alcance")
    st.markdown(
        """
        - El acceso es personal y no debe compartirse con terceros.
        - No está permitido copiar, redistribuir, publicar ni comercializar la aplicación,
          su código o los materiales académicos sin autorización escrita de ELAE.
        - Los datos conservan la propiedad y las condiciones de sus fuentes oficiales.
        - Los resultados tienen fines pedagógicos y no constituyen asesoría profesional,
          recomendación de inversión, instrucción operativa ni concepto regulatorio.
        - ELAE puede actualizar el contenido y finalizar el acceso cuando termine el curso.
        """
    )
    st.caption("© 2026 ELAE. Todos los derechos reservados.")

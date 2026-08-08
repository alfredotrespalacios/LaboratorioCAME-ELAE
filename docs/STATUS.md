# Estado y bitácora

## Estado actual

- Versión 1.0.0 completa y lista para entrega.
- Los 19 módulos están incorporados en la navegación definitiva.
- Las cinco actividades permanecen como marcadores aprobados, sin contenido ficticio.
- No existen credenciales dentro del repositorio.

## Decisiones técnicas

- Código de negocio separado de Streamlit para permitir pruebas numéricas.
- Conectores por fuente con salida canónica común.
- Dependencias opcionales de modelación se cargan de manera diferida.
- Las pruebas de integración se separan de las unitarias para distinguir fallas de código de
  indisponibilidad temporal de una fuente externa.

## Verificaciones cerradas

- Lint, 21 pruebas locales y smoke de Streamlit aprobados.
- Tres pruebas de contrato vivo aprobadas.
- Balance y curva contrastados con los Excel recibidos.
- XM validado con las siete rutas guiadas principales y la base integrada.

## Limitación documentada

- Chile requiere exportación oficial TSV/XLSX cuando Qlik/Cloudflare impide automatizar la descarga.

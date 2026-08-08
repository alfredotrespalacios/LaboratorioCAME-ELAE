# Estado y bitácora

## Estado actual

- Versión 1.1.0 implementada y validada localmente.
- Los 19 módulos están incorporados en la navegación definitiva.
- Las cinco actividades permanecen como marcadores aprobados, sin contenido ficticio.
- No existen credenciales dentro del repositorio.
- Mantenimiento construye paquetes mensuales separados para Colombia, España y Chile.

## Decisiones técnicas

- Código de negocio separado de Streamlit para permitir pruebas numéricas.
- Conectores por fuente con salida canónica común.
- Dependencias opcionales de modelación se cargan de manera diferida.
- Cada página visible tiene un archivo propio en `src/came/ui/pages/`.
- Pronósticos, SARIMA–GARCH y portafolios leen directamente el Parquet publicado.
- La aplicación no usa una base de datos externa: publica Parquet, catálogo Excel y JSON en GitHub.
- Las pruebas de integración se separan de las unitarias para distinguir fallas de código de
  indisponibilidad temporal de una fuente externa.

## Verificaciones cerradas

- Lint, 43 pruebas locales y smoke de Streamlit aprobados el 8 de agosto de 2026.
- Tres pruebas de contrato vivo aprobadas.
- Balance y curva contrastados con los Excel recibidos.
- El empaquetado mensual, el ZIP, la exclusión del mes incompleto y el último valor mensual de
  volumen útil tienen pruebas locales.

## Limitación documentada

- Chile requiere tres exportaciones oficiales TSV/XLSX cuando Qlik/Cloudflare impide automatizar:
  costos marginales, demanda por barra y generación por tecnología.
- La primera base histórica completa todavía debe ejecutarse desde Streamlit en un entorno con
  acceso a las fuentes oficiales; este entorno de desarrollo no conserva una conexión viva a XM.

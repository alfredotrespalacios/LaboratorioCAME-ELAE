# Estado y bitácora

## Estado actual

- Versión 1.2.2 implementada y validada localmente.
- Los 19 módulos están incorporados en la navegación definitiva.
- Las cinco actividades permanecen como marcadores aprobados, sin contenido ficticio.
- No existen credenciales dentro del repositorio.
- Mantenimiento construye paquetes mensuales separados para Colombia, España y Chile.
- Precio y Demanda mensual leen primero el Parquet publicado; XM queda como consulta opcional.
- El Informe ejecutivo recibe resultados únicamente cuando el usuario pulsa el botón de guardado.

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

- Lint, 52 pruebas locales y smoke de Streamlit aprobados el 8 de agosto de 2026.
- Los tres contratos vivos fueron aprobados en la validación v1.1.0; la v1.2.0 no los repitió en
  este entorno restringido.
- Balance y curva contrastados con los Excel recibidos.
- El empaquetado mensual, el ZIP, la exclusión del mes incompleto y el último valor mensual de
  volumen útil tienen pruebas locales.
- El ZIP validado se guarda en disco temporal antes de mostrar los botones y puede recuperarse
  después de un `rerun` de Streamlit sin repetir la construcción.
- Las carpetas temporales de avance y del paquete se recrean antes de cada escritura. Limpiar
  avances o perder una carpeta temporal durante una ejecución ya no bloquea el siguiente bloque.
- Rendimientos simple/logarítmico, exclusión del último día incompleto, reintentos de bloques y
  guardado manual al informe tienen pruebas locales.

## Limitación documentada

- Chile requiere tres exportaciones oficiales TSV/XLSX cuando Qlik/Cloudflare impide automatizar:
  costos marginales, demanda por barra y generación por tecnología.
- La primera base histórica completa todavía debe ejecutarse desde Streamlit en un entorno con
  acceso a las fuentes oficiales; este entorno de desarrollo no conserva una conexión viva a XM.

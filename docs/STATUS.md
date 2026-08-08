# Estado y bitácora

## Estado actual

- Versión 1.3.2 implementada y validada localmente.
- La Introducción es la primera página y explica módulos, ruta de uso, propiedad y alcance académico.
- Los 19 módulos están incorporados en la navegación definitiva.
- Los cinco casos de estudio permanecen como marcadores aprobados, sin contenido ficticio.
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
- El despliegue exige Python 3.12 antes de importar los módulos de la aplicación y las páginas se
  cargan únicamente cuando el usuario las abre.

## Verificaciones cerradas

- Lint, 60 pruebas locales y smoke de Streamlit aprobados el 8 de agosto de 2026.
- Los tres contratos vivos fueron aprobados en la validación v1.1.0; la v1.2.0 no los repitió en
  este entorno restringido.
- Balance y curva contrastados con los Excel recibidos.
- El empaquetado mensual, el ZIP, la exclusión del mes incompleto y el último valor mensual de
  volumen útil tienen pruebas locales.
- El ZIP se construye por etapas en disco, fuera del repositorio observado por Streamlit. Puede
  recuperarse después de perder `session_state` y una sesión nueva lo vuelve a mostrar.
- Una prueba de interfaz ejecuta **Construir la primera base**, comprueba el botón del ZIP y crea
  una segunda sesión que recupera la misma descarga. La versión anterior solo probaba un paquete
  preparado de antemano y por eso no cubría el cierre real reportado.
- El cierre conserva visibles **0/5** y las cinco fases. Un error bloqueante muestra en **0/5** por
  qué no comenzó el empaquetado; una ausencia de cobertura complementaria no se confunde con una
  caída de la fuente.
- Las carpetas temporales de avance y del paquete se recrean antes de cada escritura. Limpiar
  avances o perder una carpeta temporal durante una ejecución ya no bloquea el siguiente bloque.
- Rendimientos simple/logarítmico, exclusión del último día incompleto, reintentos de bloques y
  guardado manual al informe tienen pruebas locales.
- La prueba en vivo de XM respondió 502 durante el cierre de v1.3.0; REData y OMIE sí respondieron.
  El chequeo local y la navegación no dependen de esa disponibilidad externa.

## Limitación documentada

- Chile requiere tres exportaciones oficiales TSV/XLSX cuando Qlik/Cloudflare impide automatizar:
  costos marginales, demanda por barra y generación por tecnología.
- La primera base histórica completa todavía debe ejecutarse desde Streamlit en un entorno con
  acceso a las fuentes oficiales; este entorno de desarrollo no conserva una conexión viva a XM.
- El registro real recibido el 8 de agosto mostró Python 3.14.7 y fallos repetidos de importación
  durante recargas. Una instancia existente debe eliminarse y volver a desplegarse con Python 3.12;
  actualizar archivos en GitHub no cambia la versión de Python de la instancia.

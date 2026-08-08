# Laboratorio CAME — especificación funcional v1.1

Fecha de consolidación: 7 de agosto de 2026.

Este archivo es la fuente de verdad operativa durante la construcción. Consolida la
especificación funcional v1.0 aprobada y los cambios posteriores del usuario.

## Resultado esperado

Aplicación web en Streamlit, con visualizaciones Plotly, lista para GitHub y Streamlit
Community Cloud. Debe consultar fuentes oficiales abiertas, explicar unidades y supuestos,
permitir exportar resultados y soportar un uso pedagógico por estudiantes autorizados de ELAE.

## Navegación definitiva

### Colombia

1. Precio de bolsa.
2. Demanda nacional.
3. Generación nacional por tecnología.
4. Generación por planta, recurso o empresa.
5. Explorador libre de variables de XM.
6. Base integrada del mercado eléctrico.
7. Balance energético rápido.
8. Curva de oferta rápida.

La base integrada incluye la variable calculada:

`Generación no hidráulica (GWh-día) = Demanda nacional (GWh-día) - Generación hidráulica (GWh-día)`.

### Otros mercados

9. Mercado eléctrico de España.
10. Mercado eléctrico de Chile.

### Análisis y modelación

11. Laboratorio de modelación y pronóstico.
12. Modelación de volatilidad SARIMA–GARCH.

### Estructuración de portafolios

13. Portafolio de generación y simulación Monte Carlo.

### Actividades académicas

14–18. Cinco casos de estudio independientes, inicialmente marcados como “Próximamente
disponible”.

### Informe

19. Informe ejecutivo, siempre como último módulo.

## Reglas no negociables

- No inventar datos ni rellenar faltantes silenciosamente.
- Mantener homogéneas y visibles las unidades.
- Separar datos observados, supuestos editables y resultados calculados.
- Un fallo parcial no debe destruir resultados válidos de otras variables.
- Cada salida debe incluir fuente, periodo, cobertura, unidad, transformación y fecha de consulta.
- La versión 1 no usa una base de datos histórica permanente; usa consultas bajo demanda y caché.
- La contraseña se configura únicamente mediante secretos de despliegue.
- El uso es académico y no sustituye análisis profesional, regulatorio u operativo.

## Valores predeterminados aprobados

- Frecuencia general mensual y máxima historia disponible.
- Partición de modelación 80/20 cronológica; intervalos 80 % y 95 %.
- Rezagos: anterior, seis meses, un año y Tiempo, solo cuando el usuario los elige.
- GARCH(1,1) sobre residuales SARIMA; distribución normal y t de Student.
- Monte Carlo: 1.000 iteraciones iniciales y máximo 1.000.000.
- Balance: hidro 52 %/35 %, térmicas 90 %, solar 17 %, eólica 25 %.
- Curva: P5 para hidráulica, solar y eólica; P50 para las demás tecnologías.
- Exactamente dos escenarios, con nombres editables.
- Informe: hasta tres noticias y cuatro preguntas; conservar hasta “Nuevo informe”.

## Definición de terminado

La entrega solo se considera terminada cuando:

1. Todos los módulos anteriores están navegables y ejecutan su función aprobada o muestran una
   indisponibilidad oficial y trazable, nunca datos inventados.
2. Los cálculos de balance y curva se contrastan contra los Excel entregados.
3. Las fórmulas críticas tienen pruebas unitarias y las fuentes tienen pruebas de contrato/parsing.
4. Se ejecutan lint, pruebas, smoke test de Streamlit y revisión de secretos.
5. Excel, PDF y prompt TXT se generan con sus metadatos.
6. El repositorio incluye README, guía de despliegue, secretos de ejemplo y comandos de prueba.
7. No quedan credenciales, rutas locales absolutas ni datos sensibles en el código.


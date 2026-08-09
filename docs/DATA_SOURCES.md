# Fuentes, unidades y reglas de transformación

| Fuente | Uso | Unidad recibida | Transformación principal |
|---|---|---:|---|
| XM `PrecBolsNaci/Sistema` | Precio de bolsa | COP/kWh | Promedio diario o mensual de intervalos |
| XM `DemaSIN/Sistema` | Demanda nacional | kWh | Conversión a GWh; suma por periodo; GWh-día mensual |
| XM `Gene/Recurso` | Generación | kWh | Conversión a GWh; suma por recurso y tecnología |
| XM `CapEfecNeta/Recurso` | Capacidad | kW | Conversión a MW; última publicación no posterior a la fecha elegida |
| XM `PrecOferDesp/Recurso` | Ofertas | COP/kWh | Promedio simple y promedio ponderado por capacidad efectiva para gas y carbón |
| XM catálogo vivo · MC | Índice MC | COP/kWh | Promedio mensual; separado de contratos regulados/no regulados |
| XM `PrecPromContRegu` y `PrecPromContNoRegu` | Contratos | COP/kWh | Promedio mensual por segmento |
| XM `AporEner/Sistema` | Aportes hídricos | GWh | Suma mensual y promedio por día calendario |
| XM `RestSinAliv/Sistema` | Restricciones | COP | Suma mensual |
| XM demanda no atendida | Interrupciones | kWh | Área como total; subárea solo como verificación si ambas existen |
| REData | Demanda, balance, generación, potencia e intercambios | Publicada por indicador | Se conserva la agregación solicitada a la API |
| OMIE `marginalpdbc` | Precio mercado diario | EUR/MWh | Parser de 24/25 horas y 92/96/100 cuartos de hora |
| Coordinador de Chile | Costo y demanda por barra | USD/MWh y MWh | Coincidencia fecha/barra y promedio nacional ponderado por demanda |
| datos.gov.co | TRM | COP/USD | Promedio mensual |
| NOAA/CPC | ONI | °C | Alineación mensual; Niño ≥ 0,5 y Niña ≤ −0,5 |
| XM `VoluUtilDiarEner/Sistema` | Volumen útil | kWh | Conversión a GWh; último valor disponible del mes |
| Coordinador de Chile | Generación por tecnología | MWh | Suma mensual y conversión a GWh |

## Fórmulas explícitas

- Generación no hidráulica (GWh-día) = generación nacional − generación hidráulica.
- Disponibilidad (GWh-día) = CEN (MW) × factor de planta × 24 / 1.000.
- FP total = suma(CEN × FP) / suma(CEN).
- Margen energético = disponibilidad / demanda del escenario − 1.
- Demanda₀(1+g)^n − Disponibilidad = 0.
- Años hasta margen cero = ln(Disponibilidad/Demanda₀) / ln(1+g).
- Precio chileno = suma(precio por barra × demanda por barra) / suma(demanda por barra).
- Ventas sin cobertura (millones COP) = precio (COP/kWh) × generación (GWh).

No se rellenan faltantes de manera silenciosa. La unión de la base integrada es externa por fecha y
los valores ausentes quedan como `NaN` visibles.

## Paquetes mensuales

- Colombia integra XM, TRM y ONI; `Gene/Recurso` se descarga una sola vez por bloques de 14 días.
- De esa descarga se derivan y concilian generación nacional, prioridades por recurso y empresa y
  agregados tecnológicos. La asociación empresarial usa vigencias oficiales cuando están presentes.
- España integra REData mensual y promedios mensuales del precio diario OMIE.
- Chile exige exportaciones oficiales de costos marginales, demanda por barra y generación por
  tecnología; el precio mensual se pondera por demanda.
- Una falla de conexión, contrato, transformación o escritura bloquea el ZIP. Los bloques correctos
  quedan disponibles para reanudar en la misma instancia de Streamlit.
- La ausencia explícita de observaciones en una serie complementaria se conserva como advertencia
  de cobertura y no bloquea por sí sola. Colombia consulta y publica únicamente las variables que
  el usuario conserve seleccionadas; ninguna serie se agrega como obligación oculta.

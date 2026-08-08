# Fuentes, unidades y reglas de transformación

| Fuente | Uso | Unidad recibida | Transformación principal |
|---|---|---:|---|
| XM `PrecBolsNaci/Sistema` | Precio de bolsa | COP/kWh | Promedio diario o mensual de intervalos |
| XM `DemaSIN/Sistema` | Demanda nacional | kWh | Conversión a GWh; suma por periodo; GWh-día mensual |
| XM `Gene/Recurso` | Generación | kWh | Conversión a GWh; suma por recurso y tecnología |
| XM `CapEfecNeta/Recurso` | Capacidad | kW | Conversión a MW; última publicación no posterior a la fecha elegida |
| XM `PrecOferDesp/Recurso` | Ofertas | COP/kWh | Percentiles por tecnología; P5/P50 como valores iniciales editables |
| XM demanda no atendida | Interrupciones | kWh | Área como total; subárea solo como verificación si ambas existen |
| REData | Demanda, balance, generación, potencia e intercambios | Publicada por indicador | Se conserva la agregación solicitada a la API |
| OMIE `marginalpdbc` | Precio mercado diario | EUR/MWh | Parser de 24/25 horas y 92/96/100 cuartos de hora |
| Coordinador de Chile | Costo y demanda por barra | USD/MWh y MWh | Coincidencia fecha/barra y promedio nacional ponderado por demanda |
| datos.gov.co | TRM | COP/USD | Promedio mensual |
| NOAA/CPC | ONI | °C | Alineación mensual; Niño ≥ 0,5 y Niña ≤ −0,5 |

## Fórmulas explícitas

- Generación no hidráulica (GWh-día) = demanda nacional − generación hidráulica.
- Generación disponible (GWh-día) = CEN (MW) × factor de planta × 24 / 1.000.
- Margen energético = generación disponible / demanda − 1.
- Precio chileno = suma(precio por barra × demanda por barra) / suma(demanda por barra).
- Ventas sin cobertura (millones COP) = precio (COP/kWh) × generación (GWh).

No se rellenan faltantes de manera silenciosa. La unión de la base integrada es externa por fecha y
los valores ausentes quedan como `NaN` visibles.


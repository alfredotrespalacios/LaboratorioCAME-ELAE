# Informe de validación v1.1.0

Fecha: 8 de agosto de 2026.

## Resultado

- Lint: `ruff check .` sin hallazgos.
- Pruebas locales: 43 aprobadas.
- Contratos vivos: 3 aprobados (XM, REData y OMIE).
- Smoke de Streamlit: página inicial cargada sin excepciones en modo local.
- Compilación: todos los módulos Python compilados.
- Secretos: no se incorpora `secrets.toml`, `.env` ni contraseña real.
- Empaquetado mensual: Parquet, Excel, JSON y ZIP aprobados con datos sintéticos trazables.
- Navegación: cada página visible se importa desde un archivo Python independiente.

## Contraste con los Excel entregados

### Balance energético

Los valores de capacidad y factores de planta de las filas 17–27 del Excel producen:

| Resultado | Excel | Aplicación |
|---|---:|---:|
| Generación disponible normal (GWh-día) | 306,5114852424 | 306,5114852424 |
| Margen normal | 0,3043041925 | 0,3043041925 |
| Generación disponible Niño (GWh-día) | 252,6086998824 | 252,6086998824 |
| Margen Niño | 0,0642877602 | 0,0642877602 |

### Curva rápida

Con los valores de las filas 26–36 del Excel:

| Resultado | Excel | Aplicación |
|---|---:|---:|
| Disponibilidad total (GWh-día) | 297,9920001126 | 297,9920001126 |
| Demanda (GWh-día) | 240,83315642 | 240,83315642 |
| Unidad marginal | Gas | Gas |
| Precio marginal discreto (COP/kWh) | 450 | 450 |

La aplicación reestima los coeficientes polinómicos y exponenciales con precisión completa a partir
de la tabla editada; no copia los coeficientes redondeados escritos en el Excel. También evita
extrapolar un precio de equilibrio cuando la oferta total es inferior a la demanda.

## Consultas guiadas reales

Con datos XM de julio/agosto de 2026 respondieron precio, demanda, generación por tecnología,
capacidad efectiva, ofertas, demanda no atendida y base integrada. La publicación de capacidad más
reciente no posterior al 6 de agosto fue la del 5 de agosto, condición que el módulo muestra al
usuario.

## Limitación externa conocida

El Coordinador de Chile publica sus exploradores sobre Qlik/Cloudflare. La descarga automatizada no
es estable sin una URL administrada. El módulo procesa exportaciones oficiales TSV/XLSX de costos,
demanda y generación; las pruebas validan los parsers y la ponderación. No afirma disponibilidad
automática inexistente.

La carga histórica completa no se ejecutó en este contenedor porque la fuente XM no está incluida
en la lista de dominios de red disponibles. La aplicación deja visible el avance, guarda bloques
temporales y solo habilita el ZIP cuando todas las fuentes terminan sin errores.

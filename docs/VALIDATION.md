# Informe de validación v1.4.1

Fecha: 8 de agosto de 2026.

## Resultado

- Lint: `ruff check .` sin hallazgos.
- Pruebas locales: 77 aprobadas; 3 contratos externos excluidos del chequeo local.
- Contratos vivos: se mantienen separados del cierre reproducible porque dependen de servicios
  externos; ejecútelos con `make live-check` antes y después de desplegar.
- Smoke de Streamlit: página inicial cargada sin excepciones en modo local.
- Páginas críticas: Modelación, Portafolios, Base integrada y Mantenimiento arrancaron de forma
  independiente sin excepciones.
- Introducción: primera página del menú, anterior a Colombia, con propiedad, alcance y guía de uso.
- Casos de estudio: módulos 14–18 renombrados en navegación y páginas.
- Compilación: todos los módulos Python compilados.
- Secretos: no se incorpora `secrets.toml`, `.env` ni contraseña real.
- Empaquetado mensual: Parquet, Excel, JSON y ZIP aprobados con datos sintéticos trazables.
- Persistencia de descarga: el flujo completo **Construir la primera base** termina con ZIP y una
  sesión nueva vuelve a mostrar su descarga sin depender de `session_state`.
- Selección de variables: una construcción con solo demanda no consulta generación, recursos,
  capacidad, TRM ni ONI; ninguna de esas series se exige para crear el paquete.
- Fecha inicial: el selector permite elegir desde enero de 2000 hasta el último día del año
  anterior al año en curso.
- Cierre visible: **0/5** y **1/5–5/5** permanecen renderizados; un error previo al empaquetado deja
  las cinco fases como pendientes y muestra el motivo bloqueante.
- Compatibilidad: `app.py` detiene la ejecución antes de importar `came` cuando Python no es 3.12.
  Las páginas y exportadores se cargan de manera diferida para reducir importaciones durante una
  recarga del despliegue.
- Compatibilidad: se detecta un paquete completo guardado por la versión 1.3.0, cuando todavía
  existe en la instancia, antes de obligar a repetir la descarga histórica.
- Memoria: Parquet, Excel, JSON y ZIP se escriben por etapas en disco; la pantalla carga de forma
  predeterminada únicamente el ZIP y deja los archivos individuales bajo petición.
- Navegación: cada página visible se importa desde un archivo Python independiente.
- Precio y Demanda: apertura desde el Parquet mensual, con consulta XM opcional.
- Calidad diaria: un día incompleto de demanda se excluye y se informa el último día completo.
- Informe ejecutivo: la canasta permanece vacía hasta que el usuario pulsa el botón de guardado.
- Mantenimiento: un bloque temporalmente fallido se recupera dentro de tres intentos y conserva
  los puntos de avance.
- Recuperación de directorios: el almacén de avances y la escritura atómica del paquete recrean
  sus carpetas si fueron eliminadas antes de guardar un bloque o archivo, y repiten una vez la
  escritura si la carpeta desaparece exactamente durante la operación.
- Compatibilidad Streamlit 1.61: se sustituyó `use_container_width` por `width`, sin advertencias
  de la API durante el smoke local.
- Modelación supervisada: transformaciones por variable, ajuste con 100 %, importancias de Random
  Forest, pronóstico recursivo e intervalos OLS validados con datos sintéticos.
- Series temporales: validación cronológica, MASE, origen móvil, diagnósticos ACF/PACF y reporte
  Statsmodels disponibles en pantalla y exportaciones.
- Portafolios: diez porcentajes contratados y cinco escenarios de correlación o precio producen 50
  combinaciones comparables con la misma semilla; M-CVaR está incluido.

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

## Limitación externa conocida

El Coordinador de Chile publica sus exploradores sobre Qlik/Cloudflare. La descarga automatizada no
es estable sin una URL administrada. El módulo procesa exportaciones oficiales TSV/XLSX de costos,
demanda y generación; las pruebas validan los parsers y la ponderación. No afirma disponibilidad
automática inexistente.

La carga histórica completa no forma parte del chequeo local. La aplicación deja visible el avance,
guarda bloques temporales y solo habilita el ZIP cuando las variables seleccionadas y las fases de
publicación terminan sin errores bloqueantes.

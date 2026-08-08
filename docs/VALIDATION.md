# Informe de validación v1.3.1

Fecha: 8 de agosto de 2026.

## Resultado

- Lint: `ruff check .` sin hallazgos.
- Pruebas locales: 57 aprobadas.
- Contratos vivos: REData y OMIE aprobados; XM respondió 502 después de agotar reintentos. Los tres
  contratos habían sido aprobados en la validación v1.1.0.
- Smoke de Streamlit: página inicial cargada sin excepciones en modo local.
- Introducción: primera página del menú, anterior a Colombia, con propiedad, alcance y guía de uso.
- Casos de estudio: módulos 14–18 renombrados en navegación y páginas.
- Compilación: todos los módulos Python compilados.
- Secretos: no se incorpora `secrets.toml`, `.env` ni contraseña real.
- Empaquetado mensual: Parquet, Excel, JSON y ZIP aprobados con datos sintéticos trazables.
- Persistencia de descarga: el flujo completo **Construir la primera base** termina con ZIP y una
  sesión nueva vuelve a mostrar su descarga sin depender de `session_state`.
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

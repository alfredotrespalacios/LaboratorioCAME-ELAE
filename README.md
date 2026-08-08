# Laboratorio CAME

Aplicación académica de ELAE para consultar, analizar y modelar mercados eléctricos. Está
construida con Streamlit y Plotly, usa fuentes oficiales abiertas y mantiene visibles las unidades,
supuestos, coberturas y limitaciones de cada resultado.

La entrega contiene los 19 módulos acordados, exportaciones Excel/PDF, canasta para informe
ejecutivo, acceso por contraseña, pruebas numéricas contra los Excel pedagógicos y un sistema
mensual versionable que no requiere una base de datos externa.

## Módulos

| Grupo | Módulos |
|---|---|
| Colombia | 1. Precio de bolsa · 2. Demanda nacional · 3. Generación por tecnología · 4. Generación por recurso/empresa · 5. Explorador XM · 6. Base integrada · 7. Balance energético · 8. Curva de oferta |
| Otros mercados | 9. España (REData y OMIE) · 10. Chile (archivos oficiales validados) |
| Análisis y modelación | 11. Supervisados, ingenuo, ARIMA y SARIMA · 12. SARIMA–GARCH |
| Portafolios | 13. Monte Carlo de generación, precio y contratación, con VaR/CVaR |
| Actividades | 14–18. Espacios “Próximamente disponible”, sin contenido inventado |
| Informe | 19. Canasta y generador de prompt ejecutivo TXT |

Al final del menú se incluye **Mantenimiento de datos**, una página técnica no numerada. Allí se
puede construir la primera base, agregar meses, recalcular un periodo, reanudar bloques aprobados,
validar el resultado y descargar el ZIP listo para GitHub. No es un módulo de análisis y no se
utiliza durante la operación normal.

## Bases mensuales publicadas

Cada país conserva tres archivos juntos. Colombia usa exactamente:

```text
datos_por_defecto/colombia/
├── Base_integrada_mensual.parquet
├── Catalogo_Base_integrada.xlsx
└── Fecha_actualizacion_Base_integrada.json
```

España y Chile siguen la misma estructura en sus carpetas. El Parquet tiene formato largo y puede
guardar series nacionales, por tecnología, empresa y recurso sin crear una tabla inmanejable de
columnas. Los módulos convierten únicamente las series seleccionadas a formato ancho.

## Inicio local

Requiere Python 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
streamlit run app.py
```

Cambie `ACCESS_PASSWORD` en el archivo local copiado. `secrets.toml` está excluido de Git y nunca
debe publicarse. Para una revisión local sin contraseña se puede ejecutar:

```bash
CAME_DEV_MODE=1 streamlit run app.py
```

`CAME_DEV_MODE` debe permanecer desactivado en cualquier despliegue accesible por internet.

## Comprobación completa

```bash
make check       # lint + pruebas locales + smoke de Streamlit
make live-check  # 3 contratos contra XM, REData y OMIE
```

Las pruebas locales incluyen la reproducción de los totales y márgenes de
`2.1 Modelo rápido balance energético agosto 2026.xlsx` y de la disponibilidad y tecnología
marginal de `2.2 Modelo rápido fundamental spot.xlsx`.

## Publicación

1. Cree un repositorio vacío en GitHub.
2. Desde esta carpeta ejecute los comandos de [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
3. En Streamlit Community Cloud seleccione el repositorio, la rama y `app.py`.
4. Pegue los secretos en la consola de Streamlit; no cree `secrets.toml` en GitHub.
5. Ejecute `make live-check` antes y después de publicar.

La aplicación no necesita base de datos externa. Consulta bajo demanda, utiliza caché temporal y
lee los Parquet mensuales publicados en GitHub. Los resultados de sesión y la canasta del informe
se reinician cuando la sesión termina; los tres archivos mensuales permanecen versionados.

## Fuentes y trazabilidad

- Colombia: API pública de [XM/Sinergox](https://sinergox.xm.com.co/).
- España: API [REData de Red Eléctrica](https://www.ree.es/es/datos/apidatos) y archivos de
  [OMIE](https://www.omie.es/en/file-access-list).
- Chile: exportaciones TSV/XLSX de costos, demanda y generación del
  [Coordinador Eléctrico Nacional](https://www.coordinador.cl/costos-marginales/).
- TRM: portal colombiano de datos abiertos. ENSO: NOAA/CPC.

El portal chileno usa Qlik/Cloudflare y no garantiza una descarga automática estable. El módulo
acepta las exportaciones oficiales, valida sus columnas y nunca reemplaza una descarga bloqueada
por datos simulados.

## Estructura

```text
app.py                       navegación y acceso
src/came/analytics/          fórmulas y modelos probados
src/came/data/providers/     conectores y parsers por fuente
src/came/data/maintenance.py motor reanudable por bloques
src/came/data/monthly_store.py validación, Parquet, catálogo, JSON y ZIP
src/came/ui/pages/           un archivo de interfaz por módulo
src/came/ui/                 gráficos y componentes compartidos
datos_por_defecto/           paquetes mensuales publicados por país
tests/                       unitarias, numéricas, smoke y contratos vivos
docs/                        especificación, despliegue y validación
.streamlit/                  tema y ejemplo de secretos
```

## Uso y propiedad

© 2026 ELAE. Uso académico para estudiantes autorizados. Consulte [NOTICE.md](NOTICE.md). Este
repositorio no incorpora una licencia de código abierto; publicar el código no concede por sí mismo
derechos de reutilización.

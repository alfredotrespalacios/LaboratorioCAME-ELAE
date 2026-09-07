# Reemplazo completo en GitHub y Streamlit

Este paquete está preparado para sustituir directamente el contenido del repositorio. Al descomprimirlo, `app.py`, `requirements.txt`, `runtime.txt`, `src` y las demás carpetas aparecen en la raíz; no existe una carpeta exterior adicional.

## Comprobación antes de desplegar

En GitHub, el archivo `src/came/config.py` debe contener:

```python
APP_VERSION = "1.5.2"
```

También deben estar en la raíz del repositorio:

- `app.py`
- `requirements.txt`
- `runtime.txt`
- `src/`
- `.streamlit/`

## Después de reemplazar los archivos

1. Confirme que los cambios quedaron guardados en la rama que usa Streamlit.
2. En Streamlit Community Cloud, abra la aplicación y verifique que el archivo principal sea `app.py`.
3. Reinicie la aplicación o haga **Reboot app**.
4. La portada debe mostrar `versión 1.5.2`.

## Construcción y actualización de la base colombiana

El paquete conserva los tres archivos que estaban publicados en la versión recibida. En
**Mantenimiento de datos → Colombia**, revise primero la cobertura mostrada por la aplicación.
Seleccione un intervalo de máximo cinco años entre 1990 y la fecha actual y pulse **Construir o
continuar por etapas**. La aplicación leerá la base publicada, conservará lo completo y consultará
lo pendiente. Cada corrida entrega un ZIP completo o de avance.

Descomprima el ZIP y reemplace juntos los tres archivos de `datos_por_defecto/colombia/` en un mismo
*commit*. Después del despliegue, la siguiente corrida leerá el Parquet y el JSON actualizados para
continuar sin reconstruir lo ya aprobado. El mes actual se considera parcial y puede consultarse
nuevamente.

Si todavía aparece una versión anterior, el despliegue está conectado a otra rama, otro repositorio o un `app.py` ubicado en una carpeta diferente.

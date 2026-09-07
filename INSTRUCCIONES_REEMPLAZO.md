# Reemplazo completo en GitHub y Streamlit

Este paquete está preparado para sustituir directamente el contenido del repositorio. Al descomprimirlo, `app.py`, `requirements.txt`, `runtime.txt`, `src` y las demás carpetas aparecen en la raíz; no existe una carpeta exterior adicional.

## Comprobación antes de desplegar

En GitHub, el archivo `src/came/config.py` debe contener:

```python
APP_VERSION = "1.5.1"
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
4. La portada debe mostrar `versión 1.5.1`.

## Continuación de la base colombiana

El paquete incluye la base de Demanda aprobada entre enero de 2000 y junio de 2026 que se generó
durante el diagnóstico. En **Mantenimiento de datos → Colombia**, seleccione **Construir la primera
base**, conserve la **Canasta CAME completa** y pulse **Construir o reanudar automáticamente**. La
aplicación reconocerá Demanda como publicada y procesará las demás variables por etapas, sin pedir
que se agreguen manualmente una por una.

Si todavía aparece una versión anterior, el despliegue está conectado a otra rama, otro repositorio o un `app.py` ubicado en una carpeta diferente.

# Despliegue en GitHub y Streamlit Community Cloud

## 1. Verificación previa

Desde la raíz del proyecto:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
make check
make live-check
```

No continúe si alguno de los dos comandos falla. Una fuente externa puede tener una interrupción
temporal; en ese caso conserve el registro y vuelva a probar antes de publicar.

## 2. GitHub

Cree un repositorio vacío, sin README ni licencia automáticos. Luego:

```bash
git init
git add .
git commit -m "Entrega inicial del Laboratorio CAME"
git branch -M main
git remote add origin https://github.com/ORGANIZACION/REPOSITORIO.git
git push -u origin main
```

Antes de `git push`, confirme:

```bash
git status --short
git ls-files | grep -E 'secrets.toml$|\.env$' && echo "REVISAR: secreto rastreado" || true
```

Solo `.streamlit/secrets.toml.example` debe estar versionado. El archivo real
`.streamlit/secrets.toml` está ignorado.

## 3. Streamlit Community Cloud

> **Obligatorio:** Laboratorio CAME 1.5.0 se valida y se ejecuta con Python 3.12. El archivo
> `runtime.txt` no sustituye la selección del entorno en Community Cloud. Si el registro muestra
> otra versión, la aplicación se detiene antes de permitir una construcción histórica.

1. Abra `share.streamlit.io` e inicie una aplicación nueva.
2. Seleccione el repositorio, la rama `main` y el archivo `app.py`.
3. En **Advanced settings**, seleccione **Python 3.12**.
4. En **Advanced settings → Secrets** agregue:

```toml
ACCESS_PASSWORD = "una-contraseña-larga-y-única"
ACCESS_VERSION = "2026-08-v1"
CAME_DEV_MODE = false
```

5. Opcionalmente agregue:

```toml
REQUEST_TIMEOUT_SECONDS = 45
# CHILE_COSTS_URL = "https://descarga-oficial-administrada/costos.xlsx"
# CHILE_DEMAND_URL = "https://descarga-oficial-administrada/demanda.xlsx"
```

6. Despliegue y abra la URL. Debe aparecer el formulario de acceso antes de la navegación.

### Cambiar una aplicación existente que usa otra versión de Python

Community Cloud no cambia Python dentro de un despliegue ya creado. Antes de eliminarlo, anote el
subdominio, repositorio, rama, archivo `app.py` y copie los secretos. Después elimine únicamente la
aplicación de Community Cloud —no el repositorio de GitHub—, vuelva a crearla con las mismas
coordenadas y el mismo subdominio, abra **Advanced settings**, seleccione **Python 3.12** y restaure
los secretos. Compruebe en el primer registro de arranque que aparezca `Using Python 3.12`.

Para revocar todas las sesiones compartidas, cambie `ACCESS_VERSION` y reinicie la aplicación.
Para cambiar únicamente la credencial, cambie también `ACCESS_PASSWORD`.

## 4. Prueba posterior

- Autenticación: contraseña inválida rechazada y válida aceptada.
- Módulo 1: consulta corta de precio XM.
- Módulo 5: catálogo vivo de XM.
- Módulo 9: REData y un día de OMIE.
- Módulos 7–8: cálculo con los valores del Excel de referencia.
- Exportaciones: un Excel, un PDF y un prompt TXT.
- Reinicio: la aplicación vuelve a solicitar acceso cuando cambia `ACCESS_VERSION`.

## 5. Operación

- No hay base de datos ni persistencia de usuarios.
- Los paquetes mensuales se versionan en `datos_por_defecto/colombia/`, `espana/` y `chile/`.
- La caché evita repetir descargas dentro de su vigencia.
- Si una fuente falla, la interfaz muestra el error y conserva resultados válidos de las demás.
- Los bloques de mantenimiento se conservan temporalmente para reanudar en la misma instancia.
- No publique cambios en GitHub ni reinicie la aplicación durante una construcción histórica;
  espere hasta que aparezca **Descargar ZIP listo para GitHub**.
- El cierre muestra permanentemente **0/5** y las fases **1/5–5/5**. Si hay un error bloqueante,
  las cinco fases permanecen visibles como pendientes y **0/5** explica por qué no comenzaron.
- Streamlit Community Cloud no garantiza la permanencia del disco local después de un reinicio
  total. Descargue el ZIP apenas aparezca y publique sus tres archivos juntos en GitHub.
- Los archivos chilenos se procesan en memoria; solo el paquete descargado se publica en GitHub.
- Revise trimestralmente dependencias y contratos vivos antes de actualizar versiones.

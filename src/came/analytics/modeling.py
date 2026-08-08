"""Modelos pedagógicos con partición cronológica y rezagos elegidos por el usuario."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeRegressor, export_text

from came.errors import DataQualityError, ModelError


@dataclass
class SupervisedResult:
    model_name: str
    estimator: object
    predictions: pd.DataFrame
    metrics: dict[str, float | None]
    feature_effects: pd.DataFrame
    residuals: pd.DataFrame
    interval_method: str
    warnings: list[str] = field(default_factory=list)
    tree_rules: str | None = None


LAG_LABELS = {
    "anterior": "anterior",
    "seis_meses": "6m",
    "un_ano": "12m",
}


def _lag_offset(frequency: str, lag: str) -> pd.DateOffset:
    if lag == "seis_meses":
        return pd.DateOffset(months=6)
    if lag == "un_ano":
        return pd.DateOffset(years=1)
    if lag != "anterior":
        raise ValueError(f"Rezago no reconocido: {lag}")
    if frequency == "monthly":
        return pd.DateOffset(months=1)
    if frequency == "daily":
        return pd.DateOffset(days=1)
    if frequency == "hourly":
        return pd.DateOffset(hours=1)
    if frequency == "annual":
        return pd.DateOffset(years=1)
    raise ValueError(f"Frecuencia no reconocida: {frequency}")


def prepare_model_matrix(
    frame: pd.DataFrame,
    *,
    target: str,
    features: list[str],
    selected_lags: list[str] | None = None,
    lagged_features: list[str] | None = None,
    include_time: bool = False,
    frequency: str = "monthly",
) -> tuple[pd.DataFrame, list[str]]:
    """Alinea explicativas y agrega únicamente los rezagos solicitados."""

    if "datetime" not in frame or target not in frame:
        raise DataQualityError("La base debe contener datetime y la variable objetivo.")
    selected_lags = selected_lags or []
    lagged_features = lagged_features if lagged_features is not None else list(features)
    requested = list(dict.fromkeys([target] + features + lagged_features))
    missing = [column for column in requested if column not in frame]
    if missing:
        raise DataQualityError(f"Variables no encontradas: {missing}")

    data = frame[["datetime"] + requested].copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce", utc=True)
    data = data.dropna(subset=["datetime"]).sort_values("datetime").drop_duplicates("datetime")
    for column in requested:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    feature_columns = list(features)
    indexed = data.set_index("datetime")
    for feature in lagged_features:
        for lag in selected_lags:
            label = LAG_LABELS[lag]
            new_column = f"{feature}__lag_{label}"
            lookup_dates = data["datetime"] - _lag_offset(frequency, lag)
            data[new_column] = indexed[feature].reindex(lookup_dates).to_numpy()
            feature_columns.append(new_column)
    if include_time:
        data["Tiempo"] = np.arange(1, len(data) + 1, dtype=float)
        feature_columns.append("Tiempo")

    feature_columns = list(dict.fromkeys(feature_columns))
    if not feature_columns:
        raise DataQualityError("Seleccione al menos una variable explicativa, un rezago o Tiempo.")
    output = data[["datetime", target] + feature_columns].dropna().reset_index(drop=True)
    if len(output) < 10:
        raise DataQualityError(
            "Después de alinear fechas y rezagos quedan menos de 10 observaciones completas."
        )
    return output, feature_columns


def _theil_u(observed: np.ndarray, predicted: np.ndarray) -> float | None:
    denominator = np.sqrt(np.mean(observed**2)) + np.sqrt(np.mean(predicted**2))
    return float(np.sqrt(np.mean((observed - predicted) ** 2)) / denominator) if denominator else None


def regression_metrics(observed: object, predicted: object) -> dict[str, float | None]:
    y = np.asarray(observed, dtype=float)
    y_hat = np.asarray(predicted, dtype=float)
    mae = float(mean_absolute_error(y, y_hat))
    rmse = float(np.sqrt(mean_squared_error(y, y_hat)))
    nonzero = y != 0
    mape = float(np.mean(np.abs((y[nonzero] - y_hat[nonzero]) / y[nonzero])) * 100) if nonzero.any() else None
    return {
        "MAE": mae,
        "RMSE": rmse,
        "MAPE_pct": mape,
        "R2": float(r2_score(y, y_hat)) if len(y) > 1 else None,
        "U_Theil": _theil_u(y, y_hat),
    }


def _estimator(
    model: str,
    *,
    standardize: bool,
    random_state: int,
    max_depth: int,
    n_neighbors: int,
    n_estimators: int,
) -> tuple[str, object]:
    if model == "linear":
        estimator: object = LinearRegression()
        name = "Regresión lineal"
    elif model == "tree":
        estimator = DecisionTreeRegressor(max_depth=max_depth, random_state=random_state)
        name = "Árbol de regresión"
    elif model == "knn":
        estimator = KNeighborsRegressor(n_neighbors=n_neighbors, weights="distance")
        name = "KNN"
    elif model == "random_forest":
        estimator = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth if max_depth > 0 else None,
            random_state=random_state,
            n_jobs=-1,
        )
        name = "Random Forest"
    else:
        raise ValueError(f"Modelo no soportado: {model}")
    if standardize:
        estimator = Pipeline([("scale", StandardScaler()), ("model", estimator)])
    return name, estimator


def _base_estimator(estimator: object) -> object:
    if isinstance(estimator, Pipeline):
        return estimator.named_steps["model"]
    if isinstance(estimator, TransformedTargetRegressor):
        return estimator.regressor_
    return estimator


def fit_supervised(
    data: pd.DataFrame,
    *,
    target: str,
    feature_columns: list[str],
    model: str,
    train_fraction: float = 0.80,
    standardize: bool | None = None,
    random_state: int = 42,
    max_depth: int = 5,
    n_neighbors: int = 5,
    n_estimators: int = 300,
) -> SupervisedResult:
    if not 0.50 <= train_fraction <= 0.95:
        raise DataQualityError("La proporción de entrenamiento debe estar entre 50 % y 95 %.")
    if len(data) < 10:
        raise DataQualityError("Se requieren al menos 10 observaciones completas.")
    split = int(np.floor(len(data) * train_fraction))
    split = min(max(split, 5), len(data) - 2)
    train = data.iloc[:split]
    test = data.iloc[split:]
    use_standardize = model == "knn" if standardize is None else standardize
    name, estimator = _estimator(
        model,
        standardize=use_standardize,
        random_state=random_state,
        max_depth=max_depth,
        n_neighbors=min(n_neighbors, len(train)),
        n_estimators=n_estimators,
    )
    x_train = train[feature_columns]
    y_train = train[target]
    x_test = test[feature_columns]
    y_test = test[target]
    try:
        estimator.fit(x_train, y_train)
        train_prediction = np.asarray(estimator.predict(x_train), dtype=float)
        test_prediction = np.asarray(estimator.predict(x_test), dtype=float)
    except Exception as exc:  # sklearn ofrece excepciones heterogéneas
        raise ModelError(f"No fue posible estimar {name}: {exc}") from exc

    train_residuals = y_train.to_numpy(dtype=float) - train_prediction
    residual_sd = float(np.std(train_residuals, ddof=max(1, len(feature_columns))))
    predictions = pd.DataFrame(
        {
            "datetime": test["datetime"].to_numpy(),
            "observado": y_test.to_numpy(dtype=float),
            "estimado": test_prediction,
        }
    )
    for level in (0.80, 0.95):
        z_value = norm.ppf((1 + level) / 2)
        label = int(level * 100)
        predictions[f"inferior_{label}"] = test_prediction - z_value * residual_sd
        predictions[f"superior_{label}"] = test_prediction + z_value * residual_sd
    predictions["residual"] = predictions["observado"] - predictions["estimado"]
    residual_std = predictions["residual"].std(ddof=1)
    predictions["residual_estandarizado"] = (
        predictions["residual"] / residual_std if residual_std and np.isfinite(residual_std) else np.nan
    )

    base = _base_estimator(estimator)
    if hasattr(base, "coef_"):
        values = np.asarray(base.coef_).ravel()
        feature_effects = pd.DataFrame({"variable": feature_columns, "coeficiente": values})
    elif hasattr(base, "feature_importances_"):
        feature_effects = pd.DataFrame(
            {"variable": feature_columns, "importancia": base.feature_importances_}
        ).sort_values("importancia", ascending=False)
    else:
        feature_effects = pd.DataFrame({"variable": feature_columns})

    tree_rules = export_text(base, feature_names=feature_columns) if model == "tree" else None
    warnings: list[str] = []
    if use_standardize:
        warnings.append("Las variables explicativas se estandarizaron usando solo el periodo de entrenamiento.")
    warnings.append(
        "Los intervalos de modelos supervisados usan la dispersión empírica de residuales de entrenamiento; no son intervalos analíticos exactos."
    )
    return SupervisedResult(
        model_name=name,
        estimator=estimator,
        predictions=predictions,
        metrics=regression_metrics(y_test, test_prediction),
        feature_effects=feature_effects.reset_index(drop=True),
        residuals=predictions[["datetime", "residual", "residual_estandarizado"]],
        interval_method="residual empírico normal",
        warnings=warnings,
        tree_rules=tree_rules,
    )


def naive_forecast(series: pd.Series, horizon: int, seasonal_period: int | None = None) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    if values.size == 0:
        raise DataQualityError("No hay valores para el modelo ingenuo.")
    if seasonal_period and seasonal_period > 0:
        if len(values) < seasonal_period:
            raise DataQualityError("La serie es más corta que el periodo estacional.")
        pattern = values[-seasonal_period:]
        return np.resize(pattern, horizon)
    return np.repeat(values[-1], horizon)


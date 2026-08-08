"""Excepciones explícitas del dominio CAME."""


class CameError(Exception):
    """Error base que puede presentarse al usuario sin exponer detalles sensibles."""


class SourceUnavailableError(CameError):
    """La fuente oficial no respondió o bloqueó temporalmente la consulta."""


class SourceContractError(CameError):
    """La fuente respondió con una estructura distinta de la esperada."""


class DataQualityError(CameError):
    """Los datos no cumplen el mínimo requerido para el cálculo solicitado."""


class ConfigurationError(CameError):
    """Falta una configuración necesaria o contiene un valor inválido."""


class ModelError(CameError):
    """El modelo no pudo estimarse con la información suministrada."""

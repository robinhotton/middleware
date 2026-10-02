"""Exceptions applicatives avec code HTTP integre."""

# Re-export de l'exception SQLAlchemy pour centraliser la seule dependance
# directe a SQLAlchemy. Les services importent depuis ce module, jamais
# depuis sqlalchemy directement.
from sqlalchemy.exc import IntegrityError  # noqa: F401


class AppException(Exception):
    """Exception de base pour l'application."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


class NotFoundException(AppException):
    """Ressource introuvable (404)."""

    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=404, detail=detail)


class UnauthorizedException(AppException):
    """Authentification requise ou echouee (401)."""

    def __init__(self, detail: str = "Invalid credentials"):
        super().__init__(status_code=401, detail=detail)


class ForbiddenException(AppException):
    """Acces interdit (403)."""

    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(status_code=403, detail=detail)


class BadRequestException(AppException):
    """Requete invalide (400)."""

    def __init__(self, detail: str = "Bad request"):
        super().__init__(status_code=400, detail=detail)


class ConflictException(AppException):
    """Conflit de ressource (409)."""

    def __init__(self, detail: str = "Resource already exists"):
        super().__init__(status_code=409, detail=detail)


class TooManyRequestsException(AppException):
    """Trop de requetes — compte temporairement verrouille (429)."""

    def __init__(self, detail: str = "Too many requests", reason: str | None = None):
        super().__init__(status_code=429, detail=detail)
        self.reason = reason


class MoodleAPIException(AppException):
    """Erreur retournee par Moodle Web Services (502 Bad Gateway)."""

    def __init__(self, detail: str = "Erreur Moodle Web Services"):
        super().__init__(status_code=502, detail=detail)

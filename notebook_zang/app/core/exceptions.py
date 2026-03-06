class AppError(Exception):
    def __init__(self, status_code: int, detail: str, upstream_body: dict | None = None):
        self.status_code = status_code
        self.detail = detail
        self.upstream_body = upstream_body


class AuthenticationError(AppError):
    pass


class NotFoundError(AppError):
    pass


class RateLimitError(AppError):
    pass

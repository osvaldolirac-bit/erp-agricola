from erp_master import create_app

_app = create_app()


class _PrefixMiddleware:
    """Respeta X-Forwarded-Prefix (/consola) detrás de nginx."""

    def __init__(self, app, default_prefix: str = "/consola"):
        self.app = app
        self.default_prefix = (default_prefix or "").rstrip("/")

    def __call__(self, environ, start_response):
        prefix = (
            environ.get("HTTP_X_FORWARDED_PREFIX") or self.default_prefix or ""
        ).rstrip("/")
        if prefix:
            environ["SCRIPT_NAME"] = prefix
            path = environ.get("PATH_INFO") or "/"
            if path.startswith(prefix + "/") or path == prefix:
                environ["PATH_INFO"] = path[len(prefix) :] or "/"
        return self.app(environ, start_response)


app = _PrefixMiddleware(_app, "/consola")

"""Optional web interface (Mailhelp 1.1): server, application and pages."""

from .app import WebApp
from .http import Request, Response
from .server import WebServer, WebServerError

__all__ = ["Request", "Response", "WebApp", "WebServer", "WebServerError"]

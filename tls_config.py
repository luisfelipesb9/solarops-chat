"""TLS contexts for the SolarOps Chat server and clients (SPEC.md §5.6)."""

import os
import ssl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CERT = "certs/server.crt"
DEFAULT_KEY = "certs/server.key"
DEFAULT_CA = "certs/ca.crt"


def _resolve(value, env_var, default):
    """Explicit value > env var (read now) > default. Relative paths fall back to the project dir."""
    path = value or os.getenv(env_var) or default
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(BASE_DIR, path)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Arquivo TLS não encontrado: {path}. Gere os certificados com 'make certs'."
        )
    return path


def server_context(cert=None, key=None) -> ssl.SSLContext:
    """Server-side context: TLS 1.2+ with the server certificate signed by our CA."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(
        _resolve(cert, "TLS_CERT", DEFAULT_CERT), _resolve(key, "TLS_KEY", DEFAULT_KEY)
    )
    return ctx


def client_context(cafile=None) -> ssl.SSLContext:
    """Client-side context: trusts only our CA, verifies certificate and hostname, TLS 1.2+."""
    ctx = ssl.create_default_context(cafile=_resolve(cafile, "TLS_CA", DEFAULT_CA))
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx

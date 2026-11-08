import os
import socket
import ssl
import subprocess
import threading

import pytest

import tls_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN_CERTS = os.path.join(ROOT, "certs", "gen_certs.sh")


def _handshake(server_ctx, client_ctx, payload=b"ping\n"):
    """Run one TLS echo exchange on an ephemeral port. Returns (reply, server_error)."""
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(5)
    port = listener.getsockname()[1]
    result = {}

    def serve():
        try:
            conn, _ = listener.accept()
            conn.settimeout(5)
            with server_ctx.wrap_socket(conn, server_side=True) as tls:
                result["version"] = tls.version()
                tls.sendall(tls.recv(1024))
        except (ssl.SSLError, OSError) as exc:
            result["error"] = exc

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with client_ctx.wrap_socket(raw, server_hostname="localhost") as tls:
                tls.sendall(payload)
                return tls.recv(1024), result
    finally:
        thread.join(5)
        listener.close()


def test_handshake_with_explicit_paths(tls_certs):
    server = tls_config.server_context(tls_certs["cert"], tls_certs["key"])
    client = tls_config.client_context(tls_certs["ca"])
    reply, result = _handshake(server, client)
    assert reply == b"ping\n"
    assert result["version"] in ("TLSv1.2", "TLSv1.3")


def test_handshake_with_env_vars(tls_certs, monkeypatch):
    monkeypatch.setenv("TLS_CERT", tls_certs["cert"])
    monkeypatch.setenv("TLS_KEY", tls_certs["key"])
    monkeypatch.setenv("TLS_CA", tls_certs["ca"])
    reply, _ = _handshake(tls_config.server_context(), tls_config.client_context())
    assert reply == b"ping\n"


def test_client_rejects_server_signed_by_other_ca(tls_certs, wrong_ca):
    server = tls_config.server_context(tls_certs["cert"], tls_certs["key"])
    client = tls_config.client_context(wrong_ca)
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(server, client)


def test_contexts_require_tls12_and_verification(tls_certs):
    server = tls_config.server_context(tls_certs["cert"], tls_certs["key"])
    client = tls_config.client_context(tls_certs["ca"])
    assert server.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert client.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert client.check_hostname is True
    assert client.verify_mode == ssl.CERT_REQUIRED


def test_missing_certificate_gives_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("TLS_CERT", str(tmp_path / "nope.crt"))
    monkeypatch.setenv("TLS_KEY", str(tmp_path / "nope.key"))
    monkeypatch.setenv("TLS_CA", str(tmp_path / "nope.crt"))
    with pytest.raises(FileNotFoundError, match="make certs"):
        tls_config.server_context()
    with pytest.raises(FileNotFoundError, match="make certs"):
        tls_config.client_context()


def _gen(*args):
    return subprocess.run(
        ["bash", GEN_CERTS, *args], capture_output=True, text=True, timeout=8, check=True
    )


def test_gen_certs_script_creates_verifiable_chain(tmp_path):
    out = str(tmp_path)
    _gen(out)
    verify = subprocess.run(
        ["openssl", "verify", "-CAfile", "ca.crt", "server.crt"],
        cwd=out, capture_output=True, text=True, timeout=5,
    )
    assert verify.returncode == 0, verify.stderr
    text = subprocess.run(
        ["openssl", "x509", "-in", "server.crt", "-noout", "-text"],
        cwd=out, capture_output=True, text=True, timeout=5, check=True,
    ).stdout
    assert "DNS:localhost" in text and "IP Address:127.0.0.1" in text
    assert "TLS Web Server Authentication" in text
    for key in ("ca.key", "server.key"):
        assert os.stat(os.path.join(out, key)).st_mode & 0o777 == 0o600
    # The generated files work with tls_config end to end
    server = tls_config.server_context(f"{out}/server.crt", f"{out}/server.key")
    reply, _ = _handshake(server, tls_config.client_context(f"{out}/ca.crt"))
    assert reply == b"ping\n"


def test_gen_certs_is_idempotent_and_force_recreates_ca(tmp_path):
    out = str(tmp_path)
    _gen(out)
    ca_before = (tmp_path / "ca.crt").read_bytes()
    assert "reutilizada" in _gen(out).stdout
    assert (tmp_path / "ca.crt").read_bytes() == ca_before
    _gen("--force", out)
    assert (tmp_path / "ca.crt").read_bytes() != ca_before


def test_relative_default_resolves_from_project_dir_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TLS_CA", raising=False)
    path = tls_config._resolve(None, "TLS_CA", "certs/gen_certs.sh")
    assert path == os.path.join(ROOT, "certs", "gen_certs.sh")

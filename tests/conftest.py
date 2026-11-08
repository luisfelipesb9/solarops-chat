import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _make_ca(d, prefix):
    _run(["openssl", "genrsa", "-out", f"{prefix}.key", "2048"], d)
    _run(
        ["openssl", "req", "-x509", "-new", "-key", f"{prefix}.key", "-sha256", "-days", "2",
         "-subj", f"/CN=Test {prefix}", "-out", f"{prefix}.crt"],
        d,
    )


@pytest.fixture(scope="session")
def tls_certs(tmp_path_factory):
    """Test CA + server cert (SAN localhost/127.0.0.1). Independent of certs/gen_certs.sh."""
    d = str(tmp_path_factory.mktemp("certs"))
    _make_ca(d, "ca")
    _run(["openssl", "genrsa", "-out", "server.key", "2048"], d)
    _run(["openssl", "req", "-new", "-key", "server.key", "-subj", "/CN=localhost", "-out", "server.csr"], d)
    with open(os.path.join(d, "san.ext"), "w") as fh:
        fh.write(
            "basicConstraints=CA:FALSE\n"
            "keyUsage=digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            "subjectAltName=DNS:localhost,IP:127.0.0.1\n"
        )
    _run(
        ["openssl", "x509", "-req", "-in", "server.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
         "-CAcreateserial", "-out", "server.crt", "-days", "2", "-sha256", "-extfile", "san.ext"],
        d,
    )
    return {
        "dir": d,
        "ca": os.path.join(d, "ca.crt"),
        "cert": os.path.join(d, "server.crt"),
        "key": os.path.join(d, "server.key"),
    }


@pytest.fixture(scope="session")
def wrong_ca(tmp_path_factory):
    """An unrelated CA certificate path, to test that clients reject the server."""
    d = str(tmp_path_factory.mktemp("wrongca"))
    _make_ca(d, "other")
    return os.path.join(d, "other.crt")

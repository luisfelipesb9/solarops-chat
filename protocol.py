"""SolarOps Chat application protocol: one UTF-8 JSON object per line (see SPEC.md §3)."""

import json
import re
import uuid
from datetime import datetime, timezone

MAX_LINE = 65536
TYPES = frozenset(
    {"HELLO", "WELCOME", "MSG", "DM", "BOT_REQ", "BOT_RESP", "ERROR", "JOIN", "LEAVE", "LIST"}
)
HUMAN_ROLES = frozenset({"cos", "tecnico", "engenheiro"})
ROLES = HUMAN_ROLES | {"bot"}
BOT_NAME = "bot"
SERVER_NAME = "server"
FIELDS = ("type", "from", "to", "content", "req_id", "ts", "role")

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


class ProtocolError(Exception):
    """Malformed, oversized or invalid message."""


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(_NAME_RE.match(name))


def new_req_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def make_msg(type_, from_="", to="*", content="", req_id="", role="") -> dict:
    return validate(
        {
            "type": type_,
            "from": from_,
            "to": to,
            "content": content,
            "req_id": req_id,
            "ts": _now_iso(),
            "role": role,
        }
    )


def validate(msg) -> dict:
    if not isinstance(msg, dict):
        raise ProtocolError("mensagem não é um objeto JSON")
    missing = [f for f in FIELDS if f not in msg]
    if missing:
        raise ProtocolError(f"campos ausentes: {', '.join(missing)}")
    extra = set(msg) - set(FIELDS)
    if extra:
        raise ProtocolError(f"campos desconhecidos: {', '.join(sorted(extra))}")
    for field in FIELDS:
        if not isinstance(msg[field], str):
            raise ProtocolError(f"campo '{field}' deve ser string")
    if msg["type"] not in TYPES:
        raise ProtocolError(f"tipo desconhecido: {msg['type']!r}")
    if msg["role"] and msg["role"] not in ROLES:
        raise ProtocolError(f"papel desconhecido: {msg['role']!r}")
    return msg


def encode(msg) -> bytes:
    data = json.dumps(validate(msg), ensure_ascii=False).encode("utf-8") + b"\n"
    if len(data) > MAX_LINE:
        raise ProtocolError("mensagem excede o tamanho máximo")
    return data


def decode(line: bytes) -> dict:
    if len(line) > MAX_LINE:
        raise ProtocolError("mensagem excede o tamanho máximo")
    try:
        obj = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"JSON inválido: {exc}") from exc
    return validate(obj)


def send_msg(sock, msg, lock=None) -> None:
    data = encode(msg)
    if lock is None:
        sock.sendall(data)
    else:
        with lock:
            sock.sendall(data)


class LineReader:
    """Buffers a stream socket and yields one decoded message per newline-delimited line."""

    def __init__(self, sock, bufsize=4096):
        self._sock = sock
        self._bufsize = bufsize
        self._buf = bytearray()

    def read_msg(self):
        """Return the next message, or None on clean EOF. Raises ProtocolError on bad data."""
        while True:
            idx = self._buf.find(b"\n")
            if idx >= 0:
                line = bytes(self._buf[:idx])
                del self._buf[: idx + 1]
                if not line.strip():
                    continue
                return decode(line)
            if len(self._buf) > MAX_LINE:
                raise ProtocolError("mensagem excede o tamanho máximo")
            chunk = self._sock.recv(self._bufsize)
            if not chunk:
                if self._buf.strip():
                    raise ProtocolError("conexão encerrada no meio de uma mensagem")
                return None
            self._buf.extend(chunk)

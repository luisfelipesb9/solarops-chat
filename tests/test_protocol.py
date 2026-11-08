import json
import socket
import threading

import pytest

import protocol as p


def test_make_msg_has_all_fields_as_strings():
    m = p.make_msg("MSG", "ana", "*", "olá")
    assert set(m) == set(p.FIELDS)
    assert all(isinstance(v, str) for v in m.values())
    assert m["ts"].endswith("+00:00")


def test_encode_decode_roundtrip_utf8():
    m = p.make_msg("BOT_REQ", "tecnico1", "bot", "código 2032? ção", req_id=p.new_req_id())
    data = p.encode(m)
    assert data.endswith(b"\n") and data.count(b"\n") == 1
    assert p.decode(data[:-1]) == m


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"type": "MSG"},
        {**dict.fromkeys(p.FIELDS, ""), "type": "NOPE"},
        {**dict.fromkeys(p.FIELDS, ""), "type": "MSG", "role": "admin"},
        {**dict.fromkeys(p.FIELDS, ""), "type": "MSG", "extra": "x"},
        {**dict.fromkeys(p.FIELDS, ""), "type": "MSG", "content": 1},
    ],
)
def test_validate_rejects(bad):
    with pytest.raises(p.ProtocolError):
        p.validate(bad)


def test_decode_rejects_invalid_json():
    with pytest.raises(p.ProtocolError):
        p.decode(b"{not json")


def test_encode_rejects_oversized():
    with pytest.raises(p.ProtocolError):
        p.encode(p.make_msg("MSG", "a", "*", "x" * p.MAX_LINE))


def test_valid_name():
    assert p.valid_name("tecnico_1")
    assert not p.valid_name("")
    assert not p.valid_name("a b")
    assert not p.valid_name("x" * 21)
    assert not p.valid_name(None)


def test_line_reader_handles_partial_and_coalesced_messages():
    a, b = socket.socketpair()
    try:
        m1 = p.make_msg("MSG", "a", "*", "um")
        m2 = p.make_msg("MSG", "b", "*", "dois")
        raw = p.encode(m1) + p.encode(m2)
        a.sendall(raw[:7])
        a.sendall(raw[7:])
        a.shutdown(socket.SHUT_WR)
        r = p.LineReader(b, bufsize=5)
        assert r.read_msg() == m1
        assert r.read_msg() == m2
        assert r.read_msg() is None
    finally:
        a.close()
        b.close()


def test_line_reader_rejects_oversized_line():
    a, b = socket.socketpair()
    sender = threading.Thread(target=lambda: _quiet_sendall(a, b"x" * (p.MAX_LINE + 10)), daemon=True)
    try:
        b.settimeout(5)
        sender.start()
        with pytest.raises(p.ProtocolError):
            p.LineReader(b).read_msg()
    finally:
        b.close()
        a.close()
        sender.join(timeout=5)


def _quiet_sendall(sock, data):
    try:
        sock.sendall(data)
    except OSError:
        pass


def test_line_reader_truncated_message_at_eof():
    a, b = socket.socketpair()
    try:
        a.sendall(json.dumps({"type": "MSG"}).encode())
        a.shutdown(socket.SHUT_WR)
        with pytest.raises(p.ProtocolError):
            p.LineReader(b).read_msg()
    finally:
        a.close()
        b.close()

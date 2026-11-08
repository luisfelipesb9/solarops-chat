"""Tests for server.py: real sockets, ephemeral ports, test clients built on protocol.py."""

import importlib
import json
import os
import queue
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time

import pytest

from protocol import LineReader, make_msg, new_req_id, send_msg
from server import ChatServer

TIMEOUT = 5.0


# --------------------------------------------------------------------------- helpers
class Client:
    """Minimal test client: raw socket + LineReader, with a timeout on every call."""

    def __init__(self, address, ctx=None):
        sock = socket.create_connection(address, timeout=TIMEOUT)
        if ctx is not None:
            sock = ctx.wrap_socket(sock, server_hostname="localhost")
        sock.settimeout(TIMEOUT)
        self.sock = sock
        self.reader = LineReader(sock)
        self.name = ""
        self.role = ""

    def send(self, type_, **fields):
        send_msg(self.sock, make_msg(type_, **fields))

    def recv(self):
        return self.reader.read_msg()

    def hello(self, name, role):
        self.name, self.role = name, role
        self.send("HELLO", from_=name, role=role)
        return self.recv()

    def expect_silence(self, seconds=0.4):
        self.sock.settimeout(seconds)
        try:
            msg = self.reader.read_msg()
        except (socket.timeout, TimeoutError):
            return
        finally:
            self.sock.settimeout(TIMEOUT)
        raise AssertionError(f"unexpected message: {msg!r}")

    def abort(self):
        """Close with RST (SO_LINGER 0), simulating an abrupt crash."""
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        self.sock.close()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def connect(address, name, role="tecnico", ctx=None):
    """Connect and finish the handshake (consumes WELCOME and LIST)."""
    client = Client(address, ctx)
    assert client.hello(name, role)["type"] == "WELCOME"
    assert client.recv()["type"] == "LIST"
    return client


def make_room(address, *specs):
    """Connect (name, role) clients in order; earlier humans consume the JOIN of each newcomer."""
    clients = []
    for name, role in specs:
        new = connect(address, name, role)
        for other in clients:
            if other.role != "bot":
                join = other.recv()
                assert (join["type"], join["from"]) == ("JOIN", name)
        clients.append(new)
    return clients


def wait_until(predicate, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def drain(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


@pytest.fixture
def events():
    return queue.Queue()


@pytest.fixture
def server(events):
    srv = ChatServer(host="127.0.0.1", plain_port=0, tls_port=0, bot_timeout=30.0, event_queue=events)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def clients():
    opened = []
    yield opened
    for c in opened:
        c.close()


@pytest.fixture
def room(server, clients):
    def _make(*specs):
        made = make_room(server.plain_address, *specs)
        clients.extend(made)
        return made

    return _make


# --------------------------------------------------------------------------- handshake
def test_handshake_sends_welcome_then_list(server, clients):
    c = Client(server.plain_address)
    clients.append(c)
    welcome = c.hello("ana", "cos")
    assert (welcome["type"], welcome["to"], welcome["content"]) == ("WELCOME", "ana", "Bem-vindo, ana")
    lst = c.recv()
    assert lst["type"] == "LIST"
    assert json.loads(lst["content"]) == [{"name": "ana", "role": "cos", "tls": False}]


def test_join_is_broadcast_to_existing_humans(room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    # make_room already asserted ana received JOIN from bia; check the new client got none
    bia.expect_silence()
    assert ana is not bia


def test_duplicate_name_is_rejected_and_connection_closed(server, room, clients):
    room(("ana", "cos"))
    dup = Client(server.plain_address)
    clients.append(dup)
    err = dup.hello("ana", "tecnico")
    assert err["type"] == "ERROR"
    assert dup.recv() is None
    assert [p["name"] for p in server.snapshot()] == ["ana"]


@pytest.mark.parametrize("role", ["", "chefe"])  # "" is valid for protocol.py; "chefe" is not
def test_invalid_role_is_rejected(server, clients, role):
    c = Client(server.plain_address)
    clients.append(c)
    hello = {"type": "HELLO", "from": "ana", "to": "*", "content": "", "req_id": "",
             "ts": "2026-01-01T00:00:00.000+00:00", "role": role}
    c.sock.sendall(json.dumps(hello).encode() + b"\n")  # raw: make_msg would refuse "chefe"
    assert c.recv()["type"] == "ERROR"
    assert c.recv() is None
    assert server.snapshot() == []


@pytest.mark.parametrize("name", ["a b", "", "x" * 21, "server", "bot"])
def test_invalid_or_reserved_human_name_is_rejected(server, clients, name):
    c = Client(server.plain_address)
    clients.append(c)
    assert c.hello(name, "tecnico")["type"] == "ERROR"
    assert c.recv() is None
    assert server.snapshot() == []


def test_bot_must_use_bot_name(server, clients):
    c = Client(server.plain_address)
    clients.append(c)
    assert c.hello("robo", "bot")["type"] == "ERROR"
    assert c.recv() is None


def test_first_message_must_be_hello(server, clients):
    c = Client(server.plain_address)
    clients.append(c)
    c.send("MSG", from_="ana", content="oi")
    assert c.recv()["type"] == "ERROR"
    assert c.recv() is None
    assert server.snapshot() == []


def test_second_bot_is_rejected(server, room, clients):
    room(("bot", "bot"))
    second = Client(server.plain_address)
    clients.append(second)
    assert second.hello("bot", "bot")["type"] == "ERROR"
    assert second.recv() is None
    assert [p["name"] for p in server.snapshot()] == ["bot"]


def test_hello_must_arrive_in_time(events, clients):
    srv = ChatServer(host="127.0.0.1", plain_port=0, tls_port=0, event_queue=events)
    srv.HELLO_TIMEOUT = 0.3
    srv.start()
    try:
        c = Client(srv.plain_address)
        clients.append(c)
        err = c.recv()
        assert err["type"] == "ERROR"
        assert c.recv() is None
    finally:
        srv.stop()


# --------------------------------------------------------------------------- chat routing
def test_broadcast_skips_sender_and_bot(room):
    ana, bia, bot = room(("ana", "cos"), ("bia", "tecnico"), ("bot", "bot"))
    ana.send("MSG", from_="ana", content="bom dia")
    got = bia.recv()
    assert (got["type"], got["from"], got["to"], got["content"]) == ("MSG", "ana", "*", "bom dia")
    ana.expect_silence()
    bot.expect_silence()


def test_from_field_is_overwritten_with_session_name(room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    ana.send("MSG", from_="engenheiro_falso", content="oi")
    assert bia.recv()["from"] == "ana"


def test_role_field_is_overwritten_with_session_role(room):
    ana, bia = room(("ana", "tecnico"), ("bia", "tecnico"))
    ana.send("MSG", from_="ana", role="engenheiro", content="religamento liberado")
    assert bia.recv()["role"] == "tecnico"
    ana.send("DM", from_="ana", to="bia", role="bot", content="oi")
    assert bia.recv()["role"] == "tecnico"


def test_lone_surrogate_content_is_rejected_and_server_keeps_routing(server, room, events):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    drain(events)
    # json.dumps escapes the lone surrogate as \ud800, so it travels as valid ASCII JSON.
    line = json.dumps(make_msg("MSG", from_="ana", content="\ud800")) + "\n"
    ana.sock.sendall(line.encode("ascii"))
    err = ana.recv()
    assert (err["type"], err["content"]) == ("ERROR", "Mensagem inválida.")
    assert [kind for kind, _ in drain(events)] == []  # nothing unprintable reached the event queue
    ana.send("MSG", from_="ana", content="ainda funciona")
    assert bia.recv()["content"] == "ainda funciona"


def test_client_vanishing_right_after_hello_never_joins_after_leaving(server, clients):
    errors = []
    original = threading.excepthook
    threading.excepthook = lambda args: errors.append(args)
    try:
        (observer,) = make_room(server.plain_address, ("obs", "cos"))
        clients.append(observer)
        for i in range(40):
            ghost = Client(server.plain_address)
            ghost.send("HELLO", from_=f"g{i}", role="tecnico")
            ghost.abort()
        events = []
        observer.sock.settimeout(0.5)
        try:
            while True:
                msg = observer.recv()
                events.append((msg["type"], msg["from"]))
        except (socket.timeout, TimeoutError):
            pass
        time.sleep(0.2)
    finally:
        threading.excepthook = original
    assert errors == []
    for kind, name in events:
        if kind == "JOIN":
            assert ("LEAVE", name) not in events[:events.index((kind, name))]


def test_dm_goes_only_to_recipient(room):
    ana, bia, caio = room(("ana", "cos"), ("bia", "tecnico"), ("caio", "engenheiro"))
    ana.send("DM", from_="ana", to="bia", content="segredo")
    got = bia.recv()
    assert (got["type"], got["from"], got["content"]) == ("DM", "ana", "segredo")
    caio.expect_silence()
    ana.expect_silence()


def test_dm_to_unknown_user_returns_error_to_sender(room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    ana.send("DM", from_="ana", to="ninguem", content="oi")
    err = ana.recv()
    assert (err["type"], err["to"]) == ("ERROR", "ana")
    bia.expect_silence()


def test_dm_to_bot_is_refused(room):
    ana, bot = room(("ana", "cos"), ("bot", "bot"))
    ana.send("DM", from_="ana", to="bot", content="oi")
    assert ana.recv()["type"] == "ERROR"
    bot.expect_silence()


def test_list_reports_tls_flag_and_roles(room):
    ana, bot = room(("ana", "cos"), ("bot", "bot"))
    ana.send("LIST", from_="ana")
    lst = ana.recv()
    assert lst["type"] == "LIST"
    assert sorted(json.loads(lst["content"]), key=lambda e: e["name"]) == [
        {"name": "ana", "role": "cos", "tls": False},
        {"name": "bot", "role": "bot", "tls": False},
    ]


def test_humans_cannot_send_server_only_types(room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    ana.send("BOT_RESP", from_="ana", to="bia", content="forjada", req_id=new_req_id())
    assert ana.recv()["type"] == "ERROR"
    bia.expect_silence()


# --------------------------------------------------------------------------- bot routing
def test_bot_req_without_bot_gets_immediate_error(room):
    (ana,) = room(("ana", "cos"))
    rid = new_req_id()
    ana.send("BOT_REQ", from_="ana", to="bot", content="oi?", req_id=rid)
    err = ana.recv()
    assert (err["type"], err["to"], err["req_id"], err["content"]) == (
        "ERROR", "ana", rid, "Bot indisponível no momento.")


def test_bot_req_requires_req_id(room):
    ana, bot = room(("ana", "cos"), ("bot", "bot"))
    ana.send("BOT_REQ", from_="ana", to="bot", content="oi?", req_id="")
    assert ana.recv()["type"] == "ERROR"
    bot.expect_silence()


def test_bot_req_is_routed_to_bot_with_requester_as_sender(server, room):
    ana, bia, bot = room(("ana", "cos"), ("bia", "tecnico"), ("bot", "bot"))
    rid = new_req_id()
    ana.send("BOT_REQ", from_="intruso", to="bot", content="o que é string box?", req_id=rid)
    got = bot.recv()
    assert (got["type"], got["from"], got["to"], got["req_id"], got["content"]) == (
        "BOT_REQ", "ana", "bot", rid, "o que é string box?")
    bia.expect_silence()
    pend = server.pending_snapshot()
    assert [(p["req_id"], p["from"]) for p in pend] == [(rid, "ana")]
    assert pend[0]["age"] >= 0


def test_bot_resp_is_delivered_only_to_requester(server, room):
    ana, bia, bot = room(("ana", "cos"), ("bia", "tecnico"), ("bot", "bot"))
    rid = new_req_id()
    ana.send("BOT_REQ", from_="ana", to="bot", content="pergunta", req_id=rid)
    bot.recv()
    bot.send("BOT_RESP", from_="bot", to="ana", content="resposta", req_id=rid)
    got = ana.recv()
    assert (got["type"], got["from"], got["to"], got["req_id"], got["content"]) == (
        "BOT_RESP", "bot", "ana", rid, "resposta")
    bia.expect_silence()
    assert server.pending_snapshot() == []


def test_bot_error_is_delivered_only_to_requester(server, room):
    ana, bia, bot = room(("ana", "cos"), ("bia", "tecnico"), ("bot", "bot"))
    rid = new_req_id()
    ana.send("BOT_REQ", from_="ana", to="bot", content="pergunta", req_id=rid)
    bot.recv()
    bot.send("ERROR", from_="bot", to="ana", content="LLM fora do ar", req_id=rid)
    got = ana.recv()
    assert (got["type"], got["content"], got["req_id"]) == ("ERROR", "LLM fora do ar", rid)
    bia.expect_silence()
    assert server.pending_snapshot() == []


def test_bot_resp_with_wrong_recipient_or_unknown_req_id_is_dropped(server, room):
    ana, bia, bot = room(("ana", "cos"), ("bia", "tecnico"), ("bot", "bot"))
    rid = new_req_id()
    ana.send("BOT_REQ", from_="ana", to="bot", content="pergunta", req_id=rid)
    bot.recv()
    bot.send("BOT_RESP", from_="bot", to="bia", content="desviada", req_id=rid)
    bot.send("BOT_RESP", from_="bot", to="ana", content="inventada", req_id=new_req_id())
    ana.expect_silence()
    bia.expect_silence()
    assert [p["req_id"] for p in server.pending_snapshot()] == [rid]
    bot.send("BOT_RESP", from_="bot", to="ana", content="certa", req_id=rid)
    assert ana.recv()["content"] == "certa"


def test_bot_timeout_sends_error_and_late_response_is_discarded(events, clients):
    srv = ChatServer(host="127.0.0.1", plain_port=0, tls_port=0, bot_timeout=0.3, event_queue=events)
    srv.start()
    try:
        ana, bot = make_room(srv.plain_address, ("ana", "cos"), ("bot", "bot"))
        clients.extend([ana, bot])
        rid = new_req_id()
        ana.send("BOT_REQ", from_="ana", to="bot", content="lenta", req_id=rid)
        bot.recv()
        err = ana.recv()
        assert (err["type"], err["req_id"], err["content"]) == (
            "ERROR", rid, "Tempo limite excedido na consulta ao bot.")
        assert srv.pending_snapshot() == []
        drain(events)
        bot.send("BOT_RESP", from_="bot", to="ana", content="tardia", req_id=rid)
        ana.expect_silence()
        kinds = [k for k, _ in drain(events)]
        assert "info" in kinds
        assert "bot_resp" not in kinds
    finally:
        srv.stop()


def test_bot_timeout_event_is_emitted(events, clients):
    srv = ChatServer(host="127.0.0.1", plain_port=0, tls_port=0, bot_timeout=0.2, event_queue=events)
    srv.start()
    try:
        ana, bot = make_room(srv.plain_address, ("ana", "cos"), ("bot", "bot"))
        clients.extend([ana, bot])
        rid = new_req_id()
        ana.send("BOT_REQ", from_="ana", to="bot", content="lenta", req_id=rid)
        assert ana.recv()["type"] == "ERROR"
        timeouts = [d for k, d in drain(events) if k == "bot_timeout"]
        assert [(d["req_id"], d["from"]) for d in timeouts] == [(rid, "ana")]
    finally:
        srv.stop()


def test_bot_disconnect_errors_every_pending_request(server, room):
    ana, bia, bot = room(("ana", "cos"), ("bia", "tecnico"), ("bot", "bot"))
    r1, r2 = new_req_id(), new_req_id()
    ana.send("BOT_REQ", from_="ana", to="bot", content="p1", req_id=r1)
    bia.send("BOT_REQ", from_="bia", to="bot", content="p2", req_id=r2)
    bot.recv()
    bot.recv()
    bot.close()
    for user, rid in ((ana, r1), (bia, r2)):
        got = {m["type"]: m for m in (user.recv(), user.recv())}  # LEAVE + ERROR, in either order
        assert set(got) == {"LEAVE", "ERROR"}
        assert (got["ERROR"]["req_id"], got["ERROR"]["content"]) == (rid, "Bot desconectado.")
        assert got["LEAVE"]["from"] == "bot"
    assert server.pending_snapshot() == []


# --------------------------------------------------------------------------- leaving
def test_voluntary_leave_is_broadcast_as_saiu(server, room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    bia.send("LEAVE", from_="bia")
    got = ana.recv()
    assert (got["type"], got["from"], got["content"]) == ("LEAVE", "bia", "saiu")
    assert bia.recv() is None
    assert wait_until(lambda: [p["name"] for p in server.snapshot()] == ["ana"])


def test_abrupt_drop_is_broadcast_as_conexao_perdida(server, room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    bia.abort()
    got = ana.recv()
    assert (got["type"], got["from"], got["content"]) == ("LEAVE", "bia", "conexão perdida")
    assert wait_until(lambda: [p["name"] for p in server.snapshot()] == ["ana"])


def test_eof_without_leave_is_conexao_perdida(room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    bia.close()
    assert ana.recv()["content"] == "conexão perdida"


def test_invalid_json_after_handshake_drops_client(room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    bia.sock.sendall(b"isto nao e json\n")
    got = ana.recv()
    assert (got["type"], got["from"], got["content"]) == ("LEAVE", "bia", "conexão perdida")


def test_left_name_can_be_reused(server, room, clients):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    bia.close()
    assert ana.recv()["type"] == "LEAVE"
    again = Client(server.plain_address)
    clients.append(again)
    assert again.hello("bia", "tecnico")["type"] == "WELCOME"


# --------------------------------------------------------------------------- state and events
def test_snapshot_has_name_role_tls_addr(server, room):
    room(("ana", "cos"), ("bot", "bot"))
    snap = {p["name"]: p for p in server.snapshot()}
    assert set(snap) == {"ana", "bot"}
    assert set(snap["ana"]) == {"name", "role", "tls", "addr"}
    assert (snap["ana"]["role"], snap["ana"]["tls"]) == ("cos", False)
    assert snap["ana"]["addr"].startswith("127.0.0.1:")


def test_events_cover_join_msg_dm_leave(server, events, room):
    ana, bia = room(("ana", "cos"), ("bia", "tecnico"))
    ana.send("MSG", from_="ana", content="publica")
    bia.recv()
    ana.send("DM", from_="ana", to="bia", content="privada")
    bia.recv()
    bia.close()
    ana.recv()  # LEAVE
    seen = drain(events)
    kinds = [k for k, _ in seen]
    assert kinds.count("join") == 2
    assert {"msg", "dm", "leave"} <= set(kinds)
    msg_data = next(d for k, d in seen if k == "msg")
    assert (msg_data["from"], msg_data["content"]) == ("ana", "publica")
    join_data = next(d for k, d in seen if k == "join")
    assert (join_data["name"], join_data["role"], join_data["tls"]) == ("ana", "cos", False)


def test_bot_req_and_resp_emit_events(server, events, room):
    ana, bot = room(("ana", "cos"), ("bot", "bot"))
    rid = new_req_id()
    ana.send("BOT_REQ", from_="ana", to="bot", content="p", req_id=rid)
    bot.recv()
    bot.send("BOT_RESP", from_="bot", to="ana", content="r", req_id=rid)
    ana.recv()
    kinds = [k for k, _ in drain(events)]
    assert "bot_req" in kinds and "bot_resp" in kinds


def test_stop_is_idempotent_and_closes_clients(events):
    srv = ChatServer(host="127.0.0.1", plain_port=0, tls_port=0, event_queue=events)
    srv.start()
    c = connect(srv.plain_address, "ana", "cos")
    srv.stop()
    srv.stop()
    assert c.recv() is None
    c.close()


def test_tls_address_is_none_without_ssl_context(server):
    assert server.tls_address is None
    assert server.plain_address[1] != 0


# --------------------------------------------------------------------------- concurrency
def test_concurrent_broadcasts_arrive_intact(room):
    names = ["u1", "u2", "u3", "u4"]
    users = room(*[(n, "tecnico") for n in names])
    per_sender = 25

    def blast(user):
        for i in range(per_sender):
            user.send("MSG", from_=user.name, content=f"{user.name}:{i}")

    threads = [threading.Thread(target=blast, args=(u,)) for u in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join(TIMEOUT)

    for user in users:
        got = [user.recv()["content"] for _ in range((len(users) - 1) * per_sender)]
        expected = {f"{n}:{i}" for n in names if n != user.name for i in range(per_sender)}
        assert set(got) == expected
        assert len(got) == len(expected)


# --------------------------------------------------------------------------- TLS
@pytest.fixture
def tls_server(tls_certs, events):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tls_certs["cert"], tls_certs["key"])
    srv = ChatServer(host="127.0.0.1", plain_port=0, tls_port=0, ssl_context=ctx, event_queue=events)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def tls_client_ctx(tls_certs):
    ctx = ssl.create_default_context(cafile=tls_certs["ca"])
    return ctx


def test_tls_and_plain_clients_share_one_room_and_list_shows_tls(tls_server, tls_client_ctx, clients):
    assert tls_server.tls_address is not None and tls_server.tls_address[1] != 0
    plain = connect(tls_server.plain_address, "ana", "cos")
    secure = connect(tls_server.tls_address, "bia", "tecnico", ctx=tls_client_ctx)
    clients.extend([plain, secure])
    assert plain.recv()["type"] == "JOIN"

    secure.send("LIST", from_="bia")
    entries = {e["name"]: e["tls"] for e in json.loads(secure.recv()["content"])}
    assert entries == {"ana": False, "bia": True}

    secure.send("MSG", from_="bia", content="por tls")
    assert plain.recv()["content"] == "por tls"
    plain.send("MSG", from_="ana", content="em claro")
    assert secure.recv()["content"] == "em claro"
    assert {p["name"]: p["tls"] for p in tls_server.snapshot()} == {"ana": False, "bia": True}


def test_stalled_tls_handshake_does_not_block_accept(tls_server, tls_client_ctx, clients):
    stalled = socket.create_connection(tls_server.tls_address, timeout=TIMEOUT)  # never speaks TLS
    try:
        started = time.monotonic()
        ok = connect(tls_server.tls_address, "ana", "cos", ctx=tls_client_ctx)
        clients.append(ok)
        assert time.monotonic() - started < 3.0  # handshake runs in the client thread, not in accept
    finally:
        stalled.close()


def test_garbage_on_tls_port_does_not_break_server(tls_server, tls_client_ctx, clients):
    junk = socket.create_connection(tls_server.tls_address, timeout=TIMEOUT)
    junk.sendall(b"GET / HTTP/1.0\r\n\r\n")
    junk.close()
    clients.append(connect(tls_server.tls_address, "ana", "cos", ctx=tls_client_ctx))
    assert [p["name"] for p in tls_server.snapshot()] == ["ana"]


# --------------------------------------------------------------------------- GUI module and CLI
def test_server_gui_imports_without_opening_a_window():
    tk = pytest.importorskip("tkinter")
    assert tk is not None
    gui = importlib.import_module("server_gui")
    assert callable(gui.ServerGUI)


def test_server_module_does_not_import_tkinter():
    code = "import server, sys; sys.exit(1 if 'tkinter' in sys.modules else 0)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=TIMEOUT)
    assert result.returncode == 0, result.stderr


def test_cli_serves_and_exits_cleanly_on_sigint():
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--host", "127.0.0.1", "--port", "0", "--no-tls"],
        cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        line = proc.stdout.readline()
        port = int(line.rsplit(":", 1)[1].split()[0])
        client = connect(("127.0.0.1", port), "ana", "cos")
        client.close()
        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=TIMEOUT) == 0
        assert "Traceback" not in proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.stderr.close()

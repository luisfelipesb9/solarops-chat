"""Stress: 10 simultaneous clients (5 plain, 5 TLS) each send 20 public messages to the same room."""

import socket
import threading
import time

import pytest

import tls_config
from protocol import LineReader, make_msg, send_msg
from server import ChatServer

CLIENTS = 10
MESSAGES_EACH = 20
EXPECTED_PER_CLIENT = (CLIENTS - 1) * MESSAGES_EACH  # 180: everything sent by the others
DEADLINE = 8.0  # global limit; a deadlock shows up as a client thread still alive after this


@pytest.fixture
def thread_errors(monkeypatch):
    """Collect exceptions that escape from any thread (server threads included)."""
    errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args))
    return errors


def connect(name, address, ssl_context):
    sock = socket.create_connection(address, timeout=DEADLINE)
    if ssl_context is not None:
        sock = ssl_context.wrap_socket(sock, server_hostname="127.0.0.1")
    reader = LineReader(sock)
    send_msg(sock, make_msg("HELLO", name, role="tecnico"))
    assert reader.read_msg()["type"] == "WELCOME"
    return sock, reader


def run_client(index, server, client_ctx, all_connected, received, failures):
    name = f"user{index}"
    tls = index % 2 == 1
    try:
        sock, reader = connect(name, server.tls_address if tls else server.plain_address,
                               client_ctx if tls else None)
        all_connected.wait(DEADLINE)  # nobody sends before everybody is in the room

        def send_all():
            for n in range(MESSAGES_EACH):
                send_msg(sock, make_msg("MSG", name, "*", f"{name}:{n}"))

        sender = threading.Thread(target=send_all, daemon=True)  # reading must not wait for sending
        sender.start()
        got = []
        while len(got) < EXPECTED_PER_CLIENT:
            msg = reader.read_msg()
            if msg is None:
                break
            if msg["type"] == "MSG":
                got.append((msg["from"], msg["content"]))
        sender.join(DEADLINE)
        received[name] = got
        send_msg(sock, make_msg("LEAVE", name))
        sock.close()
    except Exception as exc:  # reported by the test thread, with the client name
        failures.append(f"{name}: {type(exc).__name__}: {exc}")


def test_ten_clients_each_receive_every_message_of_the_others(tls_certs, thread_errors):
    server = ChatServer("127.0.0.1", 0, 0, tls_config.server_context(tls_certs["cert"], tls_certs["key"]))
    server.start()
    try:
        client_ctx = tls_config.client_context(tls_certs["ca"])
        all_connected = threading.Barrier(CLIENTS)
        received, failures = {}, []
        threads = [
            threading.Thread(target=run_client, args=(i, server, client_ctx, all_connected, received, failures),
                             daemon=True)
            for i in range(CLIENTS)
        ]
        started = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(max(0.1, started + DEADLINE - time.monotonic()))

        assert not [t for t in threads if t.is_alive()], "deadlock: clients still running after the deadline"
        assert failures == []
        assert len(received) == CLIENTS

        for name, got in received.items():
            assert len(got) == EXPECTED_PER_CLIENT, f"{name} received {len(got)} messages"
            assert all(sender != name for sender, _ in got), f"{name} got an echo of its own message"
            for other in (f"user{i}" for i in range(CLIENTS) if f"user{i}" != name):
                # exactly the 20 messages of that sender, in the order they were sent
                assert [c for s, c in got if s == other] == [f"{other}:{n}" for n in range(MESSAGES_EACH)]

        deadline = time.monotonic() + 3
        while server.snapshot() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.snapshot() == [], "every client said LEAVE, the room should be empty"
    finally:
        server.stop()
    time.sleep(0.2)  # let handler threads finish unwinding before checking for stray exceptions
    assert thread_errors == []

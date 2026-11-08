"""Tests for client.py. They use a tiny fake server (socket + thread + protocol.py), not server.py."""

import json
import queue
import re
import socket
import ssl
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import client as client_mod
from client import ChatClient, CommandError, format_incoming, main, parse_args, parse_command
from protocol import LineReader, make_msg, send_msg

WAIT = 5  # seconds; every blocking call in these tests has a timeout


# ---------------------------------------------------------------- fake server

class FakeServer:
    """Accepts ONE connection and speaks just enough SolarOps protocol for the client.

    reply: "welcome" answers HELLO with WELCOME; "error" answers with ERROR;
           "close" closes right after reading HELLO.
    """

    def __init__(self, reply="welcome", ssl_context=None, error_text="Nome já em uso."):
        self.reply = reply
        self.ssl_context = ssl_context
        self.error_text = error_text
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(WAIT)
        self.port = self.listener.getsockname()[1]
        self.conn = None
        self.hello = None
        self.connected = threading.Event()
        self.received = queue.Queue()  # messages sent by the client after HELLO
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            conn, _ = self.listener.accept()
            conn.settimeout(WAIT)
            if self.ssl_context:
                conn = self.ssl_context.wrap_socket(conn, server_side=True)
            self.conn = conn
            reader = LineReader(conn)
            self.hello = reader.read_msg()
            if self.reply == "close":
                return
            if self.reply == "error":
                send_msg(conn, make_msg("ERROR", "server", self.hello["from"], self.error_text))
                return
            send_msg(conn, make_msg("WELCOME", "server", self.hello["from"], f"Bem-vindo, {self.hello['from']}"))
            self.connected.set()
            while True:
                try:
                    msg = reader.read_msg()
                except socket.timeout:
                    continue  # idle is fine; the test decides when to stop
                if msg is None:
                    return
                self.received.put(msg)
        except (OSError, ssl.SSLError):
            pass  # e.g. client rejected our certificate
        finally:
            self.drop()

    def push(self, type_, from_, content, to="ana", req_id="", role=""):
        send_msg(self.conn, make_msg(type_, from_, to, content, req_id=req_id, role=role))

    def drop(self):
        """Close the client connection abruptly (simulates the server going down)."""
        if self.conn is not None:
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.conn.close()

    def close(self):
        self.drop()
        self.listener.close()


@pytest.fixture
def serve():
    servers = []

    def make(**kwargs):
        srv = FakeServer(**kwargs)
        servers.append(srv)
        return srv

    yield make
    for srv in servers:
        srv.close()


@pytest.fixture
def lines():
    """Queue that collects everything the client prints through out()."""
    return queue.Queue()


@pytest.fixture
def make_client(lines):
    clients = []

    def make(srv, name="ana", role="tecnico", **kwargs):
        c = ChatClient(name, role, "127.0.0.1", srv.port, out=lines.put, **kwargs)
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.close()


def started(srv, make_client, **kwargs):
    """Connected client with its receiver thread running."""
    c = make_client(srv, **kwargs)
    c.connect()
    c.start_receiver()
    assert srv.connected.wait(WAIT)
    return c


def drain(lines, count):
    return [lines.get(timeout=WAIT) for _ in range(count)]


# ---------------------------------------------------------------- parse_command

class TestParseCommand:
    def test_plain_text_becomes_public_msg(self):
        msg = parse_command("bom dia, equipe", "ana")
        assert (msg["type"], msg["from"], msg["to"], msg["content"]) == ("MSG", "ana", "*", "bom dia, equipe")

    def test_text_is_stripped(self):
        assert parse_command("   oi   ", "ana")["content"] == "oi"

    @pytest.mark.parametrize("line", ["", "   ", "\t\n"])
    def test_blank_line_is_ignored(self, line):
        assert parse_command(line, "ana") is None

    def test_bot_question_becomes_bot_req_with_req_id(self):
        msg = parse_command("@bot qual a tensão do string?", "ana")
        assert (msg["type"], msg["from"], msg["to"]) == ("BOT_REQ", "ana", "bot")
        assert msg["content"] == "qual a tensão do string?"
        assert re.fullmatch(r"[0-9a-f]{32}", msg["req_id"])

    def test_each_bot_req_gets_a_new_req_id(self):
        ids = {parse_command("@bot oi", "ana")["req_id"] for _ in range(5)}
        assert len(ids) == 5

    @pytest.mark.parametrize("line", ["@bot", "@bot   ", "  @BOT  "])
    def test_bot_without_question_shows_usage(self, line):
        with pytest.raises(CommandError, match=r"Uso: @bot <pergunta>"):
            parse_command(line, "ana")

    def test_word_starting_with_bot_is_a_normal_message(self):
        assert parse_command("@bottle cheia", "ana")["type"] == "MSG"

    def test_dm(self):
        msg = parse_command("/w carlos  pode ir ao inversor 3?", "ana")
        assert (msg["type"], msg["from"], msg["to"], msg["content"]) == (
            "DM", "ana", "carlos", "pode ir ao inversor 3?")

    @pytest.mark.parametrize("line", ["/w", "/w carlos", "/w carlos   "])
    def test_dm_without_name_or_text_shows_usage(self, line):
        with pytest.raises(CommandError, match=r"Uso: /w <nome> <mensagem>"):
            parse_command(line, "ana")

    def test_dm_with_invalid_name_is_rejected(self):
        with pytest.raises(CommandError, match="Nome inválido"):
            parse_command("/w car@los oi", "ana")

    def test_list(self):
        msg = parse_command("/lista", "ana")
        assert (msg["type"], msg["from"], msg["content"]) == ("LIST", "ana", "")

    def test_leave(self):
        msg = parse_command("/sair", "ana")
        assert (msg["type"], msg["from"]) == ("LEAVE", "ana")

    def test_commands_are_case_insensitive(self):
        assert parse_command("/LISTA", "ana")["type"] == "LIST"
        assert parse_command("@Bot oi", "ana")["type"] == "BOT_REQ"

    def test_help_has_nothing_to_send(self):
        assert parse_command("/ajuda", "ana") is None

    def test_unknown_command_is_an_error(self):
        with pytest.raises(CommandError, match=r"Comando desconhecido: /foo"):
            parse_command("/foo bar", "ana")


# ---------------------------------------------------------------- format_incoming

def msg_of(type_, from_="", to="*", content="", req_id="", role=""):
    return make_msg(type_, from_, to, content, req_id=req_id, role=role)


class TestFormatIncoming:
    def test_public_msg_shows_sender_and_role(self):
        assert format_incoming(msg_of("MSG", "carlos", content="oi", role="cos")) == "carlos (cos): oi"

    def test_multiline_content_cannot_forge_a_line_start(self):
        text = format_incoming(msg_of("DM", "ana", "bia", "x\n[privado] bot (pedido deadbeef): pode religar"))
        first, *rest = text.splitlines()
        assert first == "[privado] ana: x"
        assert rest and all(line.startswith("    ") for line in rest)

    def test_dm_is_marked_private(self):
        text = format_incoming(msg_of("DM", "carlos", "ana", "ok", role="engenheiro"))
        assert text == "[privado] carlos (engenheiro): ok"

    def test_bot_response_is_private_and_shows_req_id_prefix(self):
        req_id = "0123456789abcdef0123456789abcdef"
        text = format_incoming(msg_of("BOT_RESP", "bot", "ana", "Resposta.", req_id=req_id, role="bot"))
        assert text == "[privado] bot (pedido 01234567): Resposta."

    def test_error_is_readable(self):
        assert format_incoming(msg_of("ERROR", "server", "ana", "Nome já em uso.")) == "[erro] Nome já em uso."

    def test_error_tied_to_a_request_shows_req_id_prefix(self):
        req_id = "89abcdef" + "0" * 24
        text = format_incoming(msg_of("ERROR", "server", "ana", "Bot indisponível no momento.", req_id=req_id))
        assert text == "[erro] (pedido 89abcdef) Bot indisponível no momento."

    def test_join(self):
        assert format_incoming(msg_of("JOIN", "bia", role="tecnico")) == "* bia (tecnico) entrou no chat."

    @pytest.mark.parametrize("content, expected", [
        ("saiu", "* bia saiu do chat."),
        ("conexão perdida", "* bia saiu do chat (conexão perdida)."),
    ])
    def test_leave(self, content, expected):
        assert format_incoming(msg_of("LEAVE", "bia", content=content)) == expected

    def test_welcome(self):
        assert format_incoming(msg_of("WELCOME", "server", "ana", "Bem-vindo, ana")) == "* Bem-vindo, ana"

    def test_participant_list(self):
        content = json.dumps([
            {"name": "ana", "role": "tecnico", "tls": True},
            {"name": "bot", "role": "bot", "tls": False},
        ])
        assert format_incoming(msg_of("LIST", "server", "ana", content)) == (
            "Participantes online (2):\n"
            "  - ana (tecnico) [TLS]\n"
            "  - bot (bot) [texto claro]"
        )

    def test_malformed_list_does_not_crash(self):
        assert "não é json" in format_incoming(msg_of("LIST", "server", "ana", "não é json"))

    def test_unexpected_type_falls_back_to_generic_line(self):
        assert format_incoming(msg_of("HELLO", "x", content="y")) == "[HELLO] x: y"


# ---------------------------------------------------------------- connect()

class TestConnect:
    def test_returns_welcome_and_sent_hello(self, serve, make_client):
        srv = serve()
        welcome = make_client(srv, name="ana", role="cos").connect()
        assert (welcome["type"], welcome["content"]) == ("WELCOME", "Bem-vindo, ana")
        assert (srv.hello["type"], srv.hello["from"], srv.hello["role"]) == ("HELLO", "ana", "cos")

    def test_socket_has_no_timeout_after_handshake(self, serve, make_client):
        # a quiet chat must not be dropped by the 10 s handshake timeout
        c = make_client(serve())
        c.connect()
        assert c.sock.gettimeout() is None

    def test_error_reply_raises_connection_error_with_server_text(self, serve, make_client):
        srv = serve(reply="error", error_text="Nome já em uso.")
        with pytest.raises(ConnectionError, match="Nome já em uso."):
            make_client(srv).connect()

    def test_server_closing_during_handshake_is_a_clear_error(self, serve, make_client):
        srv = serve(reply="close")
        with pytest.raises(ConnectionError, match="encerrou a conexão"):
            make_client(srv).connect()

    def test_connection_refused_is_a_clear_error(self, make_client):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nobody listens here now
        with pytest.raises(ConnectionError, match="Não foi possível conectar"):
            make_client(SimpleNamespace(port=port)).connect()


# ---------------------------------------------------------------- receiver / input

class TestReceiverAndInput:
    def test_receives_while_sending_concurrently(self, serve, make_client, lines):
        srv = serve()
        c = started(srv, make_client)
        count = 50

        def push_all():
            for i in range(count):
                srv.push("MSG", "bia", f"in-{i}", to="*", role="cos")

        pusher = threading.Thread(target=push_all)
        pusher.start()
        for i in range(count):
            c.handle_input(f"out-{i}")  # typing never waits for incoming traffic
        pusher.join(WAIT)

        assert drain(lines, count) == [f"bia (cos): in-{i}" for i in range(count)]
        assert [srv.received.get(timeout=WAIT)["content"] for _ in range(count)] == [
            f"out-{i}" for i in range(count)]

    def test_can_keep_typing_while_bot_is_processing(self, serve, make_client, lines):
        srv = serve()
        c = started(srv, make_client)

        t0 = time.monotonic()
        sent = c.handle_input("@bot qual o torque do parafuso?")
        c.handle_input("alguém no campo?")
        assert time.monotonic() - t0 < 1  # no wait for the (still silent) bot
        assert sent["type"] == "BOT_REQ"

        req = srv.received.get(timeout=WAIT)
        assert req["type"] == "BOT_REQ"
        assert srv.received.get(timeout=WAIT)["content"] == "alguém no campo?"

        srv.push("BOT_RESP", "bot", "Consulte a tabela.", req_id=req["req_id"], role="bot")
        assert lines.get(timeout=WAIT) == f"[privado] bot (pedido {req['req_id'][:8]}): Consulte a tabela."

    def test_handle_input_returns_the_sent_message(self, serve, make_client):
        srv = serve()
        c = started(srv, make_client)
        sent = c.handle_input("oi")
        assert sent["type"] == "MSG" and sent["content"] == "oi"
        assert srv.received.get(timeout=WAIT)["content"] == "oi"

    def test_list_dm_are_sent_to_the_server(self, serve, make_client):
        srv = serve()
        c = started(srv, make_client)
        c.handle_input("/lista")
        c.handle_input("/w carlos oi")
        assert srv.received.get(timeout=WAIT)["type"] == "LIST"
        dm = srv.received.get(timeout=WAIT)
        assert (dm["type"], dm["to"], dm["content"]) == ("DM", "carlos", "oi")

    def test_leave_sends_leave_and_stops_quietly(self, serve, make_client, lines):
        srv = serve()
        c = started(srv, make_client)
        assert c.handle_input("/sair")["type"] == "LEAVE"
        assert srv.received.get(timeout=WAIT)["type"] == "LEAVE"
        assert c.stopped.wait(WAIT)
        c.receiver.join(WAIT)
        assert not c.receiver.is_alive()
        assert lines.empty()  # leaving on purpose is not "connection lost"

    def test_help_is_local_and_sends_nothing(self, serve, make_client, lines):
        srv = serve()
        c = started(srv, make_client)
        assert c.handle_input("/ajuda") is None
        assert "/sair" in lines.get(timeout=WAIT)
        c.handle_input("fim")
        assert srv.received.get(timeout=WAIT)["content"] == "fim"  # first thing the server saw

    @pytest.mark.parametrize("line, usage", [("@bot", "Uso: @bot"), ("/w ana", "Uso: /w"), ("/xyz", "Comando desconhecido")])
    def test_bad_command_prints_hint_and_sends_nothing(self, serve, make_client, lines, line, usage):
        srv = serve()
        c = started(srv, make_client)
        assert c.handle_input(line) is None
        assert usage in lines.get(timeout=WAIT)
        c.handle_input("depois")
        assert srv.received.get(timeout=WAIT)["content"] == "depois"

    def test_blank_line_is_ignored(self, serve, make_client, lines):
        srv = serve()
        c = started(srv, make_client)
        assert c.handle_input("   ") is None
        assert lines.empty()

    def test_oversized_message_is_reported_not_raised(self, serve, make_client, lines):
        srv = serve()
        c = started(srv, make_client)
        assert c.handle_input("x" * 70000) is None
        assert "muito longa" in lines.get(timeout=WAIT)
        assert not c.stopped.is_set()


# ---------------------------------------------------------------- server going down

class TestServerLoss:
    def test_drop_prints_message_once_and_stops(self, serve, make_client, lines):
        srv = serve()
        c = started(srv, make_client)
        called = threading.Event()
        c.on_lost = called.set

        srv.drop()

        assert lines.get(timeout=WAIT) == "Conexão com o servidor perdida."
        assert c.stopped.wait(WAIT) and called.wait(WAIT)
        # typing after the loss neither raises nor repeats the message
        assert c.handle_input("alguém aí?") is None
        time.sleep(0.3)
        assert lines.empty()

    def test_voluntary_close_does_not_call_on_lost(self, serve, make_client):
        srv = serve()
        c = started(srv, make_client)
        called = threading.Event()
        c.on_lost = called.set
        c.close()
        c.close()  # idempotent
        assert c.stopped.is_set()
        assert not called.wait(0.3)


# ---------------------------------------------------------------- TLS

def _server_ctx(certs):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certs["cert"], certs["key"])
    return ctx


def _client_ctx(cafile):
    ctx = ssl.create_default_context(cafile=cafile)
    return ctx


class TestTLS:
    def test_connects_and_chats_over_tls(self, tls_certs, serve, make_client, lines):
        srv = serve(ssl_context=_server_ctx(tls_certs))
        c = started(srv, make_client, ssl_context=_client_ctx(tls_certs["ca"]))
        c.handle_input("criptografado")
        assert srv.received.get(timeout=WAIT)["content"] == "criptografado"
        srv.push("MSG", "bia", "recebido", to="*", role="cos")
        assert lines.get(timeout=WAIT) == "bia (cos): recebido"
        c.handle_input("/sair")
        c.receiver.join(WAIT)
        assert not c.receiver.is_alive()
        assert lines.empty()

    def test_untrusted_certificate_is_rejected_with_clear_message(self, tls_certs, wrong_ca, serve, make_client):
        srv = serve(ssl_context=_server_ctx(tls_certs))
        with pytest.raises(ConnectionError, match="certificado"):
            make_client(srv, ssl_context=_client_ctx(wrong_ca)).connect()


# ---------------------------------------------------------------- CLI

class TestCli:
    def test_default_port_is_5050_plain_and_5051_with_tls(self):
        assert parse_args(["--name", "ana", "--role", "cos"]).port == 5050
        assert parse_args(["--name", "ana", "--role", "cos", "--tls"]).port == 5051

    def test_explicit_port_wins(self):
        assert parse_args(["--name", "ana", "--role", "cos", "--tls", "--port", "6000"]).port == 6000

    def test_other_defaults(self):
        args = parse_args(["--name", "ana", "--role", "cos"])
        assert (args.host, args.ca, args.tls) == ("127.0.0.1", "certs/ca.crt", False)

    @pytest.mark.parametrize("role", ["bot", "chefe"])
    def test_only_human_roles_are_accepted(self, role):
        with pytest.raises(SystemExit):
            parse_args(["--name", "ana", "--role", role])

    @pytest.mark.parametrize("name", ["", "com espaço", "a" * 21, "açaí"])
    def test_invalid_name_is_rejected_before_connecting(self, name):
        with pytest.raises(SystemExit):
            parse_args(["--name", name, "--role", "cos"])

    def test_handshake_error_prints_message_and_exits_nonzero(self, serve, capsys):
        srv = serve(reply="error", error_text="Nome já em uso.")
        code = main(["--name", "ana", "--role", "cos", "--port", str(srv.port)])
        assert code != 0
        assert "Nome já em uso." in capsys.readouterr().err

    def test_session_sends_typed_lines_and_leaves_on_sair(self, serve, monkeypatch, capsys):
        srv = serve()
        typed = iter(["olá, pessoal", "/sair"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(typed))
        code = main(["--name", "ana", "--role", "cos", "--port", str(srv.port)])
        assert code == 0
        assert srv.received.get(timeout=WAIT)["content"] == "olá, pessoal"
        assert srv.received.get(timeout=WAIT)["type"] == "LEAVE"
        assert "Bem-vindo, ana" in capsys.readouterr().out

    def test_ctrl_d_leaves_gracefully(self, serve, monkeypatch):
        srv = serve()

        def eof(prompt=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", eof)
        assert main(["--name", "ana", "--role", "cos", "--port", str(srv.port)]) == 0
        assert srv.received.get(timeout=WAIT)["type"] == "LEAVE"

    def test_tls_session_uses_tls_config_client_context(self, tls_certs, serve, monkeypatch):
        srv = serve(ssl_context=_server_ctx(tls_certs))
        seen = {}

        def fake_client_context(cafile):
            seen["cafile"] = cafile
            return _client_ctx(cafile)

        # tls_config.py is written by another agent; the CLI imports it lazily, only with --tls
        monkeypatch.setitem(sys.modules, "tls_config", SimpleNamespace(client_context=fake_client_context))
        typed = iter(["/sair"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(typed))
        code = main(["--name", "ana", "--role", "cos", "--tls", "--port", str(srv.port), "--ca", tls_certs["ca"]])
        assert code == 0
        assert seen["cafile"] == tls_certs["ca"]
        assert srv.received.get(timeout=WAIT)["type"] == "LEAVE"

    def test_missing_ca_file_is_a_clear_error(self, monkeypatch, capsys):
        def broken_client_context(cafile):
            raise FileNotFoundError(2, "No such file", cafile)

        monkeypatch.setitem(sys.modules, "tls_config", SimpleNamespace(client_context=broken_client_context))
        code = main(["--name", "ana", "--role", "cos", "--tls", "--ca", "nao/existe.crt"])
        assert code != 0
        assert "nao/existe.crt" in capsys.readouterr().err

    def test_connection_lost_during_session_exits_nonzero_without_traceback(self, serve, monkeypatch, capsys):
        srv = serve()
        gate = threading.Event()

        def input_then_wait(prompt=""):
            gate.wait(WAIT)  # blocks like a real terminal until the server drops
            raise KeyboardInterrupt  # what on_lost triggers in the real CLI

        monkeypatch.setattr("builtins.input", input_then_wait)
        monkeypatch.setattr(client_mod, "interrupt_main", lambda: gate.set())
        threading.Timer(0.3, srv.drop).start()
        code = main(["--name", "ana", "--role", "cos", "--port", str(srv.port)])
        assert code != 0
        captured = capsys.readouterr()
        assert "Conexão com o servidor perdida." in captured.out
        assert "Traceback" not in captured.out + captured.err

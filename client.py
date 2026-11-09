"""SolarOps Chat client (SPEC §5.3): the receiver thread prints while the main thread reads input()."""

import argparse
import json
import signal
import socket
import ssl
import sys
import threading

from protocol import (
    HUMAN_ROLES, LineReader, ProtocolError, make_msg, new_req_id, send_msg, valid_name,
)

CONNECT_TIMEOUT = 10  # seconds for TCP connect, TLS handshake and WELCOME
LOST_TEXT = "Conexão com o servidor perdida."
HELP_TEXT = """Comandos:
  <texto>               envia mensagem para todos
  @bot <pergunta>       pergunta ao bot (a resposta é privada)
  /w <nome> <mensagem>  mensagem privada para um participante
  /lista                mostra quem está online
  /sair                 sai do chat
  /ajuda                mostra esta ajuda"""


class CommandError(ValueError):
    """The user typed a command wrongly; the message is the pt-BR hint to print."""


def parse_command(line, name):
    """Turn one line typed by the user into a protocol message.

    Returns None when there is nothing to send (blank line or /ajuda).
    Raises CommandError for a misused or unknown command.
    """
    text = line.strip()
    if not text:
        return None
    head, _, rest = text.partition(" ")
    head, rest = head.lower(), rest.strip()

    if head == "@bot":
        if not rest:
            raise CommandError("Uso: @bot <pergunta>")
        return make_msg("BOT_REQ", name, "bot", rest, req_id=new_req_id())
    if head == "/w":
        target, _, body = rest.partition(" ")
        if not target or not body.strip():
            raise CommandError("Uso: /w <nome> <mensagem>")
        if not valid_name(target):
            raise CommandError(f"Nome inválido: {target!r}")
        return make_msg("DM", name, target, body.strip())
    if head == "/lista":
        return make_msg("LIST", name)
    if head == "/sair":
        return make_msg("LEAVE", name)
    if head == "/ajuda":
        return None
    if head.startswith("/"):
        raise CommandError(f"Comando desconhecido: {head}. Digite /ajuda.")
    return make_msg("MSG", name, "*", text)


def _label(name, role):
    return f"{name} ({role})" if role else name


def _format_list(content):
    try:
        entries = json.loads(content)
        rows = [
            f"  - {_label(e['name'], e['role'])} [{'TLS' if e.get('tls') in (True, 'true', 'sim') else 'texto claro'}]"
            for e in entries
        ]
    except (ValueError, TypeError, KeyError, AttributeError):
        return f"Participantes: {content}"
    return "\n".join([f"Participantes online ({len(rows)}):", *rows])


def format_incoming(msg):
    """Human-readable pt-BR line for a message received from the server."""
    kind, who, role, content = msg["type"], msg["from"], msg["role"], msg["content"]
    short_id = msg["req_id"][:8]
    content = content.replace("\n", "\n    ")  # continuation lines can never imitate a client line
    if kind == "MSG":
        return f"{_label(who, role)}: {content}"
    if kind == "DM":
        return f"[privado] {_label(who, role)}: {content}"
    if kind == "BOT_RESP":
        return f"[privado] {who} (pedido {short_id}): {content}"
    if kind == "ERROR":
        return f"[erro] (pedido {short_id}) {content}" if short_id else f"[erro] {content}"
    if kind == "JOIN":
        return f"* {_label(who, role)} entrou no chat."
    if kind == "LEAVE":
        detail = "" if content in ("", "saiu") else f" ({content})"
        return f"* {who} saiu do chat{detail}."
    if kind == "WELCOME":
        return f"* {content}"
    if kind == "LIST":
        return _format_list(content)
    return f"[{kind}] {who}: {content}"


class ChatClient:
    def __init__(self, name, role, host="127.0.0.1", port=5050, ssl_context=None, out=print):
        self.name, self.role, self.host, self.port = name, role, host, port
        self.ssl_context = ssl_context
        self.out = out
        self.sock = None
        self.receiver = None
        self.on_lost = None  # optional callback, called once if the server connection drops
        self.lost = False
        self.stopped = threading.Event()
        self.leaving = threading.Event()  # set before LEAVE: the server closing next is expected
        self._reader = None
        self._send_lock = threading.Lock()   # one writer at a time on the socket
        self._state_lock = threading.Lock()  # makes stopping happen exactly once

    def connect(self):
        """Send HELLO and return the WELCOME message; raise ConnectionError with a pt-BR reason."""
        try:
            reply = self._handshake()
        except ssl.SSLCertVerificationError as exc:
            self._abort(f"Falha na verificação do certificado TLS do servidor ({exc.verify_message}). "
                        "Confira a CA informada em --ca.")
        except ssl.SSLError as exc:
            self._abort(f"Falha no handshake TLS: {exc}")
        except TimeoutError:
            self._abort("Tempo esgotado aguardando o servidor.")
        except (ConnectionResetError, BrokenPipeError):
            self._abort("O servidor encerrou a conexão durante o handshake.")
        except OSError as exc:
            self._abort(f"Não foi possível conectar a {self.host}:{self.port}: {exc.strerror or exc}")
        except ProtocolError as exc:
            self._abort(f"Resposta inválida do servidor: {exc}")

        if reply is None:
            self._abort("O servidor encerrou a conexão durante o handshake.")
        if reply["type"] == "ERROR":
            self._abort(reply["content"])
        if reply["type"] != "WELCOME":
            self._abort(f"Resposta inesperada do servidor: {reply['type']}")
        self.sock.settimeout(None)  # from now on the receiver may wait for as long as the chat is quiet
        return reply

    def _handshake(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT)
        if self.ssl_context:
            self.sock = self.ssl_context.wrap_socket(self.sock, server_hostname=self.host)
        self._reader = LineReader(self.sock)
        send_msg(self.sock, make_msg("HELLO", self.name, role=self.role), self._send_lock)
        return self._reader.read_msg()

    def _abort(self, text):
        self._close_socket()
        raise ConnectionError(text)

    def start_receiver(self):
        self.receiver = threading.Thread(target=self._receive_loop, daemon=True, name="receiver")
        self.receiver.start()

    def _receive_loop(self):
        try:
            while (msg := self._reader.read_msg()) is not None:
                self.out(format_incoming(msg))
        except (OSError, ProtocolError, ValueError):
            pass  # reset, TLS error, bad data or our own close(): all end the same way
        self._lost()  # silent if we closed on purpose

    def handle_input(self, line):
        """Parse and send what the user typed; return the sent message, or None if nothing was sent."""
        try:
            msg = parse_command(line, self.name)
        except CommandError as exc:
            self.out(str(exc))
            return None
        if msg is None:
            if line.strip():  # not blank, so it was /ajuda
                self.out(HELP_TEXT)
            return None
        if self.stopped.is_set():
            return None
        if msg["type"] == "LEAVE":
            self.leaving.set()
        try:
            send_msg(self.sock, msg, self._send_lock)
        except ProtocolError:
            self.out("Mensagem muito longa (o limite é 64 KB).")
            return None
        except OSError:
            self._lost()
            return None
        if msg["type"] == "LEAVE":
            self.close()
        return msg

    def close(self):
        self._stop()

    def _stop(self):
        """Close the socket; True only for the call that actually stopped the client."""
        with self._state_lock:
            first = not self.stopped.is_set()
            self.stopped.set()
        self._close_socket()
        return first

    def _lost(self):
        if self._stop() and not self.leaving.is_set():
            self.lost = True
            self.out(LOST_TEXT)
            if self.on_lost:
                self.on_lost()

    def _close_socket(self):
        if self.sock is None:
            return
        try:
            self.sock.shutdown(socket.SHUT_RDWR)  # also wakes a receiver blocked in recv()
        except OSError:
            pass
        self.sock.close()


def interrupt_main():
    """Wake the main thread blocked in input() (POSIX). Elsewhere the user just presses Enter."""
    if hasattr(signal, "pthread_kill"):
        signal.pthread_kill(threading.main_thread().ident, signal.SIGINT)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Cliente do SolarOps Chat.")
    parser.add_argument("--name", required=True, help="seu nome no chat")
    parser.add_argument("--role", required=True, choices=sorted(HUMAN_ROLES), help="seu papel")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, help="padrão: 5050 (5051 com --tls)")
    parser.add_argument("--tls", action="store_true", help="conecta com TLS")
    parser.add_argument("--ca", default="certs/ca.crt", help="certificado da CA (com --tls)")
    args = parser.parse_args(argv)
    if not valid_name(args.name):
        parser.error("nome inválido: use de 1 a 20 caracteres entre letras, números, _ e -")
    if args.port is None:
        args.port = 5051 if args.tls else 5050
    return args


def run_session(client):
    """Read lines from the terminal until /sair, Ctrl+D/Ctrl+C or loss of the server."""
    try:
        while not client.stopped.is_set():
            client.handle_input(input("> "))
    except (EOFError, KeyboardInterrupt):
        client.handle_input("/sair")  # no-op if the connection was already lost
    return 1 if client.lost else 0


def main(argv=None):
    args = parse_args(argv)
    ssl_context = None
    if args.tls:
        from tls_config import client_context  # imported late: only needed with --tls
        try:
            ssl_context = client_context(args.ca)
        except (OSError, ssl.SSLError) as exc:
            print(f"Erro: não foi possível carregar a CA '{args.ca}': {exc}", file=sys.stderr)
            return 1

    client = ChatClient(args.name, args.role, args.host, args.port, ssl_context)
    try:
        welcome = client.connect()
    except ConnectionError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(format_incoming(welcome))
    print("Digite /ajuda para ver os comandos.")
    client.on_lost = interrupt_main
    client.start_receiver()
    try:
        return run_session(client)
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())

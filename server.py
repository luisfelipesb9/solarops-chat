"""SolarOps Chat server: plain-text and TLS TCP ports, one thread per client (SPEC.md §3-§5)."""

import argparse
import json
import os
import queue
import signal
import socket
import ssl
import struct
import threading
import time
from dataclasses import dataclass, field

from protocol import (
    BOT_NAME, ROLES, SERVER_NAME, LineReader, ProtocolError, encode, make_msg, valid_name,
)

SEND_TIMEOUT = 5       # seconds a send may block: a stalled reader must not freeze the others
ACCEPT_POLL = 0.5      # accept() wakes up this often to notice stop()
REAPER_INTERVAL = 0.5  # how often pending bot requests are checked for timeout

# What each kind of session may send after the handshake.
HUMAN_TYPES = frozenset({"MSG", "DM", "BOT_REQ", "LIST"})
BOT_TYPES = frozenset({"BOT_RESP", "ERROR", "LIST"})
MESSAGE_KINDS = frozenset({"msg", "dm", "bot_req", "bot_resp"})  # events whose data is a protocol message


@dataclass(eq=False)
class Participant:
    name: str
    role: str
    tls: bool
    addr: str
    sock: socket.socket
    # Reentrant: the handshake holds it while WELCOME/LIST go out through _send().
    send_lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def is_bot(self) -> bool:
        return self.role == "bot"


@dataclass
class Pending:
    sender: str
    started: float
    deadline: float


def _close(sock) -> None:
    """shutdown() first: it wakes up a thread blocked in recv() on this socket."""
    for action in (lambda: sock.shutdown(socket.SHUT_RDWR), sock.close):
        try:
            action()
        except OSError:
            pass


class ChatServer:
    HELLO_TIMEOUT = 10.0  # seconds the client has to complete TLS and send HELLO

    def __init__(self, host="0.0.0.0", plain_port=5000, tls_port=5001,
                 ssl_context=None, bot_timeout=30.0, event_queue=None):
        self.host = host
        self.plain_port = plain_port
        self.tls_port = tls_port
        self.bot_timeout = bot_timeout
        self.plain_address = None
        self.tls_address = None
        self._ssl_context = ssl_context
        self._events = event_queue
        # ONE lock guards both dicts. No socket I/O is ever done while holding it.
        self._lock = threading.Lock()
        self._participants: dict[str, Participant] = {}
        self._pending: dict[str, Pending] = {}
        self._stop = threading.Event()
        self._listeners: list[socket.socket] = []
        self._accept_threads: list[threading.Thread] = []

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        try:
            plain = self._listen(self.plain_port)
            self.plain_address = plain.getsockname()[:2]
            self._spawn_accept(plain, tls=False)
            if self._ssl_context is not None:
                secure = self._listen(self.tls_port)
                self.tls_address = secure.getsockname()[:2]
                self._spawn_accept(secure, tls=True)
        except OSError:
            self.stop()
            raise
        threading.Thread(target=self._reaper_loop, name="reaper", daemon=True).start()

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for thread in self._accept_threads:
            thread.join(timeout=ACCEPT_POLL * 3)
        for listener in self._listeners:
            _close(listener)
        with self._lock:
            sessions = list(self._participants.values())
        for p in sessions:
            _close(p.sock)

    def _listen(self, port) -> socket.socket:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listeners.append(listener)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, port))
        listener.listen()
        listener.settimeout(ACCEPT_POLL)
        return listener

    def _spawn_accept(self, listener, tls) -> None:
        thread = threading.Thread(target=self._accept_loop, args=(listener, tls),
                                  name="accept-tls" if tls else "accept-plain", daemon=True)
        self._accept_threads.append(thread)
        thread.start()

    def _accept_loop(self, listener, tls) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            # Anything slow (TLS handshake, waiting for HELLO) happens in the client thread.
            threading.Thread(target=self._handle_client, args=(conn, addr, tls), daemon=True).start()

    # ------------------------------------------------------------------ events and snapshots
    def _emit(self, kind, data) -> None:
        if self._events is not None:
            try:
                self._events.put_nowait((kind, data))
            except queue.Full:
                pass

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [{"name": p.name, "role": p.role, "tls": p.tls, "addr": p.addr}
                    for p in self._participants.values()]

    def pending_snapshot(self) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            return [{"req_id": rid, "from": e.sender, "age": round(now - e.started, 1)}
                    for rid, e in self._pending.items()]

    def _list_json(self) -> str:
        with self._lock:
            entries = [{"name": p.name, "role": p.role, "tls": p.tls} for p in self._participants.values()]
        return json.dumps(entries, ensure_ascii=False)

    def _find(self, name):
        with self._lock:
            return self._participants.get(name)

    # ------------------------------------------------------------------ sending
    def _send(self, p, msg) -> bool:
        """Send outside the registry lock. A dead socket removes the participant (once)."""
        try:
            data = encode(msg)
        except (ProtocolError, ValueError):  # ValueError: lone surrogate that cannot be encoded
            return False  # too big after rewriting 'from': drop the message, keep the receiver
        try:
            with p.send_lock:
                p.sock.sendall(data)
        except (OSError, ValueError):  # ssl.SSLError and ConnectionResetError are OSErrors
            self._remove(p, "conexão perdida")
            return False
        return True

    def _error_to(self, p, text, req_id="") -> None:
        self._send(p, make_msg("ERROR", SERVER_NAME, p.name, text, req_id))

    def _broadcast(self, msg, exclude=None) -> None:
        """Deliver to every human except `exclude`; the bot never sees the public chat."""
        with self._lock:
            targets = [p for p in self._participants.values() if not p.is_bot and p.name != exclude]
        for p in targets:
            self._send(p, msg)

    # ------------------------------------------------------------------ client thread
    def _handle_client(self, conn, addr, tls) -> None:
        sock = conn
        try:
            # Send-only timeout: a client that stops reading becomes an OSError in _send() instead of
            # blocking the sender's thread (or the reaper) forever. Python ignores it while the socket
            # has a timeout (it polls instead); it only applies after settimeout(None) below.
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack("ll", SEND_TIMEOUT, 0))
            conn.settimeout(self.HELLO_TIMEOUT)
            if tls:
                sock = self._ssl_context.wrap_socket(conn, server_side=True)
            reader = LineReader(sock)
            participant = self._handshake(sock, reader, addr, tls)
        except (OSError, ProtocolError) as exc:  # failed TLS, reset before HELLO...
            self._emit("info", {"text": f"Conexão de {addr[0]}:{addr[1]} descartada antes do HELLO "
                                        f"({type(exc).__name__})."})
            _close(sock)
            return
        if participant is None:
            _close(sock)
            return
        try:
            sock.settimeout(None)
        except OSError:  # the peer already reset the connection: p is registered, so unregister it
            self._remove(participant, "conexão perdida")
            return
        self._serve(participant, reader)

    def _handshake(self, sock, reader, addr, tls):
        """Return the registered Participant, or None if the client was refused."""
        try:
            hello = reader.read_msg()
        except TimeoutError:
            return self._refuse(sock, "HELLO não recebido a tempo.")
        except ProtocolError:
            return self._refuse(sock, "Mensagem inválida.")
        if hello is None:
            return None
        problem = self._check_hello(hello)
        if problem:
            return self._refuse(sock, problem)

        p = Participant(hello["from"], hello["role"], tls, f"{addr[0]}:{addr[1]}", sock)
        with p.send_lock:  # WELCOME and LIST must reach the newcomer before anything else does
            problem = self._register(p)
            if problem:
                return self._refuse(sock, problem)
            sent = (self._send(p, make_msg("WELCOME", SERVER_NAME, p.name, f"Bem-vindo, {p.name}"))
                    and self._send(p, make_msg("LIST", SERVER_NAME, p.name, self._list_json())))
        if not sent:  # _send() already removed p; no JOIN may follow its LEAVE
            return None
        self._emit("join", {"name": p.name, "role": p.role, "tls": p.tls, "addr": p.addr,
                            "text": f"{p.name} ({p.role}) entrou [{'TLS' if tls else 'texto claro'}]"})
        self._broadcast(make_msg("JOIN", p.name, role=p.role), exclude=p.name)
        return p

    @staticmethod
    def _check_hello(hello):
        if hello["type"] != "HELLO":
            return "A primeira mensagem deve ser HELLO."
        name, role = hello["from"], hello["role"]
        if role not in ROLES:
            return "Papel inválido."
        if role == "bot":
            return None if name == BOT_NAME else "O bot deve usar o nome 'bot'."
        if not valid_name(name) or name in (BOT_NAME, SERVER_NAME):
            return "Nome inválido ou reservado."
        return None

    def _register(self, p):
        with self._lock:
            if p.is_bot and any(q.is_bot for q in self._participants.values()):
                return "Já existe um bot conectado."
            if p.name in self._participants:
                return "Nome já em uso."
            self._participants[p.name] = p
        return None

    @staticmethod
    def _refuse(sock, text):
        try:
            sock.sendall(encode(make_msg("ERROR", SERVER_NAME, "", text)))
        except (OSError, ProtocolError):
            pass
        return None

    def _serve(self, p, reader) -> None:
        reason = "conexão perdida"
        try:
            while True:
                msg = reader.read_msg()
                if msg is None:
                    break
                if msg["type"] == "LEAVE":
                    reason = "saiu"
                    break
                self._dispatch(p, msg)
        except (OSError, ProtocolError, ValueError):
            pass
        self._remove(p, reason)

    def _remove(self, p, reason) -> None:
        """Idempotent: only the call that actually removes `p` announces it."""
        with self._lock:
            if self._participants.get(p.name) is not p:
                return
            del self._participants[p.name]
            if p.is_bot:
                orphans = list(self._pending.items())
                self._pending.clear()
            else:
                orphans = []
                for rid in [r for r, e in self._pending.items() if e.sender == p.name]:
                    del self._pending[rid]
        _close(p.sock)
        if self._stop.is_set():
            return
        self._emit("leave", {"name": p.name, "role": p.role,
                             "text": f"{p.name} ({p.role}) deixou o chat [{reason}]"})
        self._broadcast(make_msg("LEAVE", p.name, "*", reason, role=p.role))
        for rid, entry in orphans:
            requester = self._find(entry.sender)
            if requester is not None:
                self._error_to(requester, "Bot desconectado.", rid)

    # ------------------------------------------------------------------ message routing
    def _dispatch(self, p, msg) -> None:
        try:
            encode(msg)  # reject what could not be forwarded or printed (e.g. a lone surrogate)
        except (ProtocolError, ValueError):
            self._error_to(p, "Mensagem inválida.")
            return
        if msg["type"] not in (BOT_TYPES if p.is_bot else HUMAN_TYPES):
            self._error_to(p, "Tipo de mensagem não permitido.", msg["req_id"][:64])
            return
        msg["from"] = p.name  # anti-spoofing: the session name is the only identity
        msg["role"] = p.role  # role comes from the session, never from the client
        handler = {
            "MSG": self._on_msg, "DM": self._on_dm, "BOT_REQ": self._on_bot_req,
            "LIST": self._on_list, "BOT_RESP": self._on_bot_answer, "ERROR": self._on_bot_answer,
        }[msg["type"]]
        handler(p, msg)

    def _on_msg(self, p, msg) -> None:
        msg["to"] = "*"
        self._emit("msg", dict(msg))
        self._broadcast(msg, exclude=p.name)

    def _on_dm(self, p, msg) -> None:
        target = self._find(msg["to"])
        if target is None or target.is_bot:
            self._error_to(p, f"Destinatário '{msg['to'][:20]}' indisponível.")
            return
        self._emit("dm", dict(msg))
        self._send(target, msg)

    def _on_list(self, p, msg) -> None:
        self._send(p, make_msg("LIST", SERVER_NAME, p.name, self._list_json()))

    def _on_bot_req(self, p, msg) -> None:
        rid = msg["req_id"]
        if not rid:
            self._error_to(p, "req_id obrigatório.")
            return
        msg["to"] = BOT_NAME
        problem = None
        with self._lock:
            bot = next((q for q in self._participants.values() if q.is_bot), None)
            if bot is None:
                problem = "Bot indisponível no momento."
            elif rid in self._pending:
                problem = "req_id já está em uso."
            else:
                now = time.monotonic()
                self._pending[rid] = Pending(p.name, now, now + self.bot_timeout)
        if problem:
            self._error_to(p, problem, rid[:64])
            return
        self._emit("bot_req", dict(msg))
        self._send(bot, msg)  # if this kills the bot, _remove() answers every pending request

    def _on_bot_answer(self, bot, msg) -> None:
        """BOT_RESP/ERROR from the bot: only for a pending req_id and its own requester."""
        rid = msg["req_id"]
        target = None
        with self._lock:
            entry = self._pending.get(rid)
            if entry is not None and entry.sender == msg["to"]:
                del self._pending[rid]
                target = self._participants.get(entry.sender)
        if entry is None:
            self._emit("info", {"req_id": rid, "text": f"Resposta do bot descartada: req_id "
                                                       f"{rid[:8]} desconhecido ou já expirado."})
        elif entry.sender != msg["to"]:
            self._emit("error", {"req_id": rid, "text": f"Resposta do bot descartada: destinatário "
                                                        f"diverge do solicitante (req_id {rid[:8]})."})
        else:
            self._emit("bot_resp", dict(msg))
            if target is not None:
                self._send(target, msg)

    # ------------------------------------------------------------------ bot timeout
    def _reaper_loop(self) -> None:
        while not self._stop.wait(REAPER_INTERVAL):
            now = time.monotonic()
            with self._lock:
                expired = [(rid, e.sender, self._participants.get(e.sender))
                           for rid, e in self._pending.items() if e.deadline <= now]
                for rid, _, _ in expired:
                    del self._pending[rid]
            for rid, sender, requester in expired:
                self._emit("bot_timeout", {"req_id": rid, "from": sender,
                                           "text": f"Consulta {rid[:8]} de {sender} expirou."})
                if requester is not None:
                    self._error_to(requester, "Tempo limite excedido na consulta ao bot.", rid)


# ---------------------------------------------------------------------- console / GUI formatting
def format_event(kind, data) -> str:
    """One display line for an event; shared by the console loop and the GUI."""
    if kind in MESSAGE_KINDS:
        req = f" (req {data['req_id'][:8]})" if data["req_id"] else ""
        return f"[{data['ts'][11:19]}] {data['type']} {data['from']} -> {data['to']}{req}: {data['content']}"
    return f"[{kind}] {data.get('text', '')}"


# ---------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Servidor do SolarOps Chat.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000, help="porta em texto claro")
    parser.add_argument("--tls-port", type=int, default=5001, help="porta TLS")
    parser.add_argument("--no-tls", action="store_true", help="não abre a porta TLS")
    parser.add_argument("--gui", action="store_true", help="abre a interface gráfica")
    parser.add_argument("--bot-timeout", type=float, default=None,
                        help="segundos de espera pela resposta do bot (padrão: BOT_TIMEOUT ou 30)")
    return parser


def main(argv=None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    args = build_parser().parse_args(argv)
    bot_timeout = args.bot_timeout if args.bot_timeout is not None else float(os.environ.get("BOT_TIMEOUT", "30"))

    ssl_context = None
    if not args.no_tls:
        try:
            import tls_config  # imported late: plain-text mode and the tests do not need it

            ssl_context = tls_config.server_context()
        except (ImportError, OSError, ssl.SSLError) as exc:
            print(f"Falha ao carregar o TLS ({exc}). Gere os certificados (certs/gen_certs.sh) "
                  f"ou use --no-tls.")
            return 1

    events = queue.Queue()
    server = ChatServer(args.host, args.port, args.tls_port, ssl_context, bot_timeout, events)
    signal.signal(signal.SIGINT, signal.default_int_handler)  # Ctrl+C must always raise KeyboardInterrupt
    try:
        server.start()
    except OSError as exc:
        print(f"Não foi possível abrir as portas: {exc}")
        return 1
    print(f"Servidor SolarOps (texto claro) ouvindo em {server.plain_address[0]}:{server.plain_address[1]}",
          flush=True)
    if server.tls_address:
        print(f"Servidor SolarOps (TLS) ouvindo em {server.tls_address[0]}:{server.tls_address[1]}", flush=True)

    try:
        if args.gui:
            import tkinter as tk

            from server_gui import ServerGUI

            root = tk.Tk()
            ServerGUI(root, server, events)
            root.mainloop()
        else:
            print("Ctrl+C para encerrar.", flush=True)
            while True:
                try:
                    print(format_event(*events.get(timeout=0.5)), flush=True)
                except queue.Empty:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    print("Servidor encerrado.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

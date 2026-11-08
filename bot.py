"""SolarOps bot: connects to the chat as 'bot' and answers BOT_REQ with an LLM (SPEC 5.5)."""

import argparse
import os
import socket
import ssl
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from llm import LLMError, build_llm_from_env
from protocol import BOT_NAME, LineReader, ProtocolError, make_msg, send_msg


def log(text):
    print(f"[bot] {text}", flush=True)


class ChatBot:
    def __init__(self, llm, host="127.0.0.1", port=5000, ssl_context=None, history_size=6, workers=4):
        self.llm = llm
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.history_size = history_size
        self.workers = workers
        self._history = {}  # user -> deque of {"role", "content"}
        self._history_lock = threading.Lock()
        self._send_lock = threading.Lock()  # several workers share one socket
        self._sock = None

    def history_for(self, user) -> list:
        with self._history_lock:
            return list(self._history.get(user, ()))

    def run(self) -> None:
        """Connect, say HELLO and serve BOT_REQ until the server closes the connection."""
        sock = socket.create_connection((self.host, self.port), timeout=10)
        if self.ssl_context is not None:
            sock = self.ssl_context.wrap_socket(sock, server_hostname=self.host)
        sock.settimeout(None)
        self._sock = sock
        pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="bot-worker")
        try:
            self._send(make_msg("HELLO", BOT_NAME, "server", role="bot"))
            self._read_loop(LineReader(sock), pool)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            sock.close()

    def _read_loop(self, reader, pool):
        welcomed = False
        while True:
            try:
                msg = reader.read_msg()
            except (OSError, ProtocolError) as exc:
                log(f"conexão encerrada ({type(exc).__name__})")
                return
            if msg is None:
                log("servidor encerrou a conexão")
                return
            if msg["type"] == "WELCOME":
                welcomed = True
                log("conectado ao servidor")
            elif msg["type"] == "ERROR" and not welcomed:
                log(f"servidor recusou o bot: {msg['content']}")
                return
            elif msg["type"] == "BOT_REQ":
                pool.submit(self._handle, msg)  # never block the reader on the LLM

    def _handle(self, msg):
        user, req_id, question = msg["from"], msg["req_id"], msg["content"]
        started = time.monotonic()
        history = self.history_for(user)
        try:
            answer = self.llm.complete(history + [{"role": "user", "content": question}])
        except LLMError as exc:
            self._reply("ERROR", user, req_id, str(exc))
            result = f"erro ({type(exc).__name__})"
        except Exception as exc:  # a bug in the LLM layer must not kill the worker silently
            self._reply("ERROR", user, req_id, "Erro interno do bot ao consultar a LLM.")
            result = f"erro interno ({type(exc).__name__})"
        else:
            self._remember(user, question, answer)
            self._reply("BOT_RESP", user, req_id, answer)
            result = "ok"
        log(f"req={req_id[:8]} user={user} {result} {time.monotonic() - started:.2f}s")

    def _remember(self, user, question, answer):
        with self._history_lock:
            turns = self._history.setdefault(user, deque(maxlen=self.history_size))
            turns.append({"role": "user", "content": question})
            turns.append({"role": "assistant", "content": answer})

    def _reply(self, type_, user, req_id, content):
        self._send(make_msg(type_, BOT_NAME, user, content, req_id, role="bot"))

    def _send(self, msg):
        try:
            send_msg(self._sock, msg, self._send_lock)
        except (OSError, ProtocolError) as exc:
            log(f"falha ao enviar {msg['type']} req={msg['req_id'][:8]} ({type(exc).__name__})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bot LLM do SolarOps Chat")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="padrão: 5000, ou 5001 com --tls")
    parser.add_argument("--tls", action="store_true", help="conecta usando TLS")
    parser.add_argument("--ca", default=None, help="certificado da CA (padrão: TLS_CA do .env)")
    args = parser.parse_args(argv)

    try:
        llm = build_llm_from_env()
    except LLMError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    ssl_context = None
    if args.tls:
        import tls_config  # late import: only needed with --tls

        try:
            ssl_context = tls_config.client_context(args.ca) if args.ca else tls_config.client_context()
        except (OSError, ssl.SSLError) as exc:
            print(f"Erro ao carregar o certificado da CA: {exc}", file=sys.stderr)
            return 1
    port = args.port or (5001 if args.tls else 5000)
    history_size = int(os.getenv("BOT_HISTORY_SIZE", "6"))
    bot = ChatBot(llm, args.host, port, ssl_context, history_size)
    log(f"conectando a {args.host}:{port} ({'TLS' if args.tls else 'texto claro'}), LLM={type(llm).__name__}")
    try:
        bot.run()
    except KeyboardInterrupt:
        log("encerrado pelo usuário")
    except OSError as exc:
        print(f"Não foi possível conectar ao servidor: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

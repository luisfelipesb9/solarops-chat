"""End-to-end scenarios (SPEC section 8): real server.py, bot.py and client.py processes over TCP/TLS.

Every process talks through pipes; ports are ephemeral (found by binding port 0) and the bot always
uses the FakeLLM, so nothing here touches ports 5050/5051 or the network outside loopback.
"""

import os
import socket
import subprocess
import sys
import threading
import time

import pytest

from client import ChatClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAIT = 6.0  # seconds any single expectation may take


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Output:
    """Thread-safe list of output lines with blocking 'wait until a line contains X'."""

    def __init__(self, name):
        self.name = name
        self.lines = []
        self._cond = threading.Condition()

    def add(self, line):
        with self._cond:
            self.lines.append(line)
            self._cond.notify_all()

    def seen(self, text) -> bool:
        with self._cond:
            return any(text in line for line in self.lines)

    def wait_for(self, text, timeout=WAIT) -> str:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for line in self.lines:
                    if text in line:
                        return line
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    shown = "\n".join(self.lines[-15:])
                    raise AssertionError(f"[{self.name}] never saw {text!r}. Last output:\n{shown}")
                self._cond.wait(remaining)


class Proc(Output):
    """A python subprocess (server.py, bot.py or client.py) whose stdout+stderr are collected."""

    def __init__(self, name, args, env):
        super().__init__(name)
        self.popen = subprocess.Popen(
            [sys.executable, *args], cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.popen.stdout:
            self.add(line.rstrip("\n"))

    def send(self, line):
        self.popen.stdin.write(line + "\n")
        self.popen.stdin.flush()

    def kill(self):
        self.popen.kill()
        self.popen.wait(timeout=5)

    def stop(self):
        if self.popen.poll() is None:
            self.popen.terminate()
            try:
                self.popen.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.popen.kill()
                self.popen.wait(timeout=3)
        for stream in (self.popen.stdin, self.popen.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


class LibClient(Output):
    """In-process ChatClient; unlike client.py it lets the test see the req_id it generated."""

    def __init__(self, name, role, port):
        super().__init__(name)
        self.client = ChatClient(name, role, "127.0.0.1", port, out=self.add)
        self.client.connect()
        self.client.start_receiver()

    def say(self, line):
        return self.client.handle_input(line)

    def stop(self):
        self.client.close()


class Stack:
    """Starts the processes of one scenario and guarantees they are all gone afterwards."""

    def __init__(self, certs):
        self.certs = certs
        self.plain_port = free_port()
        self.tls_port = free_port()
        self._owned = []
        self.server = None
        self.bot = None

    def _env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "LLM_", "FAKE_LLM_"))}
        env.update(
            PYTHONUNBUFFERED="1", LLM_PROVIDER="fake", FAKE_LLM_DELAY="0", FAKE_LLM_FAIL="0",
            LLM_TIMEOUT="20", BOT_HISTORY_SIZE="6",
            TLS_CERT=self.certs["cert"], TLS_KEY=self.certs["key"], TLS_CA=self.certs["ca"],
        )
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def _spawn(self, name, args, **env):
        proc = Proc(name, args, self._env(**env))
        self._owned.append(proc)
        return proc

    def start_server(self, bot_timeout=None):
        args = ["server.py", "--host", "127.0.0.1", "--port", str(self.plain_port),
                "--tls-port", str(self.tls_port)]
        if bot_timeout is not None:
            args += ["--bot-timeout", str(bot_timeout)]
        self.server = self._spawn("server", args)
        self.server.wait_for("(TLS) ouvindo")
        return self.server

    def start_bot(self, delay=0, llm_timeout=20):
        """The bot always connects over TLS."""
        args = ["bot.py", "--host", "127.0.0.1", "--port", str(self.tls_port), "--tls",
                "--ca", self.certs["ca"]]
        self.bot = self._spawn("bot", args, FAKE_LLM_DELAY=delay, LLM_TIMEOUT=llm_timeout)
        self.bot.wait_for("conectado ao servidor")
        return self.bot

    def client(self, name, role, tls=False):
        """A real client.py process. Returns once the server said WELCOME."""
        port = self.tls_port if tls else self.plain_port
        args = ["client.py", "--name", name, "--role", role, "--port", str(port)]
        if tls:
            args += ["--tls", "--ca", self.certs["ca"]]
        proc = self._spawn(name, args)
        proc.wait_for(f"Bem-vindo, {name}")
        return proc

    def lib_client(self, name, role):
        lib = LibClient(name, role, self.plain_port)
        self._owned.append(lib)
        return lib

    def close(self):
        for proc in reversed(self._owned):
            proc.stop()


@pytest.fixture
def stack(tls_certs):
    s = Stack(tls_certs)
    try:
        yield s
    finally:
        s.close()


def sync(sender, *receivers, marker):
    """Send a public marker and wait for every receiver to get it (everything sent earlier is in)."""
    sender.send(marker) if isinstance(sender, Proc) else sender.say(marker)
    for r in receivers:
        r.wait_for(marker)


# --------------------------------------------------------------------------- 1) LIST
def test_list_shows_three_humans_and_bot_with_correct_tls_flag(stack):
    stack.start_server()
    stack.start_bot()
    cos = stack.client("cos1", "cos")
    stack.client("tecnico1", "tecnico", tls=True)
    stack.client("eng1", "engenheiro")

    cos.send("/lista")
    cos.wait_for("Participantes online (4)")

    cos.wait_for("cos1 (cos) [texto claro]")
    cos.wait_for("tecnico1 (tecnico) [TLS]")
    cos.wait_for("eng1 (engenheiro) [texto claro]")
    cos.wait_for("bot (bot) [TLS]")


# --------------------------------------------------------------------------- 2) no blocking, private answer
def test_slow_bot_does_not_block_chat_and_answer_reaches_only_requester(stack):
    stack.start_server()
    stack.start_bot(delay=2)
    cos = stack.client("cos1", "cos")
    eng = stack.client("eng1", "engenheiro")
    tec = stack.lib_client("tecnico1", "tecnico")

    started = time.monotonic()
    request = tec.say("@bot codigo 2032?")
    assert request["type"] == "BOT_REQ" and request["req_id"]

    # While the bot is "thinking", the others keep talking and receive each other's messages.
    cos.send("alguem viu o inversor 7?")
    eng.wait_for("alguem viu o inversor 7?")
    eng.send("vi sim, esta em falha")
    cos.wait_for("vi sim, esta em falha")
    tec.wait_for("vi sim, esta em falha")
    assert time.monotonic() - started < 2.0
    assert not tec.seen("[FakeLLM]"), "the answer must not exist yet"

    answer = tec.wait_for("[FakeLLM]")
    assert answer.startswith("[privado] bot")
    assert request["req_id"][:8] in answer
    assert "codigo 2032?" in answer

    sync(tec, cos, eng, marker="fim-do-cenario-2")
    assert not cos.seen("[FakeLLM]") and not eng.seen("[FakeLLM]")
    assert stack.server.seen(f"(req {request['req_id'][:8]})")


# --------------------------------------------------------------------------- 3) continuation
def test_follow_up_question_carries_the_history(stack):
    stack.start_server()
    stack.start_bot()
    tec = stack.client("tecnico1", "tecnico")

    tec.send("@bot primeira pergunta")
    tec.wait_for("para: primeira pergunta (mensagens no contexto: 1)")
    tec.send("@bot segunda pergunta")
    # history = first question + first answer, plus the new question
    tec.wait_for("para: segunda pergunta (mensagens no contexto: 3)")


# --------------------------------------------------------------------------- 4) separate contexts
def test_each_user_has_their_own_history(stack):
    stack.start_server()
    stack.start_bot()
    tec = stack.client("tecnico1", "tecnico")
    eng = stack.client("eng1", "engenheiro")

    tec.send("@bot pergunta A1")
    tec.wait_for("para: pergunta A1 (mensagens no contexto: 1)")
    tec.send("@bot pergunta A2")
    tec.wait_for("para: pergunta A2 (mensagens no contexto: 3)")

    eng.send("@bot pergunta B1")
    eng.wait_for("para: pergunta B1 (mensagens no contexto: 1)")  # starts from scratch
    eng.send("@bot pergunta B2")
    eng.wait_for("para: pergunta B2 (mensagens no contexto: 3)")


# --------------------------------------------------------------------------- 5) abrupt disconnect
def test_killed_client_is_announced_as_connection_lost_and_server_keeps_working(stack):
    stack.start_server()
    cos = stack.client("cos1", "cos")
    tec = stack.client("tecnico1", "tecnico", tls=True)
    eng = stack.client("eng1", "engenheiro")

    cos.kill()
    tec.wait_for("cos1 saiu do chat (conexão perdida)")
    eng.wait_for("cos1 saiu do chat (conexão perdida)")

    # The server still serves the survivors and newcomers.
    eng.send("ainda estamos aqui")
    tec.wait_for("ainda estamos aqui")
    novo = stack.client("cos2", "cos")
    novo.send("/lista")
    novo.wait_for("Participantes online (3)")
    assert not novo.seen("cos1 (cos)")


# --------------------------------------------------------------------------- 6) LLM failure / timeouts
def test_llm_timeout_error_goes_only_to_the_requester(stack):
    stack.start_server()
    stack.start_bot(delay=3, llm_timeout=1)  # the LLM gives up after 1 s
    cos = stack.client("cos1", "cos")
    tec = stack.client("tecnico1", "tecnico")

    tec.send("@bot pergunta lenta")
    tec.wait_for("[erro]")
    tec.wait_for("A consulta à LLM demorou demais")

    sync(tec, cos, marker="fim-do-cenario-6a")
    assert not cos.seen("[erro]") and not cos.seen("demorou demais")


def test_server_timeout_answers_requester_and_drops_the_late_bot_reply(stack):
    stack.start_server(bot_timeout=1)
    stack.start_bot(delay=3, llm_timeout=30)  # the LLM is slow but does not time out by itself
    cos = stack.client("cos1", "cos")
    tec = stack.client("tecnico1", "tecnico")

    tec.send("@bot pergunta muito lenta")
    tec.wait_for("Tempo limite excedido na consulta ao bot.")
    assert stack.server.seen("expirou")

    # The bot answers at ~3 s: the server discards it, nobody sees it.
    stack.server.wait_for("Resposta do bot descartada")
    sync(tec, cos, marker="fim-do-cenario-6b")
    assert not tec.seen("[FakeLLM]") and not cos.seen("[FakeLLM]")
    assert not cos.seen("Tempo limite")


# --------------------------------------------------------------------------- 7) no bot
def test_request_without_bot_fails_immediately(stack):
    stack.start_server()
    cos = stack.client("cos1", "cos")
    tec = stack.client("tecnico1", "tecnico")

    started = time.monotonic()
    tec.send("@bot alguem ai?")
    tec.wait_for("Bot indisponível no momento.")
    assert time.monotonic() - started < 2.0

    sync(tec, cos, marker="fim-do-cenario-7")
    assert not cos.seen("Bot indisponível")


# --------------------------------------------------------------------------- 8) bot dies mid-request
def test_bot_crash_with_pending_request_returns_error_to_requester(stack):
    stack.start_server()
    bot = stack.start_bot(delay=10)
    cos = stack.client("cos1", "cos")
    tec = stack.client("tecnico1", "tecnico")

    tec.send("@bot pergunta pendente")
    stack.server.wait_for("BOT_REQ tecnico1 -> bot")  # the request is now pending on the server
    bot.kill()

    tec.wait_for("Bot desconectado.")
    # LEAVE and ERROR can arrive in either order; both humans learn that the bot left.
    cos.wait_for("bot saiu do chat (conexão perdida)")
    tec.wait_for("bot saiu do chat (conexão perdida)")

    sync(tec, cos, marker="fim-do-cenario-8")
    assert not cos.seen("Bot desconectado.")

    # With the bot gone, new requests fail fast.
    tec.send("@bot e agora?")
    tec.wait_for("Bot indisponível no momento.")

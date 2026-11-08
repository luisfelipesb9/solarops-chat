"""Tests for llm.py, bot.py and check_llm.py. No real server.py, no external network."""

import queue
import socket
import ssl
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx2
import openai
import pytest

import check_llm
import llm
from bot import ChatBot
from llm import FakeLLM, LLMError, LLMTimeout, OpenAILLM
from protocol import LineReader, make_msg, new_req_id, send_msg

WAIT = 5.0  # max seconds any test waits for a message


# ---------------------------------------------------------------- fake server


class FakeServer:
    """Minimal one-client server: answers the bot's HELLO and records what it sends."""

    def __init__(self, ssl_context=None):
        self._ssl_context = ssl_context
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(WAIT)
        self.port = self._listener.getsockname()[1]
        self.received = queue.Queue()
        self._conn = None
        self._send_lock = threading.Lock()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            conn, _ = self._listener.accept()
            conn.settimeout(WAIT)
            if self._ssl_context is not None:
                conn = self._ssl_context.wrap_socket(conn, server_side=True)
            self._conn = conn
            reader = LineReader(self._conn)
            while (msg := reader.read_msg()) is not None:
                self.received.put(msg)
                if msg["type"] == "HELLO":
                    send_msg(self._conn, make_msg("WELCOME", "server", msg["from"], "Bem-vindo, bot"), self._send_lock)
        except OSError:  # includes ssl.SSLError (handshake rejected) and closed sockets
            pass

    def next_msg(self):
        return self.received.get(timeout=WAIT)

    def ask(self, user, question, req_id=None):
        req_id = req_id or new_req_id()
        send_msg(self._conn, make_msg("BOT_REQ", user, "bot", question, req_id), self._send_lock)
        return req_id

    def close(self):
        for sock in (self._conn, self._listener):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


@pytest.fixture
def server():
    srv = FakeServer()
    yield srv
    srv.close()


@pytest.fixture
def start_bot(server):
    started = []

    def _start(llm_obj, **kwargs):
        bot = ChatBot(llm_obj, host="127.0.0.1", port=server.port, **kwargs)
        thread = threading.Thread(target=bot.run, daemon=True)
        thread.start()
        started.append(thread)
        hello = server.next_msg()
        assert hello["type"] == "HELLO"
        return bot

    yield _start
    server.close()  # EOF makes bot.run() return
    for thread in started:
        thread.join(timeout=WAIT)


class RoutedLLM:
    """Test LLM whose latency depends on the last question ('lenta' = slow)."""

    def __init__(self, slow=0.6):
        self.slow = slow

    def complete(self, messages):
        question = messages[-1]["content"]
        if "lenta" in question:
            time.sleep(self.slow)
        return f"resposta:{question}"


# ------------------------------------------------------------------ bot.py


def test_bot_sends_hello_as_bot(server):
    bot = ChatBot(FakeLLM(), port=server.port)
    thread = threading.Thread(target=bot.run, daemon=True)
    thread.start()
    hello = server.next_msg()
    server.close()
    thread.join(timeout=WAIT)
    assert hello["type"] == "HELLO"
    assert hello["from"] == "bot"
    assert hello["role"] == "bot"


def test_bot_works_over_tls(tls_certs):
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(tls_certs["cert"], tls_certs["key"])
    client_ctx = ssl.create_default_context(cafile=tls_certs["ca"])
    srv = FakeServer(ssl_context=server_ctx)
    bot = ChatBot(FakeLLM(), port=srv.port, ssl_context=client_ctx)
    thread = threading.Thread(target=bot.run, daemon=True)
    thread.start()
    try:
        assert srv.next_msg()["type"] == "HELLO"
        req_id = srv.ask("ana", "pergunta segura")
        resp = srv.next_msg()
        assert (resp["type"], resp["req_id"]) == ("BOT_RESP", req_id)
    finally:
        srv.close()
        thread.join(timeout=WAIT)


def test_response_has_same_req_id_and_goes_to_requester(server, start_bot):
    start_bot(FakeLLM())
    req_id = server.ask("ana", "O que é 2032?")
    resp = server.next_msg()
    assert resp["type"] == "BOT_RESP"
    assert resp["req_id"] == req_id
    assert resp["to"] == "ana"
    assert resp["from"] == "bot"
    assert "O que é 2032?" in resp["content"]


def test_history_is_isolated_between_users(server, start_bot):
    bot = start_bot(FakeLLM())
    server.ask("ana", "pergunta da ana")
    server.next_msg()
    req_id = server.ask("beto", "pergunta do beto")
    resp = server.next_msg()
    assert resp["to"] == "beto"
    assert "mensagens no contexto: 1" in resp["content"]  # ana's history not leaked
    assert bot.history_for("ana")[0]["content"] == "pergunta da ana"
    assert bot.history_for("beto")[0]["content"] == "pergunta do beto"
    assert req_id == resp["req_id"]


def test_follow_up_uses_user_history(server, start_bot):
    bot = start_bot(FakeLLM())
    server.ask("ana", "primeira")
    first = server.next_msg()
    server.ask("ana", "segunda")
    second = server.next_msg()
    assert "mensagens no contexto: 1" in first["content"]
    assert "mensagens no contexto: 3" in second["content"]
    assert [m["role"] for m in bot.history_for("ana")] == ["user", "assistant", "user", "assistant"]


def test_history_respects_deque_limit(server, start_bot):
    bot = start_bot(FakeLLM(), history_size=2)
    for question in ("q1", "q2", "q3"):
        server.ask("ana", question)
        last = server.next_msg()
    assert "mensagens no contexto: 3" in last["content"]  # 2 kept + the new question
    assert bot.history_for("ana") == [
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": last["content"]},
    ]


def test_slow_llm_returns_error_and_keeps_history(server, start_bot):
    bot = start_bot(FakeLLM(delay=0.3, timeout=0.05))
    req_id = server.ask("ana", "demora")
    resp = server.next_msg()
    assert resp["type"] == "ERROR"
    assert resp["req_id"] == req_id
    assert resp["to"] == "ana"
    assert resp["content"]  # pt-BR text for the user
    assert bot.history_for("ana") == []


def test_llm_error_returns_error_and_keeps_history(server, start_bot):
    bot = start_bot(FakeLLM(fail=True))
    req_id = server.ask("ana", "qualquer")
    resp = server.next_msg()
    assert (resp["type"], resp["req_id"], resp["to"]) == ("ERROR", req_id, "ana")
    assert bot.history_for("ana") == []


def test_unexpected_exception_becomes_generic_error(server, start_bot):
    class Broken:
        def complete(self, messages):
            raise RuntimeError("detalhe interno secreto")

    start_bot(Broken())
    req_id = server.ask("ana", "qualquer")
    resp = server.next_msg()
    assert (resp["type"], resp["req_id"]) == ("ERROR", req_id)
    assert "secreto" not in resp["content"]


def test_two_requests_are_processed_in_parallel(server, start_bot):
    start_bot(RoutedLLM(slow=0.6), workers=4)
    start = time.monotonic()
    slow_id = server.ask("ana", "pergunta lenta")
    fast_id = server.ask("beto", "pergunta rapida")
    first = server.next_msg()
    second = server.next_msg()
    elapsed = time.monotonic() - start
    assert first["req_id"] == fast_id  # fast one overtakes the slow one
    assert second["req_id"] == slow_id
    assert elapsed < 1.2


def test_log_has_req_id_and_user_but_not_content(server, start_bot, capsys):
    start_bot(FakeLLM())
    req_id = server.ask("ana", "texto-sigiloso")
    server.next_msg()
    deadline = time.monotonic() + WAIT
    out = capsys.readouterr().out
    while req_id[:8] not in out and time.monotonic() < deadline:
        time.sleep(0.05)
        out += capsys.readouterr().out
    assert req_id[:8] in out
    assert "ana" in out
    assert "texto-sigiloso" not in out


# ------------------------------------------------------------------ llm.py


def test_fake_llm_cites_last_question_and_message_count():
    answer = FakeLLM().complete([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                                 {"role": "user", "content": "ultima?"}])
    assert "ultima?" in answer
    assert "mensagens no contexto: 3" in answer


def test_fake_llm_raises_timeout_when_delay_exceeds_timeout():
    with pytest.raises(LLMTimeout):
        FakeLLM(delay=0.2, timeout=0.01).complete([{"role": "user", "content": "x"}])


def test_fake_llm_fail_raises_llm_error():
    with pytest.raises(LLMError):
        FakeLLM(fail=True).complete([{"role": "user", "content": "x"}])


def test_llm_timeout_is_an_llm_error():
    assert issubclass(LLMTimeout, LLMError)


def _req():
    return httpx2.Request("POST", "https://api.openai.com/v1/responses")


def _status_error(cls, status):
    resp = httpx2.Response(status, request=_req())
    return cls("detalhe com sk-SEGREDO", response=resp, body=None)


SDK_ERRORS = [
    (openai.APITimeoutError(request=_req()), LLMTimeout),
    (_status_error(openai.AuthenticationError, 401), LLMError),
    (_status_error(openai.RateLimitError, 429), LLMError),
    (_status_error(openai.NotFoundError, 404), LLMError),
    (_status_error(openai.BadRequestError, 400), LLMError),
    (openai.APIConnectionError(request=_req()), LLMError),
    (openai.APIError("falha sk-SEGREDO", _req(), body=None), LLMError),
]


class FakeClient:
    """Stands in for openai.OpenAI: records create() kwargs, returns or raises what it is told."""

    def __init__(self, result=None, error=None):
        self.calls = []
        self._result, self._error = result, error
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result


def make_openai_llm(client, **overrides):
    params = dict(model="m", api_key="sk-SEGREDO", timeout=5, max_output_tokens=50,
                  system_prompt="regras")
    params.update(overrides)
    obj = OpenAILLM(**params)
    obj._client = client
    return obj


@pytest.mark.parametrize("sdk_error,expected", SDK_ERRORS, ids=lambda v: type(v).__name__)
def test_openai_llm_maps_sdk_exceptions(sdk_error, expected):
    obj = make_openai_llm(FakeClient(error=sdk_error))
    with pytest.raises(expected) as info:
        obj.complete([{"role": "user", "content": "oi"}])
    assert type(info.value) is expected
    assert info.value.args[0]  # short pt-BR message
    assert "sk-SEGREDO" not in str(info.value)


def test_openai_llm_sends_responses_api_arguments():
    client = FakeClient(result=SimpleNamespace(output_text="ok"))
    obj = make_openai_llm(client)
    messages = [{"role": "user", "content": "oi"}]
    assert obj.complete(messages) == "ok"
    assert client.calls == [dict(model="m", instructions="regras", input=messages, max_output_tokens=50)]


def test_openai_llm_sends_reasoning_only_when_configured():
    client = FakeClient(result=SimpleNamespace(output_text="ok"))
    make_openai_llm(client, reasoning_effort="low").complete([{"role": "user", "content": "oi"}])
    assert client.calls[0]["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize("text", ["", "   ", None])
def test_openai_llm_empty_output_is_llm_error(text):
    obj = make_openai_llm(FakeClient(result=SimpleNamespace(output_text=text, status="incomplete")))
    with pytest.raises(LLMError):
        obj.complete([{"role": "user", "content": "oi"}])


def test_openai_llm_client_has_no_retries_and_given_timeout():
    obj = OpenAILLM("m", "sk-SEGREDO", 7, 50, "regras")
    assert obj._client.max_retries == 0
    assert obj._client.timeout == 7


def test_system_prompt_has_rules_and_knowledge():
    prompt = llm.load_system_prompt()
    assert "Não consta na base de conhecimento da usina." in prompt
    assert "NR-10" in prompt
    assert "SOLX-100" in prompt
    assert "2032" in prompt


def test_knowledge_base_states_it_is_illustrative():
    text = (Path(llm.__file__).parent / "knowledge" / "solar_om.md").read_text(encoding="utf-8")
    assert "ILUSTRATIV" in text.upper()
    assert "megôhmetro" in text.lower() or "megômetro" in text.lower() or "megohmetro" in text.lower()


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    for var in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_REASONING_EFFORT", "LLM_PROVIDER", "LLM_TIMEOUT",
                "LLM_MAX_OUTPUT_TOKENS", "FAKE_LLM_DELAY", "FAKE_LLM_FAIL"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_build_llm_fake_provider(clean_env):
    clean_env.setenv("LLM_PROVIDER", "fake")
    clean_env.setenv("FAKE_LLM_FAIL", "1")
    built = llm.build_llm_from_env()
    assert isinstance(built, FakeLLM)
    with pytest.raises(LLMError):
        built.complete([{"role": "user", "content": "x"}])


def test_build_llm_openai_defaults(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "sk-teste")
    built = llm.build_llm_from_env()
    assert isinstance(built, OpenAILLM)
    assert built.model == "gpt-5.4-nano"
    assert built.reasoning_effort is None
    assert built.max_output_tokens == 600
    assert built.timeout == 20


def test_build_llm_openai_reads_overrides(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "sk-teste")
    clean_env.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    clean_env.setenv("OPENAI_REASONING_EFFORT", "low")
    built = llm.build_llm_from_env()
    assert (built.model, built.reasoning_effort) == ("gpt-5.4-mini", "low")


def test_build_llm_without_key_fails_clearly(clean_env):
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        llm.build_llm_from_env()


def test_build_llm_unknown_provider(clean_env):
    clean_env.setenv("LLM_PROVIDER", "outro")
    with pytest.raises(LLMError, match="LLM_PROVIDER"):
        llm.build_llm_from_env()


# ------------------------------------------------------------- check_llm.py


@pytest.fixture
def clean_check_env(monkeypatch):
    monkeypatch.setattr(check_llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return monkeypatch


def test_check_llm_without_key_exits_nonzero(clean_check_env, capsys):
    assert check_llm.main() != 0
    assert "OPENAI_API_KEY" in capsys.readouterr().out


def test_check_llm_never_prints_the_key(clean_check_env, capsys):
    clean_check_env.setenv("OPENAI_API_KEY", "sk-SEGREDO")

    class Client:
        def __init__(self, **kwargs):
            self.models = SimpleNamespace(list=self._fail)

        def _fail(self):
            raise _status_error(openai.AuthenticationError, 401)

    clean_check_env.setattr(check_llm, "OpenAI", Client)
    assert check_llm.main() != 0
    captured = capsys.readouterr()
    assert "sk-SEGREDO" not in captured.out + captured.err

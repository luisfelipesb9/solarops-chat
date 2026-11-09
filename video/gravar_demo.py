"""Executa a demonstração ao vivo usada no vídeo e grava as transcrições reais.

Sobe servidor (GUI), bot (OpenAI real, TLS) e 3 clientes como processos reais, roda os
cenários da seção 8 do enunciado e, em cada CHECKPOINT, espera o arquivo
video/build/go_<nome> aparecer (tempo para capturar a janela da GUI).

Uso: .venv/bin/python video/gravar_demo.py
Saída: video/build/demo.json com as linhas de cada terminal e o tempo de cada uma.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "video", "build")
PY = os.path.join(ROOT, ".venv", "bin", "python")
T0 = time.monotonic()
LOG = {}  # nome do terminal -> [(t, texto)]
LOCK = threading.Lock()


def now():
    return round(time.monotonic() - T0, 2)


def record(term, text):
    with LOCK:
        LOG.setdefault(term, []).append((now(), text))


def spawn(term, args, env_extra=None):
    env = {**os.environ, "PYTHONUNBUFFERED": "1", **(env_extra or {})}
    proc = subprocess.Popen(
        [PY, *args], cwd=ROOT, env=env, text=True, bufsize=1,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    def pump():
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            while line.startswith("> "):  # prompt do input() sem TTY
                line = line[2:]
            if line.strip() and line.strip() != ">":
                record(term, line)

    threading.Thread(target=pump, daemon=True).start()
    record(term, "$ " + " ".join(["python", *args]))
    return proc


def type_(term, proc, text):
    record(term, "> " + text)
    proc.stdin.write(text + "\n")
    proc.stdin.flush()


def checkpoint(name, timeout=180):
    flag = os.path.join(BUILD, f"go_{name}")
    print(f"CHECKPOINT {name}", flush=True)
    deadline = time.monotonic() + timeout
    while not os.path.exists(flag) and time.monotonic() < deadline:
        time.sleep(0.2)
    record("_marks", name)


def wait_for(term, needle, timeout=30, since=None):
    """Espera `needle` em uma linha nova do terminal (a partir do índice `since`)."""
    with LOCK:
        start = len(LOG.get(term, [])) if since is None else since
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with LOCK:
            lines = LOG.get(term, [])[start:]
        if any(needle in text for _, text in lines):
            return True
        time.sleep(0.1)
    print(f"AVISO: '{needle}' não apareceu em {term}", flush=True)
    return False


def mark(term):
    with LOCK:
        return len(LOG.get(term, []))


def main():
    os.makedirs(BUILD, exist_ok=True)
    for f in os.listdir(BUILD):
        if f.startswith("go_"):
            os.remove(os.path.join(BUILD, f))

    server = spawn("servidor", ["server.py", "--gui"])
    time.sleep(2.5)
    checkpoint("gui_vazia")

    bot = spawn("bot", ["bot.py", "--tls"])
    wait_for("bot", "conectado ao servidor", since=0)
    ana = spawn("ana", ["client.py", "--name", "ana", "--role", "cos"])
    time.sleep(0.6)
    rui = spawn("rui", ["client.py", "--name", "rui", "--role", "tecnico", "--tls"])
    time.sleep(0.6)
    eva = spawn("eva", ["client.py", "--name", "eva", "--role", "engenheiro"])
    time.sleep(1.0)
    type_("rui", rui, "/lista")
    time.sleep(1.5)
    checkpoint("gui_conectados")

    # Cenário: chat continua enquanto o bot consulta a LLM; resposta privada
    type_("ana", ana, "INV-07 do bloco B caiu. Quem está perto?")
    time.sleep(1.2)
    m = mark("rui")
    type_("rui", rui, "@bot o inversor SOLX-100 mostra o código 2032, o que significa?")
    time.sleep(0.4)
    type_("eva", eva, "Rui, não religa antes de medir a isolação.")
    time.sleep(0.4)
    type_("rui", rui, "Ok, chego em 10 minutos.")
    wait_for("rui", "[privado] bot", 30, since=m)
    time.sleep(1.0)
    checkpoint("gui_bot")

    # Cenário: pergunta de continuação e contextos separados
    m = mark("rui")
    type_("rui", rui, "@bot e qual EPI eu uso pra essa medição?")
    wait_for("rui", "[privado] bot", 30, since=m)
    time.sleep(1.0)
    m = mark("eva")
    type_("eva", eva, "@bot qual foi o código de falha que eu perguntei antes?")
    wait_for("eva", "[privado] bot", 30, since=m)
    time.sleep(1.0)
    type_("ana", ana, "/w eva Libera o religamento depois da medição?")
    time.sleep(1.5)
    checkpoint("gui_contexto")

    # Cenário: desconexão abrupta (processo da ana morto)
    m = mark("eva")
    ana.kill()
    record("ana", "[processo encerrado com kill -9]")
    wait_for("eva", "conexão perdida", 10, since=m)
    time.sleep(1.0)
    checkpoint("gui_queda")

    # Cenário: bot fora do ar e tempo limite da LLM
    bot.send_signal(signal.SIGINT)
    bot.wait(timeout=10)
    time.sleep(1.0)
    type_("rui", rui, "@bot o que significa o código 2041?")
    time.sleep(1.5)
    m = mark("bot")
    bot2 = spawn("bot", ["bot.py", "--tls"], {"LLM_TIMEOUT": "0.001"})
    wait_for("bot", "conectado ao servidor", since=m)
    time.sleep(1.0)
    m = mark("rui")
    type_("rui", rui, "@bot o que significa o código 2041?")
    wait_for("rui", "pedido", 20, since=m)
    time.sleep(1.0)
    type_("eva", eva, "O chat continua normal durante a falha do bot.")
    time.sleep(1.5)
    checkpoint("gui_timeout")

    for term, proc in (("rui", rui), ("eva", eva)):
        type_(term, proc, "/sair")
    time.sleep(1.0)
    bot2.send_signal(signal.SIGINT)
    server.send_signal(signal.SIGINT)
    for proc in (bot2, server, rui, eva):
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    time.sleep(0.5)

    with open(os.path.join(BUILD, "demo.json"), "w", encoding="utf-8") as fh:
        json.dump(LOG, fh, ensure_ascii=False, indent=1)
    print("DEMO_OK", flush=True)


if __name__ == "__main__":
    sys.exit(main())

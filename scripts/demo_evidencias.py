"""Roteiro automatizado de evidências: roda contra o servidor e o bot já em execução.

Uso: .venv/bin/python scripts/demo_evidencias.py
Mostra: chat não bloqueia durante a consulta ao bot, resposta privada, continuação,
contextos separados e a mensagem conhecida usada na comparação do Wireshark.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tls_config  # noqa: E402
from client import ChatClient  # noqa: E402

T0 = time.monotonic()


def stamp(text):
    print(f"[{time.monotonic() - T0:5.2f}s] {text}")


def connect(name, role, tls):
    inbox = []
    ctx = tls_config.client_context() if tls else None
    client = ChatClient(name, role, port=5051 if tls else 5050, ssl_context=ctx, out=inbox.append)
    client.connect()
    client.start_receiver()
    stamp(f"{name} conectado ({'TLS 5051' if tls else 'texto claro 5050'})")
    return client, inbox


def wait_for(inbox, start, needle, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for line in inbox[start:]:
            if needle in line:
                return line
        time.sleep(0.05)
    return None


def ask(client, inbox, question):
    start = len(inbox)
    stamp(f"{client.name}> @bot {question}")
    client.handle_input(f"@bot {question}")
    return start


def main():
    ana, ana_in = connect("ana_cos", "cos", tls=False)
    rui, rui_in = connect("rui_tec", "tecnico", tls=True)
    eva, eva_in = connect("eva_eng", "engenheiro", tls=False)

    start = ask(rui, rui_in, "o inversor SOLX-100 mostra o código 2032, o que significa?")
    ana.handle_input("teste wireshark 123 (texto claro)")
    stamp("ana_cos> teste wireshark 123 (texto claro)")
    rui.handle_input("teste wireshark 456 (cifrado)")
    stamp("rui_tec> teste wireshark 456 (cifrado)")
    stamp("eva_eng recebeu: " + str(wait_for(eva_in, 0, "456")))
    stamp("rui_tec recebeu: " + str(wait_for(rui_in, 0, "123")))
    stamp("(chat entregue enquanto o bot ainda processa)")
    stamp("rui_tec recebeu: " + str(wait_for(rui_in, start, "bot (pedido")))

    start = ask(rui, rui_in, "e qual EPI eu uso pra essa medição?")
    stamp("rui_tec recebeu: " + str(wait_for(rui_in, start, "bot (pedido")))

    start = ask(eva, eva_in, "qual foi o código de falha que eu perguntei antes?")
    stamp("eva_eng recebeu: " + str(wait_for(eva_in, start, "bot (pedido")))

    leaked = [line for line in ana_in + eva_in if "2032" in line and "bot (pedido" in line]
    stamp(f"respostas do bot sobre o 2032 vistas por ana_cos/eva_eng: {len(leaked)} (esperado 0)")

    time.sleep(float(os.getenv("DEMO_HOLD", "0")))  # mantém conectados para print da GUI
    for client in (ana, rui, eva):
        client.handle_input("/sair")
    time.sleep(0.3)


if __name__ == "__main__":
    main()

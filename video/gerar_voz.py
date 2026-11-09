"""Gera a narração de cada batida do roteiro com o TTS da OpenAI (cache por hash do texto).

Uso: .venv/bin/python video/gerar_voz.py
Saída: video/build/audio/<id>.mp3
"""

import hashlib
import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "video"))
from roteiro import BEATS  # noqa: E402

OUT = os.path.join(ROOT, "video", "build", "audio")
MODEL = "gpt-4o-mini-tts"
VOICE = "onyx"
INSTRUCTIONS = (
    "Fale em português do Brasil, com sotaque brasileiro natural. Tom de apresentação técnica de um trabalho "
    "acadêmico: claro, calmo, confiante e didático, ritmo moderado, pausas curtas entre as frases. "
    "Pronuncie siglas em inglês como um desenvolvedor brasileiro (TLS: tê-éle-ésse; JSON: djêison; LLM: éle-éle-ême)."
)


def main():
    load_dotenv(os.path.join(ROOT, ".env"))
    client = OpenAI(max_retries=2, timeout=120)
    os.makedirs(OUT, exist_ok=True)
    cache_path = os.path.join(OUT, "cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for beat in BEATS:
        key = hashlib.sha256(f"{MODEL}|{VOICE}|{INSTRUCTIONS}|{beat['text']}".encode()).hexdigest()
        path = os.path.join(OUT, f"{beat['id']}.mp3")
        if cache.get(beat["id"]) == key and os.path.exists(path):
            print("cache", beat["id"])
            continue
        resp = client.audio.speech.create(
            model=MODEL, voice=VOICE, input=beat["text"], instructions=INSTRUCTIONS, response_format="mp3",
        )
        with open(path, "wb") as fh:
            fh.write(resp.content)
        cache[beat["id"]] = key
        json.dump(cache, open(cache_path, "w"), indent=1)
        print("ok", beat["id"], len(resp.content))


if __name__ == "__main__":
    main()

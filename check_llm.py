"""Checks the OpenAI setup: key, model, a real call and timeout handling (SPEC 5.7)."""

import os
import sys
import time

import openai
from dotenv import load_dotenv
from openai import OpenAI

from llm import DEFAULT_MODEL, LLMError, LLMTimeout, OpenAILLM, to_llm_error


def fail(text):
    print(f"FALHA: {text}")
    return 1


def main() -> int:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return fail("OPENAI_API_KEY ausente. Copie .env.example para .env e preencha a chave.")
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    effort = os.getenv("OPENAI_REASONING_EFFORT") or None
    client = OpenAI(api_key=api_key, timeout=20, max_retries=0)

    # 1. the configured model must be available to this key
    try:
        available = sorted(m.id for m in client.models.list())
    except openai.OpenAIError as exc:
        return fail(f"não foi possível listar modelos: {to_llm_error(exc)}")
    if model not in available:
        cheap = [m for m in available if "nano" in m or "mini" in m]
        return fail(f"modelo '{model}' indisponível. Opções baratas: {', '.join(cheap) or 'nenhuma encontrada'}")
    print(f"OK modelo '{model}' disponível")

    # 2. one short real call
    llm = OpenAILLM(model, api_key, 20, 200, "Responda em uma palavra.", effort)
    started = time.monotonic()
    try:
        resp = llm.request([{"role": "user", "content": "Diga apenas: ok"}])
    except LLMError as exc:
        return fail(str(exc))
    latency = time.monotonic() - started
    if not (resp.output_text or "").strip():
        return fail("a LLM respondeu sem texto (aumente LLM_MAX_OUTPUT_TOKENS ou reduza o raciocínio)")
    print(f"OK chamada real: modelo={model} latência={latency:.2f}s usage={getattr(resp, 'usage', None)}")

    # 3. an impossible timeout must surface as LLMTimeout
    try:
        OpenAILLM(model, api_key, 0.001, 50, "x").complete([{"role": "user", "content": "oi"}])
    except LLMTimeout:
        print("OK timeout de 0,001 s convertido em LLMTimeout")
    except LLMError as exc:
        return fail(f"esperava LLMTimeout, veio: {exc}")
    else:
        return fail("a chamada com timeout de 0,001 s não estourou o tempo")
    return 0


if __name__ == "__main__":
    sys.exit(main())

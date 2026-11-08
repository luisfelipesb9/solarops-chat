# SolarOps Chat: atalhos de desenvolvimento e demo. Rode 'make help'.
PYTHON ?= python3.14
PY := .venv/bin/python
NAME ?=
ROLE ?=
TLS ?=

.DEFAULT_GOAL := help
.PHONY: help setup certs test server server-console bot bot-fake client check-llm clean

help: ## Lista os comandos disponíveis
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-15s %s\n", $$1, $$2}'

setup: ## Cria o .venv e instala as dependências
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -r requirements.txt

certs: ## Gera CA e certificado do servidor em certs/ (idempotente)
	bash certs/gen_certs.sh

test: ## Roda todos os testes
	$(PY) -m pytest -q

server: ## Servidor com interface gráfica (portas 5000 claro e 5001 TLS)
	$(PY) server.py --gui

server-console: ## Servidor em modo console
	$(PY) server.py

bot: ## Bot com a OpenAI, conectado via TLS
	$(PY) bot.py --tls

bot-fake: ## Bot com FakeLLM (sem chave), conectado via TLS
	LLM_PROVIDER=fake $(PY) bot.py --tls

client: ## Cliente: make client NAME=ana ROLE=cos [TLS=1]
	@test -n "$(NAME)" -a -n "$(ROLE)" || { echo "uso: make client NAME=<nome> ROLE=<cos|tecnico|engenheiro> [TLS=1]"; exit 1; }
	$(PY) client.py --name $(NAME) --role $(ROLE) $(if $(TLS),--tls)

check-llm: ## Testa a chave, o modelo e o timeout da OpenAI
	$(PY) check_llm.py

clean: ## Remove caches do Python e do pytest (mantém .venv e certs)
	find . -path ./.venv -prune -o -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache

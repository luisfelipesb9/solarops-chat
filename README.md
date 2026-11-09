# SolarOps Chat

Chat cliente-servidor para a equipe de operação e manutenção (O&M) de usinas solares: o centro de operação (COS), os técnicos de campo e o engenheiro responsável conversam em tempo real, e um bot consulta uma LLM para tirar dúvidas de procedimento com base na base de conhecimento da usina (`knowledge/solar_om.md`).

Trabalho prático de Sistemas Distribuídos II (Unimontes). O contrato técnico completo está em [`SPEC.md`](SPEC.md).

## Arquitetura

1. `server.py`: servidor TCP com uma thread de accept por porta (5050 em claro, 5051 com TLS) e uma thread por cliente.
2. `server_gui.py`: interface Tkinter do servidor com participantes, mensagens, eventos e pedidos pendentes ao bot.
3. `client.py`: cliente humano de terminal; uma thread recebe mensagens enquanto a principal lê o teclado.
4. `bot.py`: cliente bot em processo separado, conectado por socket; cada pergunta vai para um pool de threads que chama a LLM (`llm.py`, OpenAI Responses API).
5. `protocol.py`: protocolo de aplicação, um JSON por linha; `tls_config.py`: contextos TLS com CA própria.

## Pré-requisitos

- Python 3.14 (`brew install python@3.14` no macOS).
- Tkinter para a interface do servidor: `brew install python-tk@3.14` no macOS.
- `openssl` no PATH (para gerar os certificados).
- Uma chave da OpenAI para o bot real. Sem chave, use `make bot-fake`.
- As portas padrão são 5050 (texto claro) e 5051 (TLS). A porta 5000 não é usada porque o macOS a reserva para o receptor AirPlay.

## Passo a passo

```bash
make setup                 # cria o .venv e instala openai, python-dotenv e pytest
make certs                 # gera certs/ca.crt, certs/server.crt e as chaves
cp .env.example .env       # depois cole sua OPENAI_API_KEY no .env
make check-llm             # confere chave, modelo, latência e timeout
make test                  # roda a suíte de testes

make server                # terminal 1: servidor com interface gráfica
make bot                   # terminal 2: bot (TLS, porta 5051)
make client NAME=ana   ROLE=cos        TLS=1   # terminal 3
make client NAME=bruno ROLE=tecnico    TLS=1   # terminal 4
make client NAME=carla ROLE=engenheiro          # terminal 5 (sem TLS, porta 5050)
```

Rode `make help` para ver todos os comandos. Papéis válidos: `cos`, `tecnico`, `engenheiro`.

### Comandos do cliente

| Digite | Efeito |
|---|---|
| texto simples | mensagem para todos os humanos |
| `@bot <pergunta>` | pergunta privada ao bot |
| `/w <nome> <msg>` | mensagem direta |
| `/lista` | participantes conectados |
| `/sair` | sai do chat |
| `/ajuda` | mostra a ajuda |

## Roteiro da demonstração

1. **Três humanos e um bot.** Suba servidor, bot e os três clientes. A interface do servidor mostra os quatro participantes, o papel e se a conexão usa TLS.
2. **Chat simultâneo durante a consulta.** Ana envia `@bot o inversor SOLX-100 mostrou o código 2032, o que fazer?`. Enquanto o bot processa, Bruno e Carla continuam trocando mensagens. A resposta chega só para Ana, marcada como privada e com o `req_id` da pergunta.
3. **Pergunta de continuação.** Ana envia `@bot e depois disso, posso religar?`. O bot usa o histórico da Ana (até 6 mensagens, 3 trocas) e lembra que a liberação do engenheiro é obrigatória (NR-10).
4. **Contextos separados.** Bruno envia `@bot e depois disso, posso religar?`. Como Bruno não tem histórico, o bot não sabe do que se trata: o contexto da Ana não vaza.
5. **Desconexão.** Feche um cliente com `/sair` (aparece `saiu`) e feche a janela de outro terminal para simular uma queda (aparece `conexão perdida`). O servidor registra o evento e atualiza a lista.
6. **Falha ou tempo limite na LLM.**
   - Timeout na LLM (o bot responde com erro): pare o bot e suba `LLM_TIMEOUT=3 FAKE_LLM_DELAY=5 make bot-fake`. Faça uma pergunta; após 3 s chega um `ERROR` com o mesmo `req_id`.
   - Timeout no servidor: suba o servidor com `.venv/bin/python server.py --gui --bot-timeout 5` e o bot com `LLM_TIMEOUT=60 FAKE_LLM_DELAY=10 make bot-fake`. Após 5 s o servidor responde `Tempo limite excedido na consulta ao bot.`; a resposta atrasada é descartada e aparece nos eventos.
   - Falha simulada: `FAKE_LLM_FAIL=1 make bot-fake`.
   - Bot fora do ar: pare o bot e pergunte algo; a resposta é `Bot indisponível no momento.`

## Criptografia

### Quais enlaces são cifrados

| Enlace | Porta | Proteção |
|---|---|---|
| Cliente humano com `TLS=1` ↔ servidor | 5051 | TLS 1.2 ou superior (na prática TLS 1.3) |
| Bot ↔ servidor (`make bot` usa `--tls`) | 5051 | TLS |
| Cliente humano sem `TLS=1` ↔ servidor | 5050 | **em claro**, mantido só como referência para o Wireshark |
| Bot ↔ OpenAI | 443 | HTTPS, feito pela biblioteca `openai` |

A decifragem acontece nas pontas: no servidor, dentro da thread de cada cliente (o `ssl.SSLSocket` decifra no `recv`), e no cliente ou no bot, na thread receptora. O servidor decifra, processa a mensagem e cifra de novo para cada destinatário TLS. Uma mensagem de um cliente TLS para um cliente na porta 5050 sai em claro nesse segundo enlace: por isso a porta 5050 é só para a comparação.

### Certificados e validação

- `certs/gen_certs.sh` cria a CA própria `SolarOps CA` (`ca.key`, `ca.crt`, RSA 2048, 365 dias) e o certificado do servidor (`server.key`, `server.crt`) com `CN=localhost`, SAN `DNS:localhost, IP:127.0.0.1` e uso `serverAuth`, assinado pela CA.
- O script é idempotente: reaproveita a CA existente. Para recriar tudo: `bash certs/gen_certs.sh --force`.
- As chaves (`*.key`) ficam com permissão 600 e nunca vão para o git.
- O cliente valida explicitamente a CA configurada: `tls_config.client_context()` usa `create_default_context(cafile=certs/ca.crt)`, com `CERT_REQUIRED`, `check_hostname=True` e mínimo TLS 1.2. Um servidor com certificado de outra CA é rejeitado (`SSLCertVerificationError`).
- Os caminhos vêm de `TLS_CERT`, `TLS_KEY` e `TLS_CA` (veja `.env.example`). Conferência manual: `openssl verify -CAfile certs/ca.crt certs/server.crt`.

### Comparação no Wireshark

1. Capture na interface de loopback (`lo0` no macOS).
2. Conecte um cliente sem TLS e outro com TLS e envie a mesma mensagem conhecida, por exemplo `teste wireshark 123`.
3. Filtro `tcp.port==5050`: em *Follow TCP Stream* aparece o JSON inteiro (`"type": "MSG"`, `"from"`, `"content": "teste wireshark 123"`).
4. Filtro `tcp.port==5051`: aparecem o *Client Hello* (com SNI `localhost`), o *Server Hello* e depois só registros `Application Data` com bytes ilegíveis. O conteúdo fica protegido porque é cifrado com chaves de sessão negociadas no handshake (ECDHE) e autenticado (AEAD); quem só observa a rede não tem essas chaves.

## Protocolo (resumo)

Uma mensagem JSON UTF-8 por linha, terminada em `\n`, com no máximo 65536 bytes. Campos sempre presentes: `type`, `from`, `to`, `content`, `req_id`, `ts`, `role`. O servidor sobrescreve `from` com o nome da sessão.

| `type` | Sentido | Uso |
|---|---|---|
| `HELLO` | cliente → servidor | primeira mensagem: nome e papel |
| `WELCOME` | servidor → cliente | entrada aceita |
| `MSG` | ambos | chat público (`to:"*"`), só entre humanos |
| `DM` | ambos | mensagem direta (`to:<nome>`) |
| `BOT_REQ` | cliente → servidor → bot | pergunta ao bot, com `req_id` gerado pelo cliente |
| `BOT_RESP` | bot → servidor → solicitante | resposta privada, mesmo `req_id` |
| `ERROR` | servidor ou bot → cliente | erro em pt-BR; carrega o `req_id` quando é de uma consulta |
| `JOIN` / `LEAVE` | servidor → humanos | entrada e saída (`saiu` ou `conexão perdida`) |
| `LIST` | ambos | pedido e lista de participantes (`content` é um array JSON) |

## Variáveis de ambiente

Todas estão documentadas em `.env.example` (modelo, timeouts, tamanho do histórico, provedor `openai` ou `fake` e caminhos TLS). A chave da OpenAI fica só no `.env`, que está no `.gitignore`.

## Evidências e relatório

| Comando | O que faz |
|---|---|
| `make demo` | Roda `scripts/demo_evidencias.py` contra o servidor e o bot já em execução: chat durante a consulta, continuação, contextos separados e mensagens conhecidas para o Wireshark |
| `sudo tcpdump -i lo0 -w evidencias/captura_5050_5051.pcap 'tcp port 5050 or tcp port 5051'` | Captura o loopback durante o `make demo` (Ctrl+C para parar) |
| `make evidencias` | Extrai do pcap, com `tshark`, o fluxo em claro, os pacotes TLS e a busca pelas mensagens conhecidas |
| `make relatorio` | Gera `docs/Trabalho Prático - SD2.docx` e o PDF a partir de `evidencias/` (requer Node.js e LibreOffice) |
| `make entrega` | Empacota o código versionado em `entrega/SolarOps_SD2_codigo.zip`, sem `.env` e sem chaves privadas |

### Vídeo de demonstração

`video/SolarOps_Chat_SD2.mp4` (9 min, 1080p, narração em pt-BR e legenda `.srt`) mostra uma execução real com o bot OpenAI: 3 humanos e o bot, chat durante a consulta, resposta privada, continuação, contextos separados, desconexão, bot fora do ar, tempo limite da LLM e a comparação no Wireshark.

| Etapa | Comando |
|---|---|
| Demo ao vivo roteirizada (grava as transcrições e pausa para os prints da GUI) | `.venv/bin/python video/gravar_demo.py` |
| Narração (TTS da OpenAI, `gpt-4o-mini-tts`) | `make voz` |
| Renderização e montagem (Pillow + ffmpeg) | `make video` |

O texto narrado está em `video/roteiro.py`; o roteiro para gravação própria está em `docs/roteiro_video.md`.

## Testes

```bash
make test
```

Os testes usam portas efêmeras, `FakeLLM` e certificados gerados em diretório temporário; não acessam a rede externa.

# SolarOps Chat: contrato técnico (SPEC)

Chat cliente-servidor para a equipe de O&M de usinas solares: COS, técnicos de campo e engenheiro. Inclui um bot que consulta uma LLM.
Trabalho prático de Sistemas Distribuídos II (Unimontes). Este arquivo é **a fonte da verdade**: nenhum módulo inventa campo, tipo de mensagem, flag ou variável de ambiente fora daqui.

## 1. Regras gerais
- Python 3.14, executado sempre pelo venv `.venv/bin/python`.
- Rede usa só a biblioteca padrão: `socket`, `threading`, `ssl`, `queue`, `json`, `tkinter`.
- Dependências externas permitidas: `openai`, `python-dotenv` e `pytest`. Nenhuma outra.
- Código, identificadores e comentários em inglês. Texto mostrado ao usuário (UI, mensagens de erro do protocolo) em pt-BR.
- Proibido: framework web, banco de dados, asyncio, bibliotecas de chat prontas.
- Nenhuma credencial no código, em log ou em teste. A chave vem só do `.env`.

## 2. Arquivos e donos
| Arquivo | Dono |
|---|---|
| `SPEC.md`, `protocol.py`, `tests/test_protocol.py`, `tests/conftest.py` | Contrato (não editar sem atualizar o SPEC) |
| `server.py`, `server_gui.py`, `tests/test_server.py` | Agente Servidor |
| `client.py`, `tests/test_client.py` | Agente Cliente |
| `llm.py`, `bot.py`, `check_llm.py`, `knowledge/solar_om.md`, `tests/test_bot.py` | Agente Bot/LLM |
| `tls_config.py`, `certs/gen_certs.sh`, `requirements.txt`, `.env.example`, `.gitignore`, `Makefile`, `README.md`, `tests/test_tls.py` | Agente Segurança/DevOps |
| `tests/test_e2e.py`, `tests/test_stress.py` | Agente Integrador |

## 3. Protocolo de aplicação (`protocol.py`, já implementado)
**Transporte:** TCP, uma mensagem JSON UTF-8 por linha, terminada em `\n`. O tamanho máximo da linha é `MAX_LINE = 65536` bytes. Uma linha maior encerra a conexão com `ProtocolError`.

**Campos (sempre presentes, todos `str`):**

| Campo | Significado |
|---|---|
| `type` | Um de `HELLO WELCOME MSG DM BOT_REQ BOT_RESP ERROR JOIN LEAVE LIST` |
| `from` | Remetente. O servidor **sobrescreve** com o nome da sessão (anti-spoofing). O servidor usa `"server"`. |
| `to` | `"*"` (todos), um nome de usuário, ou `"bot"` |
| `content` | Texto da mensagem. Em `LIST`, é um JSON (array) serializado como string. |
| `req_id` | uuid4 hex que correlaciona `BOT_REQ`, `BOT_RESP` e `ERROR`. `""` quando não se aplica. |
| `ts` | ISO 8601 UTC, preenchido por `make_msg` |
| `role` | `cos`, `tecnico`, `engenheiro`, `bot` ou `""` |

**API pública de `protocol.py`:**
- `make_msg(type_, from_="", to="*", content="", req_id="", role="") -> dict`
- `validate(msg) -> dict` (lança `ProtocolError`)
- `encode(msg) -> bytes` e `decode(line: bytes) -> dict`
- `send_msg(sock, msg, lock=None)`: faz `sendall` dentro do `lock`, se for passado
- `LineReader(sock).read_msg() -> dict | None` (devolve `None` em EOF)
- `new_req_id()`
- `valid_name(name) -> bool`, com regex `^[A-Za-z0-9_-]{1,20}$`
- Constantes: `TYPES`, `ROLES`, `HUMAN_ROLES`, `BOT_NAME = "bot"`, `SERVER_NAME = "server"`, `MAX_LINE`

### 3.1 Fluxos
1. **Handshake.** A primeira mensagem do cliente é `HELLO{from:nome, role}`.
   - O servidor responde `WELCOME{to:nome, content:"Bem-vindo, <nome>"}`, depois envia `LIST` ao novo cliente e faz broadcast de `JOIN{from:nome, role}` para os humanos já conectados.
   - O servidor responde `ERROR` e fecha a conexão se:
     - o nome é inválido ou duplicado;
     - o papel é inválido;
     - um segundo bot tenta entrar;
     - a primeira mensagem não é `HELLO`;
     - o HELLO não chega em 10 s.
   - `role:"bot"` exige `from:"bot"`. Um humano não pode usar o nome `bot`.
2. **MSG** (`to:"*"`): o servidor repassa a todos os **humanos** menos o remetente. O bot não recebe o chat público.
3. **DM** (`to:<nome>`): entregue só ao destinatário. Se o destinatário não existir, o remetente recebe `ERROR`.
4. **BOT_REQ** (`to:"bot"`, `req_id` obrigatório e gerado pelo cliente):
   - Sem bot conectado: o servidor devolve na hora `ERROR{to:remetente, req_id, content:"Bot indisponível no momento."}`.
   - Com bot: o servidor encaminha ao bot com `from:<remetente>` e registra `pending[req_id] = (remetente, deadline)`, com deadline em `BOT_TIMEOUT` s.
   - Se o prazo vencer, o servidor envia ao remetente `ERROR{req_id, content:"Tempo limite excedido na consulta ao bot."}` e descarta o pendente. Uma resposta que chegar depois é descartada e registrada como evento.
5. **BOT_RESP / ERROR vindos do bot** (`from:"bot"`, `to:<solicitante>`, `req_id`):
   - Só são aceitos se `req_id` estiver pendente e `to` for o solicitante registrado.
   - O servidor entrega **somente** ao solicitante (resposta privada) e remove o pendente.
6. **LIST:** o cliente envia `LIST{}` e recebe `LIST{content: json.dumps([{"name","role","tls"}...])}`.
7. **LEAVE:**
   - Saída voluntária: o cliente envia `LEAVE`. O servidor fecha a conexão e faz broadcast de `LEAVE{from:nome, content:"saiu"}`.
   - Queda abrupta (EOF, `ConnectionResetError`, `ssl.SSLError` ou `ProtocolError`): o broadcast é `LEAVE{content:"conexão perdida"}`.
   - Se quem saiu foi o bot, cada pendente recebe `ERROR{content:"Bot desconectado."}`.

## 4. Concorrência (obrigatória, faz parte da nota)
- Há uma thread de *accept* por porta (texto claro e TLS) e uma thread por cliente.
- No TLS, o handshake é feito **na thread do cliente** (`server_side=True`, com timeout de 10 s), nunca na thread de accept.
- O registro de participantes (`dict` nome → `Participant`) e o dicionário `pending` são protegidos por **um** `threading.Lock`.
- **Nenhum I/O de socket acontece com esse lock seguro.** Para enviar, primeiro se tira um snapshot da lista com o lock; depois o envio é feito sem ele.
- Cada `Participant` tem um `send_lock` próprio, para que duas threads nunca intercalem bytes no mesmo socket.
- Uma falha de envio para um participante remove esse participante (uma vez só, de forma idempotente) e gera o `LEAVE` correspondente.
- Uma thread *reaper* (daemon) varre `pending` a cada 0,5 s para aplicar o `BOT_TIMEOUT`.

## 5. Componentes e interfaces públicas

### 5.1 `server.py`
```
class ChatServer:
    def __init__(self, host="0.0.0.0", plain_port=5000, tls_port=5001,
                 ssl_context=None, bot_timeout=30.0, event_queue=None): ...
    def start(self) -> None          # abre sockets e threads, retorna imediatamente
    def stop(self) -> None           # fecha tudo, idempotente
    plain_address: tuple[str,int]    # disponível após start() (porta 0 = efêmera em testes)
    tls_address: tuple[str,int] | None   # None se ssl_context is None
    def snapshot(self) -> list[dict] # [{"name","role","tls","addr"}]
    def pending_snapshot(self) -> list[dict]  # [{"req_id","from","age"}]
```
- `event_queue` recebe tuplas `(kind: str, data: dict)`. Valores de `kind`: `join`, `leave`, `msg`, `dm`, `bot_req`, `bot_resp`, `bot_timeout`, `error`, `info`.
- CLI: `python server.py [--host H] [--port 5000] [--tls-port 5001] [--no-tls] [--gui] [--bot-timeout 30]`.
  - Sem `--gui`, roda em modo console, imprimindo os eventos.
  - O TLS usa `tls_config.server_context()`.
- Ao receber `Ctrl+C` ou fechar a janela, encerra limpo.

### 5.2 `server_gui.py`
`ServerGUI(root: tk.Tk, server: ChatServer, event_queue: queue.Queue)` mostra:
- participantes (nome, papel, TLS sim/não, endereço);
- log de mensagens;
- log de eventos;
- pedidos ao bot pendentes.

A interface é atualizada **só na thread principal**, via `root.after(100, poll)`. O `tkinter` só é importado quando `--gui` é usado.

### 5.3 `client.py`
```
class ChatClient:
    def __init__(self, name, role, host="127.0.0.1", port=5000, ssl_context=None, out=print): ...
    def connect(self) -> dict        # envia HELLO, devolve WELCOME ou lança ConnectionError com o texto do ERROR
    def start_receiver(self) -> None # thread daemon que chama out(format_incoming(msg))
    def handle_input(self, line) -> dict | None   # converte texto do usuário em mensagem e envia
    def close(self) -> None
def parse_command(line, name) -> dict | None
def format_incoming(msg) -> str
```
- Comandos:
  - texto simples vira `MSG`;
  - `@bot <pergunta>` vira `BOT_REQ` com `new_req_id()`;
  - `/w <nome> <msg>` vira `DM`;
  - `/lista` vira `LIST`;
  - `/sair` vira `LEAVE` e encerra;
  - `/ajuda` mostra a ajuda localmente.
- Linha vazia é ignorada.
- `format_incoming` deixa visível que uma resposta do bot é privada e mostra os primeiros 8 caracteres do `req_id`.
- Queda do servidor: imprime "Conexão com o servidor perdida." e encerra sem traceback.
- CLI: `python client.py --name N --role R [--host 127.0.0.1] [--port P] [--tls] [--ca certs/ca.crt]`. A porta padrão é 5000, ou 5001 com `--tls`.

### 5.4 `llm.py`
```
class LLMError(Exception)
class LLMTimeout(LLMError)
class OpenAILLM:   # Responses API: client.responses.create(model, instructions, input, max_output_tokens, timeout[, reasoning])
    def __init__(self, model, api_key, timeout, max_output_tokens, system_prompt, reasoning_effort=None)
    def complete(self, messages: list[dict]) -> str   # messages = [{"role":"user|assistant","content":str}]
class FakeLLM:     # para testes e demo sem chave
    def __init__(self, delay=0.0, fail=False, timeout=None)
    def complete(self, messages) -> str   # resposta determinística citando a última pergunta e len(messages)
def load_system_prompt(path="knowledge/solar_om.md") -> str
def build_llm_from_env() -> OpenAILLM | FakeLLM
```
- Toda exceção do SDK (timeout, conexão, autenticação, limite de requisições) é convertida em `LLMTimeout` ou `LLMError`, com mensagem curta em pt-BR e **sem incluir a chave**.
- `FakeLLM` com `delay > timeout` lança `LLMTimeout`.

### 5.5 `bot.py`
```
class ChatBot:
    def __init__(self, llm, host="127.0.0.1", port=5000, ssl_context=None, history_size=6, workers=4): ...
    def run(self) -> None   # conecta (HELLO role=bot, from=bot) e processa até EOF
    def history_for(self, user) -> list[dict]
```
- Cada `BOT_REQ` é enviado a um `ThreadPoolExecutor`. A thread de leitura nunca bloqueia esperando a LLM.
- O histórico é um `deque(maxlen=history_size)` **por usuário**, protegido por lock. Ele só é atualizado (pergunta e resposta) quando a chamada dá certo. Usuários diferentes nunca compartilham contexto.
- Em sucesso, envia `BOT_RESP{to:solicitante, req_id}`. Em `LLMTimeout` ou `LLMError`, envia `ERROR{to:solicitante, req_id, content:<mensagem pt-BR>}`.
- CLI: `python bot.py [--host] [--port] [--tls] [--ca]`. O provider vem de `LLM_PROVIDER`.

### 5.6 `tls_config.py`
- `server_context(cert=TLS_CERT, key=TLS_KEY) -> ssl.SSLContext`: `PROTOCOL_TLS_SERVER`, mínimo TLS 1.2.
- `client_context(cafile=TLS_CA) -> ssl.SSLContext`: `create_default_context(cafile=...)`, com `check_hostname=True`, `CERT_REQUIRED` e mínimo TLS 1.2.
- `certs/gen_certs.sh [outdir]` gera, com `openssl`:
  - `ca.key` e `ca.crt` (CA própria da usina);
  - `server.key` e `server.crt`, com SAN `DNS:localhost, IP:127.0.0.1`, assinados pela CA.
- Arquivos `.key` nunca são versionados.

### 5.7 `check_llm.py`
- Carrega o `.env`. Falha com mensagem clara se `OPENAI_API_KEY` estiver ausente.
- Confere se `OPENAI_MODEL` aparece em `client.models.list()`. Se não aparecer, sugere modelos `*nano*` e `*mini*` disponíveis.
- Faz uma chamada real curta, imprimindo o modelo, a latência e o `usage`.
- Faz uma chamada com timeout de 0,001 s e confirma que ela vira `LLMTimeout`.
- Nunca imprime a chave. Código de saída 0 só se tudo passar.

## 6. Variáveis de ambiente (`.env`, carregado com `python-dotenv`)
| Variável | Padrão | Uso |
|---|---|---|
| `OPENAI_API_KEY` | (nenhum) | bot e check_llm |
| `OPENAI_MODEL` | `gpt-5.4-nano` | modelo barato; confirmado com `check_llm.py` |
| `OPENAI_REASONING_EFFORT` | vazio | se definido, envia `reasoning={"effort":...}` |
| `LLM_PROVIDER` | `openai` | `openai` ou `fake` |
| `LLM_TIMEOUT` | `20` | segundos por chamada à LLM |
| `LLM_MAX_OUTPUT_TOKENS` | `600` | |
| `FAKE_LLM_DELAY` | `0` | atraso do FakeLLM (demo e testes) |
| `FAKE_LLM_FAIL` | `0` | `1` faz o FakeLLM falhar |
| `BOT_HISTORY_SIZE` | `6` | mensagens por usuário (3 trocas) |
| `BOT_TIMEOUT` | `30` | timeout do servidor para BOT_REQ (deve ser > `LLM_TIMEOUT`) |
| `TLS_CERT` / `TLS_KEY` / `TLS_CA` | `certs/server.crt` / `certs/server.key` / `certs/ca.crt` | |

## 7. Bot: comportamento (system prompt)
- O tema é a operação e manutenção de usinas fotovoltaicas, e o bot responde **só** com base em `knowledge/solar_om.md`.
- Quando a resposta não estiver na base, ele responde "Não consta na base de conhecimento da usina.".
- Responde em pt-BR, com no máximo 5 linhas, de forma objetiva.
- Toda orientação de manobra ou religamento termina lembrando que a liberação do engenheiro responsável é obrigatória (NR-10).
- O inversor "SOLX-100" e os códigos de falha são **ilustrativos** e a base deixa isso explícito.

## 8. Testes (`.venv/bin/pytest -q`)
- Usam portas efêmeras (`port=0`) e nunca as portas 5000 e 5001.
- Usam `FakeLLM` e nunca rede externa.
- Cada teste dura menos de 10 s e todos usam timeouts nos sockets.
- O fixture `tls_certs` (em `tests/conftest.py`) gera a CA e o certificado de servidor em um diretório temporário. Ele devolve `{"ca","cert","key","dir"}`.
- O fixture `wrong_ca` gera uma CA alheia, para testar a rejeição do certificado.

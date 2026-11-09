# Roteiro do vídeo: SolarOps Chat (SD2)

O vídeo tem cerca de 10 minutos e cobre os cenários da seção 8 do enunciado e as explicações individuais.
Antes de gravar:
- feche apps que mostrem dados pessoais;
- deixe o `.env` fora da tela;
- aumente a fonte do terminal.

## Preparação (fora da gravação)
```bash
make certs && make test
```
Abra 6 abas de terminal e o Wireshark na interface `lo0` (Loopback), com o filtro `tcp.port==5050 || tcp.port==5051`.

## Cena 1: problema e arquitetura (1 min)
- Fala: "Em usinas solares do Norte de Minas, COS, técnicos e engenheiro coordenam falhas pelo WhatsApp, e o conhecimento de códigos de inversor e NR-10 fica com poucas pessoas. O SolarOps Chat roda na LAN da usina, e o técnico consulta um bot em privado sem parar a conversa da equipe."
- Mostrar a tabela de arquitetura do relatório: servidor, cliente e bot como processos separados, ligados só por socket TCP.

## Cena 2: servidor e GUI (1 min)
- `make server`. Mostrar a janela e os quatro painéis.
- Fala: "Uma thread de accept por porta, 5050 em claro e 5051 com TLS, e uma thread por cliente. A GUI só é atualizada pela thread principal, lendo uma fila a cada 100 ms."

## Cena 3: bot e 3 humanos (1 min)
- `make bot`. Depois:
  - `make client NAME=ana ROLE=cos`
  - `make client NAME=rui ROLE=tecnico TLS=1`
  - `make client NAME=eva ROLE=engenheiro`
- Rodar `/lista` em um cliente. Mostrar a coluna TLS na GUI.

## Cena 4: chat simultâneo durante a consulta ao bot (1,5 min)
- rui: `@bot o inversor SOLX-100 mostra o código 2032, o que significa?`
- **Logo em seguida**, ana e eva trocam mensagens, que chegam antes da resposta do bot.
- Mostrar que a resposta chega só para o rui, marcada `[privado]` e com o req_id. Ana e eva não a veem.
- Mostrar o pedido pendente sumindo do painel da GUI.

## Cena 5: continuação e contextos separados (1 min)
- rui: `@bot e qual EPI eu uso pra essa medição?`: a resposta usa o contexto anterior.
- eva: `@bot qual foi o código de falha que eu perguntei antes?`: a resposta é "Não consta na base…", o que prova que o histórico é por usuário (limite de 6 mensagens).

## Cena 6: desconexão (0,5 min)
- Fechar a aba da ana com Ctrl+C ou fechando o terminal. Os outros recebem "conexão perdida" e a GUI registra o evento.

## Cena 7: falha ou timeout da LLM (1 min)
- Parar o bot e subir de novo com um timeout impossível:
```bash
LLM_TIMEOUT=0.001 .venv/bin/python bot.py --tls
```
- rui pergunta ao bot e recebe "tempo limite" só para ele, enquanto o chat segue.
- Variação: parar o bot e perguntar de novo, o que gera "Bot indisponível no momento.".

## Cena 8: Wireshark (2 min)
- ana (5050) envia `teste wireshark 123`. No Wireshark, Follow TCP Stream mostra o JSON legível.
- rui (5051) envia `teste wireshark 456`. Na porta 5051 aparecem só Client Hello, Server Hello (TLS 1.3) e Application Data.
- Fala: "A chave de sessão é derivada no handshake por ECDHE e nunca trafega. O cliente valida o certificado contra a CA da usina (ca.crt). A decifragem acontece no servidor, na thread de cada cliente, e no cliente, na thread receptora."
- Observação: a mensagem do rui aparece na 5050 porque o servidor a repassa para ana e eva, que estão sem TLS. A proteção vale por enlace.

## Cena 9: explicações individuais (1 min cada integrante)
Cada integrante explica com o código aberto:
1. **Protocolo** (`protocol.py`): JSON por linha, campos, `LineReader` e o limite de 64 KB.
2. **Threads** (`server.py`): accept, thread por cliente, reaper, lock único sem I/O, `send_lock` por participante.
3. **Proteção** (`tls_config.py`, `certs/gen_certs.sh`): CA própria, SAN, `CERT_REQUIRED`, `check_hostname`.
4. **Percurso até a LLM** (`client.py` → `server.py` → `bot.py` → `llm.py`): req_id, pendente com prazo, pool de workers, Responses API e resposta só ao solicitante.

## Encerramento (0,5 min)
- `make test`: 188 testes passando.
- Limitações em uma frase: proteção por enlace, sem autenticação de usuário, histórico em memória.

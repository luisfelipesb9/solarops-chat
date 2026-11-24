// Gera docs/Trabalho Prático - SD2.docx no padrão Unimontes (skill exercicio-academico).
// Uso: NODE_PATH=<pasta com node_modules/docx> node docs/gerar_relatorio.js
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, BorderStyle, LevelFormat, ImageRun, PageBreak,
} = require("docx");

const ROOT = path.resolve(__dirname, "..");
const EV = path.join(ROOT, "evidencias");
const OUT = path.join(ROOT, "docs", "Trabalho Prático - SD2.docx");
const FONT = "Times New Roman";
const MONO = "Courier New";
const CONTENT_W = 9071; // A4 menos margens ABNT (3 cm + 2 cm)
const read = (f) => fs.readFileSync(path.join(EV, f), "utf8").replace(/\s+$/, "");
const exists = (f) => fs.existsSync(path.join(EV, f));

// ---------- blocos básicos ----------
const run = (text, o = {}) => new TextRun({ text, font: FONT, size: 24, ...o });
const P = (text, o = {}) =>
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    spacing: { line: 360, after: 120, before: 0 },
    children: Array.isArray(text) ? text : [run(text)],
    ...o,
  });
const H2 = (text, first = false) =>
  new Paragraph({
    pageBreakBefore: first,
    keepNext: true,
    spacing: { before: first ? 0 : 240, after: 60, line: 360 },
    children: [run(text, { bold: true, size: 28 })],
  });
const H3 = (text) =>
  new Paragraph({
    keepNext: true,
    spacing: { before: 120, after: 60, line: 360 },
    children: [run(text, { bold: true })],
  });
const B = (text, level = 0) =>
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    numbering: { reference: "bullets", level },
    spacing: { line: 276, after: 80 },
    children: [run(text)],
  });

const cellBorder = { style: BorderStyle.SINGLE, size: 4, color: "808080" };
const borders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
function T(rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((r, i) =>
      new TableRow({
        tableHeader: i === 0,
        cantSplit: true,
        children: r.map((c, j) =>
          new TableCell({
            borders,
            width: { size: widths[j], type: WidthType.DXA },
            margins: { top: 40, bottom: 40, left: 80, right: 80 },
            shading: i === 0 ? { type: ShadingType.CLEAR, fill: "E7E6E6", color: "auto" } : undefined,
            children: [new Paragraph({ spacing: { line: 240, after: 0 }, children: [run(c, { size: 20, bold: i === 0 })] })],
          })
        ),
      })
    ),
  });
}
const gap = () => new Paragraph({ spacing: { after: 120, line: 240 }, children: [] });

function Terminal(caption, text) {
  const lines = text.split("\n");
  return [
    new Paragraph({ keepNext: true, spacing: { before: 120, after: 60, line: 276 }, children: [run(caption, { bold: true })] }),
    new Table({
      width: { size: CONTENT_W, type: WidthType.DXA },
      columnWidths: [CONTENT_W],
      rows: [
        new TableRow({
          children: [
            new TableCell({
              width: { size: CONTENT_W, type: WidthType.DXA },
              shading: { type: ShadingType.CLEAR, fill: "1E1E1E", color: "auto" },
              margins: { top: 100, bottom: 100, left: 140, right: 140 },
              borders: { top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE }, left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE } },
              children: lines.map((l) =>
                new Paragraph({ spacing: { line: 240, after: 0 }, children: [new TextRun({ text: l.replace(/\t/g, "    ") || " ", font: MONO, size: 18, color: "D4D4D4" })] })
              ),
            }),
          ],
        }),
      ],
    }),
    gap(),
  ];
}

function Figure(file, caption, widthPx) {
  const data = fs.readFileSync(path.join(EV, file));
  const w = data.readUInt32BE(16), h = data.readUInt32BE(20); // PNG IHDR
  const width = widthPx, height = Math.round((h / w) * widthPx);
  return [
    new Paragraph({ keepNext: true, spacing: { before: 120, after: 60, line: 276 }, children: [run(caption, { bold: true })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new ImageRun({ type: "png", data, transformation: { width, height } })] }),
  ];
}

// ---------- capa ----------
const C = (text, o = {}, p = {}) =>
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { line: 360, after: 0, ...(p.spacing || {}) }, children: [run(text, { bold: true, ...o })], ...p });
const cover = [
  C("ESTADO DE MINAS GERAIS"),
  C("UNIVERSIDADE ESTADUAL DE MONTES CLAROS"),
  C("CENTRO DE CIÊNCIAS EXATAS E TECNOLÓGICAS"),
  C("CURSO DE BACHARELADO EM SISTEMAS DE INFORMAÇÃO"),
  C("Trabalho Prático: SolarOps Chat", {}, { spacing: { before: 3400 } }),
  C("Chat Cliente-Servidor com Sockets, Threads, Criptografia e Bot LLM"),
  C("Alisson Silveira Cardoso", { bold: false }, { spacing: { before: 900 } }),
  C("André Felipe Souto Araújo", { bold: false }, { spacing: { before: 0 } }),
  C("Luís Felipe Silva Barbosa", { bold: false }, { spacing: { before: 0 } }),
  new Paragraph({ alignment: AlignmentType.RIGHT, spacing: { before: 1800, line: 360, after: 0 }, children: [run("Disciplina: Sistemas Distribuídos II", { bold: true })] }),
  new Paragraph({ alignment: AlignmentType.RIGHT, spacing: { line: 360, after: 0 }, children: [run("Prof. Marcel Veloso Campos", { bold: true })] }),
  C("MONTES CLAROS - MG", {}, { spacing: { before: 2000 } }),
  C("2026/2"),
];

// ---------- conteúdo ----------
const body = [];
const add = (...xs) => xs.flat().forEach((x) => body.push(x));

add(H2("1. Tema e problema", true));
add(P("O SolarOps Chat é um sistema de troca de mensagens para equipes de operação e manutenção (O&M) de usinas fotovoltaicas. Em usinas do Norte de Minas Gerais (Janaúba e Jaíba), o centro de operação (COS), os técnicos de campo e o engenheiro responsável coordenam falhas de inversores por aplicativos de mensagem, e o conhecimento sobre códigos de falha e sobre os procedimentos da NR-10 fica concentrado em poucas pessoas."));
add(P("O servidor roda na rede local da usina. O técnico consulta o bot em privado com @bot, e a equipe continua conversando durante a consulta. A proteção do canal responde à exigência de cibersegurança do setor elétrico (Resolução Normativa ANEEL nº 964/2021): comandos e ocorrências operacionais não devem trafegar em texto claro."));

add(H2("2. Arquitetura"));
add(P("A aplicação tem três programas independentes que se comunicam apenas por sockets TCP: servidor, cliente humano e cliente bot. A linguagem é Python 3.14; a rede usa somente a biblioteca padrão (socket, threading, ssl, queue, json e tkinter). As únicas dependências externas são openai e python-dotenv, no bot, e pytest, nos testes. O código de aplicação tem cerca de 1.360 linhas e os testes, cerca de 2.400."));
add(T([
  ["Arquivo", "Processo", "Porta", "Threads", "Responsabilidade"],
  ["server.py", "servidor", "5050 (claro) e 5051 (TLS)", "accept por porta, uma por cliente, reaper, principal", "Aceita conexões, identifica participantes, encaminha mensagens e aplica o tempo limite do bot"],
  ["server_gui.py", "servidor", "não se aplica", "principal (tkinter)", "Exibe participantes, mensagens, eventos e pedidos pendentes ao bot"],
  ["client.py", "um por humano", "5050 ou 5051", "principal (input) e receptora", "Envia e recebe mensagens sem bloquear a digitação"],
  ["bot.py e llm.py", "processo próprio", "5051 (TLS)", "leitora e pool de 4 workers", "Recebe pedidos, consulta a OpenAI e devolve a resposta com o mesmo req_id"],
  ["protocol.py", "biblioteca comum", "não se aplica", "não se aplica", "Enquadramento por linha, validação e serialização das mensagens"],
  ["tls_config.py e certs/", "biblioteca comum", "não se aplica", "não se aplica", "Contextos TLS do servidor e do cliente; CA própria da usina"],
], [1500, 1150, 1350, 1900, 3171]));
add(gap());
add(H3("a) Percurso de uma solicitação ao bot"));
add(B("Cliente: rui_tec digita @bot seguido da pergunta; client.py gera um req_id (uuid4) e envia BOT_REQ pelo socket TLS."));
add(B("Servidor: a thread do cliente valida a mensagem, sobrescreve o campo from com o nome da sessão, registra pending[req_id] com prazo BOT_TIMEOUT (30 s) e encaminha o pedido ao bot."));
add(B("Bot: a thread leitora entrega o pedido ao ThreadPoolExecutor; o worker monta o histórico daquele usuário mais a pergunta e chama a OpenAI com tempo limite de 20 s."));
add(B("Bot: devolve BOT_RESP com o mesmo req_id e to igual ao solicitante; em falha ou tempo limite, devolve ERROR com o mesmo req_id."));
add(B("Servidor: confirma que o req_id está pendente e que o destinatário é o solicitante registrado, remove o pendente e entrega a resposta somente ao solicitante."));
add(B("Concorrência: durante todo o percurso as threads dos demais clientes continuam encaminhando MSG e DM, pois nenhuma delas espera a LLM."));

add(H2("3. Protocolo de aplicação"));
add(P("O transporte é TCP. Cada mensagem é um objeto JSON em UTF-8 terminado por \\n, o que delimita as mensagens dentro do fluxo de bytes. O limite é de 65.536 bytes por linha; uma linha maior encerra a conexão. A classe LineReader acumula os bytes recebidos até encontrar \\n, o que trata tanto mensagens partidas em vários recv quanto várias mensagens coladas em um único recv. Todos os campos estão sempre presentes e são strings; campos desconhecidos são rejeitados."));
add(T([
  ["Campo", "Significado"],
  ["type", "HELLO, WELCOME, MSG, DM, BOT_REQ, BOT_RESP, ERROR, JOIN, LEAVE ou LIST"],
  ["from", "Remetente; o servidor sobrescreve com o nome da sessão (anti-spoofing) e usa server nas próprias mensagens"],
  ["to", "* para todos, o nome de um usuário ou bot"],
  ["content", "Texto da mensagem; em LIST, um array JSON serializado"],
  ["req_id", "Identificador uuid4 que correlaciona BOT_REQ, BOT_RESP e ERROR; vazio quando não se aplica"],
  ["ts", "Data e hora ISO 8601 em UTC"],
  ["role", "cos, tecnico, engenheiro ou bot (o servidor também sobrescreve)"],
], [1400, 7671]));
add(gap());
add(T([
  ["Tipo", "Sentido", "Uso"],
  ["HELLO", "cliente → servidor", "Primeira mensagem: nome e papel; deve chegar em até 10 s"],
  ["WELCOME", "servidor → cliente", "Aceite da conexão, seguido de LIST"],
  ["MSG", "cliente → servidor → humanos", "Chat público; não volta ao remetente e não vai ao bot"],
  ["DM", "cliente → servidor → destinatário", "Mensagem privada; destinatário inexistente gera ERROR"],
  ["BOT_REQ", "cliente → servidor → bot", "Pergunta ao bot com req_id"],
  ["BOT_RESP", "bot → servidor → solicitante", "Resposta privada com o mesmo req_id"],
  ["ERROR", "servidor ou bot → cliente", "Recusa, falha ou tempo limite, com req_id quando houver"],
  ["JOIN e LEAVE", "servidor → humanos", "Entrada, saída voluntária (saiu) ou queda (conexão perdida)"],
  ["LIST", "cliente ↔ servidor", "Lista de participantes com nome, papel e uso de TLS"],
], [1500, 2700, 4871]));
add(gap());
add(P("Regras de identificação: o nome segue a expressão ^[A-Za-z0-9_-]{1,20}$ e é único; os nomes bot e server são reservados; só um bot pode estar conectado; cada papel só envia os tipos que lhe cabem (um humano não envia BOT_RESP, por exemplo). Uma resposta do bot só é aceita se o req_id estiver pendente e se o destinatário for o solicitante registrado, o que impede que uma resposta chegue a outro usuário."));
add(Terminal("protocol.py: linha BOT_REQ serializada", read("exemplo_protocolo.txt")));

add(H2("4. Uso de threads e sincronização"));
add(H3("a) Servidor"));
add(B("Accept: uma thread por porta (5050 e 5051) aceita conexões e cria uma thread por cliente. O handshake TLS e a espera do HELLO (10 s) acontecem na thread do cliente, de modo que um handshake lento não trava o accept."));
add(B("Thread por cliente: lê mensagens com LineReader e trata cada uma (_dispatch). Os envios a outros participantes acontecem na thread de quem enviou."));
add(B("Reaper: thread daemon que verifica a cada 0,5 s os pedidos ao bot vencidos e envia ERROR ao solicitante."));
add(B("Principal: executa o laço do tkinter (com --gui) ou imprime os eventos no console."));
add(H3("b) Recursos compartilhados"));
add(B("Um único threading.Lock protege o dicionário de participantes e o dicionário pending. Nenhum I/O de socket é feito com esse lock seguro: o servidor tira uma cópia da lista com o lock e envia fora dele."));
add(B("Cada participante tem um send_lock próprio, para que duas threads nunca intercalem bytes no mesmo socket."));
add(B("O socket tem tempo limite de envio de 5 s (SO_SNDTIMEO): um cliente que para de ler é desconectado em vez de travar quem envia para ele."));
add(B("A remoção de um participante é idempotente e gera um único LEAVE; se o bot cai, cada pedido pendente recebe ERROR com o texto Bot desconectado."));
add(H3("c) Cliente e bot"));
add(B("Cliente: a thread principal lê o teclado com input() e uma thread daemon recebe e imprime as mensagens; por isso a digitação nunca bloqueia, inclusive enquanto o bot processa."));
add(B("Bot: a thread leitora nunca espera a LLM; cada BOT_REQ vai para um ThreadPoolExecutor de 4 workers, e os workers compartilham o socket por meio de um lock de envio."));

add(H2("5. Interface gráfica do servidor"));
add(P("A interface em tkinter (server_gui.py) tem quatro painéis: participantes (nome, papel, TLS sim ou não e endereço), pedidos pendentes ao bot (req_id, solicitante e idade), log de mensagens e log de eventos (entradas, saídas, quedas, erros e tempos limite). As threads de rede nunca tocam a interface: elas publicam tuplas (tipo, dados) em uma queue.Queue, e a thread principal consome a fila a cada 100 ms com root.after. Fechar a janela chama server.stop(), que encerra os sockets e as threads."));
if (exists("gui_servidor.png")) add(Figure("gui_servidor.png", "Figura 1: interface do servidor com 3 humanos e o bot conectados", 600));

add(H2("6. Criptografia"));
add(H3("a) Mecanismo e certificados"));
add(P("O canal protegido usa TLS sobre os sockets, pelo módulo ssl da biblioteca padrão (OpenSSL 4.1), com versão mínima TLS 1.2; na prática a negociação resulta em TLS 1.3. O script certs/gen_certs.sh cria com openssl uma CA própria da usina (SolarOps CA, RSA 2048, validade de 365 dias, com basicConstraints CA:TRUE e keyUsage keyCertSign) e o certificado do servidor (CN=localhost, SAN DNS:localhost e IP:127.0.0.1, extendedKeyUsage serverAuth), assinado por essa CA. As chaves privadas recebem permissão 600 e não são versionadas."));
add(P("A validação é explícita: tls_config.client_context() cria o contexto com ssl.create_default_context(cafile=certs/ca.crt), com CERT_REQUIRED e check_hostname ligados e com a verificação X.509 estrita do Python 3.14 mantida. O cliente confia apenas na CA da usina; um servidor com certificado de outra CA é recusado, como mostra o teste test_client_rejects_server_signed_by_other_ca."));
add(T([
  ["Enlace", "Porta", "Proteção"],
  ["Cliente humano com --tls ↔ servidor", "5051", "TLS 1.3, CA própria validada pelo cliente"],
  ["Bot ↔ servidor", "5051", "TLS 1.3, mesma validação"],
  ["Bot ↔ API da OpenAI", "443", "HTTPS feito pelo SDK openai"],
  ["Cliente humano sem --tls ↔ servidor", "5050", "Texto claro, mantido só como referência para o Wireshark"],
], [3600, 900, 4571]));
add(gap());
add(P("A decifragem acontece nas pontas de cada enlace: no servidor, dentro da thread do cliente, quando o SSLSocket executa recv; no cliente e no bot, na thread receptora. O servidor vê o texto claro para poder encaminhar, então a proteção é por enlace e não ponta a ponta."));
if (exists("wireshark_claro.txt")) {
  add(H3("b) Comparação no Wireshark"));
  add(P("A captura foi feita na interface de loopback (lo0) com o filtro tcp port 5050 or tcp port 5051, durante a execução de scripts/demo_evidencias.py. Nesse roteiro, ana_cos (texto claro, 5050) envia a mensagem conhecida teste wireshark 123 e rui_tec (TLS, 5051) envia teste wireshark 456. O arquivo da captura está em evidencias/captura_5050_5051.pcap e foi analisado no Wireshark (Figura 2) e com o tshark, sua versão de linha de comando."));
  add(Terminal("tshark: fluxo TCP da porta 5050 (Follow TCP Stream)", read("wireshark_claro.txt")));
  add(P("Na porta 5050 a mensagem aparece inteira: tipo, remetente, conteúdo e papel podem ser lidos por qualquer pessoa com acesso à rede."));
  if (exists("wireshark_claro.png")) add(Figure("wireshark_claro.png", "Figura 2: Wireshark, Follow TCP Stream de ana_cos na porta 5050 (texto claro)", 470));
  add(Terminal("tshark: pacotes da porta 5051", read("wireshark_tls.txt")));
  add(P("Na porta 5051 só aparecem o handshake e registros Application Data. O Client Hello é rotulado TLSv1.2 porque essa é a versão do cabeçalho de registro por compatibilidade, mas a extensão supported_versions do Server Hello escolhe 0x0304, isto é, TLS 1.3; a troca de chaves é por ECDHE. O último comando mostra o início de um registro Application Data: bytes sem nenhum trecho legível. O conteúdo fica protegido porque é cifrado com uma chave de sessão AEAD derivada no handshake, que nunca trafega na rede; sem essa chave, os bytes capturados não podem ser lidos nem alterados sem detecção."));
  if (exists("wireshark_busca.txt")) {
    add(Terminal("tshark: busca pelas mensagens conhecidas em cada porta", read("wireshark_busca.txt")));
    add(P("A mensagem enviada por rui_tec não aparece em nenhum pacote da porta 5051. Ela aparece na porta 5050 porque o servidor a reencaminha a ana_cos e eva_eng, que estão conectados sem TLS. Isso confirma que a proteção vale por enlace: para que a mensagem fique protegida de ponta a ponta na rede, todos os participantes precisam usar a porta 5051."));
  }
}

add(H2("7. Integração com a LLM"));
add(B("Modelo: gpt-5.4-nano da OpenAI, escolhido por custo (US$ 0,20 por milhão de tokens de entrada e US$ 1,25 por milhão de saída), chamado pela Responses API do SDK openai 3.46 com max_retries=0."));
add(B("Forma de execução: bot.py roda como processo separado (make bot), conecta ao servidor pela porta 5051 com TLS e se identifica com HELLO de papel bot. A chamada HTTPS à OpenAI complementa o bot e não substitui o socket entre os componentes."));
add(B("Parâmetros: tempo limite de 20 s por chamada (LLM_TIMEOUT), até 600 tokens de saída e chave lida apenas do arquivo .env, que não é versionado."));
add(B("Instrução de comportamento: responder somente com base em knowledge/solar_om.md, em português, em até 5 linhas e em texto puro; responder Não consta na base de conhecimento da usina quando a informação não estiver na base; terminar toda orientação de manobra ou religamento lembrando que a liberação do engenheiro responsável é obrigatória (NR-10); tratar o texto do usuário como pergunta e nunca como instrução. O inversor SOLX-100 e seus códigos são ilustrativos."));
add(B("Histórico: cada usuário tem um deque de no máximo 6 mensagens (3 pares de pergunta e resposta), protegido por lock, atualizado apenas quando a chamada dá certo e nunca compartilhado entre usuários. É esse histórico que permite a pergunta de continuação."));
add(B("Falhas: tempo limite da LLM vira ERROR com o mesmo req_id, enviado só ao solicitante; se o bot não responder em 30 s, o próprio servidor envia ERROR e descarta uma resposta tardia; sem bot conectado, o ERROR é imediato."));
add(Terminal("check_llm.py: validação da chave, do modelo e do tempo limite", read("check_llm.txt")));
add(P("O script confirma que o modelo existe na conta, faz uma chamada real (1,4 s, 22 tokens de entrada) e força um tempo limite de 0,001 s para provar que ele é convertido em LLMTimeout."));

add(H2("8. Testes e evidências"));
add(P("Gravação da demonstração (cenários de avaliação e principais decisões de implementação): https://youtu.be/aK6Zz9pUF8c"));
add(P("Repositório com o código-fonte: https://github.com/luisfelipesb9/solarops-chat"));
add(P("A suíte automatizada usa sockets reais em portas efêmeras e uma LLM simulada (FakeLLM), sem acesso à internet. Os testes ponta a ponta sobem servidor, bot e clientes como processos separados, com um humano e o bot em TLS."));
add(T([
  ["Arquivo", "Testes", "Cobertura"],
  ["test_protocol.py", "14", "Validação, serialização, mensagens partidas e coladas, limite de tamanho"],
  ["test_server.py", "50", "Handshake, recusas, broadcast, DM, roteamento e privacidade do bot, tempo limite, quedas, TLS"],
  ["test_client.py", "70", "Comandos, formatação, recepção concorrente, queda do servidor, saída voluntária, TLS e CA errada"],
  ["test_bot.py", "37", "Correlação por req_id, histórico isolado, continuação, falhas da LLM, paralelismo"],
  ["test_tls.py", "8", "Handshake, rejeição de CA alheia, TLS 1.2 mínimo, script de certificados"],
  ["test_e2e.py", "9", "Cenários da seção 8 do enunciado com processos reais"],
  ["test_stress.py", "1", "10 clientes simultâneos com 20 mensagens cada, sem perda"],
], [2000, 900, 6171]));
add(gap());
add(Terminal("pytest: suíte completa", read("pytest.txt")));
add(T([
  ["Cenário exigido na demonstração", "Teste ponta a ponta"],
  ["3 humanos e 1 bot conectados", "test_list_shows_three_humans_and_bot_with_correct_tls_flag"],
  ["Chat continua durante a consulta ao bot; resposta privada", "test_slow_bot_does_not_block_chat_and_answer_reaches_only_requester"],
  ["Pergunta de continuação", "test_follow_up_question_carries_the_history"],
  ["Contextos separados para dois usuários", "test_each_user_has_their_own_history"],
  ["Desconexão", "test_killed_client_is_announced_as_connection_lost_and_server_keeps_working"],
  ["Falha ou tempo limite na LLM", "test_llm_timeout_error_goes_only_to_the_requester e test_server_timeout_answers_requester_and_drops_the_late_bot_reply"],
  ["Bot ausente ou caído", "test_request_without_bot_fails_immediately e test_bot_crash_with_pending_request_returns_error_to_requester"],
], [3300, 5771]));
add(gap());
add(Terminal("scripts/demo_evidencias.py: execução com a LLM real", read("demo_bot_real.txt")));
add(P("As mensagens entre ana_cos, rui_tec e eva_eng foram entregues em 0,07 s enquanto o bot levou 3,2 s para responder, o que comprova que o chat não bloqueia durante a consulta. A segunda pergunta de rui_tec (qual EPI) usou o contexto da primeira. A mesma pergunta de eva_eng, que não tinha histórico, recebeu Não consta na base de conhecimento da usina, o que comprova a separação de contextos. Nenhuma resposta do bot chegou a quem não perguntou."));

add(H2("9. Instalação e execução"));
add(B("Pré-requisitos: Python 3.14 com tkinter (no macOS, brew install python-tk@3.14) e openssl."));
add(B("make setup: cria o ambiente virtual .venv e instala as dependências de requirements.txt."));
add(B("make certs: gera a CA e o certificado do servidor em certs/."));
add(B("cp .env.example .env e preencher OPENAI_API_KEY; make check-llm valida a configuração."));
add(B("make server (interface gráfica), make bot (OpenAI) ou make bot-fake (sem chave) e make client NAME=<nome> ROLE=<cos|tecnico|engenheiro> [TLS=1] para cada humano."));
add(B("make test: executa a suíte completa."));

add(H2("10. Limitações"));
add(B("A proteção é por enlace: o servidor decifra e vê o conteúdo, então não há cifragem ponta a ponta entre usuários."));
add(B("A porta 5050 em texto claro existe apenas para a comparação no Wireshark; em uso real ela seria desativada."));
add(B("Não há autenticação de usuário: o nome é declarado no HELLO, e o TLS autentica apenas o servidor (sem certificado de cliente)."));
add(B("O histórico do bot fica em memória: é perdido quando o bot reinicia e não é apagado quando o usuário sai."));
add(B("A base de conhecimento é ilustrativa (inversor SOLX-100 fictício) e não substitui o manual do fabricante nem o procedimento oficial da usina."));
add(B("O bot depende de internet para falar com a OpenAI; sem ela, cada consulta recebe ERROR e o chat local continua funcionando."));
add(B("O cliente é de terminal: uma mensagem recebida pode aparecer no meio da linha que o usuário está digitando."));

// ---------- documento ----------
const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: 24 } } } },
  numbering: {
    config: [{
      reference: "bullets",
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 240 } } } },
      ],
    }],
  },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1701, bottom: 1134, left: 1701, right: 1134 } } },
    children: [...cover, ...body],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("gerado:", OUT);
});

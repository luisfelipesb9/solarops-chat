"""Roteiro do vídeo: cada batida (beat) tem o visual da tela e o texto narrado.

O texto é escrito para ser falado (números e siglas por extenso quando ajuda a pronúncia).
Os tempos `until` referem-se às transcrições reais em video/build/demo.json.
"""

BEATS = [
    {
        "id": "01_titulo", "title": "",
        "visual": {"type": "title"},
        "text": "Olá! Este vídeo apresenta o SolarOps Chat, o trabalho prático de Sistemas Distribuídos dois, "
                "da Unimontes, desenvolvido por Luís Felipe Silva Barbosa.",
    },
    {
        "id": "02_problema", "title": "O problema",
        "visual": {"type": "bullets", "items": [
            "Usinas solares do Norte de Minas (Janaúba e Jaíba)",
            "COS, técnicos de campo e engenheiro coordenam falhas por aplicativo de mensagem",
            "Códigos de falha de inversor e NR-10 ficam na cabeça de poucas pessoas",
            "Solução: chat na rede local da usina + bot privado que não para a conversa",
            "Canal cifrado: cibersegurança do setor elétrico (ANEEL REN 964/2021)",
        ]},
        "text": "O problema: em usinas solares do Norte de Minas, como Janaúba e Jaíba, o centro de operação, "
                "os técnicos de campo e o engenheiro coordenam falhas de inversores por aplicativos de mensagem. "
                "O conhecimento sobre códigos de falha e sobre a NR-10 fica concentrado em poucas pessoas. "
                "A solução é um chat que roda na rede local da usina, com um bot que responde em privado, "
                "sem parar a conversa da equipe. E como o setor elétrico exige cibersegurança, o canal é cifrado.",
    },
    {
        "id": "03_arquitetura", "title": "Arquitetura",
        "visual": {"type": "diagram", "name": "arquitetura"},
        "text": "A arquitetura tem três programas independentes, que só conversam por sockets TCP. "
                "O servidor escuta em duas portas: cinco mil e cinquenta, em texto claro, e cinco mil e cinquenta e um, com TLS. "
                "Os clientes humanos e o bot são processos separados. O bot é um cliente como os outros: "
                "conecta ao servidor pelo socket, se identifica como bot, e só ele faz a chamada HTTPS para a OpenAI. "
                "Tudo foi feito em Python, usando apenas a biblioteca padrão para a rede.",
    },
    {
        "id": "04_protocolo", "title": "Protocolo de aplicação",
        "visual": {"type": "protocol"},
        "text": "O protocolo de aplicação é JSON, com uma mensagem por linha, terminada por quebra de linha. "
                "Isso resolve a delimitação no fluxo TCP: o leitor acumula bytes até encontrar a quebra de linha, "
                "então mensagens partidas, ou coladas num mesmo recv, são tratadas corretamente. "
                "Toda mensagem tem tipo, remetente, destinatário, conteúdo, identificador da requisição, horário e papel. "
                "O servidor sobrescreve o remetente com o nome da sessão, o que impede que alguém se passe por outro usuário.",
    },
    {
        "id": "05_threads", "title": "Threads e sincronização",
        "visual": {"type": "code", "panels": [["server.py", 124, 133], ["server.py", 181, 186],
                                                ["server.py", 170, 175]]},
        "text": "No servidor, cada porta tem uma thread de accept, e cada cliente ganha uma thread própria. "
                "O handshake TLS acontece na thread do cliente, para não travar novas conexões. "
                "A lista de participantes e os pedidos pendentes ao bot são protegidos por um único lock, "
                "e nenhum envio pela rede acontece com esse lock seguro: o servidor copia a lista e envia fora dele. "
                "Cada participante ainda tem um lock de envio próprio, para que duas threads nunca misturem bytes no mesmo socket. "
                "E uma thread separada verifica os pedidos ao bot que passaram do prazo.",
    },
    {
        "id": "06_gui", "title": "Demonstração ao vivo: interface do servidor",
        "visual": {"type": "gui", "image": "gui_vazia.jpg",
                   "boxes": [[6, 52, 494, 352], [506, 52, 994, 352], [6, 376, 494, 666], [506, 376, 994, 666]]},
        "text": "Agora, a demonstração ao vivo, com a LLM real. Esta é a interface gráfica do servidor, feita em tkinter. "
                "Ela tem quatro painéis: participantes, pedidos pendentes ao bot, mensagens e eventos. "
                "As threads de rede publicam eventos numa fila, e só a thread principal atualiza a tela.",
    },
    {
        "id": "07_conectados", "title": "Três humanos e um bot",
        "visual": {"type": "demo", "image": "gui_conectados.jpg", "terms": ["ana", "rui", "eva"], "until": 22.5,
                   "boxes": [[250, 80, 370, 160]]},
        "text": "O bot se conecta pela porta TLS, seguido de três humanos: Ana, do centro de operação, em texto claro; "
                "Rui, técnico de campo, com TLS; e Eva, a engenheira, em texto claro. "
                "A coluna TLS da interface mostra quais conexões estão protegidas. "
                "No terminal do Rui, o comando barra lista confirma os quatro participantes.",
    },
    {
        "id": "08a_concorrencia", "title": "Chat continua durante a consulta ao bot",
        "visual": {"type": "demo", "image": "gui_pendente.jpg", "terms": ["ana", "rui", "eva"], "until": 37.0,
                   "since": 34.0, "boxes": [[506, 80, 994, 108]]},
        "text": "Ana avisa que o inversor sete do bloco B caiu. Rui pergunta ao bot, com arroba bot, "
                "o que significa o código dois mil e trinta e dois. Enquanto o bot consulta a LLM, "
                "Eva e Rui continuam conversando, e as mensagens chegam normalmente. "
                "Na interface do servidor, o pedido aparece em pedidos pendentes, com o identificador e o solicitante.",
    },
    {
        "id": "08b_privado", "title": "Resposta privada, correlacionada pelo identificador",
        "visual": {"type": "demo", "image": "gui_bot.jpg", "terms": ["ana", "rui", "eva"], "until": 39.0,
                   "since": 37.0},
        "text": "Cerca de dois segundos depois, a resposta chega apenas para o Rui, marcada como privada "
                "e com o mesmo identificador do pedido. Ana e Eva não recebem essa resposta. "
                "O bot respondeu com base na base de conhecimento da usina, e lembrou que o religamento "
                "exige a liberação do engenheiro.",
    },
    {
        "id": "09_contexto", "title": "Continuação e contextos separados",
        "visual": {"type": "demo", "image": "gui_contexto.jpg", "terms": ["rui", "eva"], "until": 55.0,
                   "since": 48.0},
        "text": "Agora a pergunta de continuação. Rui pergunta: e qual EPI eu uso pra essa medição? "
                "O bot entende que se trata da medição de isolação, porque guarda um histórico curto por usuário: "
                "no máximo seis mensagens, ou seja, três trocas. Para provar que os contextos são separados, "
                "Eva pergunta qual foi o código que ela perguntou antes. Como Eva não tem histórico, "
                "o bot responde que isso não consta na base. Em seguida, Ana manda uma mensagem direta, "
                "que só a Eva recebe.",
    },
    {
        "id": "10_queda", "title": "Desconexão abrupta",
        "visual": {"type": "demo", "image": "gui_queda.jpg", "terms": ["ana", "rui", "eva"], "until": 66.0,
                   "since": 64.0, "boxes": [[506, 432, 994, 448]]},
        "text": "Agora, uma desconexão abrupta: o processo da Ana é encerrado com kill menos nove, "
                "sem enviar a mensagem de saída. O servidor detecta a queda na leitura do socket, "
                "remove a Ana de forma segura e avisa os demais com: conexão perdida. "
                "A interface registra o evento, e a lista de participantes é atualizada.",
    },
    {
        "id": "11_falhas", "title": "Bot fora do ar e tempo limite da LLM",
        "visual": {"type": "demo", "image": "gui_timeout.jpg", "terms": ["rui", "eva"], "until": 80.0,
                   "since": 73.0, "boxes": [[6, 594, 494, 620]]},
        "text": "Por fim, as falhas do bot. Primeiro, o bot é desligado: quando Rui pergunta, o servidor responde "
                "na hora que o bot está indisponível. Depois, o bot volta com um tempo limite impossível, "
                "de um milésimo de segundo, para simular a demora da LLM. A consulta falha, e o erro, "
                "com o mesmo identificador, vai só para o Rui. Enquanto isso, Eva continua conversando normalmente. "
                "O servidor também tem um prazo próprio de trinta segundos, caso o bot não responda.",
    },
    {
        "id": "12_tls", "title": "Criptografia: TLS com CA própria",
        "visual": {"type": "tls"},
        "text": "Agora, a criptografia. O canal protegido usa TLS sobre os sockets, com o módulo ssl do Python. "
                "Criamos uma autoridade certificadora própria da usina e, com ela, assinamos o certificado do servidor, "
                "válido para localhost e para o endereço cento e vinte e sete ponto zero ponto zero ponto um. "
                "O cliente valida explicitamente essa autoridade e o nome do servidor, e um certificado de outra autoridade é recusado. "
                "Estão protegidos os enlaces do Rui e do bot com o servidor. A decifragem acontece nas pontas de cada enlace: "
                "no servidor, dentro da thread do cliente, e no cliente, na thread receptora.",
    },
    {
        "id": "13_wireshark_claro", "title": "Wireshark: porta 5050 em texto claro",
        "visual": {"type": "image", "path": "evidencias/wireshark_claro.png"},
        "text": "No Wireshark, capturamos a interface de loopback. Na porta cinco mil e cinquenta, "
                "o Follow TCP Stream mostra a mensagem de teste inteira, em JSON: tipo, remetente e conteúdo "
                "podem ser lidos por qualquer pessoa com acesso à rede.",
    },
    {
        "id": "14_wireshark_tls", "title": "Wireshark: porta 5051 com TLS 1.3",
        "visual": {"type": "terminal", "files": ["evidencias/wireshark_tls.txt", "evidencias/wireshark_busca.txt"],
                   "label": "tshark · captura_5050_5051.pcap"},
        "text": "Na porta cinco mil e cinquenta e um, só aparecem o handshake e registros Application Data. "
                "O Server Hello negocia TLS um ponto três, e a chave de sessão é derivada por ECDHE, sem nunca trafegar na rede. "
                "A busca confirma: a mensagem conhecida aparece quatro vezes na porta em texto claro, e nenhuma vez na porta TLS. "
                "Ela só aparece na cinco mil e cinquenta porque o servidor a repassa a clientes sem TLS: a proteção vale por enlace.",
    },
    {
        "id": "15_llm", "title": "Bot com LLM",
        "visual": {"type": "bullets", "items": [
            "Modelo gpt-5.4-nano (OpenAI), Responses API, timeout de 20 s",
            "Responde só com base em knowledge/solar_om.md, em até 5 linhas",
            "Manobra ou religamento: sempre lembra a liberação do engenheiro (NR-10)",
            "Histórico de 6 mensagens por usuário, nunca compartilhado",
            "Pool de 4 threads: a leitura do socket nunca espera a LLM",
            "Chave da API só no .env, fora do repositório",
        ]},
        "text": "Sobre o bot: ele usa o modelo GPT cinco ponto quatro nano, da OpenAI, pela Responses API, "
                "com tempo limite de vinte segundos. A instrução de comportamento manda responder só com base "
                "na base de conhecimento da usina, em português, em até cinco linhas, e lembrar da liberação do engenheiro "
                "em qualquer manobra. Cada pergunta vai para um pool de quatro threads, então a leitura do socket "
                "nunca espera a LLM. E a chave da API fica só no arquivo ponto env, fora do repositório.",
    },
    {
        "id": "16_percurso", "title": "Percurso de uma solicitação ao bot",
        "visual": {"type": "diagram", "name": "percurso"},
        "text": "Resumindo o percurso de uma solicitação: o cliente gera um identificador e envia o pedido pelo socket TLS. "
                "O servidor valida, registra o pedido como pendente, com prazo, e encaminha ao bot. "
                "O bot consulta a LLM e devolve a resposta com o mesmo identificador. "
                "O servidor confere que o pedido está pendente e que o destino é o solicitante, e entrega a resposta só para ele.",
    },
    {
        "id": "17_fim", "title": "Testes e limitações",
        "visual": {"type": "final"},
        "text": "O projeto tem cento e oitenta e nove testes automatizados, com sockets reais, "
                "incluindo testes ponta a ponta com processos separados e um teste de carga com dez clientes simultâneos. "
                "Todos passam. As principais limitações: a proteção é por enlace, e não de ponta a ponta; "
                "não há autenticação de usuário; e o histórico do bot fica em memória. Muito obrigado pela atenção.",
    },
]

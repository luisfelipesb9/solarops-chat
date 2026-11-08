# Base de conhecimento: O&M de usina fotovoltaica (SolarOps)

> **AVISO:** o inversor "SOLX-100" e todos os códigos de falha abaixo são **ILUSTRATIVOS**, criados para este trabalho acadêmico. Não representam nenhum fabricante real. Em campo, vale sempre o manual do fabricante do equipamento instalado.

## 1. Inversor SOLX-100: códigos de falha (ilustrativos)

| Código | Falha | Causa provável | Ação |
|---|---|---|---|
| 2001 | Sobretensão CC | Strings com tensão acima do limite em dia frio e de alta irradiância | Conferir número de módulos por string e tensão de circuito aberto; não religar sem análise |
| 2002 | Subtensão CC | Sombreamento, sujeira, string aberta ou conector solto | Inspecionar a string, limpar módulos e revisar conectores MC4 |
| 2010 | Sobretensão CA | Rede da concessionária acima do limite | Medir tensão no ponto de conexão; acionar a concessionária se persistir |
| 2011 | Subtensão CA | Rede fraca ou cabo CA subdimensionado | Medir tensão e queda no cabo CA; revisar bitola |
| 2020 | Frequência da rede fora da faixa | Instabilidade da rede | Aguardar o retorno automático; se repetir, acionar a concessionária |
| 2025 | Ilhamento detectado | Perda da rede da concessionária | Aguardar o retorno da rede; o inversor religa sozinho após o tempo de reconexão |
| 2032 | Baixa resistência de isolamento CC (falha de isolação) | Cabo CC danificado, conector com umidade, módulo com falha de isolação ou string em contato com a estrutura | Desenergizar conforme NR-10, medir a isolação por string com megôhmetro, isolar a string defeituosa e corrigir antes de religar |
| 2040 | Corrente de fuga (GFCI/RCD) | Fuga à terra no lado CC ou CA | Mesmo tratamento do 2032; investigar aterramento e umidade |
| 2050 | Sobretemperatura do inversor | Ventilação obstruída, filtro sujo ou ambiente quente | Limpar filtros e grades; conferir ventiladores e a folga de instalação |
| 2051 | Falha de ventilador | Ventilador travado ou com defeito | Substituir o ventilador com o inversor desenergizado |
| 2060 | Falha do seccionador CC | Contato desgastado ou acionamento travado | Não manobrar à força; solicitar avaliação do engenheiro responsável |
| 2070 | Falha de comunicação | Cabo de comunicação, antena ou configuração de rede | Conferir cabos e energia do datalogger; reiniciar o módulo de comunicação |

## 2. Medição de isolação com megôhmetro (código 2032)

1. Desenergize e bloqueie o inversor e a string (ver seção 4). Medição de isolação só com o circuito desenergizado.
2. Desconecte a string do inversor nos dois polos (positivo e negativo).
3. Escolha a tensão de ensaio do megôhmetro conforme o manual (valor típico em sistemas de 1000 V CC: 1000 V).
4. Meça entre cada polo (positivo e negativo, curto-circuitados entre si) e a terra, na string desconectada.
5. Compare com o mínimo do fabricante. Como referência ilustrativa deste material: abaixo de 1 MΩ, a string é considerada com falha de isolação.
6. Se reprovar, divida a string em trechos (módulo a módulo) para localizar o ponto de fuga.
7. Registre string, valor medido, data, hora, condição climática e responsável.
8. Descarregue o circuito após o ensaio: o megôhmetro carrega a capacitância dos módulos e dos cabos.

## 3. EPIs para serviço em CC e CA

- Luvas isolantes de borracha de classe adequada à tensão (com luvas de cobertura de couro por cima), com teste de validade em dia.
- Vestimenta antichama (risco de arco elétrico), de acordo com a energia incidente calculada.
- Óculos de proteção (ou protetor facial para risco de arco).
- Capacete de segurança com jugular, classe adequada para trabalho com eletricidade.
- Calçado de segurança isolante (sem biqueira de aço exposta).
- Ferramentas isoladas e detector de tensão adequado à classe de tensão (verificado antes do uso).

Atenção: o lado CC é energizado sempre que houver luz sobre os módulos, mesmo com o inversor desligado.

## 4. Desenergização conforme a NR-10

Etapas, nesta ordem:

1. **Seccionamento:** abrir os dispositivos de seccionamento (CA no disjuntor, CC no seccionador do inversor).
2. **Impedimento de reenergização:** travar e etiquetar os dispositivos abertos (bloqueio e etiquetagem).
3. **Constatação da ausência de tensão:** testar com detector adequado, em todos os condutores, nos lados CA e CC.
4. **Instalação de aterramento temporário:** aterrar e curto-circuitar o circuito, conforme o procedimento.
5. **Proteção dos elementos energizados existentes:** isolar ou barrar partes energizadas próximas à zona de trabalho.
6. **Instalação da sinalização de impedimento de reenergização:** placas e avisos visíveis no local.

Nota ilustrativa: em CC fotovoltaico, a constatação de ausência de tensão deve considerar que as strings continuam geradoras enquanto houver luz; use a abertura de todos os pontos de seccionamento da string.

## 5. Checklist de religamento

- [ ] Causa da falha identificada e corrigida (ex.: isolação da string aprovada na medição).
- [ ] Equipe fora da zona de risco e ferramentas recolhidas.
- [ ] Aterramentos temporários retirados.
- [ ] Sinalização e travas removidas somente por quem as instalou.
- [ ] Inspeção visual do inversor, cabos e conectores concluída.
- [ ] Registro do serviço (o que foi feito, valores medidos, responsáveis) preenchido.
- [ ] Ordem de religamento: primeiro CA, depois CC, com acompanhamento dos valores no inversor.
- [ ] **Liberação do engenheiro responsável obtida.**

## 6. Quem libera

A liberação para religamento e para qualquer manobra é do **engenheiro responsável** (NR-10). Técnicos e o COS executam e registram, mas não substituem essa liberação.

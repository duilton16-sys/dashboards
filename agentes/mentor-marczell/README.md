# Mentor Marczell

Agente de mentoria sobre mentalidade, confiança, crenças, dinheiro e vendas, montado a partir do conteúdo público do canal do hipnotista Marczell Klein: https://www.youtube.com/@marczellk

> É um agente independente, sem ligação com o Marczell Klein. Ele não fala em nome dele e não substitui terapia nem atendimento médico. O Marczell tem um coach de IA oficial (Momentum / Marczell AI), e este agente não é esse produto.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| [`.claude/agents/mentor-marczell.md`](../../.claude/agents/mentor-marczell.md) | O agente: instruções, modos de trabalho e regras de segurança |
| [`base-de-conhecimento.md`](base-de-conhecimento.md) | As ideias do canal organizadas em princípios, com as fontes |
| [`coletar_transcricoes.py`](coletar_transcricoes.py) | Baixa as transcrições dos vídeos (pelo YouTube direto ou pela API da Supadata) para deixar o agente mais completo |
| `transcricoes/` | Criada pelo coletor: uma transcrição por vídeo, mais o `INDICE.md` |

## O que ele faz

- **Mentoria:** você conta o problema e ele encontra a crença por trás, faz a virada com uma ideia do canal e passa uma ação para as próximas 24 horas.
- **Auto-hipnose guiada:** roteiro de 5 a 10 minutos para ler, gravar e ouvir, por exemplo para ganhar confiança antes de gravar, vender ou falar em público.
- **Vendas e persuasão:** frases prontas para ligação, reunião e WhatsApp, sempre com ética.
- **Conteúdo:** roteiros de Reels, legendas e carrosséis na sua voz, com crédito às ideias dele.
- **Pergunte ao canal:** responde "o que o Marczell diz sobre X?" com as fontes.

## Como usar

### No Claude Code, neste repositório

Abra uma sessão no repositório `dashboards` e peça, por exemplo:

- "Use o mentor-marczell: eu travo na hora de gravar Reels. O que eu faço?"
- "Use o mentor-marczell para criar uma auto-hipnose de confiança para antes das reuniões de venda."
- "Use o mentor-marczell para transformar a ideia 'identidade antes de hábito' em 3 roteiros de Reels sobre vendas."

### No app do Claude, como Projeto

1. Crie um Projeto, por exemplo "Mentor Marczell".
2. Nas instruções do projeto, cole o texto de `.claude/agents/mentor-marczell.md` que vem depois do segundo `---`.
3. Nos arquivos do projeto, envie o `base-de-conhecimento.md` e, se já tiver, as transcrições mais relevantes.
4. Converse dentro do projeto.

## Como deixar o agente mais completo

A base de hoje vem de títulos, descrições, entrevistas e reportagens. Os vídeos ainda não foram transcritos, porque o YouTube estava bloqueado na sessão em que o agente foi criado. Com as transcrições, o agente passa a citar o que o Marczell disse de fato, com o minuto do vídeo.

O coletor começa pelos 24 vídeos do YouTube citados na base, inclusive as entrevistas em canais de outras pessoas. Depois passa para os vídeos do canal, nesta ordem: vídeos, lives e shorts. Ele funciona por dois caminhos:

| Caminho | Custo | O que você configura uma vez |
|---|---|---|
| **YouTube direto** | Grátis | Liberar `www.youtube.com` e `youtube.com` no acesso à rede do ambiente |
| **API da Supadata** | 100 créditos grátis por mês, 1 crédito por vídeo com legenda. Buscar o título dos vídeos do canal também pode gastar créditos. | Criar uma conta em https://supadata.ai, cadastrar a chave no ambiente com o nome `SUPADATA_API_KEY` e liberar `api.supadata.ai` no acesso à rede |

As duas configurações ficam no menu do ambiente, na barra de título da sessão → Editar. O passo a passo está em https://code.claude.com/docs/en/cloud-environments#network-access. A chave vai em **Network secrets** ou como variável de ambiente; nunca cole a chave no chat. Quando a chave existe, o coletor usa a Supadata sozinho.

Depois de configurar, abra uma sessão nova e peça: "rode o coletor de transcrições do mentor-marczell e atualize a base".

Com a Supadata, se os créditos acabarem, o coletor para e guarda o que já baixou; no mês seguinte, ele continua de onde parou. Para vídeos sem legenda, a opção `--gerar-com-ia` pede para a Supadata transcrever o áudio, mas isso gasta 2 créditos por minuto de vídeo.

O YouTube às vezes bloqueia servidores na nuvem. Se isso acontecer no caminho direto, use a Supadata ou rode o coletor no seu computador (precisa de Python 3.11 ou mais novo):

```bash
cd agentes/mentor-marczell
pip install -U -r requirements.txt
python coletar_transcricoes.py              # tudo
python coletar_transcricoes.py --limite 30  # só os 30 mais recentes de cada aba do canal
```

Depois, faça commit da pasta `transcricoes/`. Quando você rodar de novo, ele baixa só o que ainda falta.

## Limites

- A base atual é um resumo de fontes públicas, muitas delas promocionais. Números e resultados citados são alegações dele.
- O agente não é terapeuta. Em crise, ligue 188 (CVV) ou 192 (SAMU).

# Corte automático de podcast — v1 (por link)

O que isso faz: você manda o LINK do episódio (YouTube ou Instagram) por
texto pro seu bot do Telegram, e em alguns minutos ele te devolve um corte
de 30-60s já em formato vertical (9:16) com legenda queimada, pronto pra
você revisar e postar no TikTok.

**O que NÃO faz de propósito:** não posta sozinho no TikTok. Isso é
proposital — te protege de corte mal escolhido, erro de legenda, ou áudio
com problema de direitos autorais que a IA não percebeu.

Tudo isso roda de graça, sem precisar de computador — só o navegador do
celular pra configurar uma vez.

## O que você vai precisar (tudo grátis)

1. Uma conta no [GitHub](https://github.com) (se não tiver).
2. Um bot no Telegram, criado em 2 minutos pelo **@BotFather** (dentro do
   próprio Telegram, procura por "BotFather", manda `/newbot` e segue as
   instruções). No final ele te dá um **token** — guarda ele.
3. Uma chave de API grátis da [Groq](https://console.groq.com) (usa pra
   transcrição e pra achar o melhor trecho — tem camada gratuita generosa).
4. Descobrir o **seu chat ID** do Telegram: manda qualquer mensagem pro seu
   bot novo, depois abre no navegador
   `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` e procura o número
   em `"chat":{"id": ...}`.

## Como configurar (tudo pelo celular)

1. Crie um repositório novo no GitHub (pode ser privado) e suba estes
   arquivos mantendo a mesma estrutura de pastas (`.github/workflows/`,
   `scripts/`, `state.json`, `README.md`). Pelo app/site do GitHub dá pra
   fazer upload de arquivo direto, sem precisar de terminal.
2. No repositório, vá em **Settings → Secrets and variables → Actions** e
   crie 3 segredos:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GROQ_API_KEY`
3. Pronto. O workflow em `.github/workflows/pipeline.yml` já está
   configurado pra rodar sozinho a cada 30 minutos.

## Como usar no dia a dia

1. Pega o link do episódio (YouTube ou Instagram) — não precisa mais
   baixar nada manualmente.
2. Cola o link numa mensagem de texto pro seu bot no Telegram.
3. Em até ~30 minutos (ou antes, se você rodar manualmente pela aba
   "Actions" do GitHub) o bot te manda o corte pronto de volta.
4. Você revisa e posta no TikTok.

## Limitações honestas da v1

- **YouTube costuma funcionar liso pra conteúdo público.** Instagram é
  mais instável: reels públicos geralmente baixam bem, mas stories e
  conteúdo de conta privada exigem login (cookies), o que essa versão
  não faz — e ferramentas como yt-dlp quebram com mais frequência no
  Instagram porque a plataforma muda a estrutura do site sem aviso. Se
  os links forem majoritariamente do Instagram e começar a falhar
  bastante, me avisa que a gente vê o que ajustar.
- O GitHub Actions grátis dá ~2.000 minutos/mês em repositório privado —
  de sobra pra 1 corte/dia, mas se você aumentar o volume, fica de olho.
- A IA escolhe só **1 trecho** por episódio nessa versão. Dá pra evoluir
  pra sugerir 3-4 opções depois.
- A legenda queimada é simples (sem estilo/animação). Se quiser algo mais
  bonito, dá pra trocar essa etapa por CapCut manualmente, mantendo o resto
  automático.
- O corte final (que volta pra você) ainda passa pelo Telegram, então se
  o vídeo de saída ficar muito grande isso pode dar problema — mas como é
  só um clipe de 30-60s, dificilmente vai bater nesse limite.
- Groq tem limite de requisições grátis por minuto/dia — não é ilimitado.
  Se dependência disso for e virar um problema, o serviço muda.

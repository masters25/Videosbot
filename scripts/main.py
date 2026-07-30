"""
Pipeline de corte automático de podcast — versão "cola o link".

Fluxo:
1. Você manda o LINK do episódio (YouTube, Instagram ou TikTok) por texto
   pro seu bot do Telegram.
2. Este script (rodando no GitHub Actions) detecta a mensagem nova.
3. Baixa o vídeo do link com yt-dlp.
4. Transcreve o episódio (Groq Whisper).
5. Pede pra uma IA achar o trecho mais forte pra virar corte (Groq Llama).
6. Corta esse trecho com ffmpeg, redimensiona pra 9:16 e queima a legenda.
7. Manda o corte pronto de volta pra você no Telegram, pra revisar e postar.

NADA disso posta automaticamente no TikTok — essa etapa fica com você de
propósito (é o seu checkpoint de qualidade e direitos autorais).
"""

import json
import os
import pathlib
import re
import subprocess
import tempfile

import requests
import yt_dlp

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1"

STATE_FILE = pathlib.Path("state.json")
URL_RE = re.compile(r"https?://\S+")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_update_id": 0}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def tg_send_message(text):
    requests.post(f"{TELEGRAM_API}/sendMessage", data={"chat_id": CHAT_ID, "text": text})


def get_new_link_update(state):
    """Verifica se há uma mensagem de texto nova no bot contendo um link."""
    resp = requests.get(
        f"{TELEGRAM_API}/getUpdates",
        params={"offset": state["last_update_id"] + 1, "timeout": 0},
    )
    resp.raise_for_status()
    updates = resp.json().get("result", [])

    url = None
    highest_update_id = state["last_update_id"]

    for update in updates:
        highest_update_id = max(highest_update_id, update["update_id"])
        msg = update.get("message", {})
        if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
            continue
        text = msg.get("text", "")
        match = URL_RE.search(text)
        if match and url is None:
            url = match.group(0)

    state["last_update_id"] = highest_update_id
    return url


COOKIES_FILE = "cookies.txt"


def list_formats_diagnostic(url):
    """Lista os formatos que a plataforma está oferecendo pra esse link,
    sem baixar nada — só pra diagnóstico."""
    ydl_opts = {"quiet": True, "noplaylist": True, "skip_download": True}
    if pathlib.Path(COOKIES_FILE).exists():
        ydl_opts["cookiefile"] = COOKIES_FILE
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get("formats", []) or []
        linhas = []
        for f in formats:
            linhas.append(
                f"id={f.get('format_id')} vcodec={f.get('vcodec')} "
                f"acodec={f.get('acodec')} ext={f.get('ext')} "
                f"nota={f.get('format_note')}"
            )
        return "\n".join(linhas) if linhas else "(nenhum formato listado)"
    except Exception as e:
        return f"(não consegui listar formatos: {e})"


def check_has_audio(path):
    """Usa ffprobe pra checar se o arquivo baixado tem alguma trilha de áudio."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    streams = result.stdout.strip().splitlines()
    return "audio" in streams


def format_for_url(url):
    """Cada plataforma entrega o arquivo de um jeito diferente:

    - YouTube separa vídeo e áudio em faixas distintas (precisa pedir os
      dois e deixar o yt-dlp juntar).
    - TikTok e Instagram normalmente já entregam um único arquivo com
      vídeo+áudio juntos — pedir "bestvideo+bestaudio" nesses casos pode
      fazer o yt-dlp tentar juntar a mesma faixa com ela mesma e perder o
      áudio no processo, então aqui é melhor só pedir "best" direto.
    """
    dominio = url.lower()
    if "youtube.com" in dominio or "youtu.be" in dominio:
        return "bestvideo+bestaudio/best"
    return "best"


def download_via_ytdlp(url, dest_path_no_ext):
    """Baixa o link (YouTube, Instagram ou TikTok) usando yt-dlp.

    Se existir um cookies.txt na raiz do repositório (escrito pelo workflow
    a partir do segredo YOUTUBE_COOKIES), usa ele pra autenticar — ajuda a
    driblar bloqueios de login, mas não garante 100% de sucesso.
    """
    ydl_opts = {
        "outtmpl": dest_path_no_ext + ".%(ext)s",
        "format": format_for_url(url),
        "merge_output_format": "mp4",
        "quiet": True,
        "noplaylist": True,
    }
    if pathlib.Path(COOKIES_FILE).exists():
        ydl_opts["cookiefile"] = COOKIES_FILE
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    print(f"Formato baixado: {info.get('format_id')} / {info.get('format')}")

    # Acha o arquivo baixado (extensão pode variar)
    parent = pathlib.Path(dest_path_no_ext).parent
    stem = pathlib.Path(dest_path_no_ext).name
    for f in parent.glob(f"{stem}.*"):
        return str(f)
    raise FileNotFoundError("yt-dlp não gerou o arquivo esperado.")


def transcribe(audio_path):
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    with open(audio_path, "rb") as f:
        r = requests.post(
            f"{GROQ_API}/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": f},
            data={"model": "whisper-large-v3", "response_format": "verbose_json"},
        )
    if not r.ok:
        raise RuntimeError(
            f"Groq recusou a transcrição (arquivo de {size_mb:.1f}MB, "
            f"HTTP {r.status_code}): {r.text[:500]}"
        )
    return r.json()


def find_highlight(transcript):
    segments = transcript.get("segments", [])
    transcript_text = "\n".join(
        f'[{s["start"]:.1f}-{s["end"]:.1f}] {s["text"]}' for s in segments
    )
    prompt = (
        "Você é um editor de cortes virais de podcast brasileiro. "
        "Aqui está a transcrição com timestamps em segundos:\n\n"
        f"{transcript_text}\n\n"
        "Escolha o TRECHO MAIS FORTE pra virar um corte de 30 a 60 segundos "
        "(momento de maior impacto, polêmica, humor ou insight, que funcione "
        "sozinho fora de contexto). Responda SOMENTE em JSON no formato: "
        '{"start": <segundos, número>, "end": <segundos, número>, '
        '"legenda": "<legenda curta e chamativa pro TikTok>"}'
    )
    r = requests.post(
        f"{GROQ_API}/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
    )
    if not r.ok:
        raise RuntimeError(f"Groq recusou a análise (HTTP {r.status_code}): {r.text[:500]}")
    content = r.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def format_srt_timestamp(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments, clip_start, clip_end, path):
    lines = []
    idx = 1
    for seg in segments:
        if seg["end"] <= clip_start or seg["start"] >= clip_end:
            continue
        start = max(seg["start"], clip_start) - clip_start
        end = min(seg["end"], clip_end) - clip_start
        lines.append(str(idx))
        lines.append(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}")
        lines.append(seg["text"].strip())
        lines.append("")
        idx += 1
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")


def cut_and_format(source_path, start, end, segments, out_path, work_dir):
    duration = max(1.0, end - start)
    srt_path = os.path.join(work_dir, "clip.srt")
    write_srt(segments, start, end, srt_path)

    vf = f"crop=ih*9/16:ih,scale=1080:1920,subtitles='{srt_path}'"
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start), "-i", source_path, "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    subprocess.run(cmd, check=True)


def send_result(video_path, caption):
    with open(video_path, "rb") as f:
        requests.post(
            f"{TELEGRAM_API}/sendVideo",
            data={"chat_id": CHAT_ID, "caption": caption[:1024]},
            files={"video": f},
        )


def main():
    state = load_state()
    url = get_new_link_update(state)
    save_state(state)

    if not url:
        print("Nenhum link novo.")
        return

    tg_send_message("Recebi o link! Baixando e processando o corte...")

    with tempfile.TemporaryDirectory() as tmp:
        try:
            source_path = download_via_ytdlp(url, os.path.join(tmp, "episodio"))
        except Exception as e:
            tg_send_message(
                f"Não consegui baixar esse link (pode ser conteúdo privado ou "
                f"que exige login). Erro: {e}"
            )
            return

        if not check_has_audio(source_path):
            formatos = list_formats_diagnostic(url)
            print("Formatos disponíveis para esse link:\n" + formatos)
            tg_send_message(
                "O vídeo baixou, mas sem nenhuma trilha de áudio (nem a "
                "música de fundo). Provavelmente essa plataforma não libera "
                "essa faixa específica pra download. Detalhes no log do "
                "GitHub Actions (aba Actions → essa execução → log completo)."
            )
            return

        try:
            transcript = transcribe(source_path)
            highlight = find_highlight(transcript)

            out_path = os.path.join(tmp, "corte.mp4")
            cut_and_format(
                source_path,
                float(highlight["start"]),
                float(highlight["end"]),
                transcript.get("segments", []),
                out_path,
                tmp,
            )

            send_result(out_path, highlight.get("legenda", ""))
        except Exception as e:
            tg_send_message(f"Deu erro processando o corte. Motivo: {e}")
            raise

    tg_send_message("Corte pronto! Dá uma olhada e posta no TikTok se estiver bom 🚀")


if __name__ == "__main__":
    main()

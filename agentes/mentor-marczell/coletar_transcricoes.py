#!/usr/bin/env python3
"""Baixa as transcrições de um canal do YouTube para a base do agente mentor-marczell.

Lista os vídeos do canal (abas Vídeos, Shorts e Ao vivo), baixa a legenda de
cada um e salva em Markdown, um arquivo por vídeo, na pasta transcricoes/,
junto com um INDICE.md. Rodar de novo só baixa o que ainda não foi salvo.

Uso:
    pip install -U -r requirements.txt
    python coletar_transcricoes.py
    python coletar_transcricoes.py --limite 30 --abas videos,shorts
    python coletar_transcricoes.py --canal https://www.youtube.com/@outrocanal
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

try:
    import yt_dlp
    from youtube_transcript_api import (
        AgeRestricted,
        CouldNotRetrieveTranscript,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
        VideoUnplayable,
        YouTubeTranscriptApi,
    )
except ImportError:
    sys.exit("Faltam dependências. Rode: pip install -U -r requirements.txt")

CANAL_PADRAO = "https://www.youtube.com/@marczellk"
PASTA_PADRAO = Path(__file__).resolve().parent / "transcricoes"
NOMES_ABAS = {"videos": "Vídeos", "shorts": "Shorts", "streams": "Ao vivo"}
MAX_FALHAS_SEGUIDAS = 5
DICA_ACESSO = (
    "Numa sessão do Claude na nuvem, libere youtube.com e www.youtube.com no acesso à rede "
    "do ambiente (https://code.claude.com/docs/en/cloud-environments#network-access). "
    "Outra opção é rodar este script no seu computador."
)


class SemAcesso(Exception):
    """Não foi possível listar nenhuma aba do canal."""


class _Silencioso:
    """Logger do yt-dlp que não imprime nada; os erros chegam como exceção."""

    def debug(self, msg):
        pass

    info = warning = error = debug


def listar_videos(canal: str, abas: list[str], limite: int | None) -> list[dict]:
    opcoes = {"extract_flat": "in_playlist", "quiet": True, "logger": _Silencioso()}
    if limite:
        opcoes["playlistend"] = limite
    videos, vistos, erros = [], set(), {}
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        for aba in abas:
            try:
                info = ydl.extract_info(f"{canal.rstrip('/')}/{aba}", download=False)
            except yt_dlp.utils.DownloadError as erro:
                # Tira o prefixo e o pedido padrão do yt-dlp para abrir issue.
                erros[aba] = str(erro).removeprefix("ERROR: ").split("; please report this issue")[0]
                continue
            for item in (info or {}).get("entries") or []:
                if item and item.get("id") and item["id"] not in vistos:
                    vistos.add(item["id"])
                    videos.append({"id": item["id"], "titulo": item.get("title") or item["id"], "aba": aba})
    if len(erros) == len(abas):
        raise SemAcesso(next(iter(erros.values()), "nenhuma aba informada"))
    for aba, motivo in erros.items():  # ex.: o canal não tem aba de lives
        print(f"  aba '{aba}' ignorada: {motivo}", file=sys.stderr)
    return videos


def baixar_legenda(api: YouTubeTranscriptApi, video_id: str, idiomas: list[str]):
    try:
        return api.fetch(video_id, languages=idiomas)
    except NoTranscriptFound:
        # Sem legenda nos idiomas pedidos: usa a primeira que existir.
        for transcricao in api.list(video_id):
            return transcricao.fetch()
        raise


def tempo(segundos: float) -> str:
    s = int(segundos)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def formatar(legenda, intervalo: float = 60) -> str:
    """Junta os trechos da legenda em parágrafos de ~1 minuto, com o tempo de início."""
    blocos, atual, inicio = [], [], 0.0
    for trecho in legenda.snippets:
        texto = " ".join(trecho.text.split())
        if not texto:
            continue
        if atual and trecho.start - inicio >= intervalo:
            blocos.append((inicio, " ".join(atual)))
            atual = []
        if not atual:
            inicio = trecho.start
        atual.append(texto)
    if atual:
        blocos.append((inicio, " ".join(atual)))
    return "\n\n".join(f"**[{tempo(i)}]** {texto}" for i, texto in blocos)


def salvar(video: dict, legenda, pasta: Path) -> None:
    tipo = "automática" if legenda.is_generated else "manual"
    conteudo = (
        f"# {video['titulo']}\n\n"
        f"- Link: https://www.youtube.com/watch?v={video['id']}\n"
        f"- Aba do canal: {NOMES_ABAS.get(video['aba'], video['aba'])}\n"
        f"- Legenda: {legenda.language} ({tipo})\n"
        f"- Coletado em: {dt.date.today().isoformat()}\n\n"
        f"## Transcrição\n\n{formatar(legenda)}\n"
    )
    (pasta / f"{video['id']}.md").write_text(conteudo, encoding="utf-8")


def situacao_do_erro(erro: Exception) -> str:
    if isinstance(erro, (NoTranscriptFound, TranscriptsDisabled)):
        return "sem legenda"
    if isinstance(erro, AgeRestricted):
        return "restrito por idade"
    if isinstance(erro, (VideoUnavailable, VideoUnplayable)):
        return "indisponível"
    return f"erro ({type(erro).__name__})"


def _md(texto: str) -> str:
    return texto.replace("|", "/").replace("[", "(").replace("]", ")")


def escrever_indice(pasta: Path, canal: str, videos: list[dict], situacoes: dict[str, str]) -> int:
    linhas, transcritos = [], 0
    for v in videos:
        aba = NOMES_ABAS.get(v["aba"], v["aba"])
        if (pasta / f"{v['id']}.md").exists():
            transcritos += 1
            linhas.append(f"| [{_md(v['titulo'])}]({v['id']}.md) | {aba} | transcrito |")
        else:
            link = f"https://www.youtube.com/watch?v={v['id']}"
            linhas.append(f"| [{_md(v['titulo'])}]({link}) | {aba} | {situacoes.get(v['id'], 'pendente')} |")
    cabecalho = [
        f"# Transcrições: {canal}",
        "",
        f"Atualizado em {dt.date.today().isoformat()}. {transcritos} de {len(videos)} vídeos com transcrição.",
        "",
        "| Vídeo | Aba | Situação |",
        "|---|---|---|",
    ]
    (pasta / "INDICE.md").write_text("\n".join(cabecalho + linhas) + "\n", encoding="utf-8")
    return transcritos


def main() -> int:
    parser = argparse.ArgumentParser(description="Baixa as transcrições de um canal do YouTube para a base do agente.")
    parser.add_argument("--canal", default=CANAL_PADRAO, help="URL do canal (padrão: %(default)s)")
    parser.add_argument("--abas", default="videos,shorts,streams", help="abas do canal, separadas por vírgula (padrão: %(default)s)")
    parser.add_argument("--limite", type=int, help="máximo de vídeos por aba, dos mais novos para os mais antigos")
    parser.add_argument("--idiomas", default="en,pt", help="idiomas de legenda em ordem de preferência (padrão: %(default)s)")
    parser.add_argument("--pausa", type=float, default=1.5, help="segundos de espera entre vídeos (padrão: %(default)s)")
    parser.add_argument("--saida", type=Path, default=PASTA_PADRAO, help="pasta de saída (padrão: transcricoes/ ao lado deste script)")
    args = parser.parse_args()

    abas = [a.strip() for a in args.abas.split(",") if a.strip()]
    idiomas = [i.strip() for i in args.idiomas.split(",") if i.strip()]

    print(f"Listando os vídeos de {args.canal} ...")
    try:
        videos = listar_videos(args.canal, abas, args.limite)
    except SemAcesso as erro:
        print(f"Não consegui acessar o YouTube: {erro}\n{DICA_ACESSO}", file=sys.stderr)
        return 2

    args.saida.mkdir(parents=True, exist_ok=True)
    pendentes = [v for v in videos if not (args.saida / f"{v['id']}.md").exists()]
    print(f"{len(videos)} vídeos encontrados; {len(pendentes)} ainda sem transcrição.")

    api = YouTubeTranscriptApi()
    situacoes: dict[str, str] = {}
    novos = falhas_seguidas = 0
    interrompido = False
    for n, video in enumerate(pendentes, 1):
        if n > 1:
            time.sleep(args.pausa)
        print(f"[{n}/{len(pendentes)}] {video['titulo']}")
        try:
            legenda = baixar_legenda(api, video["id"], idiomas)
        except RequestBlocked:
            print("O YouTube bloqueou as requisições deste IP, o que é comum em servidores na nuvem.\n"
                  "Rode este script no seu computador.", file=sys.stderr)
            interrompido = True
            break
        except Exception as erro:  # legenda ausente, vídeo indisponível ou falha de rede
            situacoes[video["id"]] = situacao_do_erro(erro)
            print(f"  {situacoes[video['id']]}")
            if isinstance(erro, CouldNotRetrieveTranscript):
                falhas_seguidas = 0  # o YouTube respondeu; o problema é só deste vídeo
                continue
            falhas_seguidas += 1
            if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                print(f"{falhas_seguidas} falhas seguidas; verifique a conexão.\n{DICA_ACESSO}", file=sys.stderr)
                interrompido = True
                break
            continue
        salvar(video, legenda, args.saida)
        novos += 1
        falhas_seguidas = 0

    transcritos = escrever_indice(args.saida, args.canal, videos, situacoes)
    print(f"\n{novos} transcrições novas. Total: {transcritos} de {len(videos)} vídeos.")
    print(f"Índice: {args.saida / 'INDICE.md'}")
    return 2 if interrompido else 0


if __name__ == "__main__":
    sys.exit(main())

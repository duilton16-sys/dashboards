#!/usr/bin/env python3
"""Baixa as transcrições do canal @marczellk para a base do agente mentor-marczell.

Fontes:
  youtube   Acessa o YouTube direto, de graça e sem chave.
            Precisa de www.youtube.com e youtube.com liberados na rede.
  supadata  Usa a API da Supadata (https://supadata.ai). Precisa da variável de
            ambiente SUPADATA_API_KEY e de api.supadata.ai liberado na rede.
            É escolhida automaticamente quando a variável existe.

Além dos vídeos do canal, baixa os vídeos do YouTube citados em
base-de-conhecimento.md, como as entrevistas em outros canais, e começa por eles.
Salva um arquivo .md por vídeo em transcricoes/, mais o INDICE.md. Rodar de novo
só baixa o que ainda não foi salvo.

Uso:
    pip install -U -r requirements.txt
    python coletar_transcricoes.py
    python coletar_transcricoes.py --limite 30 --abas videos,streams
    python coletar_transcricoes.py --fonte supadata
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PASTA = Path(__file__).resolve().parent
CANAL_PADRAO = "https://www.youtube.com/@marczellk"
NOMES_ABAS = {"base": "Citado na base", "videos": "Vídeos", "shorts": "Shorts", "streams": "Ao vivo"}
LINK_YOUTUBE = re.compile(r"youtube\.com/(?:watch\?v=|shorts/)([\w-]{11})")
MAX_FALHAS_SEGUIDAS = 5
DICA_REDE = (
    "Numa sessão do Claude na nuvem, libere o endereço no acesso à rede do ambiente "
    "(https://code.claude.com/docs/en/cloud-environments#network-access): www.youtube.com e "
    "youtube.com para a fonte youtube, ou api.supadata.ai para a fonte supadata. "
    "Outra opção é rodar este script no seu computador."
)


class SemAcesso(Exception):
    """A fonte não está acessível (rede, bloqueio, chave ou créditos); não adianta continuar."""


class SemCreditos(SemAcesso):
    """A Supadata recusou por falta de créditos ou porque o recurso não está no plano."""


class SemLegenda(Exception):
    """Só este vídeo não tem transcrição disponível."""


@dataclass
class Legenda:
    trechos: list[tuple[float, str]]  # (segundos desde o início, texto)
    descricao: str  # idioma e tipo, por exemplo "English (automática)"


def link(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# --- Fonte 1: YouTube direto -------------------------------------------------


class _Silencioso:
    """Logger do yt-dlp que não imprime nada; os erros chegam como exceção."""

    def debug(self, msg):
        pass

    info = warning = error = debug


class FonteYouTube:
    nome = "YouTube direto"

    def __init__(self, idiomas: list[str]):
        try:
            import yt_dlp
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            sys.exit("Faltam dependências. Rode: pip install -U -r requirements.txt")
        self.yt_dlp = yt_dlp
        self.api = YouTubeTranscriptApi()
        self.idiomas = idiomas

    def listar(self, canal: str, abas: list[str], limite: int | None) -> list[dict]:
        opcoes = {"extract_flat": "in_playlist", "quiet": True, "logger": _Silencioso()}
        if limite:
            opcoes["playlistend"] = limite
        videos, erros = [], {}
        with self.yt_dlp.YoutubeDL(opcoes) as ydl:
            for aba in abas:
                try:
                    info = ydl.extract_info(f"{canal.rstrip('/')}/{aba}", download=False)
                except self.yt_dlp.utils.DownloadError as erro:
                    # Tira o prefixo e o pedido padrão do yt-dlp para abrir issue.
                    erros[aba] = str(erro).removeprefix("ERROR: ").split("; please report this issue")[0]
                    continue
                for item in (info or {}).get("entries") or []:
                    if item and item.get("id"):
                        videos.append({"id": item["id"], "titulo": item.get("title"), "aba": aba})
        if abas and len(erros) == len(abas):
            raise SemAcesso(next(iter(erros.values())))
        for aba, motivo in erros.items():  # ex.: o canal não tem aba de lives
            print(f"  aba '{aba}' ignorada: {motivo}", file=sys.stderr)
        return videos

    def legenda(self, video_id: str) -> Legenda:
        from youtube_transcript_api import (
            AgeRestricted,
            CouldNotRetrieveTranscript,
            NoTranscriptFound,
            RequestBlocked,
            TranscriptsDisabled,
            VideoUnavailable,
            VideoUnplayable,
        )

        try:
            try:
                dados = self.api.fetch(video_id, languages=self.idiomas)
            except NoTranscriptFound:
                # Sem legenda nos idiomas pedidos: usa a primeira que existir.
                outra = next(iter(self.api.list(video_id)), None)
                if outra is None:
                    raise
                dados = outra.fetch()
        except RequestBlocked as erro:
            raise SemAcesso("o YouTube bloqueou as requisições deste IP, o que é comum em servidores na nuvem") from erro
        except (NoTranscriptFound, TranscriptsDisabled) as erro:
            raise SemLegenda("sem legenda") from erro
        except AgeRestricted as erro:
            raise SemLegenda("restrito por idade") from erro
        except (VideoUnavailable, VideoUnplayable) as erro:
            raise SemLegenda("indisponível") from erro
        except CouldNotRetrieveTranscript as erro:
            raise SemLegenda(f"erro ({type(erro).__name__})") from erro
        tipo = "automática" if dados.is_generated else "manual"
        return Legenda([(t.start, t.text) for t in dados.snippets], f"{dados.language} ({tipo})")

    def titulo(self, video_id: str) -> str | None:
        return None  # a listagem do yt-dlp já traz os títulos


# --- Fonte 2: API da Supadata ------------------------------------------------


class FonteSupadata:
    nome = "API da Supadata"
    URL = "https://api.supadata.ai/v1"
    TIPOS = {"videos": ("video", "videoIds"), "shorts": ("short", "shortIds"), "streams": ("live", "liveIds")}

    def __init__(self, chave: str, idiomas: list[str], gerar_com_ia: bool, intervalo: float = 1.1):
        try:
            import requests
        except ImportError:
            sys.exit("Faltam dependências. Rode: pip install -U -r requirements.txt")
        self.requests = requests
        self.sessao = requests.Session()
        self.sessao.headers["x-api-key"] = chave
        self.idioma = idiomas[0] if idiomas else None
        # native: só legendas que já existem (1 crédito por vídeo).
        # auto: se não houver legenda, a Supadata gera com IA (2 créditos por minuto de vídeo).
        self.modo = "auto" if gerar_com_ia else "native"
        self.intervalo = intervalo  # o plano grátis aceita 1 requisição por segundo
        self._ultima = 0.0

    def _get(self, caminho: str, **parametros) -> tuple[int, dict]:
        parametros = {k: v for k, v in parametros.items() if v is not None}
        for tentativa in range(2):
            espera = self._ultima + self.intervalo - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            try:
                resposta = self.sessao.get(self.URL + caminho, params=parametros, timeout=90)
            except self.requests.RequestException as erro:
                raise SemAcesso(f"não consegui falar com a Supadata ({type(erro).__name__})") from erro
            finally:
                self._ultima = time.monotonic()
            if resposta.status_code != 429 or tentativa:
                break
            time.sleep(5)  # limite de requisições: espera um pouco e tenta de novo
        try:
            dados = resposta.json()
        except ValueError:
            dados = {}
        if not isinstance(dados, dict):
            dados = {}
        codigo = resposta.status_code
        if codigo in (401, 403):
            raise SemAcesso("a Supadata recusou a chave (confira a SUPADATA_API_KEY)")
        if codigo == 402:
            raise SemCreditos("acabaram os créditos da Supadata ou o recurso não está no seu plano")
        if codigo == 429:
            raise SemAcesso("a Supadata limitou as requisições; tente de novo mais tarde")
        if codigo >= 400:
            raise SemLegenda(str(dados.get("message") or dados.get("error") or f"HTTP {codigo}"))
        return codigo, dados

    def listar(self, canal: str, abas: list[str], limite: int | None) -> list[dict]:
        videos = []
        for aba in abas:
            if aba not in self.TIPOS:
                print(f"  aba '{aba}' ignorada: a Supadata só conhece {', '.join(self.TIPOS)}", file=sys.stderr)
                continue
            tipo, campo = self.TIPOS[aba]
            try:
                _, dados = self._get("/youtube/channel/videos", id=canal, type=tipo, limit=limite or 5000)
            except (SemLegenda, SemCreditos) as erro:
                # Se a listagem não estiver no plano, ainda dá para baixar os vídeos citados na base.
                print(f"  aba '{aba}' ignorada: {erro}", file=sys.stderr)
                continue
            videos += [{"id": vid, "titulo": None, "aba": aba} for vid in dados.get(campo) or []]
        return videos

    def legenda(self, video_id: str) -> Legenda:
        codigo, dados = self._get("/transcript", url=link(video_id), lang=self.idioma, mode=self.modo)
        if codigo == 202:  # transcrição longa ou gerada por IA: a Supadata devolve um job para acompanhar
            trabalho = dados.get("jobId")
            for _ in range(150):  # até ~5 minutos
                time.sleep(2)
                _, dados = self._get(f"/transcript/{trabalho}")
                if dados.get("status") == "completed":
                    break
                if dados.get("status") == "failed":
                    raise SemLegenda(str(dados.get("error") or "a Supadata não conseguiu gerar a transcrição"))
            else:
                raise SemLegenda("a Supadata demorou demais para gerar a transcrição")
        conteudo = dados.get("content") or []
        if isinstance(conteudo, str):
            trechos = [(0.0, conteudo)]
        else:
            trechos = [((item.get("offset") or 0) / 1000, item.get("text") or "") for item in conteudo]
        if not any(texto.strip() for _, texto in trechos):
            raise SemLegenda("sem legenda")
        return Legenda(trechos, f"{dados.get('lang') or '?'} (via Supadata)")

    def titulo(self, video_id: str) -> str | None:
        """Busca o título nos metadados. Se não der, o arquivo fica com o ID do vídeo."""
        try:
            _, dados = self._get("/metadata", url=link(video_id))
        except (SemAcesso, SemLegenda):
            return None
        return dados.get("title")


# --- Vídeos citados na base --------------------------------------------------


def videos_da_base(arquivo: Path) -> list[dict]:
    """Pega os links do YouTube das tabelas da base. O título é a 2ª coluna da linha."""
    if not arquivo.exists():
        return []
    videos, vistos = [], set()
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        celulas = [c.strip() for c in linha.strip().strip("|").split("|")]
        for video_id in LINK_YOUTUBE.findall(linha):
            if video_id in vistos:
                continue
            vistos.add(video_id)
            titulo = celulas[1] if linha.lstrip().startswith("|") and len(celulas) >= 3 else None
            videos.append({"id": video_id, "titulo": titulo, "aba": "base"})
    return videos


# --- Saída -------------------------------------------------------------------


def tempo(segundos: float) -> str:
    s = int(segundos)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def formatar(legenda: Legenda, intervalo: float = 60) -> str:
    """Junta os trechos da legenda em parágrafos de ~1 minuto, com o tempo de início."""
    blocos, atual, inicio = [], [], 0.0
    for comeco, texto in legenda.trechos:
        texto = " ".join(texto.split())
        if not texto:
            continue
        if atual and comeco - inicio >= intervalo:
            blocos.append((inicio, " ".join(atual)))
            atual = []
        if not atual:
            inicio = comeco
        atual.append(texto)
    if atual:
        blocos.append((inicio, " ".join(atual)))
    return "\n\n".join(f"**[{tempo(i)}]** {texto}" for i, texto in blocos)


def salvar(video: dict, legenda: Legenda, pasta: Path) -> None:
    conteudo = (
        f"# {video['titulo'] or video['id']}\n\n"
        f"- Link: {link(video['id'])}\n"
        f"- Origem: {NOMES_ABAS.get(video['aba'], video['aba'])}\n"
        f"- Legenda: {legenda.descricao}\n"
        f"- Coletado em: {dt.date.today().isoformat()}\n\n"
        f"## Transcrição\n\n{formatar(legenda)}\n"
    )
    (pasta / f"{video['id']}.md").write_text(conteudo, encoding="utf-8")


def _md(texto: str) -> str:
    return texto.replace("|", "/").replace("[", "(").replace("]", ")")


def titulo_salvo(arquivo: Path) -> str | None:
    """Lê o título da 1ª linha de uma transcrição já salva."""
    with arquivo.open(encoding="utf-8") as f:
        primeira = f.readline().strip()
    return primeira.removeprefix("# ") or None


def escrever_indice(pasta: Path, canal: str, videos: list[dict], situacoes: dict[str, str]) -> int:
    linhas, transcritos = [], 0
    for v in videos:
        origem = NOMES_ABAS.get(v["aba"], v["aba"])
        arquivo = pasta / f"{v['id']}.md"
        if arquivo.exists():
            transcritos += 1
            titulo = v["titulo"] or titulo_salvo(arquivo) or v["id"]
            linhas.append(f"| [{_md(titulo)}]({v['id']}.md) | {origem} | transcrito |")
        else:
            titulo = v["titulo"] or v["id"]
            linhas.append(f"| [{_md(titulo)}]({link(v['id'])}) | {origem} | {situacoes.get(v['id'], 'pendente')} |")
    cabecalho = [
        f"# Transcrições: {canal}",
        "",
        f"Atualizado em {dt.date.today().isoformat()}. {transcritos} de {len(videos)} vídeos com transcrição.",
        "",
        "| Vídeo | Origem | Situação |",
        "|---|---|---|",
    ]
    (pasta / "INDICE.md").write_text("\n".join(cabecalho + linhas) + "\n", encoding="utf-8")
    return transcritos


# --- Programa ----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Baixa as transcrições do canal para a base do agente.")
    parser.add_argument("--fonte", choices=("auto", "youtube", "supadata"), default="auto",
                        help="de onde baixar; auto usa a Supadata se SUPADATA_API_KEY existir (padrão: %(default)s)")
    parser.add_argument("--canal", default=CANAL_PADRAO, help="URL do canal (padrão: %(default)s)")
    parser.add_argument("--abas", default="videos,streams,shorts",
                        help="abas do canal, separadas por vírgula, na ordem de prioridade (padrão: %(default)s)")
    parser.add_argument("--limite", type=int, help="máximo de vídeos por aba, dos mais novos para os mais antigos")
    parser.add_argument("--idiomas", default="en,pt", help="idiomas de legenda em ordem de preferência (padrão: %(default)s)")
    parser.add_argument("--sem-base", action="store_true", help="não baixar os vídeos citados na base de conhecimento")
    parser.add_argument("--gerar-com-ia", action="store_true",
                        help="Supadata: gerar transcrição com IA quando o vídeo não tiver legenda (gasta mais créditos)")
    parser.add_argument("--pausa", type=float, default=1.5, help="segundos de espera entre vídeos (padrão: %(default)s)")
    parser.add_argument("--base", type=Path, default=PASTA / "base-de-conhecimento.md", help=argparse.SUPPRESS)
    parser.add_argument("--saida", type=Path, default=PASTA / "transcricoes",
                        help="pasta de saída (padrão: transcricoes/ ao lado deste script)")
    args = parser.parse_args()

    abas = [a.strip() for a in args.abas.split(",") if a.strip()]
    idiomas = [i.strip() for i in args.idiomas.split(",") if i.strip()]
    chave = os.environ.get("SUPADATA_API_KEY", "").strip()
    fonte_escolhida = args.fonte if args.fonte != "auto" else ("supadata" if chave else "youtube")
    if fonte_escolhida == "supadata":
        if not chave:
            print("Defina a variável de ambiente SUPADATA_API_KEY com a sua chave da Supadata.", file=sys.stderr)
            return 2
        fonte = FonteSupadata(chave, idiomas, args.gerar_com_ia)
    else:
        fonte = FonteYouTube(idiomas)
    print(f"Fonte: {fonte.nome}")

    videos = [] if args.sem_base else videos_da_base(args.base)
    print(f"{len(videos)} vídeos citados na base. Listando os vídeos de {args.canal} ...")
    try:
        do_canal = fonte.listar(args.canal, abas, args.limite)
    except SemAcesso as erro:
        print(f"Não consegui acessar a fonte: {erro}\n{DICA_REDE}", file=sys.stderr)
        return 2
    ids = {v["id"] for v in videos}
    for video in do_canal:
        if video["id"] not in ids:
            ids.add(video["id"])
            videos.append(video)

    args.saida.mkdir(parents=True, exist_ok=True)
    pendentes = [v for v in videos if not (args.saida / f"{v['id']}.md").exists()]
    print(f"{len(do_canal)} vídeos no canal, {len(videos)} no total; {len(pendentes)} ainda sem transcrição.")

    situacoes: dict[str, str] = {}
    novos = falhas_seguidas = 0
    interrompido = False
    for n, video in enumerate(pendentes, 1):
        if n > 1 and args.pausa:
            time.sleep(args.pausa)
        print(f"[{n}/{len(pendentes)}] {video['titulo'] or video['id']}")
        try:
            legenda = fonte.legenda(video["id"])
        except SemAcesso as erro:
            print(f"Parei: {erro}.\n{DICA_REDE}", file=sys.stderr)
            interrompido = True
            break
        except SemLegenda as erro:
            situacoes[video["id"]] = str(erro)
            print(f"  {erro}")
            falhas_seguidas = 0  # a fonte respondeu; o problema é só deste vídeo
            continue
        except Exception as erro:  # falha de rede ou resposta inesperada
            situacoes[video["id"]] = f"erro ({type(erro).__name__})"
            print(f"  {situacoes[video['id']]}")
            falhas_seguidas += 1
            if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                print(f"{falhas_seguidas} falhas seguidas; verifique a conexão.\n{DICA_REDE}", file=sys.stderr)
                interrompido = True
                break
            continue
        if not video["titulo"]:
            video["titulo"] = fonte.titulo(video["id"])
        salvar(video, legenda, args.saida)
        novos += 1
        falhas_seguidas = 0

    transcritos = escrever_indice(args.saida, args.canal, videos, situacoes)
    print(f"\n{novos} transcrições novas. Total: {transcritos} de {len(videos)} vídeos.")
    print(f"Índice: {args.saida / 'INDICE.md'}")
    return 2 if interrompido else 0


if __name__ == "__main__":
    sys.exit(main())

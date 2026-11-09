"""Landing zone: arquivos das respostas da API e manifestos das janelas (decisão 4)."""

import json
import os
import shutil
from pathlib import Path

from pipeline.processamento import nome_arquivo_pagina

MANIFESTO = "_manifesto.json"
ESPELHO = "_execucoes.jsonl"


def salvar_pagina(pasta: Path, pagina: int, corpo: bytes) -> Path:
    """Salva o corpo exatamente como a API respondeu."""
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / nome_arquivo_pagina(pagina)
    arquivo.write_bytes(corpo)
    return arquivo


def gravar_manifesto(pasta: Path, manifesto: dict) -> None:
    """Grava o manifesto de forma atômica: ou ele existe inteiro, ou não existe."""
    pasta.mkdir(parents=True, exist_ok=True)
    temporario = pasta / (MANIFESTO + ".tmp")
    temporario.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporario, pasta / MANIFESTO)


def ler_manifesto(pasta: Path) -> dict | None:
    arquivo = pasta / MANIFESTO
    if not arquivo.exists():
        return None
    return json.loads(arquivo.read_text(encoding="utf-8"))


def listar_janelas(raiz: Path) -> tuple[list[dict], list[Path]]:
    """Devolve (manifestos das janelas completas, pastas de janelas sem manifesto)."""
    if not raiz.exists():
        return [], []
    manifestos, incompletas = [], []
    for pasta in sorted(p for p in raiz.rglob("janela=*") if p.is_dir()):
        manifesto = ler_manifesto(pasta)
        if manifesto is None:
            incompletas.append(pasta)
        else:
            manifestos.append(manifesto)
    return manifestos, incompletas


def acrescentar_execucao(raiz: Path, execucao: dict) -> None:
    """Acrescenta uma linha ao espelho das execuções (decisão 11)."""
    raiz.mkdir(parents=True, exist_ok=True)
    with open(raiz / ESPELHO, "a", encoding="utf-8") as f:
        f.write(json.dumps(execucao, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def ler_execucoes(raiz: Path) -> list[dict]:
    """Execuções do espelho, na ordem da primeira aparição; vale a última linha de cada id."""
    arquivo = raiz / ESPELHO
    if not arquivo.exists():
        return []
    execucoes: dict[str, dict] = {}
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            execucao = json.loads(linha)
            execucoes[execucao["execucao_id"]] = execucao
    return list(execucoes.values())


def limpar_janela(pasta: Path) -> None:
    if pasta.exists():
        shutil.rmtree(pasta)


def tamanho_mb(raiz: Path) -> float:
    if not raiz.exists():
        return 0.0
    total = sum(f.stat().st_size for f in raiz.rglob("*") if f.is_file())
    return round(total / 1024**2, 2)

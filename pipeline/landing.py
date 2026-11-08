"""Landing zone: arquivos das respostas da API e manifestos das janelas (decisão 4)."""

import json
import os
import shutil
from pathlib import Path

from pipeline.processamento import nome_arquivo_pagina

MANIFESTO = "_manifesto.json"


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


def limpar_janela(pasta: Path) -> None:
    if pasta.exists():
        shutil.rmtree(pasta)


def tamanho_mb(raiz: Path) -> float:
    if not raiz.exists():
        return 0.0
    total = sum(f.stat().st_size for f in raiz.rglob("*") if f.is_file())
    return round(total / 1024**2, 2)

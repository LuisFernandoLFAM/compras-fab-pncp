"""Comando único (spec: specs/transformacao.md, decisão 10).

    uv run python -m pipeline                    # ingestão e, se ela terminar com sucesso, transformação
    uv run python -m pipeline --ate 2026-10-31   # aceita os mesmos parâmetros da ingestão
"""

import logging
import sys

from pipeline import ingestao, transformacao

log = logging.getLogger("pipeline")


def main(argv: list[str] | None = None) -> int:
    codigo = ingestao.main(argv)
    if codigo:
        log.error("a ingestão terminou com código %d; a transformação não roda", codigo)
        return codigo
    return transformacao.main()


if __name__ == "__main__":
    sys.exit(main())

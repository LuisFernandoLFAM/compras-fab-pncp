"""Comando único (specs/transformacao.md, decisão 10; specs/marts.md, decisão 2).

    uv run python -m pipeline                    # ingestão, transformação e marts, cada etapa só se a anterior der certo
    uv run python -m pipeline --ate 2026-10-31   # aceita os mesmos parâmetros da ingestão
"""

import logging
import sys

from pipeline import ingestao, marts, transformacao

log = logging.getLogger("pipeline")


def main(argv: list[str] | None = None) -> int:
    codigo = ingestao.main(argv)
    if codigo:
        log.error("a ingestão terminou com código %d; a transformação e os marts não rodam", codigo)
        return codigo
    codigo = transformacao.main()
    if codigo:
        log.error("a transformação terminou com código %d; os marts não rodam", codigo)
        return codigo
    return marts.main()


if __name__ == "__main__":
    sys.exit(main())

"""Camada bruta no DuckDB: tabelas raw.* e registro das execuções."""

from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

COLUNAS_RAW = (
    "registro",
    "_hash",
    "_endpoint",
    "_modalidade",
    "_janela_inicio",
    "_janela_fim",
    "_pagina",
    "_arquivo_origem",
    "_extraido_em",
    "_execucao_id",
)

COLUNAS_EXECUCOES = (
    "execucao_id",
    "modo",
    "inicio",
    "fim",
    "status",
    "dados_ate",
    "chamadas_api",
    "linhas_novas",
    "linhas_ja_existentes",
    "mb_landing",
    "mensagem_erro",
)


def conectar(caminho: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(caminho))


def criar_tabelas(con: duckdb.DuckDBPyConnection, tabelas: list[str]) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    colunas = ", ".join(f"{c} VARCHAR" for c in COLUNAS_RAW)
    for tabela in tabelas:
        con.execute(f"CREATE TABLE IF NOT EXISTS raw.{tabela} ({colunas})")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.execucoes (
            execucao_id VARCHAR PRIMARY KEY,
            modo VARCHAR,
            inicio TIMESTAMPTZ,
            fim TIMESTAMPTZ,
            status VARCHAR,
            dados_ate DATE,
            chamadas_api INTEGER,
            linhas_novas INTEGER,
            linhas_ja_existentes INTEGER,
            mb_landing DOUBLE,
            mensagem_erro VARCHAR
        )
        """
    )


def inserir_linhas(con: duckdb.DuckDBPyConnection, tabela: str, linhas: list[dict]) -> tuple[int, int]:
    """Acrescenta só as versões com hash ainda inexistente. Devolve (novas, já existentes)."""
    if not linhas:
        return 0, 0
    lote = pd.DataFrame(linhas, columns=list(COLUNAS_RAW))
    colunas = ", ".join(COLUNAS_RAW)
    con.register("_lote", lote)
    try:
        # O INSERT devolve uma linha com o número de linhas inseridas.
        [(novas,)] = con.execute(
            f"""
            INSERT INTO raw.{tabela} ({colunas})
            SELECT {colunas} FROM (SELECT DISTINCT ON (_hash) * FROM _lote) l
            WHERE NOT EXISTS (SELECT 1 FROM raw.{tabela} t WHERE t._hash = l._hash)
            """
        ).fetchall()
    finally:
        con.unregister("_lote")
    return novas, len(linhas) - novas


def esvaziar_raw(con: duckdb.DuckDBPyConnection, tabelas: list[str]) -> None:
    for tabela in tabelas:
        con.execute(f"DELETE FROM raw.{tabela}").fetchall()


def contar_linhas(con: duckdb.DuckDBPyConnection, tabela: str) -> int:
    [(total,)] = con.execute(f"SELECT count(*) FROM raw.{tabela}").fetchall()
    return total


def historico_execucoes(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str, date | None]]:
    return con.execute(
        "SELECT execucao_id, modo, status, dados_ate FROM raw.execucoes ORDER BY inicio"
    ).fetchall()


def ler_execucoes(con: duckdb.DuckDBPyConnection, execucao_id: str | None = None) -> list[dict]:
    """Execuções em formato JSON (datas como texto), para o espelho em data/landing."""
    filtro = "WHERE execucao_id = ?" if execucao_id else ""
    linhas = con.execute(
        f"""
        SELECT execucao_id, modo, strftime(inicio, '%Y-%m-%dT%H:%M:%S.%f%z'),
               strftime(fim, '%Y-%m-%dT%H:%M:%S.%f%z'), status, dados_ate::VARCHAR,
               chamadas_api, linhas_novas, linhas_ja_existentes, mb_landing, mensagem_erro
        FROM raw.execucoes {filtro} ORDER BY inicio
        """,
        [execucao_id] if execucao_id else [],
    ).fetchall()
    return [dict(zip(COLUNAS_EXECUCOES, linha, strict=True)) for linha in linhas]


def substituir_execucoes(con: duckdb.DuckDBPyConnection, execucoes: list[dict]) -> None:
    """Recria raw.execucoes a partir do espelho."""
    con.execute("DELETE FROM raw.execucoes").fetchall()
    for e in execucoes:
        con.execute(
            """
            INSERT INTO raw.execucoes VALUES (?, ?, CAST(? AS TIMESTAMPTZ), CAST(? AS TIMESTAMPTZ),
                ?, CAST(? AS DATE), ?, ?, ?, ?, ?)
            """,
            [e[c] for c in COLUNAS_EXECUCOES],
        ).fetchall()


def abrir_execucao(
    con: duckdb.DuckDBPyConnection, execucao_id: str, modo: str, inicio: datetime,
    dados_ate: date | None,
) -> None:
    """Registra a execução já como falha: se o processo morrer, o registro continua verdadeiro."""
    con.execute(
        """
        INSERT INTO raw.execucoes VALUES (?, ?, ?, NULL, 'falha', ?, 0, 0, 0, NULL,
            'execução em andamento ou interrompida')
        """,
        [execucao_id, modo, inicio, dados_ate],
    ).fetchall()


def fechar_execucao(
    con: duckdb.DuckDBPyConnection,
    execucao_id: str,
    *,
    status: str,
    dados_ate: date | None,
    chamadas_api: int,
    linhas_novas: int,
    linhas_ja_existentes: int,
    mb_landing: float,
    mensagem_erro: str | None,
) -> None:
    con.execute(
        """
        UPDATE raw.execucoes
        SET fim = ?, status = ?, dados_ate = ?, chamadas_api = ?, linhas_novas = ?,
            linhas_ja_existentes = ?, mb_landing = ?, mensagem_erro = ?
        WHERE execucao_id = ?
        """,
        [
            datetime.now().astimezone(),
            status,
            dados_ate,
            chamadas_api,
            linhas_novas,
            linhas_ja_existentes,
            mb_landing,
            mensagem_erro,
            execucao_id,
        ],
    ).fetchall()

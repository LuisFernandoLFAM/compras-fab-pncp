"""Etapa 3: marts, tabelas de indicadores a partir da refined (spec: specs/marts.md).

    uv run python -m pipeline.marts   # recria o schema marts a partir da refined atual

Os arquivos de sql/marts/ rodam em ordem de nome, numa única transação. O comando
único, que roda a ingestão e a transformação antes, é python -m pipeline.
"""

import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import duckdb

from pipeline import banco
from pipeline.config import RAIZ_PROJETO, carregar_config

log = logging.getLogger("marts")

PASTA_SQL = RAIZ_PROJETO / "sql" / "marts"


class FalhaMarts(Exception):
    """Os marts não podem ser montados com segurança; os anteriores ficam intactos."""


@dataclass
class Resultado:
    linhas: dict[str, int] = field(default_factory=dict)


# --- registro das execuções ----------------------------------------------------------


def criar_execucoes(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS marts")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS marts.execucoes (
            execucao_id VARCHAR PRIMARY KEY,
            execucao_transformacao VARCHAR,
            data_referencia DATE,
            inicio TIMESTAMPTZ,
            fim TIMESTAMPTZ,
            status VARCHAR,
            tabelas INTEGER,
            linhas INTEGER,
            mensagem_erro VARCHAR
        )
        """
    )


def abrir_execucao(con: duckdb.DuckDBPyConnection, execucao_id: str, inicio: datetime) -> None:
    """Registra a execução já como falha: se o processo morrer, o registro continua verdadeiro."""
    con.execute(
        """
        INSERT INTO marts.execucoes (execucao_id, inicio, status, mensagem_erro)
        VALUES (?, ?, 'falha', 'execução em andamento ou interrompida')
        """,
        [execucao_id, inicio],
    ).fetchall()


def fechar_execucao(
    con: duckdb.DuckDBPyConnection, execucao_id: str, *, execucao_transformacao: str | None,
    data_referencia: date | None, status: str, resultado: Resultado, mensagem_erro: str | None,
) -> None:
    linhas = resultado.linhas
    con.execute(
        """
        UPDATE marts.execucoes
        SET execucao_transformacao = ?, data_referencia = ?, fim = ?, status = ?, tabelas = ?,
            linhas = ?, mensagem_erro = ?
        WHERE execucao_id = ?
        """,
        [
            execucao_transformacao,
            data_referencia,
            datetime.now().astimezone(),
            status,
            len(linhas) if linhas else None,
            sum(linhas.values()) if linhas else None,
            mensagem_erro,
            execucao_id,
        ],
    ).fetchall()


# --- pré-condição e data de referência (decisão 2) ---------------------------------------


def tabela_existe(con: duckdb.DuckDBPyConnection, schema: str, tabela: str) -> bool:
    [(n,)] = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [schema, tabela],
    ).fetchall()
    return n > 0


def ultima_transformacao(con: duckdb.DuckDBPyConnection) -> tuple[str, str]:
    """(execucao_id, rodada_ingestao) da última transformação, se ela terminou com sucesso."""
    ultima = con.execute(
        "SELECT execucao_id, rodada_ingestao, status FROM refined.execucoes ORDER BY inicio DESC LIMIT 1"
    ).fetchall() if tabela_existe(con, "refined", "execucoes") else []
    if not ultima:
        raise FalhaMarts("nenhuma transformação em refined.execucoes; rode a transformação antes")
    [(execucao_id, rodada, status)] = ultima
    if status != "sucesso":
        raise FalhaMarts(
            f"a última transformação ({execucao_id}) não terminou com sucesso; rode a transformação antes"
        )
    return execucao_id, rodada


def data_referencia(con: duckdb.DuckDBPyConnection, rodada: str) -> date:
    """dados_ate da rodada de ingestão; a menor, se os CNPJs tiverem datas diferentes."""
    [(dados_ate,)] = con.execute(
        "SELECT min(dados_ate) FROM raw.execucoes WHERE rodada_id = ?", [rodada]
    ).fetchall()
    if dados_ate is None:
        raise FalhaMarts(f"a rodada de ingestão {rodada} não tem dados_ate em raw.execucoes")
    return dados_ate


# --- construção ----------------------------------------------------------------------------


def arquivos_sql(pasta: Path) -> list[Path]:
    arquivos = sorted(pasta.glob("*.sql"))
    if not arquivos:
        raise FalhaMarts(f"nenhum arquivo SQL em {pasta}")
    return arquivos


def tabelas_dos_marts(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Tabelas do schema marts, exceto marts.execucoes, que acumula o histórico."""
    return [
        tabela for (tabela,) in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'marts' AND table_name <> 'execucoes' ORDER BY table_name"
        ).fetchall()
    ]


def contar(con: duckdb.DuckDBPyConnection, sql: str):
    [(valor,)] = con.execute(sql).fetchall()
    return valor


def conferir(con: duckdb.DuckDBPyConnection) -> None:
    """As três conferências da decisão 2; qualquer diferença desfaz a transação."""
    for coluna, tabela in (("compras", "contratacoes"), ("contratos", "contratos")):
        no_mart = contar(con, f"SELECT coalesce(sum({coluna}), 0) FROM marts.compras_mensal")
        na_refined = contar(con, f"SELECT count(*) FROM refined.{tabela}")
        if no_mart != na_refined:
            raise FalhaMarts(
                f"conferência de totais: marts.compras_mensal soma {no_mart} {coluna}, "
                f"refined.{tabela} tem {na_refined}"
            )

    [(linhas, distintas, sem_segmento)] = con.execute(
        "SELECT count(*), count(DISTINCT (tabela, chave)), count(*) FILTER (WHERE segmento IS NULL) "
        "FROM marts.segmento_objeto"
    ).fetchall()
    esperado = contar(
        con, "SELECT (SELECT count(*) FROM refined.contratacoes) + (SELECT count(*) FROM refined.contratos)"
    )
    if not (linhas == distintas == esperado) or sem_segmento:
        raise FalhaMarts(
            f"conferência de segmento: {linhas} linhas, {distintas} distintas e {sem_segmento} sem "
            f"segmento em marts.segmento_objeto; esperado uma linha por compra e contrato ({esperado})"
        )

    no_mart = contar(con, "SELECT coalesce(sum(valor_contratado), 0) FROM marts.fornecedores")
    na_refined = contar(con, "SELECT coalesce(sum(valor_global), 0) FROM refined.contratos")
    if no_mart != na_refined:
        raise FalhaMarts(
            f"conferência de valor: marts.fornecedores soma {no_mart}, refined.contratos soma {na_refined}"
        )
    log.info("conferências: ok")


def construir(
    con: duckdb.DuckDBPyConnection, execucao_transformacao: str, rodada: str, referencia: date,
    pasta: Path,
) -> dict[str, int]:
    """Recria as tabelas do schema marts numa única transação; devolve as linhas de cada uma."""
    arquivos = arquivos_sql(pasta)
    con.execute("SET enable_progress_bar = false")  # a barra sujaria o log
    con.execute("BEGIN TRANSACTION")
    try:
        for tabela in tabelas_dos_marts(con):
            con.execute(f"DROP TABLE marts.{tabela}")
        con.execute(
            "CREATE TABLE marts.referencia AS SELECT CAST(? AS DATE) AS data_referencia, "
            "CAST(? AS VARCHAR) AS rodada_ingestao, CAST(? AS VARCHAR) AS execucao_transformacao",
            [referencia, rodada, execucao_transformacao],
        )
        for arquivo in arquivos:
            try:
                con.execute(arquivo.read_text(encoding="utf-8"))
            except duckdb.Error as e:
                raise FalhaMarts(f"{arquivo.name}: {e}") from e
        conferir(con)
        linhas = {tabela: contar(con, f"SELECT count(*) FROM marts.{tabela}") for tabela in tabelas_dos_marts(con)}
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return linhas


# --- execução ----------------------------------------------------------------------------------


def executar(con: duckdb.DuckDBPyConnection, pasta: Path = PASTA_SQL) -> int:
    """Registra a execução, confere a pré-condição, recria os marts e fecha o registro."""
    execucao_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    criar_execucoes(con)
    abrir_execucao(con, execucao_id, datetime.now().astimezone())
    log.info("execução %s", execucao_id)

    comeco = time.perf_counter()
    transformacao, referencia, resultado = None, None, Resultado()
    status, mensagem, codigo = "sucesso", None, 0
    try:
        transformacao, rodada = ultima_transformacao(con)
        referencia = data_referencia(con, rodada)
        log.info("transformação %s, data de referência %s", transformacao, referencia)
        resultado.linhas = construir(con, transformacao, rodada, referencia, pasta)
    except FalhaMarts as e:
        status, mensagem, codigo = "falha", str(e), 1
    except KeyboardInterrupt:
        status, mensagem, codigo = "falha", "interrompida pelo usuário", 130
    except Exception as e:
        # Guarda de topo, mantido de propósito: um erro não previsto (DuckDB, disco, bug) também
        # precisa fechar a execução como falha, senão o finally a gravaria como sucesso. Nada é
        # engolido: o traceback vai para o log, a mensagem para mensagem_erro e o código 1 encerra
        # o comando. A transação já foi desfeita em construir().
        status, mensagem, codigo = "falha", f"{type(e).__name__}: {e}", 1
        log.exception("erro inesperado")
    finally:
        fechar_execucao(
            con, execucao_id, execucao_transformacao=transformacao, data_referencia=referencia,
            status=status, resultado=resultado, mensagem_erro=mensagem,
        )

    segundos = time.perf_counter() - comeco
    if status == "sucesso":
        log.info("linhas: %s", ", ".join(f"{t} {n}" for t, n in resultado.linhas.items()))
        log.info("sucesso em %.1f s", segundos)
    else:
        log.error("falha em %.1f s: %s", segundos, mensagem)
        log.error("os marts anteriores continuam intactos")
    return codigo


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = carregar_config()
    con = banco.conectar(cfg.banco)
    try:
        return executar(con)
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())

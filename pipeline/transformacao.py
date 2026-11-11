"""Etapa 2: transformação da camada bruta para a refinada (spec: specs/transformacao.md).

    uv run python -m pipeline.transformacao   # recria a refined a partir da raw atual

O comando único, que roda a ingestão antes, é python -m pipeline (decisão 10).
"""

import logging
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import duckdb
import pandas as pd

from pipeline import banco
from pipeline.anomalias import REGRAS, registrar_anomalias
from pipeline.config import Config, carregar_config
from pipeline.contrato_dados import conferir_contrato
from pipeline.refinamento import (
    COLUNAS_CONTRATACOES,
    COLUNAS_CONTRATOS,
    COLUNAS_FONTES,
    COLUNAS_RASTRO,
    LIGACOES,
    Coluna,
    FalhaTransformacao,
    LinhaRaw,
    escolher_vigentes,
    ler_registro,
    linhas_contratacoes,
    linhas_contratos,
)

log = logging.getLogger("transformacao")

TABELAS = {
    "contratacoes": COLUNAS_CONTRATACOES + COLUNAS_RASTRO,
    "contratacoes_fontes": COLUNAS_FONTES + COLUNAS_RASTRO,
    "contratos": COLUNAS_CONTRATOS + COLUNAS_RASTRO,
}
CHAVES = {
    "contratacoes": ("numero_controle_pncp",),
    "contratacoes_fontes": ("numero_controle_pncp", "ordem"),
    "contratos": ("numero_controle_pncp",),
}
# Tabelas da refined que vêm direto de uma tabela da raw (conferências de linhas e somas).
ORIGEM = {"contratacoes": COLUNAS_CONTRATACOES, "contratos": COLUNAS_CONTRATOS}


@dataclass
class Resultado:
    linhas: dict[str, int] = field(default_factory=dict)
    ligacoes: Counter = field(default_factory=Counter)
    anomalias: Counter = field(default_factory=Counter)
    avisos: int = 0

    def avisar(self, mensagem: str, *args) -> None:
        self.avisos += 1
        log.warning(mensagem, *args)


# --- registro das execuções ----------------------------------------------------------


def criar_execucoes(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS refined")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS refined.execucoes (
            execucao_id VARCHAR PRIMARY KEY,
            rodada_ingestao VARCHAR,
            inicio TIMESTAMPTZ,
            fim TIMESTAMPTZ,
            status VARCHAR,
            linhas_contratacoes INTEGER,
            linhas_contratos INTEGER,
            linhas_fontes INTEGER,
            linhas_anomalias INTEGER,
            avisos INTEGER,
            mensagem_erro VARCHAR
        )
        """
    )


def abrir_execucao(con: duckdb.DuckDBPyConnection, execucao_id: str, inicio: datetime) -> None:
    """Registra a execução já como falha: se o processo morrer, o registro continua verdadeiro."""
    con.execute(
        """
        INSERT INTO refined.execucoes (execucao_id, inicio, status, mensagem_erro)
        VALUES (?, ?, 'falha', 'execução em andamento ou interrompida')
        """,
        [execucao_id, inicio],
    ).fetchall()


def fechar_execucao(
    con: duckdb.DuckDBPyConnection, execucao_id: str, *, rodada: str | None, status: str,
    resultado: Resultado, mensagem_erro: str | None,
) -> None:
    """Numa falha, as linhas ficam nulas, porque nada foi gravado; os avisos já emitidos contam."""
    linhas = resultado.linhas
    con.execute(
        """
        UPDATE refined.execucoes
        SET rodada_ingestao = ?, fim = ?, status = ?, linhas_contratacoes = ?,
            linhas_contratos = ?, linhas_fontes = ?, linhas_anomalias = ?, avisos = ?,
            mensagem_erro = ?
        WHERE execucao_id = ?
        """,
        [
            rodada,
            datetime.now().astimezone(),
            status,
            linhas.get("contratacoes"),
            linhas.get("contratos"),
            linhas.get("contratacoes_fontes"),
            linhas.get("anomalias"),
            resultado.avisos,
            mensagem_erro,
            execucao_id,
        ],
    ).fetchall()


# --- pré-condição (decisão 10) -----------------------------------------------------------


def ultima_rodada(con: duckdb.DuckDBPyConnection, cnpjs: tuple[str, ...]) -> str:
    """rodada_id da última rodada de ingestão, se ela terminou com sucesso para todos os CNPJs."""
    [(existe,)] = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'raw' AND table_name = 'execucoes'"
    ).fetchall()
    ultima = con.execute(
        "SELECT rodada_id FROM raw.execucoes ORDER BY inicio DESC LIMIT 1"
    ).fetchall() if existe else []
    if not ultima:
        raise FalhaTransformacao("nenhuma rodada de ingestão em raw.execucoes")
    [(rodada,)] = ultima
    com_sucesso = {
        cnpj for (cnpj,) in con.execute(
            "SELECT cnpj FROM raw.execucoes WHERE rodada_id = ? AND status = 'sucesso'", [rodada]
        ).fetchall()
    }
    faltando = [cnpj for cnpj in cnpjs if cnpj not in com_sucesso]
    if faltando:
        raise FalhaTransformacao(
            f"a última rodada de ingestão ({rodada}) não terminou com sucesso para: "
            f"{', '.join(faltando)}; rode a ingestão antes"
        )
    return rodada


def execucoes_da_rodada(con: duckdb.DuckDBPyConnection, rodada: str) -> set[str]:
    return {
        execucao_id for (execucao_id,) in con.execute(
            "SELECT execucao_id FROM raw.execucoes WHERE rodada_id = ?", [rodada]
        ).fetchall()
    }


# --- contrato de dados (decisão 9) ----------------------------------------------------------


def conferir_contrato_de_dados(
    raw: dict[str, list[LinhaRaw]], execucoes: set[str], resultado: Resultado
) -> None:
    """Avisa o que é novo; falha, antes de tocar na refined, se um campo da de/para sumiu."""
    falhas = []
    for tabela, linhas in raw.items():
        ultima = [linha for linha in linhas if linha.execucao_id in execucoes]
        contrato = conferir_contrato(tabela, linhas, ultima)
        for aviso in contrato.avisos:
            resultado.avisar("contrato de dados: %s", aviso)
        if not ultima:
            log.info(
                "contrato de dados: a última rodada não trouxe registros de %s; "
                "a conferência de campos ausentes não se aplica", tabela,
            )
        falhas += contrato.falhas
    if falhas:
        raise FalhaTransformacao("contrato de dados: " + "; ".join(falhas))
    log.info("contrato de dados: nenhum campo da tabela de/para ausente")


# --- leitura e gravação --------------------------------------------------------------------


def ler_raw(con: duckdb.DuckDBPyConnection, tabela: str) -> list[LinhaRaw]:
    return [
        LinhaRaw(ler_registro(registro), hash_, extraido_em, execucao_id)
        for registro, hash_, extraido_em, execucao_id in con.execute(
            f"SELECT registro, _hash, _extraido_em, _execucao_id FROM raw.{tabela}"
        ).fetchall()
    ]


def gravar(con: duckdb.DuckDBPyConnection, tabela: str, colunas: list[Coluna], linhas: list[dict]) -> None:
    """Recria a tabela com os tipos da spec; os valores chegam em texto e o CAST tipa."""
    definicao = ", ".join(f"{c.nome} {c.tipo_sql}" for c in colunas)
    con.execute(f"CREATE OR REPLACE TABLE refined.{tabela} ({definicao})")
    if not linhas:
        return
    nomes = [c.nome for c in colunas]
    lote = pd.DataFrame(linhas, columns=nomes, dtype=object)
    selecao = ", ".join(f"CAST({c.nome} AS {c.tipo_sql})" for c in colunas)
    con.register("_lote", lote)
    try:
        con.execute(
            f"INSERT INTO refined.{tabela} ({', '.join(nomes)}) SELECT {selecao} FROM _lote"
        ).fetchall()
    finally:
        con.unregister("_lote")


# --- conferências (decisão 10) ---------------------------------------------------------------


def contar(con: duckdb.DuckDBPyConnection, sql: str):
    [(valor,)] = con.execute(sql).fetchall()
    return valor


def conferir(con: duckdb.DuckDBPyConnection) -> None:
    """As quatro conferências; qualquer diferença desfaz a transação."""
    # 1. Linhas, contadas na raw sem depender da escolha da versão vigente.
    for tabela in ORIGEM:
        esperado = contar(con, f"SELECT count(DISTINCT registro->>'numeroControlePNCP') FROM raw.{tabela}")
        gravado = contar(con, f"SELECT count(*) FROM refined.{tabela}")
        if gravado != esperado:
            raise FalhaTransformacao(
                f"conferência de linhas: refined.{tabela} tem {gravado}, a raw tem {esperado} registros"
            )
    esperado = contar(
        con,
        """
        SELECT coalesce(sum(json_array_length(r.registro, '$.fontesOrcamentarias')), 0)
        FROM raw.contratacoes r JOIN refined.contratacoes c USING (_hash)
        """,
    )
    gravado = contar(con, "SELECT count(*) FROM refined.contratacoes_fontes")
    if gravado != esperado:
        raise FalhaTransformacao(
            f"conferência de linhas: refined.contratacoes_fontes tem {gravado}, "
            f"as versões vigentes têm {esperado} fontes"
        )
    log.info("conferência de linhas: ok")

    # 2. Chave única.
    for tabela, chave in CHAVES.items():
        colunas = ", ".join(chave)
        repetidas = con.execute(
            f"SELECT {colunas} FROM refined.{tabela} GROUP BY {colunas} HAVING count(*) > 1 LIMIT 5"
        ).fetchall()
        if repetidas:
            raise FalhaTransformacao(f"conferência de chave: refined.{tabela} repete {repetidas}")
    log.info("conferência de chave única: ok")

    # 3. Somas, calculadas em SQL direto do texto do JSON das versões vigentes.
    for tabela, colunas in ORIGEM.items():
        for c in colunas:
            if not c.tipo.startswith("dinheiro"):
                continue
            [campo] = c.caminho
            [(na_raw, na_refined)] = con.execute(
                f"""
                SELECT sum(CAST(r.registro->>'{campo}' AS DECIMAL(38,4))),
                       sum(CAST(t.{c.nome} AS DECIMAL(38,4)))
                FROM raw.{tabela} r JOIN refined.{tabela} t USING (_hash)
                """
            ).fetchall()
            if na_raw != na_refined:
                raise FalhaTransformacao(
                    f"conferência de somas: refined.{tabela}.{c.nome} soma {na_refined}, "
                    f"o JSON soma {na_raw}"
                )
    log.info("conferência de somas: ok")

    # 4. Ligação preenchida em todos os contratos.
    sem_ligacao = contar(con, "SELECT count(*) FROM refined.contratos WHERE ligacao_compra IS NULL")
    if sem_ligacao:
        raise FalhaTransformacao(f"conferência de ligação: {sem_ligacao} contratos sem ligacao_compra")
    log.info("conferência de ligação: ok")


# --- execução ----------------------------------------------------------------------------------


def transformar(con: duckdb.DuckDBPyConnection, cfg: Config, rodada: str, resultado: Resultado) -> None:
    """Confere o contrato de dados, monta as linhas em memória e recria a refined numa transação."""
    raw = {tabela: ler_raw(con, tabela) for tabela in ORIGEM}
    conferir_contrato_de_dados(raw, execucoes_da_rodada(con, rodada), resultado)

    contratacoes, fontes = linhas_contratacoes(escolher_vigentes(raw["contratacoes"], "contratacoes"))
    compras = {linha["numero_controle_pncp"] for linha in contratacoes}
    contratos = linhas_contratos(
        escolher_vigentes(raw["contratos"], "contratos"),
        compras, cfg.cnpjs, cfg.matriz, cfg.data_inicial,
    )
    linhas = {"contratacoes": contratacoes, "contratacoes_fontes": fontes, "contratos": contratos}

    con.execute("BEGIN TRANSACTION")
    try:
        for tabela, colunas in TABELAS.items():
            gravar(con, tabela, colunas, linhas[tabela])
        anomalias = registrar_anomalias(con)
        conferir(con)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise

    resultado.linhas = {tabela: len(valores) for tabela, valores in linhas.items()}
    resultado.linhas["anomalias"] = sum(anomalias.values())
    resultado.anomalias = anomalias
    resultado.ligacoes = Counter(linha["ligacao_compra"] for linha in contratos)
    nao_encontradas = resultado.ligacoes["compra_fab_nao_encontrada"]
    if nao_encontradas:
        resultado.avisar(
            "%d contratos apontam para compra da FAB do período ausente da refined "
            "(compra_fab_nao_encontrada): possível lacuna na ingestão",
            nao_encontradas,
        )


def executar(con: duckdb.DuckDBPyConnection, cfg: Config) -> int:
    """Registra a execução, confere a pré-condição, transforma e fecha o registro."""
    execucao_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    criar_execucoes(con)
    abrir_execucao(con, execucao_id, datetime.now().astimezone())
    log.info("execução %s", execucao_id)

    comeco = time.perf_counter()
    rodada, resultado = None, Resultado()
    status, mensagem, codigo = "sucesso", None, 0
    try:
        rodada = ultima_rodada(con, cfg.cnpjs)
        log.info("rodada de ingestão %s: sucesso para os %d CNPJs", rodada, len(cfg.cnpjs))
        transformar(con, cfg, rodada, resultado)
    except FalhaTransformacao as e:
        status, mensagem, codigo = "falha", str(e), 1
    except KeyboardInterrupt:
        status, mensagem, codigo = "falha", "interrompida pelo usuário", 130
    except Exception as e:
        # Guarda de topo, mantido de propósito: um erro não previsto (DuckDB, disco, bug) também
        # precisa fechar a execução como falha, senão o finally a gravaria como sucesso. Nada é
        # engolido: o traceback vai para o log, a mensagem para mensagem_erro e o código 1 encerra
        # o comando e impede os marts de rodar. A transação já foi desfeita em transformar().
        status, mensagem, codigo = "falha", f"{type(e).__name__}: {e}", 1
        log.exception("erro inesperado")
    finally:
        fechar_execucao(
            con, execucao_id, rodada=rodada, status=status, resultado=resultado,
            mensagem_erro=mensagem,
        )

    segundos = time.perf_counter() - comeco
    if status == "sucesso":
        log.info(
            "linhas: %s",
            ", ".join(f"{tabela} {n}" for tabela, n in resultado.linhas.items()),
        )
        log.info(
            "ligacao_compra: %s",
            ", ".join(f"{valor} {resultado.ligacoes[valor]}" for valor in LIGACOES),
        )
        log.info(
            "anomalias por regra: %s",
            ", ".join(f"{r.nome} {resultado.anomalias[r.nome]}" for r in REGRAS),
        )
        log.info("avisos: %d", resultado.avisos)
        log.info("sucesso em %.1f s", segundos)
    else:
        log.error("falha em %.1f s: %s", segundos, mensagem)
        log.error("a refined anterior continua intacta")
    return codigo


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = carregar_config()
    con = banco.conectar(cfg.banco)
    try:
        return executar(con, cfg)
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())

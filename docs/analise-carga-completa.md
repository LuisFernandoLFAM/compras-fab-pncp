# Análise da primeira carga completa: tempo e respostas HTTP 429

Execução `20261107T231604-e5c8f0`, de 07/11/2026 23:16 a 08/11/2026 08:54, com pausa de 0,5 s entre chamadas.

**Conclusão:** dos 578 minutos entre a primeira e a última chamada, só 81 foram de execução ativa; o resto foi suspensão do computador. Desses 81 minutos, cerca de metade foi espera por HTTP 429. Aumentar a pausa para cerca de 3 s quase eliminaria os 429, mas a carga continuaria levando 80 a 90 minutos ativos, porque o limite de chamadas da API já é o que determina a duração.

## Fonte e limitações

- A análise cobre os 652 manifestos da execução bem-sucedida (`20261107T231604-e5c8f0`).
  - As 6 janelas aproveitadas da execução que falhou ficaram de fora, porque pertencem àquela execução e não à analisada.
- Os manifestos não guardam todas as chamadas, e por isso uma parte dos números é estimada:

| Chamadas | Quantidade | De onde vem o horário |
|---|---|---|
| Páginas salvas (HTTP 200) | 570 | `extraido_em` |
| Janelas vazias (HTTP 204) | 380 | `concluido_em` do manifesto, gravado logo após a chamada |
| **Com horário** | **950** | |
| Sem horário (respostas 429 e outras novas tentativas) | 77 | `chamadas_api` = 1.027 menos 950 |

- Os horários têm resolução de 1 segundo.

## 1 e 2. Suspensões (intervalos acima de 10 minutos)

| De | Até | Duração |
|---|---|---|
| 08/11 00:14:18 | 00:29:46 | 15,5 min |
| 08/11 00:46:10 | 03:44:36 | 178,4 min |
| 08/11 03:50:41 | 08:54:10 | 303,5 min |
| **Total** | | **497 min (8,29 h)** |

As três suspensões coincidem com o log da execução.

## 3. Tempo ativo

- Da primeira à última chamada (23:16:06 a 08:54:36): 9,64 h.
- Menos as suspensões: **81,1 minutos de tempo ativo**.

## 4. Distribuição dos intervalos restantes (946)

| Faixa | Intervalos | Tempo somado | O que é |
|---|---|---|---|
| Abaixo de 2 s | 323 | 4,9 min | Respostas rápidas, a maioria 204 |
| 2 a 25 s | 545 | 33,5 min | Tempo de resposta da API: páginas com dados levam em média 3,3 s, e um 204 leva 1,7 s (pausa de 0,5 s incluída) |
| 25 a 40 s | 77 | 41,5 min | 74 deles entre 31 e 37 s, que é o padrão de 429 (30 s de espera + 0,5 s de pausa + resposta). Os 3 de 25 e 26 s são curtos demais para serem 429; devem ser respostas lentas |
| Acima de 40 s | 1 | 1,2 min | Um intervalo de 72 s às 00:31, logo após a primeira suspensão |

## 5. Tempo gasto esperando por 429

- **Houve 74 respostas 429.** O número confere com as chamadas sem horário: 77 no total, das quais 3 são outras novas tentativas.
- Em quase todos os casos, a primeira nova tentativa, depois de 30 s, funcionou. Não aparece nenhuma espera de 60 ou 120 s.
- **Custo estimado: 74 × cerca de 30,8 s ≈ 38 minutos, ou seja, 47% do tempo ativo.** Contando também o tempo de resposta da chamada repetida, sobe para 41,5 minutos (51%).

## 6. Padrão do limite

- **Depois de cada espera de 30 s, a API aceitou de 6 a 9 chamadas em 5 a 10 s antes do próximo 429.** Esse padrão se repetiu cerca de 60 vezes.
- **Quando o ritmo caiu para cerca de 3 s por chamada,** porque as páginas eram mais lentas, houve corridas longas sem 429: 84 chamadas em 248 s, 70 em 210 s, 60 em 296 s e 38 em 141 s.
- **Num ritmo de cerca de 2 s por chamada,** a API aceitou de 11 a 19 chamadas antes do 429 (por exemplo, 13 em 25 s e 19 em 37 s).
- **Máximo aceito sem 429, por tamanho de janela:** 7 chamadas em 5 s, 9 em 10 s, 13 em 20 s, 18 em 30 s e 23 em 60 s.

**Estimativa do limite:** uma rajada de cerca de 7 chamadas, com ritmo sustentável de cerca de 1 chamada a cada 3 s (por volta de 20 por minuto).

Foram ajustados dois modelos de limite. Ambos reproduzem as 74 respostas 429 e os 81 minutos ativos, mas com parâmetros diferentes:
- balde de fichas: rajada de 6 ou 7 chamadas, com uma chamada liberada a cada 4 ou 5 s;
- janela deslizante: 6 chamadas a cada 11 s, ou 9 a cada 25 s.

Os dados não definem uma regra única.

Há um indício de que a API também bloqueia por um tempo depois que o limite é estourado. Na execução anterior, que falhou, esperas de 2, 4 e 8 s, somando 14 s, não bastaram; nesta, 30 s quase sempre bastaram. Esse bloqueio deve durar entre 14 e 30 s.

## 7. Pausa sugerida

Simulação da mesma sequência de 1.027 chamadas, com os tempos de resposta medidos, nos cinco modelos que melhor se ajustaram de cada tipo:

| Pausa | 429 esperados | Tempo ativo estimado |
|---|---|---|
| 0,5 s (atual) | 73 a 74 | 81 a 82 min |
| 1,5 s | 0 a 50 | 60 a 86 min |
| 2,0 s | 0 a 37 | 67 a 87 min |
| 2,5 s | 0 a 25 | 75 a 89 min |
| **3,0 s** | **0 a 11** | **83 a 89 min** |
| 3,5 s | 0 a 3 | 91 a 93 min |

**Recomendação: pausa de 3 s** (adotada na decisão 6 de [specs/ingestao.md](../specs/ingestao.md)).
- A carga completa ficaria com cerca de 85 minutos ativos, praticamente o mesmo de antes.
- Os 429 cairiam para no máximo cerca de 10, contra 74.
- O tratamento de 429 continua valendo como rede de segurança.
- Com um ritmo regular, a execução fica mais previsível, o log mais limpo e o risco de repetir o 429 persistente da primeira execução diminui.

**Isso não deixa a carga mais rápida.** O que reduziria o tempo seria fazer menos chamadas: 380 das 950 chamadas registradas (40%) voltaram vazias, das modalidades sem uso. Mas consultar as 13 modalidades é uma escolha deliberada da decisão 1.

## Achado à parte

Ler `inicio` e `fim` de `raw.execucoes` pelo Python falhava com `ModuleNotFoundError: No module named 'pytz'`. Isso acontecia porque as colunas são `TIMESTAMPTZ`, e o DuckDB precisa do `pytz` para convertê-las em objetos do Python. O pipeline não lia essas colunas, então nada quebrou. Resolvido com a inclusão do `pytz` nas dependências.

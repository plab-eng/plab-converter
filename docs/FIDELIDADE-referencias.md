# Fidelidade contra referências reais: Solaris e Ultrapex (17–18/10/2026)

Pedido do José: as famílias geradas tinham "a essência" mas LOD baixo e a parte paramétrica sem teste; ele
mandou duas referências para recriar fielmente antes da G6:

- `00.Biblioteca\Fabricantes\Solaris\Reservatorio Termico Baixa Pressao Solis.rfa` (Revit 2021, 7 tipos de
  200 a 1000 L);
- `00.Biblioteca\Fabricantes\Ultrapex\Biblioteca BIM PEX Monocamada - ULTRAPEX(ErickBIM) - R02.rte`
  (Revit 2019; 18 conexões e 10 acessórios extraídos com `EditFamily`).

## Método

Antes de recriar pelo gerador, medir quanto o pipeline reproduz delas: ida e volta pelo conversor (leitor no
2024, construtor no 2023, `validador.py` + releitura do resultado). Cópias de trabalho em `out/ref/` (os
originais do Drive não foram tocados). Inventário: `scripts/ref_inventario.py`; diagnósticos de cotas e
conectores: `scripts/ref_cotas.py`, `scripts/ref_conectores.py`. A mesma bateria rodou após cada item, com
regressão da fixture do conversor e de três famílias do gerador (todas seguiram aprovadas).

## O que as referências usam (e o pipeline não usava)

Planos com nome padrão repetido e em português; tabelas de consulta (`size_lookup` com CSV embutido); elipse no
perfil; conector com raio dirigindo o tamanho e conector hospedado em plano; materiais por parâmetro; famílias
aninhadas; travas de linha de esboço.

## Evolução (itens não reproduzidos pelo construtor; geometria da origem x convertida)

| Etapa | Solaris | Joelho | Luva emenda | Luva redução | Tê |
|---|---|---|---|---|---|
| Linha de base | 131 · volume −99,9% | 27 (construtor quebrava) | 19 (idem) | 23 (idem) | 30 (idem) |
| 1. Planos: endereço único + casamento pela geometria + qualquer orientação | 62 | 11 | 10 | 12 | 11 |
| 2. Tabelas de consulta (CSV byte a byte, aspas escapadas) | 44 → 27 com o item 3 | 6 | 7 | 9 | 6 |
| 3. Elipse no perfil | 27 · corpo passa a existir; 1 de 7 tipos exato | — | — | — | — |
| 4. Conector: raio → RN (adaptado) e conector em plano (lido) | 27 | 8 | 9 | 11 | 9 |
| 6. Materiais por nome | **6** | **7** | **8** | **10** | **8** |

Geometria própria da Ultrapex: **igual** (0,0% em extensão e volume) nas 4. Conectores: joelho e luvas 2 → 2;
tê 3 lidos → 0 criados (ver limites).

O que sobra em cada conexão Ultrapex: os 2 parâmetros embutidos de categoria com nome traduzido no Revit 2023
em português ("Loss Method", "K Coefficient Table" — pendência com a Rota B: casar por `BuiltInParameter`),
a adaptação do raio (registrada de propósito) e o tipo " " recriado como "Padrao".

## Limites provados nesta rodada

| Limite | Evidência |
|---|---|
| Raio de conector de tubo criado pela API não pode ser associado | Sonda S10 (`scripts/g5_sonda_raio.py`, Revit 2023): `CanElementParameterBeAssociated(CONNECTOR_RADIUS) = False` para Pipe Size e Length, instância e tipo; o diâmetro associa a todos. Adaptação: diâmetro → `<raio>_D`, raio = `<raio>_D / 2` (tamanho pelo tubo preservado; DN = RN × 2 continua) |
| Conector de tubo não nasce em plano de referência | `CreatePipeConnector` com referência de plano: "oEdgeLoopRef.ptr() is NULL" (tê Ultrapex, 3 conectores). Lacuna nomeada |
| Alinhamento com linha de esboço fora do modo de esboço | "The two references are not geometrically aligned" (20 na Solaris, 12 no tê); piorou o joelho; revertido. Vira a sonda S11 |
| O Revit não relê o próprio CSV de tabela com `1"` | "IncorrectNumberOfColumns"; corrigido escapando o campo com aspas |

## Onde a Solaris ainda não é fiel

- o diâmetro do corpo não flexiona (6 de 7 tipos com o diâmetro do tipo corrente; até +87% de volume): o
  perfil da revolução é preso aos planos por travas de esboço → sonda S11;
- os 9 bocais (e seus conectores) e o logo são famílias aninhadas → plano em
  `docs/PLANO-aninhadas-e-travas-de-esboco.md` (decisão do José: por último, não executado nesta rodada).

## Próximo

1. Sonda S11 (travas de esboço) — destrava o diâmetro da Solaris.
2. Aninhadas (plano pronto).
3. Recriar as duas pelo gerador com estas peças à mão (tabela de consulta e conector por diâmetro já servem às
   conexões da Tigre: uma família com todos os DN, tamanho pelo tubo).

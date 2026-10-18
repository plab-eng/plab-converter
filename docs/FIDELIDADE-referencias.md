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
| 6. Materiais por nome | 6 | 7 | 8 | 10 | 8 |
| S11 + S12. Travas de esboço, EQ, conector em plano | **6** · **7 de 7 tipos exatos** | **8** · 7/7 travas | **8** | **10** | **8** · conectores 3/3 |
| S13. Cota radial na vista do esboço, cota angular | **0** · cotas rotuladas 26/26 | **7** | **7** · cotas 2/2 | **9** · cotas 2/2 | **8** |

Geometria própria da Ultrapex: **igual** (0,0% em extensão e volume) nas 4. Conectores: 2 → 2 no joelho e nas
luvas, 3 → 3 no tê. A Solaris sai com extensão e volume iguais nos 7 tipos (200 a 1000 L).

A Solaris não tem mais nenhum item não reproduzido. Os 6 que sobravam ("One of the conditions for the inputs
was not satisfied") eram cotas de diâmetro e de raio em esboços verticais (bocais, no plano de normal X), que o
construtor criava sempre na planta. Agora nascem na vista paralela ao esboço, e o arco é casado pela geometria.
As 2 cotas radiais sem rótulo e sem trava são só anotação e ficam de fora de propósito: criá-las desfazia as
travas das faces das formas 6 e 7 (+8 mm no comprimento). Os itens que restam nas conexões são os de sempre:
parâmetros embutidos com nome traduzido (vão para a Rota B), a adaptação do raio e o tipo " ".

O que sobra em cada conexão Ultrapex: os 2 parâmetros embutidos de categoria com nome traduzido no Revit 2023
em português ("Loss Method", "K Coefficient Table" — pendência com a Rota B: casar por `BuiltInParameter`),
a adaptação do raio (registrada de propósito) e o tipo " " recriado como "Padrao".

## Limites provados nesta rodada

| Limite | Evidência |
|---|---|
| Raio de conector de tubo criado pela API não pode ser associado | Sonda S10 (`scripts/g5_sonda_raio.py`, Revit 2023): `CanElementParameterBeAssociated(CONNECTOR_RADIUS) = False` para Pipe Size e Length, instância e tipo; o diâmetro associa a todos. Adaptação: diâmetro → `<raio>_D`, raio = `<raio>_D / 2` (tamanho pelo tubo preservado; DN = RN × 2 continua) |
| Conector de tubo em plano de referência | Sonda S12 (`scripts/s12_sonda_conector_plano.py`): no **2023** `CreatePipeConnector` com o plano dá "oEdgeLoopRef.ptr() is NULL"; no **2024** funciona, mas o conector nasce na ponta do plano, e não no ponto da origem. **Solução, provada no 2023:** um disco VAZIO de 1 mm hospedado no próprio plano, no ponto da origem, recebe o conector na face. O conector acompanha o plano e o DN, liga ao tubo no projeto e não soma volume (vazio sem corte) |
| Trava de linha de esboço (alinhamento e cota) | Sonda S11 (`scripts/s11_sonda_esboco.py`): **funciona fora do modo de esboço** se for criada na vista paralela ao esboço e antes de o plano se mover (V1, V3 e V5 flexionam exatos; V4 reproduz o erro com o plano movido). O "not geometrically aligned" vinha de três coisas: (1) a trava na PONTA da curva (`LINEAR/0`, `LINEAR/1`) era lida como a curva inteira; (2) o destino recria o esboço com outra ordem e outro sentido de curvas, então o casamento por índice pegava a curva errada (corrigido: casamento pelas pontas e pelo ponto do meio); (3) a cota de igualdade (EQ) não existia no conversor: sem ela só um lado do diâmetro andava, e o diâmetro crescia em dobro |
| Cota angular no esboço | Sonda S13 (`scripts/s13_sonda_angular.py`): `FamilyItemFactory.NewAngularDimension(vista, arco, ref1, ref2)`, com o arco centrado no cruzamento das duas retas, rotulada fora do modo de esboço, **flexiona exata** no 2023 e no 2024 (30°, 45° e 60°). No fórum da Autodesk há relato de cota angular rotulada com "Constraint not satisfied", mas lá a cota era num arco, não entre duas retas |
| O Revit não relê o próprio CSV de tabela com `1"` | "IncorrectNumberOfColumns"; corrigido escapando o campo com aspas |

## Uso em projeto (tê convertido, Revit 2023)

`scripts/teste_conexao_em_projeto.py`: os 3 conectores ligam a tubos de 16 mm. Trocar o diâmetro de um tubo
ligado pela API não redimensiona a conexão, mas o tê ORIGINAL no 2024 faz o mesmo. Então a convertida se
comporta igual, e o teste de redimensionamento pela API é inconclusivo (falta conferir pela interface).

## O que ainda falta

- os 9 bocais da Solaris (e seus conectores) e o logo são famílias aninhadas → plano em
  `docs/PLANO-aninhadas-e-travas-de-esboco.md` (decisão do José: por último; não executado);
- os anéis das conexões Ultrapex também são aninhados;

## Próximo

1. Aninhadas (plano pronto).
2. Recriar as duas pelo gerador com estas peças à mão (tabela de consulta e conector por diâmetro já servem às
   conexões da Tigre: uma família com todos os DN, tamanho pelo tubo).

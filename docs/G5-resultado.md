# G5 — conexões MEP, parte 1: conector de tubo, Part Type e a luva da Tigre (17/10/2026)

Spec: `docs/SPEC-geracao-familias.md` §5.5 e §10 (G5). Depende de conector MEP, que não existia no repo (item 3 do
roadmap do conversor). Esta parte cria o conector nos dois lados do pipeline: geração e conversão.

## Sonda S9 (`scripts/g5_sonda_conector.py`, Revit 2024)

| Variante | O quê | Resultado |
|---|---|---|
| V1 família | Generic Model → categoria Pipe Fittings; Part Type `Union`; cilindro; `ConnectorElement.CreatePipeConnector(doc, PipeSystemType.Fitting, face.Reference)` nas duas faces planas; `CONNECTOR_DIAMETER` associado a `Diametro_Nominal`; conectores ligados entre si (`SetLinkedConnectorElement`) | **SIM**: DN40/50/75 com diâmetro, posição (pontas) e direção (para fora) certos |
| V2 projeto | família carregada em `Plumbing-Default_Metric.rte`, instância DN50, tubo DN50 terminando no conector, `ConnectTo` | **SIM**: `IsConnected = true` |

Nomes da API conferidos por reflexão na `RevitAPI.dll` do 2024 antes de escrever (sem chute). Armadilha:
`FamilySymbol.Name` não é acessível no IronPython; o nome vem de `SYMBOL_NAME_PARAM`.

## O que entrou

| Peça | O quê |
|---|---|
| FamilySpec 0.3.0 | `conectores` (domínio tubo, sistema, face = forma + normal, diâmetro por rótulo ou valor, `ligado_a`) e `identidade.part_type` (nome do enum) |
| Construtor | `aplicar_tipo_de_peca` e `construir_conectores` (depois das formas e das cotas radiais) |
| Leitor | `ler_conectores`: acha a face hospedeira pela geometria (a API não devolve a referência), lê o parâmetro associado ao diâmetro, o sistema e a ligação; Part Type pelo enum. Conector de outro domínio vira lacuna |
| Validador da geração | confere, por tipo, cada conector esperado: posição (0,1 mm), direção e diâmetro |
| Intenção | `tipo_de_peca`, `conectores` (componente, face `topo`/`base`, diâmetro, sistema, `ligado_a`) e a categoria `Pipe Fittings` |
| Modelo `luva_simples` | cilindro + 2 conectores ligados; tipos vêm da ficha |
| `fichas.para_luva_simples` | tabela da Tigre → um tipo por DN (legenda conferida no desenho da p.21: A comprimento, B diâmetro da bolsa, C e D profundidades das bolsas, E = DN) |
| `scripts/teste_conexao_em_projeto.py` | carrega a família num projeto de hidráulica e liga um tubo em cada conector |
| `run_ida_e_volta.ps1` | relê a família convertida no destino (o validador do conversor não confere conector) |

## Resultado

| Caso | Resultado |
|---|---|
| `PLAB_HID_Luva_Simples_Esgoto_SN` gerada da ficha Tigre FTC000021 (DN40 a DN200) | Revit 2024: **APROVADA**, 18 tipos validados (6 reais + 12 de teste) com conectores conferidos |
| Mesma luva num projeto, tipo DN100, tubo em cada ponta | **APROVADO**: os 2 conectores conectados, tubo 100 = conector 100 |
| Ida e volta 2024 → 2023 com releitura | conectores (sistema, rótulo DN, ligação, normais) e Part Type `Union` **atravessam**; geometria `REPRODUZ` nos 6 DN; 2 divergências de parâmetro (abaixo) |

**As 2 divergências não são da luva.** "Loss Method" e "K Coefficient Table" são parâmetros embutidos da
categoria Pipe Fittings. O Revit 2023 desta máquina está em português (a categoria aparece como "Conexões de
tubo") e os nomes desses parâmetros vêm traduzidos; o conversor compara parâmetro por **nome**. É um defeito do
conversor que vale para qualquer conversão entre Revits de idiomas diferentes: o certo é casar parâmetro embutido
pelo `BuiltInParameter`. A correção mexe no `validador.py` (régua da Rota B) e fica como pendência combinada.

Lacunas declaradas da luva: corpo maciço de diâmetro único (sem o furo e sem o degrau entre bolsa e corpo);
profundidade das bolsas (C e D) como dado, sem `CONNECTOR_ENGAGEMENT_LENGTH`.

Testes: 47 (pytest, < 1 s).

## Parte 2 — junção 45° (a da imagem do José, Tigre p.18)

`gerador/conexoes.py` + `python -m gerador conexoes <extracao> --produto "Junção Simples" ...`: a tabela A–F vira
uma intenção **estática por DN**, Part Type `Wye`, 3 conectores (os 2 da passagem ligados entre si; o do ramal
livre). O ramal é uma revolução em eixo inclinado (o padrão `revolucao` ganhou o eixo `xz` com ângulo); a face da
ponta recebe o conector.

Legenda pelo desenho: A altura total; B e E o DN de baixo e de cima; C da borda do corpo até a ponta do ramal
(horizontal); D e F as bolsas de cima e de baixo. Com isso, largura = C e altura = A fecham exatas.

Adotado e declarado em `lacunas_aceitas` (a ficha não traz): diâmetro externo = DN; ponta do ramal no início da
bolsa de cima (z = A − D); corpo maciço; e família estática, porque a cota de raio só foi provada em esboço
horizontal.

| Caso | Resultado |
|---|---|
| 6 famílias, DN40 a DN200 | Revit 2024: **APROVADAS** (bbox exato, 3 conectores na posição e direção certas) |
| `PLAB_HID_Juncao_45_Esgoto_SN_DN100` num projeto | **APROVADO**: tubo DN100 conectado nos 3 conectores, inclusive no ramal a 45° |

**Descoberta: o Revit calcula volume de superfície curva sobre uma malha de cordas de ~2 mm.** Na primeira rodada,
DN40 a DN100 reprovaram por volume (bbox exato): medido sempre menor, −0,153% (r = 20), −0,0635% (25),
−0,0316% (37,5), −0,0165% (50), −0,0099% (75), −0,0066% (100), ou seja, erro ≈ (2/r)²/6. A régua fixa de 0,01%
reprovaria qualquer peça curva pequena (pé redondo fino também). Agora o compilador grava, por tipo, a tolerância
de volume das peças curvas (1,5 × (2/r)²/6 sobre o volume delas, `CORDA_DA_MALHA_MM`); peça plana continua nos
0,01%, e a extensão continua a 0,1 mm.

Testes: 48 (pytest, < 1 s).

## Pendências

- Conversor: casar parâmetro embutido por `BuiltInParameter`, não pelo nome (pendência com a Rota B).
- Junção paramétrica (um arquivo com todos os DN) depende de cota de raio em esboço inclinado — a sondar.
- Furo, degrau das bolsas e profundidade de encaixe (`CONNECTOR_ENGAGEMENT_LENGTH`) nas conexões.

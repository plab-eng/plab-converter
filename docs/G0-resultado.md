# G0 — resultado das sondas (17/10/2026)

Spec: `docs/SPEC-geracao-familias.md` §10. Script: `scripts/g0_sondas.py`, orquestrado por
`scripts/run_g0.ps1 -Revit <ano>`. Saída (fora do git): `out/g0/<ano>/resultado.json` e um `.rfa` por sonda.

Rodado na JOSEDESK em **Revit 2022 (22.0.2.392)** e **Revit 2024 (24.3.30.11)**, com resultados idênticos.
O 2025 não rodou: ver "Ambiente".

## Quadro

| Sonda | Mecanismo | 2022 | 2024 | Conclusão |
|---|---|---|---|---|
| S1 | caixa centrada **sem cota EQ**: parâmetro `Meia_Largura = Largura / 2` rotulando duas cotas a partir do plano Center | SIM | SIM | 3 tipos (300/600/1500) com bbox, posição (mínimo = −L/2) e volume exatos. A cota EQ não é necessária |
| S2-A1 | cilindro: cota radial na **aresta** do sólido | ERRO | ERRO | `Constraints are not satisfied`; o Revit desfaz. Caminho descartado |
| S2-A2 | cilindro: cota radial (`NewRadialDimension`) na **curva do esboço** (`Extrusion.Sketch.Profile`), rotulada | flexiona | flexiona | Volume a ≤ 0,005% de πr²h nos 3 raios; extensão X exata. **Este é o caminho do padrão `cilindro`** |
| S2-B | cilindro: revolução com a face cilíndrica alinhada a um plano | ERRO | ERRO | `The two references cannot be matched to create an alignment`. Caminho descartado |
| S3-A | `LinearArray.Create` + `BaseArray.Label` = parâmetro inteiro `N` | SIM | SIM | N = 2, 3 e 5 com bbox e volume exatos. **Caminho do padrão `array`** |
| S3-B | 4 cópias com `IS_VISIBLE_PARAM` associado a sim/não com fórmula | SIM | SIM | A fórmula `N > k-1` avalia certo por tipo. Fica como alternativa (contagem com teto) |
| S4 | volume analítico × medido | caixa e array: 0,000000% · cilindro: 0,0014–0,0047% | idem | Dentro da tolerância de volume do validador (0,01%) |
| S5 | Revit 2022: template e `AddParameter(nome, GroupTypeId, SpecTypeId, bool)` | SIM | SIM | `Metric Generic Model.rft` em `English\`; o caminho moderno do `AddParameter` funciona no 2022 |
| S6 | `Categories.NewSubcategory` + `GenericForm.Subcategory` | SIM | SIM | A subcategoria "Tampo" é atribuída e lida de volta |
| S7 | `ImageType.Create(ImageTypeOptions(caminho, False, Import))` + parâmetro Type Image | SIM | SIM | A imagem do tipo é gravada pela API |

## Descobertas que mudam a spec

1. **Bbox de sólido curvo é folgado.** `Solid.GetBoundingBox()` devolve um cilindro de r=200 com 403,19 mm
   de largura. A extensão pelos vértices da malha (`Face.Triangulate`) dá 400,000 em X, mas pode ficar até
   ~0,3 mm curta onde a malha não tem vértice no extremo (Y no R200: 399,676). Consequência para o
   compilador: a assinatura de padrão curvo é conferida pelo **volume** (régua do validador) e pela
   extensão no eixo em que o esboço tem vértice garantido. O validador atual usa bbox do sólido nos dois
   lados da conversão, por isso nunca sentiu o problema; a geração sente, porque o esperado é analítico.
2. **Fórmula do Revit não aceita `>=` nem `<=`.** `N >= 1` é recusada ("invalid formula string").
   O compilador escreve `N > k-1` (ou `not(N < k)`).
3. **Cota radial só na curva do esboço.** A aresta do sólido não serve, e a revolução não alinha com
   plano. O construtor precisa de um campo novo na FamilySpec para "cota radial no laço X do esboço da
   forma Y" (schema 0.2.0).

## Ambiente

- **Revit 2025 não roda pelo `pyrevit run` nesta máquina.** O motor IronPython .NET 8 do pyRevit 5.3.1
  (`bin\netcore\engines\IPY2712PR`) quebra no `import os` de um script de duas linhas
  (`ValueError: Type doesn't have a method with a given name and signature`, em `warnings.py`). Não é
  do código da sonda. A instalação do pyRevit não foi mexida.
- Havia um instalador do Revit 2027 rodando durante os testes (`Autodesk_Revit_2027_3_ML_`).
- `pyrevit run` foi chamado com caminho absoluto do script e do modelo; com caminho relativo o script
  não chega a rodar e o CLI devolve exit 0 sem log.

## Próximo passo

G1 (spec §10): compilador em CPython com o padrão `caixa`, usando o S1 como receita de centragem.
Antes, decidir se a G1 já inclui o campo de cota radial (descoberta 3) ou se ele fica para a G2.

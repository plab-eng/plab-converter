# G1 — compilador + caixa + cilindro (17/10/2026)

Spec: `docs/SPEC-geracao-familias.md` §10. A G1 incluiu o cilindro com cota radial (decisão do José,
17/10), que a spec punha na G2.

## O que existe

| Peça | Arquivo | Roda em |
|---|---|---|
| Expressões (nomes, números, `+ - * /`, parênteses) | `gerador/expressao.py` | CPython |
| Validação da intenção (vocabulário fechado, imagem obrigatória, pergunta aberta bloqueia) | `gerador/intencao.py` | CPython |
| Compilador: padrões `caixa` e `cilindro`, tipos de teste, assinatura analítica, viabilidade, `fixos` | `gerador/compilador.py` | CPython |
| Orquestrador: compila → constrói → valida → fixa culpado e recompila (≤ 2 voltas) → família final | `gerador/orquestrar.py` | CPython + `pyrevit run` |
| Linha de comando | `python -m gerador compilar|gerar <intencao.json> [--revit 2024]` | |
| Validador da geração (malha, posição, tolerância por tipo) | `scripts/validador_geracao.py` | IronPython |
| Testes | `tests/` (24, pytest, < 1 s) | CPython |
| Exemplos | `exemplos/mesa_4_pes.json`, `bancada.json`, `mesa_redonda.json` | |

Mudanças no pipeline do conversor (aditivas):

- `rfaspec.SCHEMAS_ACEITOS = ("0.1.0", "0.2.0")`; 0.2.0 = cota `"Radial"` na curva do esboço de uma forma;
- `construtor.construir_cotas_radiais` (depois das formas); `construir_cotas` pula as radiais;
- `construtor._linha_para_cota` decide a direção pela **normal** dos planos, não pelas pontas de bolha
  (a ponta do plano Center do template não está alinhada com a dos planos gerados);
- o `validador.py` não foi tocado.

## Resultado

| Família | Formas | Tipos validados (reais + teste) | Revit 2022 | Revit 2024 | Revit 2025 |
|---|---|---|---|---|---|
| `PLAB_MOB_Mesa_Retangular` (tampo + 4 pés fora do centro) | 5 caixas | 2 + 14 | APROVADA | APROVADA | APROVADA |
| `PLAB_MOB_Bancada` (tampo + 2 laterais, constantes na fórmula) | 3 caixas | 1 + 10 | APROVADA | APROVADA | APROVADA |
| `PLAB_MOB_Mesa_Redonda` (tampo, coluna e base) | 3 cilindros | 2 + 14 | APROVADA | APROVADA | APROVADA |

Em todos: extensão, posição e volume de cada tipo dentro da régua, zero divergência de parâmetro, zero item
não reproduzido pelo construtor. As 5 lacunas da mesa retangular são subcategorias declaradas e ainda não
construídas (G2). Nenhum parâmetro precisou ser fixado, então **o laço de desfazer não foi exercitado em
família real** (só no teste do compilador).

**Regressão do conversor** (`run_fase0.ps1 -RevitOrigem 2024 -RevitDestino 2023`, rodada antes de o pyRevit
ser atualizado e o 2025 voltar a rodar pelo CLI): APROVADA, 4 tipos `REPRODUZ`, 0 divergências, 1 item não reproduzido (o plano
"Reference Plane" do template, o mesmo de antes). A rodada sobrescreveu os artefatos de `out/` (fora do
git) com uma fixture criada no 2024.

## Descobertas

1. **Número solto em fórmula de comprimento é lido em mm**: o Revit reescreve `0 - x` como `0 mm - x`
   (template métrico). O validador da geração normaliza o sufixo antes de comparar.
2. **Cadeia de cotas a partir do centro funciona para peça fora do centro**: centro → plano próximo
   (rotulado com o afastamento) → plano distante (rotulado com o tamanho), nessa ordem de criação.
3. O 2025 (pyRevit 6.5.5) aprova as três famílias sem mudança de código.
4. Uma família com 16 tipos sai do zero, validada, em ~75 s no 2024 (duas montagens e duas validações).

## Pendências para a G2

- subcategorias (S6 provou a API) e materiais por nome (roadmap do conversor);
- padrão `array` (S3-A provou `LinearArray` + `Label`);
- cilindro fora do centro (hoje só na origem);
- o `leitor.py` ainda não lê a cota radial (schema 0.2.0); a spec §6.2 pede os dois juntos;
- exercitar o laço de desfazer com um caso que reprove de verdade.

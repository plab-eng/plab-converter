# G2 — arrays, subcategorias, catálogo de mobiliário e cota radial na conversão (17/10/2026)

Spec: `docs/SPEC-geracao-familias.md` §10. Continua a G1 (`docs/G1-resultado.md`).

## O que entrou

| Peça | O quê |
|---|---|
| Padrão `array_retangular` | linhas × colunas de um padrão simples; os argumentos do item usam os índices `i` e `j` |
| Padrão `array_linear` | `n` cópias (número fixo ou parâmetro inteiro, com `n_max`); os argumentos do item usam `k`. Com `n` paramétrico, a cópia k fica visível por fórmula `n > k-1` |
| Caixa que cruza o centro | cota de cada lado a partir do plano Center (`t/2 - c` e `t/2 + c`); antes só peça centrada ou peça inteira de um lado |
| Tamanho constante | vira parâmetro de fórmula (ex.: `GER_encosto_tam_y = 30`), para travar a cota; sem rótulo, o plano distante ficava solto |
| Recusa de viabilidade | uma linha por causa, com os tipos em que aparece |
| Construtor: subcategoria | aplica `subcategoria` pelo nome, criando se não existir (serve à conversão: o leitor sempre gravou e o construtor ignorava) |
| Construtor: visibilidade fixa | `visivel: false` sem associação é aplicado; com `Visible` associado, fica a cargo da associação |
| Construtor: cota de diâmetro | `NewDiameterDimension` para cota `"Diameter"` no esboço |
| Leitor: cota radial | lê raio/diâmetro rotulado na curva do esboço (`{"tipo": "esboco", "forma", "laco", "curva"}`), grava schema 0.2.0 só quando há uma |
| Leitor: robustez | cota que recusa até a leitura do rótulo ("This dimension can not be labeled") vira "sem rótulo"; cotas internas do esboço continuam lacuna |
| Validador da geração | ignora formas ocultas no tipo corrente; confere a subcategoria de cada forma |
| Orquestrador | procura a CLI 6.5.5 por caminho fixo (ou `RFADG_PYREVIT`), sem depender do PATH |
| `scripts/run_ida_e_volta.ps1` | converte uma família existente pela Rota A (leitor → construtor → validador) |
| Testes | 31 (pytest, < 1 s), incluindo o laço de desfazer com o Revit simulado |

**Decisão de implementação:** o array é feito com cópias + visibilidade (sonda S3-B), não com `LinearArray`
(S3-A). Cada cópia é uma forma comum, com planos, cotas e alinhamentos próprios, então a prateleira acompanha
a largura da estante. O `LinearArray` só foi provado com peça de tamanho fixo. O custo é um teto de cópias
(`n_max`) e as cópias ocultas existirem no documento da família.

## Resultado

Seis famílias, cada uma validada com os tipos reais e os tipos de teste nos extremos das faixas:

| Família | Formas | Tipos validados | 2022 | 2024 | 2025 |
|---|---|---|---|---|---|
| `PLAB_MOB_Mesa_Retangular` (tampo + array 2×2 de pés) | 5 | 16 | APROVADA | APROVADA | APROVADA |
| `PLAB_MOB_Estante` (corpo + até 5 prateleiras por `N_Prateleiras`) | 9 | 14 | APROVADA | APROVADA | APROVADA |
| `PLAB_MOB_Armario` (estante + 2 portas) | 10 | 16 | APROVADA | APROVADA | APROVADA |
| `PLAB_MOB_Cadeira` (assento, encosto, array 2×2 de pés) | 6 | 15 | APROVADA | APROVADA | APROVADA |
| `PLAB_MOB_Bancada` | 3 | 11 | APROVADA | APROVADA | APROVADA |
| `PLAB_MOB_Mesa_Redonda` (3 cilindros) | 3 | 16 | APROVADA | APROVADA | APROVADA |

Em todas: nenhum item não reproduzido pelo construtor, nenhuma divergência de parâmetro, subcategorias
conferidas. Nenhum parâmetro precisou ser fixado; o laço de desfazer está coberto por teste com o Revit
simulado (`tests/test_compilador.py`), não por um caso real que reprove.

**Ida e volta** (família gerada no 2024 → leitor → construtor 2023 → `validador.py` do conversor):

| Família | Schema lido | Cotas | Resultado |
|---|---|---|---|
| Mesa redonda | 0.2.0 (3 cotas radiais) | 3 | APROVADA, 0 divergência, só o plano "Reference Plane" do template não reproduzido |
| Estante | 0.1.0 (subcategorias `Corpo` e `Prateleiras`) | 36 | APROVADA, 0 divergência, idem |

**Regressão do conversor** (`run_fase0.ps1 -RevitOrigem 2024 -RevitDestino 2023`), depois das mudanças no
construtor: APROVADA, 4 tipos `REPRODUZ`, 0 divergência, 1 item não reproduzido (o mesmo plano de template).

## Ambiente (17/10)

- pyRevit 6.5.5 instalado (CLI e clone), anexado ao 2021–2027; ver memória "pyRevit 6.5.5 na JOSEDESK".
- A CLI 6.5.5 baixou para o cache uma tabela de builds sem os antigos, e a portadora (salva no 2018) deixou de
  ser reconhecida. Corrigido copiando `pyrevit-hosts.json` da instalação para
  `%APPDATA%\pyRevit\Cache`. Se voltar, trocar a portadora por uma família salva no 2021.

## Pendências

- cilindro fora do centro (o centro do arco não se trava em plano pela API fora do modo de esboço; candidato:
  `SketchEditScope`, a sondar);
- materiais por nome (roadmap do conversor, item 4);
- vazio (rodapé do armário) e combinação de corte no gerador;
- G3: entradas (formulário, imagem como referência e Type Image, extrator de ficha PDF por regra, IA opcional).

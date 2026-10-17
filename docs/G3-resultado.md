# G3 — entradas, parte 1: formulário sem IA, prévia e imagem do tipo (17/10/2026)

Spec: `docs/SPEC-geracao-familias.md` §3.4 e §10 (G3). A G3 tem quatro peças; esta entrega fecha duas e
deixa as outras duas esperando material real.

| Peça | Situação |
|---|---|
| Formulário sem IA (modelos prontos + perguntas) | **feito** |
| Imagem obrigatória → prévia + Type Image na família | **feito** |
| Extrator de tabela de ficha técnica em PDF, por regra | **aguardando fichas reais** (não há nenhuma no Drive: `00.Biblioteca\Fabricantes` só tem `.rfa` e um tutorial da Sodramar) |
| IA opcional preenchendo o formulário a partir da imagem | **aguardando fotos reais** para medir acerto contra a régua de 96% |

## Formulário sem IA

`gerador/modelos/*.json`: seis modelos (mesa de 4 pés, estante, armário, cadeira, bancada, mesa redonda), cada
um com a intenção pré-montada e as perguntas que a preenchem. As perguntas usam o contrato de etapa das receitas
(`id`, `pergunta`, `opcoes`, `padrao`, `por_que`, `imagem`). Pergunta sem resposta assume o padrão e fica
registrada (`aceitou_padrao`); resposta fora da faixa do modelo ou para pergunta inexistente é recusada com o
motivo. A `origem` de cada parâmetro diz quem o preencheu (usuário, regra, IA, ficha).

```
python -m gerador modelos                                   # catálogo
python -m gerador perguntas estante --saida perguntas.json  # o que responder
python -m gerador montar estante --nome PLAB_MOB_Estante_Sala --imagem foto.jpg \
       --respostas respostas.json --saida intencao.json      # respostas -> intenção
python -m gerador previa intencao.json --saida previa.png    # conferir antes do Revit
python -m gerador gerar intencao.json --revit 2024           # .rfa validado
```

## Prévia e imagem do tipo

- `gerador/previa.py`: isométrica sombreada em PNG das primitivas do tipo corrente (caixas e cilindros),
  sem Revit; cópias ocultas de array ficam de fora. Limitação conhecida: ordem de pintura simples (pode
  sobrar uma aresta errada em peças encostadas).
- O compilador grava `imagem_do_tipo` na FamilySpec; o construtor cria a `ImageType` e a grava como Type Image
  em **todos** os tipos (API da sonda S7); o validador da geração confere tipo a tipo.
- O orquestrador resolve a imagem relativa à pasta da intenção e recusa a geração se ela não existir.
- Nos exemplos, a imagem é a prévia gerada (`exemplos/entradas/*.png`), identificada na própria legenda.

## Resultado

| Caso | Revit | Resultado |
|---|---|---|
| `exemplos/estante.json` com imagem | 2024 | APROVADA, Type Image em todos os tipos |
| Estante montada por respostas (1100 × 2000, 4 prateleiras), prévia como imagem | 2024 | APROVADA, 13/13 tipos de teste + o tipo final |

Testes: 37 (pytest, < 1 s).

## O que falta na G3

- **Fichas técnicas:** 2 ou 3 PDFs reais de fabricante (mobiliário ou conexões) com tabela de medidas, para
  escrever o extrator por regra contra arquivo real.
- **Fotos:** algumas fotos reais de móveis com as medidas conhecidas, para medir a IA preenchendo o formulário
  contra a régua de 96% (spec §9).

# G3 — entradas: formulário sem IA, prévia, imagem do tipo e ficha técnica por regra (17/10/2026)

Spec: `docs/SPEC-geracao-familias.md` §3.4 e §10 (G3). As quatro peças estão feitas.

| Peça | Situação |
|---|---|
| Formulário sem IA (modelos prontos + perguntas) | **feito** |
| Imagem obrigatória → prévia + Type Image na família | **feito** |
| Extrator de ficha técnica em PDF, por regra | **feito** (parte 2, abaixo), com as 3 fichas recebidas do José |
| IA opcional preenchendo o formulário a partir da imagem | **feito** com as 3 imagens do José (parte 3) |

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

## Parte 2 — ficha técnica por regra

`gerador/fichas.py`: três leitores, um por formato recebido; todo valor guarda página e linha; o que a regra
não decide vira pergunta com a evidência e um padrão sugerido pela própria ficha.

| Ficha (recebida em 17/10) | Formato | O que a regra extraiu | O que virou pergunta |
|---|---|---|---|
| Memorial "Armário estante p/ livros 2 portas 60x210x42cm" | `especificacao_texto` | L 600, A 2100, P 420 (de "60x210x42cm (LxAxP)"), 3 prateleiras ("três prateleiras"), lateral 18 mm, "duas portas inferiores" | altura do balcão (o memorial não dá) |
| Manual MPO "Estante 2 portas 8040/9040" (lista de peças) | `lista_de_pecas` | largura 816 (rodapé/moldura), profundidade 398 (rodapé lateral), chapa 17 (lateral 1790×380×17) | altura total (1790 ou 1825 com a moldura), balcão (porta 614 + rodapé 70 = 684), nº de prateleiras (a lista não traz quantidade) |
| Tigre FTC000021 "Esgoto Série Normal" (28 páginas) | `tabela_por_bitola` | 29 conexões com códigos e tabela por DN (102 linhas); a tabela que atravessa a página fica com o produto certo (Junção Simples: códigos na p.17, tabela na p.18) | 11 linhas sinalizadas (colunas a mais: "Tubo Ponta-Bolsa" e "Joelho 90°" com "Peso (g)"); 2 conexões sem lista de códigos |

As duas fichas de mobiliário descrevem o mesmo móvel, que nenhum modelo cobria: **estante com 2 portas
inferiores**. Novo modelo `estante_portas_inferiores` (corpo, tampo do balcão, até 4 prateleiras em cima,
2 portas no balcão).

```
python -m gerador ficha armario.pdf --modelo estante_portas_inferiores --saida armario.ficha.json
python -m gerador montar estante_portas_inferiores --nome PLAB_MOB_Armario_Livros --imagem foto.png ^
       --ficha armario.ficha.json [--respostas suas_respostas.json] --saida intencao.json
```

A origem de cada valor fica na intenção: `ficha` (com a evidência), `usuario`, `padrao_da_ficha` ou `padrao`.

| Família gerada da ficha | Revit | Resultado |
|---|---|---|
| `PLAB_MOB_Armario_Livros_60x210x42` (imagem = prévia; o PDF não tem foto) | 2024 | APROVADA, 17/17 tipos de teste + o tipo final, 0 divergência |
| `PLAB_MOB_Estante_MPO_8040` (imagem = página 1 do manual) | 2024 | APROVADA, 17/17 tipos de teste + o tipo final, 0 divergência |

A extração da Tigre fica guardada para a G5 (conexões; depende dos conectores MEP do conversor).

**Prévia com z-buffer:** a ordem de pintura pela profundidade média escondia a porta atrás da lateral; agora a
profundidade é comparada pixel a pixel e as arestas saem onde muda a face visível.

Testes: 43 (pytest, < 1 s), com trechos do texto real das três fichas.

## Parte 3 — IA preenchendo o formulário a partir da imagem (teste de ouro)

A IA (aqui, o próprio Claude Code, como fará o Assistant no produto) olha a imagem, escolhe o modelo e responde
às perguntas dele; nunca escreve a FamilySpec. A intenção registra `preenchido_por: ia`. A régua
(`gerador/regua.py`) compara a extensão **medida no Revit** na família gerada com as cotas escritas na imagem.

| Imagem (17/10) | Modelo escolhido | Leitura da IA | Revit 2024 | Régua 96% |
|---|---|---|---|---|
| Balcão Saara 80 × 37 × 75 cm, 1 porta + 4 gavetas | `balcao_porta_gavetas` (novo) | L 800; corpo 352 + frente 18 = 370; A 750; rodapé ≈ 40 (estimado na foto); 4 gavetas | APROVADA, 19/19 tipos de teste | **100% / 100% / 100%** |
| Estante 60 × 30 × 160 cm, MDF 1,5, 2 portas inferiores, vãos de 37 | `estante_portas_inferiores` | L 600; corpo 285 (+ porta) ; A 1600; chapa 15; balcão 815 (da conta dos vãos); 1 prateleira em cima | APROVADA, 17/17 | **100% / 99% / 100%** (porta saiu com 18 mm: o modelo não pergunta a espessura da porta) |
| Guarda-roupa, vista interna com cabideiros, gavetas e nichos | nenhum: fora do catálogo | a imagem não dá as medidas externas totais | não gerado | — |

Ressalvas, para não ler mais do que foi medido:
- as duas imagens trazem as cotas escritas; o teste mede a IA **lendo** cotas e escolhendo o modelo, não
  estimando medidas de uma foto sem cota;
- a régua fica no bbox: a imagem não dá o volume real;
- o que o modelo não tem fica de fora e deveria virar lacuna aceita: na estante, o rodapé de 7 cm e a
  prateleira interna do balcão; no balcão, puxadores e fechadura;
- o guarda-roupa pede "modelo completo" (divisões internas, cabideiro, gavetas em grade), fase posterior.

Modelo novo `balcao_porta_gavetas`: rodapé recuado, corpo, 1 porta e coluna de gavetas (2 a 6, frentes de
mesma altura, contagem paramétrica). A faixa de profundidade da `estante_portas_inferiores` foi alargada para
250–600 (o corpo de uma estante de 30 cm com porta de 15 tem 285).

Testes: 45 (pytest, < 1 s).

## Pendências

- As perguntas abertas das estantes vindas de ficha foram respondidas com o padrão sugerido pela ficha; o José
  pode responder de verdade (`--respostas`) e gerar de novo.
- Teste de ouro com foto **sem** cotas (a IA estimando proporções), para medir o caso difícil.
- Perguntar a espessura das frentes na `estante_portas_inferiores` (fonte do 1% da estante).

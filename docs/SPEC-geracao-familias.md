# SPEC — Geração de famílias Revit (plab-converter)

> Rascunho v0.1 · 16/10/2026 · branch `spec/geracao-familias` (a partir da `main`, ef5c882)
> Origem: conversa de 15–16/10/2026 sobre as receitas do PLAB Assistant + decisões do José em 16/10.
> Documento só de especificação. Nenhum código foi escrito nem rodado para produzi-lo.

**Marcas usadas no texto**

| Marca | Significado |
|---|---|
| **[C]** | Conferido no código deste repo ou da referência citada, em 16/10/2026 |
| **[H]** | Hipótese. Só vale depois da sonda da fase G0 |
| **[D]** | Decisão do José (16/10/2026) |

---

## 1. Objetivo e não-objetivos

**Objetivo.** Gerar uma família Revit (`.rfa`) **nova e nativa** a partir de um formulário, de uma imagem, de uma
ficha técnica em PDF e das diretrizes do cliente. A família deve ser **paramétrica de verdade**: ao trocar um
parâmetro, a geometria acompanha, e o validador do conversor comprova isso tipo a tipo. Há também um modo não
paramétrico (geometria fixa) para quem só precisa do volume.

**Tese.** Gerar família é o mesmo problema que converter. Na conversão, a FamilySpec vem do `leitor.py`. Na
geração, ela vem de um **compilador determinístico** que expande uma "intenção" simples. Construtor e validador
são os mesmos.

**Por que vale.** Os concorrentes conhecidos (conferidos em 15/10/2026) não fazem paramétrico:

| Produto | O que entrega | Limite |
|---|---|---|
| FamFab (kilkellym/ArchSmarterFamFab, MIT) | imagem/texto → JSON → add-in; chave do Claude do próprio usuário | **[C]** `FamilyGenerator.cs` avalia as expressões para número (`EvaluateExpression` com os valores padrão), não cria cota, não usa `FamilyLabel` nem fórmula, e não lê o campo `constraints` do schema. O autor desistiu do paramétrico: "resultado inconsistente é pior que resultado limitado". |
| Mainspring (beta fechado) | `.rfa` com parâmetros | os parâmetros não mexem na geometria |

Aqui já existe a metade difícil **[C]**: planos canônicos, cotas rotuladas (`Dimension.FamilyLabel`),
alinhamentos travados, associações de parâmetro, fórmulas (com locale pt-BR), compartilhados com GUID, tipos,
vazios com `CombineElements` e um validador que mede bounding box e volume tipo a tipo.

**Não-objetivos da v1**

- famílias aninhadas (Fase 3 do conversor);
- conectores MEP (Fase 4 do conversor). Por isso as conexões MEP entram depois do mobiliário (§10) **[D]**;
- famílias hospedadas em parede, piso ou face (porta, janela, luminária de teto);
- Rota B (tradução do binário): é frente do conversor, não da geração (§2);
- versão web ou nuvem: a geração roda no Revit do usuário (§3.3).

**Versões [D].** As famílias saem em **Revit 2022 a 2026**. "Retrocede até o 22" vale também para o conversor;
ver §2.3.

---

## 2. Relação com o conversor

### 2.1 Pipeline compartilhado

```
CONVERSÃO   .rfa origem --[leitor]--------------------> FamilySpec --[construtor]--> .rfa --[validador]
GERAÇÃO     formulário  --[compilador]----------------> FamilySpec --[construtor]--> .rfa --[validador]
```

A FamilySpec é o contrato entre as duas frentes. Qualquer campo novo serve aos dois produtos e é coordenado com
o `leitor.py`: quando o construtor aprende a fazer algo, o leitor deve aprender a ler o mesmo campo.

### 2.2 Prioridade e dependências

O roadmap do conversor (RELATORIO §6) **vem primeiro**: esboço ilegível, aninhadas, conectores MEP e materiais
por nome. A geração não atropela essa fila. O que ela precisar do roadmap espera o item ficar pronto. O que for
novo e só da geração entra na fila dela.

| A geração precisa de | Situação hoje | Origem do trabalho |
|---|---|---|
| Caixa paramétrica (planos verticais + cotas + altura por associação) | **[C]** existe; é a fixture | pronto |
| Cota de igualdade (EQ) | **[C]** não existe no construtor | evitável: §5.1 (centrado por fórmula) |
| Cota radial/diâmetro rotulada (cilindro) | **[C]** não existe; `construir_cotas` só resolve planos | novo (G0/G2) |
| Array com contagem paramétrica | **[C]** não existe | novo (G0/G2) |
| Planos de referência horizontais | **[C]** não existem: `NewReferencePlane(..., XYZ.BasisZ, vista_de_planta)` cria só verticais | novo, se a sonda mostrar que a associação de altura não basta |
| Subcategorias | **[C]** não existem (Fase 2 do conversor) | Fase 2 do conversor, antecipada para a geração |
| Materiais por nome | **[C]** hoje viram lacuna (ElementId) | item 4 do roadmap do conversor |
| Conectores MEP | **[C]** não existem | item 3 do roadmap (Fase 4) — pré-requisito das conexões MEP |
| Imagem do tipo (Type Image) | não existe | novo (G3) **[H]** API `ImageType` |

### 2.3 Rota B e versões

- Se a Rota B (spike de 16/10, branch `spike/rota-b`) vencer na conversão, **a Rota A continua viva como motor
  da geração**. O construtor e o validador não ficam órfãos.
- O "Portão 0" jurídico da Rota B (engenharia reversa) **não se aplica à geração**, que usa só a API pública do
  Revit.
- Enquanto o spike estiver aberto, a geração **não altera o `validador.py`**, que é a régua da Rota B.
  Isto é viável porque a geração usa o validador como está (§6.6).
- **Conflito a registrar:** o `CLAUDE.md` fixa "2023 a 2026". A decisão de 16/10 é **2022 a 2026**, para os
  dois produtos. O `CLAUDE.md` deve ser atualizado numa sessão própria, depois do merge do spike, para não
  conflitar com o §6 que a Rota B reescreveu. Esta máquina (JOSEDESK) tem Revit 2019 e 2021 a 2025; a
  Coordenador tem 2021, 2022 e 2024 a 2027, sem o 2023.
- O APS Design Automation tem engines de 2023 a 2026 (CLAUDE.md §3). Saída em 2022 só no Revit local.

---

## 3. Arquitetura

### 3.1 Fluxo

```
ENTRADAS                     PREENCHIMENTO                NÚCLEO (sem IA)                         SAÍDA
imagem (obrigatória) ─┐
ficha PDF (opcional) ─┼──> formulário ──> intencao.json ──> COMPILADOR ──> FamilySpec ──> CONSTRUTOR ──> .rfa
perfil do cliente ────┘    (regra ou IA)                    (puro, sem Revit)      │             (no Revit)     │
                                                                                     │                            ▼
                                                            assinatura esperada ─────┴──────────────────> VALIDADOR
                                                                                                                  │
                                                         lacuna? recompila com o parâmetro fixo <─────────────────┘
```

### 3.2 Peças

| Peça | Faz | Precisa de Revit? | Protótipo | Produto |
|---|---|---|---|---|
| Formulário | categoria, modelo pronto, medidas, faixas, perfil | não | JSON escrito à mão ou pelo Claude Code | WPF na aba Receitas do PLAB Assistant |
| Preenchimento por regra | modelos prontos (§5.4) e extrator de tabela da ficha PDF | não | Python 3 | C# |
| Preenchimento por IA (opcional) | lê a imagem e preenche o formulário | não | o próprio Claude Code escreve a `intencao.json` | mesmo canal de IA do PLAB Assistant |
| Compilador | intenção → FamilySpec + assinatura esperada + prévia | **não** | **Python 3 (CPython) com pytest** | C# numa biblioteca sem Revit (`dotnet test`) |
| Construtor | FamilySpec → `.rfa` | sim | pyRevit/IronPython (o atual) | C# no add-in (Fase 5 do conversor) |
| Validador | mede por tipo e compara | sim | pyRevit/IronPython (o atual) | C# no add-in |
| Prévia 3D | malha simples gerada pelo compilador | não | dispensável | WPF `Viewport3D` (WebView2 e CefSharp são vetados no add-in) |

**Por que o compilador em CPython e não em IronPython:** ele não toca o Revit. Em CPython roda com pytest em
segundos e sem as armadilhas de encoding do `pyrevit run` (CLAUDE.md §7, 15–16). A FamilySpec que ele grava é
JSON comum; o construtor a lê com `rfaspec.ler_json`. **[H]** O JSON gerado pelo CPython precisa ser lido sem
erro pelo `rfaspec.ler_json`; isso é teste da G1.

### 3.3 Onde roda

Um `.rfa` nativo só pode ser escrito por um Revit (CLAUDE.md §3: o ODA BimRv escreve só a versão mais recente).
Por isso o produto não é app de navegador nem programa separado.

- **Protótipo:** esta máquina, `pyrevit run` com família portadora e variáveis de ambiente (CLAUDE.md §7 e §9).
- **Produto:** dentro do **PLAB Assistant**, no Revit do cliente, como a receita **"Família RFA"** da aba
  Receitas. A versão de saída é a do Revit em que o add-in roda (2022 a 2026).
- **Nuvem (depois, se houver demanda):** APS Design Automation, 2023 a 2026, com custo por execução.

### 3.4 IA: opcional, fora do núcleo [D]

- O núcleo (compilador, construtor, validador) **roda sem IA**.
- **A imagem é obrigatória [D].** Sem IA, ela serve de referência visual ao lado do formulário e vira a imagem
  do tipo na família (§3.5). Com IA, a mesma imagem alimenta o preenchimento automático do formulário.
- A IA nunca escreve FamilySpec. Ela só preenche campos do formulário, que é um vocabulário fechado (§4), e o
  compilador recusa o que não reconhece.
- As dúvidas viram perguntas no contrato das receitas (§4.3), resolvidas pelo usuário.

### 3.5 Interpretação a confirmar

"Sem IA mas tem que ter imagem" foi lido como: (a) toda geração começa com uma imagem; (b) a imagem fica ao lado
do formulário; (c) ela é gravada como Type Image da família. Ver §13, pergunta A1.

---

## 4. Schema da intenção (rascunho)

### 4.1 Exemplo

```json
{
  "versao_intencao": "0.1",
  "modo": "parametrico",
  "categoria": "Furniture",
  "nome": "PLAB_MOB_Mesa_Retangular",
  "perfil": "perfis/plab.json",
  "entradas": {
    "imagem": "entradas/mesa.jpg",
    "ficha": null,
    "preenchido_por": "regra"
  },
  "modelo": "mesa_4_pes",
  "parametros": [
    {"nome": "Largura",       "especie": "length", "instancia": true,  "padrao": 1200, "faixa": [600, 2400], "origem": "usuario"},
    {"nome": "Profundidade",  "especie": "length", "instancia": true,  "padrao": 800,  "faixa": [500, 1200], "origem": "usuario"},
    {"nome": "Altura",        "especie": "length", "instancia": true,  "padrao": 750,  "faixa": [600, 1100], "origem": "regra"},
    {"nome": "Espessura_Tampo","especie": "length","instancia": false, "padrao": 30,   "faixa": [15, 60],    "origem": "regra"},
    {"nome": "Lado_Pe",       "especie": "length", "instancia": false, "padrao": 50,   "faixa": [30, 100],   "origem": "regra"},
    {"nome": "Recuo_Pe",      "especie": "length", "instancia": false, "padrao": 40,   "faixa": [0, 150],    "origem": "regra"}
  ],
  "componentes": [
    {"id": "tampo", "padrao": "caixa",
     "args": {"largura": "Largura", "profundidade": "Profundidade", "altura": "Espessura_Tampo",
              "base": "Altura - Espessura_Tampo", "ancora": "centro"},
     "subcategoria": "Tampo", "material": "Madeira"},
    {"id": "pes", "padrao": "array_retangular",
     "args": {"item": {"padrao": "caixa",
                       "args": {"largura": "Lado_Pe", "profundidade": "Lado_Pe",
                                "altura": "Altura - Espessura_Tampo", "base": "0"}},
              "linhas": 2, "colunas": 2,
              "vao_x": "Largura - 2 * Recuo_Pe - Lado_Pe",
              "vao_y": "Profundidade - 2 * Recuo_Pe - Lado_Pe",
              "ancora": "centro"},
     "subcategoria": "Pes", "material": "Metal"}
  ],
  "tipos": [
    {"nome": "1200x800", "valores": {"Largura": 1200, "Profundidade": 800}},
    {"nome": "1600x900", "valores": {"Largura": 1600, "Profundidade": 900}}
  ],
  "perguntas": [],
  "lacunas_aceitas": []
}
```

### 4.2 Regras do schema

- **Vocabulário fechado.** `modelo`, `padrao`, `especie`, `ancora` e as chaves de `args` vêm de listas do
  compilador. Chave desconhecida = recusa com o nome da chave. Nada é ignorado em silêncio.
- **Expressões** usam só nomes de parâmetro, números, `+ - * /` e parênteses (o mesmo subconjunto que o FamFab
  documenta). O compilador faz o parse; uma expressão inválida vira pergunta, não erro no Revit.
- **Unidades:** milímetros, como a FamilySpec (CLAUDE.md §8).
- **`faixa`** é obrigatória em todo parâmetro dimensional no modo paramétrico. É dela que saem os tipos de
  teste (§6.6).
- **`origem`** (`usuario`, `regra`, `ia`, `ficha`) fica registrada para medir quanto a regra ou a IA acertou.
- No modo `estatico`, `faixa` é dispensada e os componentes podem usar números em vez de expressões.

### 4.3 Perguntas

Mesmo formato do contrato de etapa das receitas (`P-LAB/docs/SPEC-receitas-assistant.md` §4.1):

```json
{"id": "pes_recuo", "pergunta": "Os pés ficam alinhados à borda do tampo ou recuados?",
 "opcoes": ["alinhados", "recuados"], "padrao": "recuados",
 "por_que": "a imagem não mostra o encontro do pé com o tampo", "imagem": "entradas/mesa.jpg"}
```

O compilador **não roda com pergunta aberta**. "Aceitar padrão" grava o `padrao` e fica registrado como tal.

---

## 5. Padrões paramétricos v1

Um padrão é **código testado** que expande uma forma paramétrica em planos, cotas, alinhamentos, associações,
fórmulas e na assinatura esperada. A IA ou a regra só escolhem o padrão e preenchem os argumentos.

### 5.1 `caixa`

| | |
|---|---|
| Argumentos | `largura`, `profundidade`, `altura`, `base` (cota inferior), `ancora` (`centro`, `esquerda_frente`, `face:<plano>`), `vazio` (sim/não) |
| Emite | 4 planos verticais `RFADG_<id>_Esq/Dir/Frente/Tras`; cotas rotuladas entre eles; extrusão com perfil retangular no tipo corrente; alinhamento de cada face lateral ao seu plano; altura e base por associação a `EXTRUSION_END_PARAM`/`EXTRUSION_START_PARAM` com parâmetro de fórmula |
| Âncora `centro` sem EQ | um parâmetro de fórmula `<id>_meia_largura = Largura / 2` e duas cotas a partir do plano do centro, cada uma rotulada com ele. Evita a cota EQ, que o construtor não tem **[C]**. Funcionar igual à EQ é **[H]** (sonda S1) |
| Assinatura | bbox = (L, P, A); volume = L·P·A (menos os vazios combinados) |
| Situação | **[C]** é a fixture: Largura/Profundidade/Altura com planos, cotas, alinhamentos e altura por associação aprovada a 0,00% nos 4 tipos |

### 5.2 `cilindro`

| | |
|---|---|
| Argumentos | `diametro`, `altura`, `base`, `eixo` (`z` na v1), `ancora` (`centro`) |
| Candidato A | extrusão de círculo + cota de raio/diâmetro rotulada (`NewRadialDimension`/`NewDiameterDimension` em vista de planta) **[H]** |
| Candidato B | revolução de um retângulo (raio × altura) em torno do eixo, com o raio dirigido por planos e alinhamentos. A revolução já é coberta pelo construtor **[C]**; travar o perfil nos planos é **[H]** |
| Assinatura | bbox = (D, D, A); volume = π·D²/4·A |
| Risco | o volume medido pelo Revit bater com o analítico dentro de 0,01% é **[H]** (sonda S4) |

### 5.3 `array_retangular` e `array_linear`

| | |
|---|---|
| Argumentos | `item` (outro padrão), `linhas`, `colunas` ou `n`, `vao_x`/`vao_y` ou `distribuido_em` |
| Candidato A | `LinearArray` com a contagem rotulada (`BaseArray.Label`) **[H]** |
| Candidato B | N cópias fixas, cada uma com parâmetro de visibilidade ligado por fórmula a `n` (limite `n_max`). É o caminho do FamFab para elementos repetidos **[C]** (`SKILL.md`, "Repetitive Geometry") |
| Assinatura | soma das assinaturas dos itens visíveis |
| Uso na v1 | pés de mesa (2×2 fixo) e prateleiras (n variável) |

### 5.4 Modelos prontos (catálogo de mobiliário)

Um modelo é uma intenção pré-montada com perguntas próprias. É o caminho **sem IA** do formulário.

| Modelo | Padrões | Fase |
|---|---|---|
| `mesa_4_pes` | caixa + array 2×2 | G1 (pés como 4 caixas) → G2 (array) |
| `bancada` | caixa + caixa(s) de apoio | G1 |
| `estante` | caixas (laterais, base, topo) + array linear de prateleiras | G2 |
| `armario` | estante + portas (caixas) + vazio de rodapé | G2 |
| `cadeira_simples` | caixa (assento) + caixa (encosto) + array 2×2 | G2 |
| `mesa_redonda` | cilindro (tampo) + cilindro (coluna) + cilindro (base) | G2 |

Medidas padrão: a tabela do FamFab (`SKILL.md`, "Standard Dimensions Reference", em polegadas) serve de ponto
de partida, convertida para mm e revista contra a prática brasileira. Se o texto for copiado, mantém-se o aviso
de copyright MIT.

### 5.5 Conexões MEP (depois do mobiliário) [D]

Tê, joelho, luva, redução. Dependem de: conectores (Fase 4 do conversor), template Pipe Fitting, Part Type e
parâmetros de conector. As tabelas de medidas por DN vêm da ficha do fabricante (extração por regra, §3.2). Os
padrões novos (`revolucao_por_perfil`, `tubo_ao_longo_de_eixo`) serão especificados na G5.

---

## 6. Regras do compilador

1. **Puro e determinístico.** Mesma intenção → mesma FamilySpec, byte a byte. Sem relógio, sem aleatório, sem
   ordenar por nome o que tem ordem semântica.
2. **Saída compatível com o construtor atual.** Emite FamilySpec `versao_schema = "0.1.0"`; o construtor recusa
   outra versão **[C]** (`principal()`). Campos novos (subcategoria, material, array, cota radial) sobem o
   schema para `0.2.0` **no mesmo commit** em que o construtor e o leitor passam a tratá-los.
3. **Ordem dos planos = âncora.** O plano criado primeiro fica parado quando o parâmetro muda (CLAUDE.md §5).
   Cada padrão declara a sua âncora, e o compilador emite os planos nessa ordem.
4. **Ordem de construção** é a do `construtor.principal()` **[C]**: parâmetros → tipo corrente → planos → cotas
   → formas (cada forma alinhada e associada antes da próxima) → combinações de vazio → tipos → fórmulas. O
   compilador emite listas que respeitam essa linha do tempo; vazio só depois do sólido que corta.
5. **Geometria no tipo corrente.** Perfis e planos são emitidos com os valores do `tipo_corrente` **[C]** (é
   assim que o leitor grava).
6. **Assinatura esperada e tipos de teste.** O compilador grava `medicoes` por tipo no mesmo formato do leitor
   (`extensao_mm`, `volume_mm3`) **[C]**. Com isso o validador atual compara sem mudança. A flexão por faixa é
   feita por **tipos de teste**: um com todos os parâmetros no mínimo, um com todos no máximo, e um por
   parâmetro em cada extremo com os demais no padrão (2n+2 tipos). A família é construída **duas vezes**: com os
   tipos de teste (validação) e sem eles (entrega). Nenhum script novo apaga tipos.
7. **Viabilidade antes do Revit.** O compilador avalia as expressões nos extremos das faixas e recusa geometria
   impossível (largura negativa, pé maior que o tampo, prateleira fora da caixa). A recusa vira pergunta.
8. **Laço de desfazer.** Se o validador reprovar um tipo de teste, o compilador recompila com o parâmetro
   culpado **fixo** no padrão e registra a lacuna `PARAMETRO_FIXADO: <nome> — <veredito do validador>`. No
   máximo 2 voltas; depois disso a geração para e reporta.
9. **Nomes.** Planos `RFADG_<componente>_<lado>` (prefixo do `rfaspec`). Parâmetros, família e subcategorias
   pelo perfil do cliente (§7), nunca fixos no código.
10. **Modo estático.** O mesmo compilador sem cotas, sem alinhamentos e sem associações; os tipos viram
    geometrias fixas. O aceite é só a geometria (§8).
11. **Prévia.** O compilador emite também uma malha simples (caixas e cilindros facetados) para a prévia 3D,
    sem precisar do Revit.

---

## 7. Perfil do cliente

Diretrizes vêm de um JSON por cliente, como nas receitas. **Nunca do código.**

```json
{
  "cliente": "plab",
  "nomenclatura": {"familia": "{DISC}_{CAT}_{Nome}", "parametros": "Title_Case_Sem_Acento"},
  "compartilhados": {"arquivo": "perfis/plab_shared.txt", "mapear": {"Largura": "PLAB_Largura"}},
  "subcategorias": {"tampo": "Tampo", "pes": "Estrutura"},
  "materiais": {"padrao": "Por categoria", "por_componente": {"tampo": "Madeira - MDF"}},
  "lod": {"200": ["tampo", "pes"], "300": ["tampo", "pes", "travessas"]},
  "templates": {"Furniture": "Metric Furniture.rft"},
  "versao_alvo": "2024"
}
```

| Item | Situação |
|---|---|
| Compartilhados com GUID | **[C]** pronto no construtor |
| Subcategorias | novo (Fase 2 do conversor) |
| Materiais por nome | item 4 do roadmap do conversor |
| Templates por categoria | **[C]** hoje o construtor parte do Generic Model e troca a categoria (`ajustar_categoria`); um template por categoria é **[H]**/novo |

Protótipo: `perfis/<cliente>.json` no repo. Produto: tabela por empresa, como `perfil_documentos` nas receitas.

---

## 8. Critério de aceite

### 8.1 Modo paramétrico

Uma família gerada é **aprovada** quando:

1. todos os tipos reais saem `REPRODUZ` no validador contra a assinatura do compilador (0,1 mm no bbox, 0,01%
   no volume, as tolerâncias atuais **[C]**);
2. todos os tipos de teste (§6.6) saem `REPRODUZ`;
3. zero divergências de parâmetro (existência, instância/tipo, fórmula, valores);
4. toda lacuna está nomeada e foi aceita explicitamente (`lacunas_aceitas` ou `PARAMETRO_FIXADO`).

No primeiro uso de cada padrão vale também o critério da Fase 0 do conversor: abrir no Family Editor, trocar o
parâmetro à mão e ver a geometria flexionar.

### 8.2 Modo estático

Item 1 apenas.

### 8.3 Versões

Cada padrão é aprovado em **2022** e na versão mais nova disponível na máquina (2025 aqui; 2026 e 2027 na
Coordenador).

---

## 9. Avaliação pelo acervo ("testes de ouro")

### 9.1 Mecânica

1. O `leitor.py` lê uma família real e grava a FamilySpec e as `medicoes` da origem **[C]**.
2. Monta-se a entrada como o usuário faria: **imagem + medidas principais** (as que a ficha do fabricante
   daria). Só com foto a escala fica chutada; por isso as medidas entram.
3. O formulário é preenchido por regra ou por IA **[D]**; o compilador e o construtor geram a família.
4. O validador mede a família gerada e a compara com a origem, tipo a tipo.

### 9.2 Régua [D]

**≥ 96%**: desvio de no máximo **4%** em cada eixo do bbox e no volume de cada tipo comparável. Os nomes de
parâmetro da origem e da gerada não precisam bater; o caso de teste declara o mapa (`Largura` ↔ `Comprimento`).
Esta régua é dos testes de ouro; a régua de §8 (0,1 mm) continua valendo para a fidelidade do construtor.

### 9.3 Quais famílias

- Sem aninhadas (20 de 27 da amostra têm **[C]** RELATORIO).
- Conector MEP não reprova: vira lacuna aceita até a Fase 4 (26 de 27 têm).
- O acervo conhecido (Kamae: Fortlev, Bakof, Solaris, Sodramar…) é de **equipamento MEP**, não de mobiliário.
  Para a G4 é preciso um acervo de mobiliário (pergunta A2, §13).
- Imagem: catálogo do fabricante ou export de vista do Revit. Exportar imagem de vista em `pyrevit run` sem
  interface é **[H]**: vista nunca exibida pode devolver gráfico vazio (CLAUDE.md §7, armadilha 13).

### 9.4 O que se mede

Acerto (régua de 96%), tempo, número de perguntas, correções humanas e tokens (quando houver IA). As mesmas
métricas das receitas, para comparar regra × IA com dado.

### 9.5 Testes do compilador (sem Revit)

pytest com intenções de exemplo e a FamilySpec esperada salva (teste de regressão). Rodam a cada mudança, em
segundos.

---

## 10. Fases

Prefixo **G** para não colidir com as Fases 0–5 do conversor.

| Fase | Entrega | Critério de saída | Depende de |
|---|---|---|---|
| **G0 — sondas** | S1 caixa centrada sem EQ; S2 cilindro (A e B); S3 array (A e B); S4 volume analítico × medido; S5 `GroupTypeId` e template no Revit 2022; S6 subcategoria pela API; S7 Type Image pela API | tabela sim/não com evidência (log do `pyrevit run`), em cópia, sem tocar o pipeline | — |
| **G1 — compilador + caixa** | `gerador/` em CPython com pytest; padrão `caixa`; modelos `mesa_4_pes` (pés como caixas) e `bancada`; tipos de teste; laço de desfazer | §8.1 aprovado em 2022 e 2025 | G0 (S1, S4, S5) |
| **G2 — cilindro, array, subcategorias** | padrões `cilindro` e `array_*`; subcategorias; demais modelos de §5.4 | §8.1 em todos os modelos | G0 (S2, S3, S6); subcategoria = Fase 2 do conversor antecipada |
| **G3 — entradas** | formulário; imagem obrigatória (referência + Type Image); extrator de tabela de ficha PDF por regra; preenchimento por IA opcional | uma família gerada de cada entrada | G1; S7 |
| **G4 — testes de ouro** | conjunto de mobiliário + régua de 96% + métricas | relatório com acerto por modelo, regra × IA | G3; acervo de mobiliário (A2) |
| **G5 — conexões MEP** | tê, joelho, luva, redução; template Pipe Fitting; conectores | §8.1 + conectores conferidos | **Fase 4 do conversor (conectores)** |
| **G6 — produto** | porte C# do compilador; construtor e validador em C# (Fase 5 do conversor); receita "Família RFA" no PLAB Assistant; prévia `Viewport3D` | geração dentro do Revit do cliente, 2022–2026 | G2; Fase 5 do conversor |
| depois | modelos completos (famílias maiores, aninhadas) [D] | — | Fase 3 do conversor (aninhadas) |

### 10.1 Custo estimado (referência)

Estimativa feita na conversa de 15/10 (Opus 5.5, em tokens de desenvolvimento): intenção + compilador ~US$ 40;
porte de construtor e validador para C# ~70 (já previsto na Fase 5 do conversor); padrões paramétricos ~50;
etapa de IA + avaliação pelo acervo ~50; prévia + aba ~50. **Total ~US$ 260.** Uso: ~US$ 0,30–0,50 por família
no Sonnet 5.5 **quando a IA é usada**; no caminho por regra o custo de uso é zero.

Mudanças desde a estimativa: entrou a G0 (sondas); a etapa de IA virou opcional; entrou o extrator de ficha por
regra. **Reestimar no fim da G0**, com as sondas respondidas.

---

## 11. pyRevit × C#

A regra segue o padrão da suíte P-LAB: **o protótipo é a fonte da regra e o C# é o espelho.**

| Fica no protótipo (fonte) | Vai para C# (espelho), na G6 |
|---|---|
| compilador (CPython) e seus testes | compilador em biblioteca sem Revit, com os mesmos casos de teste |
| padrões e modelos prontos | os mesmos, portados com teste de equivalência (mesma intenção → mesma FamilySpec) |
| construtor e validador (IronPython) | add-in C# multi-target .NET 4.8 / .NET 8 (Fase 5 do conversor) |
| perfis em JSON no repo | perfis por empresa no banco |
| intenção escrita à mão ou pelo Claude Code | formulário WPF + prévia `Viewport3D` + IA pelo canal do Assistant |

Toda correção é feita primeiro no protótipo, validada, e só então portada. As divergências pendentes ficam num
ledger `gerador-pendente-sincronizar.md`.

---

## 12. Riscos

| # | Risco | Mitigação |
|---|---|---|
| 1 | Âncora invertida (ordem dos planos) | regra §6.3 + tipos de teste nos extremos, que pegam a âncora errada pelo volume |
| 2 | Volume analítico ≠ volume medido pelo Revit | sonda S4; se divergir, a assinatura usa tolerância por padrão |
| 3 | Cilindro ou array sem caminho paramétrico pela API | dois candidatos por padrão; se os dois falharem, o padrão sai só no modo estático, com lacuna nomeada |
| 4 | Revit 2022 diferente do 2023+ (templates, enums) | sonda S5; acesso defensivo por `getattr` (CLAUDE.md §7, 12b) |
| 5 | A geração atropelar o roadmap do conversor | tabela §2.2; a geração não mexe no `validador.py` durante o spike |
| 6 | Conflito de merge com `spike/rota-b` no `CLAUDE.md` | esta spec não edita o `CLAUDE.md`; um ponteiro entra depois do merge do spike |
| 7 | IA sair do vocabulário | compilador recusa com nome; IA só preenche formulário |
| 8 | Imagem e ficha do fabricante com direitos autorais | a imagem fica dentro da família do próprio usuário, como referência; não se redistribui catálogo |
| 9 | Dados do cliente enviados a provedor de IA | IA opcional e desligável; caminho por regra não envia nada |
| 10 | Testes de ouro sem acervo de mobiliário | pergunta A2 |
| 11 | Export de imagem sem interface não funcionar | imagem do catálogo como alternativa |

---

## 13. Decisões

### 13.1 Tomadas [D] — 16/10/2026

| # | Decisão |
|---|---|
| 1 | Produto: **plab-converter** (a geração é uma frente dele) |
| 2 | Fica **neste repo** |
| 3 | Ordem: **mobiliário**, depois **conexões MEP**, depois **modelos completos** |
| 4 | Formulário preenchido **por regra ou por IA**; o núcleo roda **sem IA** |
| 5 | **Imagem obrigatória** na entrada |
| 6 | Versões: famílias de **2022 a 2026** (vale também para o conversor) |
| 7 | Testes de ouro com régua de **~96%** |
| 8 | Branch a partir da **main** |
| 9 | Spec com cópia no espelho de docs do Drive |

### 13.2 Em aberto

| # | Pergunta |
|---|---|
| A1 | "Imagem obrigatória" é como em §3.5 (referência ao lado do formulário + Type Image)? |
| A2 | De onde vem o acervo de mobiliário para os testes de ouro (biblioteca de cliente, fabricante, BIMobject)? |
| A3 | Qual provedor e modelo de IA quando o preenchimento for por IA, e quem paga o token (chave do cliente ou proxy P-LAB)? |
| A4 | Preço da geração no plab-converter (créditos por família, como a conversão?) |
| A5 | Atualizar o `CLAUDE.md` para 2022–2026 (depois do merge do spike) |

---

## 14. Pendências herdadas da conversa da Rota B

Levantadas em 16/10 a partir da conversa original (análise do rvtconvert.com) e da branch `spike/rota-b`. São do
**conversor**, não da geração. **Ficam para a sessão da Rota B [D].**

| # | Pendência |
|---|---|
| 1 | Registrar o Portão 0 jurídico no `CLAUDE.md` §12 (a Rota B só vira produto com parecer sobre engenharia reversa); o prompt da Rota B pede e não foi feito |
| 2 | Resolver a contradição do `CLAUDE.md`: o §2 diz "não se faz engenharia reversa do binário" e o §6 descreve a Rota B fazendo isso |
| 3 | Escrever a seção "Rota B" do `RELATORIO.md` (etapa 6 do prompt) |
| 4 | Fechar as falhas de corpo pela lista do `dados.py --corpos` (`CategoryElem`, `LinePatternElem`, `RefPlane.m_paramSet`, `LinearDimString`…) |
| 5 | Olhar a região depois dos corpos (~20% da partição), `Global/Latest` e `ElemTable` |
| 6 | Escrever o primeiro salto 2024→2023 e o teste de ida e volta byte a byte |
| 7 | Anexar o pyRevit ao Revit 2026/2027 na Coordenador para o corpus por upgrade |
| 8 | Incluir os saltos até 2022 no plano da Rota B, já que a versão mínima passou a ser 2022 |

Registro: a primeira análise do rvtconvert (início daquela conversa) supôs reconstrução pela API; o teste
provou tradução do binário. Vale a conclusão do `docs/PROMPT-rota-binaria.md`, não a hipótese inicial.

---

## 15. Referências

- `CLAUDE.md` deste repo (§5 endereçamento e ordem, §7 armadilhas, §10 fases) e `RELATORIO.md` (§3 e §6)
- `pylib/rfaspec.py`, `scripts/construtor.py`, `scripts/validador.py`, `out/familyspec.json` (exemplo, fora do git)
- FamFab — github.com/kilkellym/ArchSmarterFamFab (licença MIT; lido via `gh api` em 16/10/2026, último push
  01/10/2026): `ArchSmarterFamFab/EmbeddedContent/SKILL.md`, `EmbeddedContent/family-schema.json`,
  `Data/FamilyGenerator.cs`
- Contrato de etapa e perguntas: `P-LAB/docs/SPEC-receitas-assistant.md` §4.1 (branch `receitas-21a-entrega`)
- Rota B: branch `spike/rota-b`, `docs/PROMPT-rota-binaria.md`

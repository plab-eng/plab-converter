# plab-converter — conversor de versão de famílias Revit

> Contexto completo do projeto. Leia isto antes de escrever qualquer código aqui.
> Escrito para que uma conversa nova comece sem repetir pesquisa nem repetir erro.

**Onde o projeto vive**

| | |
|---|---|
| Repositório | `plab-eng/plab-converter` (privado) — https://github.com/plab-eng/plab-converter |
| Working copy | `C:\Users\usuario\projetos\rfa-downgrader` |
| Espelho de docs | `G:\Meu Drive\P-LAB\02.Projetos\01.2026-PLAB-Plugins Revit\plab-converter` |

Projeto da P-LAB Engenharia, então o repositório fica **na organização
`plab-eng`**, nunca na conta pessoal. E o git nunca mora no Google Drive — o
sync corrompe o index; o Drive guarda só documentos e artefatos espelhados.

---

## 1. O problema

O Revit nunca teve "salvar como versão anterior". O formato só é compatível para
cima. Uma família criada no Revit 2026 é inutilizável num projeto 2025.

Todo workaround conhecido — IFC, SAT, DWG, STEP — devolve **geometria morta**:
perde parâmetros, fórmulas, tipos e, sobretudo, as **cotas rotuladas** que fazem
a família flexionar. É por isso que "downgrade de família" é considerado
impossível no mercado.

## 2. A tese

**O arquivo não é convertido. É regenerado.**

Não se faz engenharia reversa do formato binário `.rfa`. Lê-se a definição
paramétrica da família na versão de origem, guarda-se numa representação neutra,
e **reconstrói-se a família dentro de um Revit da versão de destino**. O `.rfa`
de saída é nativo porque foi o Revit 2025 que o escreveu.

Isso não é especulação — é como a Autodesk faz. O "Export RFA" do Autodesk
Informed Design é processado por Design Automation for Revit no APS, e o
Inventor 2025+ exporta `.rfa` para Revit 2023–2026 escolhendo a versão-alvo.

### Origem da investigação

Um post da **Atomatiq** (atomatiq.io — software house de AEC/BIM em Varsóvia,
fundada em 2020, liderada por Ilia Krachkovskii) anunciou downgrade de famílias
2026→2025 "no navegador, via kernel Web-CAD paramétrico".

A frase reveladora está no site deles: *"our cloud plugin extracts precise
mathematical data from Revit files **on Autodesk servers**"*. Servidores da
Autodesk = APS Design Automation. O "kernel Web-CAD" é a camada de exibição; o
trabalho pesado é o Revit da Autodesk nas duas pontas.

O marketing exagera ("extraímos a verdade matemática do B-Rep"). Uma família
Revit **não é B-Rep** — é histórico de features sobre planos de referência, com
parâmetros, fórmulas e restrições. Se você extrai B-Rep, você tem um sólido
morto, que é exatamente o que SAT já fazia.

## 3. Pesquisa consolidada

| Fonte | Conclusão |
|---|---|
| Autodesk | Sem "save as previous". Estrutural do formato. Confirmado 2026. |
| **ODA BimRv SDK** | Lê `.rfa` de 2011+, mas **escreve só na versão mais recente**. Downgrade não suportado — verificado na página do produto em ago/2026. |
| **Autodesk Informed Design** | Export RFA processado por Design Automation for Revit. Prova a arquitetura. |
| **Inventor 2025+** | Exporta `.rfa` para Revit 2023, 2024, 2025 e 2026. Inventor 2026 usa `.rte` para definir a versão de saída. |
| Inventor ← Revit | **Não serve para round-trip.** Inventor não abre `.rfa`; exige SAT/STEP/IFC e *"the parametric qualities will be lost"*. |
| **APS Design Automation** | Engines Revit 2023–2026. ~6 cloud credits/hora. **Regras mudam em 17/08/2026** (Cloud Credits → Flex tokens). |
| **FamFab** (kilkellym/ArchSmarterFamFab, MIT) | Schema JSON de família + `FamilyGenerator.cs` que constrói extrusões, sweeps, blends, planos de referência e subcategorias. **Declaradamente não religa cotas a parâmetros** — que é justamente a parte difícil. Reusar como base do construtor. |
| `aps-create-revit-family` | Molde do AppBundle DA4R; o `.rft` vai como input do workitem. |

### A peça central

**`Dimension.FamilyLabel` é gravável via API** (só em family document). É o que
religa uma cota a um parâmetro de família e faz a geometria flexionar. É o que
nenhuma rota SAT/IFC consegue e o que o FamFab não faz.

## 4. Stack

| Camada | Escolha |
|---|---|
| Protótipo | **pyRevit + IronPython 2.7**, orquestrado por PowerShell |
| Produção | **C#**, multi-target .NET Framework 4.8 (2023–2024) e .NET 8 (2025–2026) |
| Execução em produção | **APS Design Automation**, `IExternalDBApplication` + `DesignAutomationBridge` |
| Representação intermediária | **FamilySpec**, JSON neutro de versão |
| Modelo de negócio | SaaS — créditos avulsos + assinatura de estúdio + API |

Compatibilidade obrigatória: o mesmo código roda de **Revit 2023 a 2026**.

## 5. Arquitetura

```
.rfa origem (2026)
   -> [LEITOR]      addin no Revit de ORIGEM, percorre o family document
   -> FamilySpec    JSON neutro de versão
   -> [CONSTRUTOR]  addin no Revit de DESTINO, NewFamilyDocument + reconstrução
   -> [VALIDADOR]   flexiona e compara com a origem
   -> .rfa destino (2025) nativo + relatório de fidelidade
```

Em produção: dois workitems encadeados, um por engine
(`Autodesk.Revit+2026` → `Autodesk.Revit+2025`), FamilySpec trafegando via OSS.

### Endereçamento de referência — o risco nº 1

Objetos `Reference` do Revit **não atravessam documentos**. Para religar uma
cota do outro lado é preciso reencontrar as mesmas referências. O contrato:

- Planos de referência → endereçados pelo **nome canônico** (`RFADG_<rótulo>`)
- Faces de sólido → endereçadas por **(índice da forma, normal)**
- **Nunca** por `ElementId`

Se um endereço não for reencontrável, entra em `lacunas` no FamilySpec e é
reportado. Nunca falhar em silêncio.

### A ordem de criação é semântica, não cosmética

**O FamilySpec preserva a ordem de criação (ElementId crescente) de planos de
referência e de formas. Nunca reordenar por nome "para dar determinismo".**

Numa cota rotulada entre dois planos, quando o parâmetro muda o Revit mantém
parado o plano **criado primeiro** e move o outro. Ordenar os planos
alfabeticamente punha `RFADG_Dir` antes de `RFADG_Esq` no destino e invertia a
âncora: o sólido encolhia pela esquerda em vez de pela direita. A família
parecia perfeita — mesmos parâmetros, mesmas cotas, mesmos alinhamentos, mesmo
bounding box — mas um vazio parado deixava de intersectá-la nos tipos menores,
e só o **volume** denunciava (custou 4 hipóteses erradas antes de instrumentar).

Lição geral: quando duas famílias têm estrutura idêntica e comportamento
diferente, a diferença está em algo que o FamilySpec não captura. Instrumentar
antes de formular a quinta hipótese.

## 6. Estado atual

### ✅ FASE 0 APROVADA — 2026-08-05

**A tese está provada.** Ciclo completo rodou de ponta a ponta:

```
fixture (Revit 2025) -> leitor (2025) -> FamilySpec JSON ->
construtor (Revit 2023) -> validador (2023)
```

Veredito do validador (`out/relatorio_flex.json`): os **4 tipos FLEXIONAM**
no Revit 2023 com desvio 0,000 mm — Pequeno 400×300×700, Medio 600×400×900,
Grande 900×550×1200. Uma família criada no 2025 virou um `.rfa` nativo 2023
com parâmetros, tipos, cotas rotuladas e alinhamentos vivos.

O que sobrou fora da cobertura (11 itens no `relatorio_fidelidade.json`):
parâmetros builtin do template (strings/moeda/imagem — Manufacturer, Cost,
Keynote etc.) e um plano não-canônico do template. Tudo assunto da Fase 1,
sem impacto no flex.

### ✅ FASE 1 — geometria e parâmetros fechados

Fixture ampliada (vazio cortando, fórmula `Area_Base = Largura * Profundidade`,
parâmetro de instância, texto, sim/não, inteiro) atravessa a conversão
**2025 → 2023** com os 4 tipos em `REPRODUZ`, volume idêntico ao da origem:
558M / 189M / 189M / 63M mm³.

Placar da fase: divergências de parâmetro **37 → 0**, lacunas de fidelidade
**11 → 1** (um plano do template que não existe no idioma do destino).

O validador virou genérico: o leitor grava a assinatura geométrica da origem
(bbox + volume por tipo) e o validador compara o destino contra ela — não sabe
nada sobre a família, então serve para qualquer uma.

### ⚠️ Realidade do acervo — inventário de famílias reais (2026-08-06)

`scripts/inventario.py` levanta o que famílias reais usam, em uma só
inicialização do Revit. Rodado sobre o acervo de trabalho em
`G:\Meu Drive\Servidor - Kamae\...\Famílias` — 152 famílias em 6 bibliotecas
(Piscina, Gás, Fortlev, Bakof, Solaris, Sodramar): caixas d'água, cisternas,
biodigestores, coletores solares, reservatórios térmicos, registros de gás,
trocadores de calor, duchas, escadas.

Amostra estratificada de 27 famílias, 7 por biblioteca:

| Construto | Ocorrências | Situação |
|---|---|---|
| `Extrusion` | 194 | ✅ coberto |
| **`Sweep`** | **81** | não coberto |
| `Revolution` | 54 | ✅ coberto (2026-08-06) |
| **`SweptBlend`** | **21** | não coberto |
| `Blend` | 5 | não coberto |

- **4 de 27** famílias usam apenas extrusão
- **20 de 27** têm famílias aninhadas
- **26 de 27** têm conectores MEP
- **5 famílias têm ZERO geometria própria** — toda a geometria vive em
  aninhadas (Tanque Fortlev 310L, coletores Solaris, duchas Sodramar). Para
  essas, aninhadas não é refinamento: é o conteúdo inteiro.

Caminho curto identificado: os trocadores de calor Sodramar têm 26–30
extrusões e **0 aninhadas** — só falta `Revolution` para ficarem convertíveis
ponta a ponta. É o primeiro alvo real.

> Nota de método: um inventário anterior amostrou 25 famílias de uma única
> pasta de projeto (`4 - PISCINA`) e me levou a descrever o acervo como sendo
> de piscina. Era uma pasta de projeto, não a especialidade. Amostrar de uma
> pasta só e generalizar foi erro de método — daí a estratificação por
> biblioteca.

**A cobertura real do conversor sobre este acervo é zero hoje.** A Fase 1
"aprovada" vale para o conjunto de construtos da fixture, que nenhuma família
real da biblioteca reproduz. Isso não invalida a tese — a mecânica de
regeneração está provada — mas dimensiona honestamente o que falta.

Espécies de parâmetro que o acervo usa e o construtor não mapeava: `aec:number`
e `aec:material` (não `spec.number` / `reference:material` — prefixo diferente
do que se imagina), `string:url`, `piping:pipeSize`, `piping:flow`,
`piping:temperature`, `electrical:frequency|potential|power`. Já adicionadas.

### Primeira família REAL convertida — 2026-08-07

`New SD 25-40 - SODRAMAR.rfa` (2 MB, Mechanical Equipment, 29 formas,
0 aninhadas) atravessou leitor → construtor → validador em 2025 → 2023.

- Geometria: **281.019.688 → 283.045.768 mm³ (0,72% de diferença)**
- 28 de 29 formas lidas
- 12 divergências de parâmetro, 32 itens não reproduzidos

Não aprovou — e não deveria. O valor está em ter cada lacuna nomeada.

**Quatro coisas que só apareceram em família real** (nenhuma existiria numa
fixture escrita por quem já sabe o que espera):

1. `Sketch loops cannot be obtained` — o Revit se recusa a devolver o esboço
   de certas formas. **Uma forma ilegível derrubava a leitura da família
   inteira**; agora cada forma é isolada e vira lacuna com o motivo real.
2. **Categoria sem template disponível.** A família é Mechanical Equipment,
   mas esta máquina só tem Generic Model instalado para o 2023. Resolvido com
   `OwnerFamily.FamilyCategory` — que também é a resposta certa em produção,
   onde não se controla o que está instalado no destino.
3. **Tipo chamado `" "`** (um espaço). O Revit deixa existir mas recusa criar
   pela API: `The value cannot be empty. Parameter name: typeName`.
4. `The storage type of family parameter is not a double type` — atribuir
   valor a parâmetro sem checar o StorageType real.

### Parâmetros da família real fechados — 2026-08-07

Três rodadas sobre a New SD 25-40: divergências **12 → 6 → 1**, itens não
reproduzidos **32 → 15 → 8**. O que fechou:

- **Associações por nome**: builtin resolvido dinamicamente
  (`_parametro_do_elemento`), fallback `LookupParameter`. Eram 17 itens.
- **Compartilhados com GUID da origem**: arquivo temporário de shared
  parameters (único por processo), ativo durante TODO o lote — restaurá-lo
  antes do `AddParameter` deixava a ExternalDefinition órfã e o Revit
  respondia "Shared parameter creation failed." O GUID preservado é o que
  mantém tabelas e etiquetas funcionando. 7 de 8 entraram.
- **Despacho por StorageType real** no `Set`; ElementId (Material/Imagem)
  vira lacuna explícita — id não atravessa documentos.
- **Fórmula com locale**: família autorada em pt-BR traz `'47,2 kg'` e o
  destino recusa. Retry com vírgula→ponto, SÓ em fórmula sem `(` — em
  `if(a>1,2,3)` a troca corromperia para algo possivelmente válido e errado.
- Validador não compara mais valores de ElementId (13010 vs None não mede
  fidelidade) e normaliza fórmulas dos dois lados.

Sobras da família, todas justificadas: `numberOfPoles` (spec não existe na
API do 2023), materiais por id (fase de materiais), tipo `" "` (API recusa),
plano de template, e a revolução ilegível — que responde pelos 0,72% de
diferença de volume (provavelmente um vazio de furação).

### Sweep e Blend fechados — 2026-08-07

Fixture com as 5 formas (extrusão, vazio, revolução, sweep, blend) **APROVADA
a 0,00% nos 4 tipos**. Cisterna Fortlev: 41/42 formas, 30/31 sweeps
reproduzidos. Ver `RELATORIO.md` para o quadro completo.

Armadilhas novas: perfil de Sweep vai em 2D LOCAL para NewCurveLoopsProfile
(mundo produziria geometria em lugar nenhum); Blend é normalizado pelo Revit
para plano+offsets (TopOffset/BottomOffset — FirstEnd/SecondEnd NÃO existem
como propriedade; builtins reais BLEND_END_PARAM/BLEND_START_PARAM, achados
por sonda exaustiva depois de 5 candidatos errados); NewBlend com os dois
perfis no mesmo plano = "Unexpected internal error: code 1".

### Rota B (tradução do binário) — spike aberto em 2026-10-16

Branch `spike/rota-b`. Prompt completo em `docs/PROMPT-rota-binaria.md`; não
substitui a Rota A. Motivo: o rvtconvert.com (domínio de 12/10/2026) faz
downgrade 2024–2027 → 2023 traduzindo o binário, preservando 89.180 UniqueIds
num .rvt real, mas quebrando 6 conexões de tubo.

**Referência externa:** o **rvt-rs** (github.com/DrunkOnJava/rvt-rs,
Apache-2.0, v0.4.0 de 28/09/2026, se declara clean-room) já lê o
`Formats/Latest` de 2016–2026, registros de elemento 2024/2025 e tem escritor
que preserva bytes. Usamos a gramática dele como ponto de partida e
**conferimos tudo aqui** (CRC e consumo total do stream). Reaproveitar código
dele exige manter a atribuição Apache.

**Etapa 1 concluída** — `tools/rvtbin/ole_inspect.py` (Python 3, `olefile`):
- **paginação**: streams comprimidos são gravados em páginas de 65.249 bytes
  (64.896 de dado + 353 de checksum/ECC no fim de cada página cheia). Remover
  os 353 bytes ANTES de descomprimir; aí o CRC do gzip confere em todos os
  streams. ⚠️ Errata 16/10: a primeira versão desta nota dizia "CRC inválido
  de propósito" — era o lixo das páginas. Sem remover, o deflate segue
  "decodificando" bytes errados SEM dar erro depois da 1ª página;
- `Formats/Latest` = 1 membro gzip no byte 0; `Global/*` = 8 bytes de prefixo
  + 1 membro; `Partitions/N` = cabeçalho + vários membros gzip;
- **o dicionário é fixo por VERSÃO do Revit** (não por build nem por arquivo):
  2024.0 e 2024.3, 2025.0 e 2025.4, `.rfa` e `.rvt` dão o mesmo hash. O
  rvtconvert usa exatamente o dicionário 2023 padrão. ⚠️ Errata: a nota
  anterior ("fixo por build", "nomes ofuscados `bOVOO`") veio da descompressão
  errada.

**Etapa 2 (corpus) — parcial.** `tools/rvtbin/corpus_upgrade.py` (IronPython,
via pyRevit Routes) abre cada `.rfa` em 2º plano e salva cópia na versão do
Revit corrente. Corpus em `out/rotaB/corpus/<ano>/` (fora do git):
2023 = `fixture`, `newsd`, `real2` (saídas da Rota A, salvas por Revit 2023
real); **2024 gerado** (Revit 2024.3, sem erro); **2025 pendente** (Revit 2025
fechado). Dicionários de 2021/2022/2024/2025 vêm das bibliotecas em
`C:\ProgramData\Autodesk\RVT <ano>\Libraries` (conteúdo da Autodesk, sem cliente).

**Etapa 3 concluída** — `tools/rvtbin/schema.py` (parser, gramática no
docstring) e `tools/rvtbin/schema_diff.py` (diff por NOME de classe — os tags
são ordinais e mudam entre versões). Os 5 dicionários são consumidos por
inteiro (sobram só 8 bytes de zero no fim):

| Versão | Classes | Campos |
|---|---|---|
| 2021 | 4.168 | 11.512 |
| 2022 | 4.307 | 11.709 |
| 2023 | 4.418 | 11.866 |
| 2024 | 4.492 | 11.982 |
| 2025 | 4.600 | 12.296 |

| Salto | Classes só na versão nova | Classes alteradas | c/ campo novo | c/ campo sumido |
|---|---|---|---|---|
| 2025→2024 | 123 | 70 | 52 | 22 |
| 2024→2023 | 103 | 339 | 63 | 43 |
| 2023→2022 | 117 | 80 | 55 | 32 |
| 2022→2021 | 151 | 93 | 57 | 34 |

**2024→2023 é o salto pesado:** 242 classes só **reordenaram campos** (o 2024
pôs os campos ElementId na frente; o 2023 os tem em ordem alfabética). Se o
dado do elemento segue a ordem do dicionário, o tradutor reordena 242 classes
nesse salto — hipótese forte para as conexões que o rvtconvert quebrou.
Espécie de tipo `0x0a` (primitivo, provável i64) aparece em
`ClassDefinitionRef.m_ref`. Ponteiro (`0x0e` com nibble baixo 1–3) não leva ref.

Esta máquina (Coordenador) tem Revit 2021, 2022, 2024 e 2025, **sem o 2023**;
a validação final em 2023 exige a máquina que tem o 2023.

**Corpus completo (16/10):** `fixture`, `newsd`, `real2` em 2023, 2024 (Revit
2024.3) e 2025 (Revit 2025.4). A numeração da partição muda no upgrade
(`Partitions/0` no 2023 → `Partitions/1` no 2024/2025).

**Etapa 4 — primeira rodada (16/10).** `tools/rvtbin/dados.py` decodifica dados
guiado pelo dicionário (`--varrer` mede a cobertura de uma partição).
Confirmado em 2023, 2024 e 2025 da mesma família:
- **o dado segue a ordem dos campos do dicionário**, base antes dos campos
  próprios — o tradutor pode ser 100% guiado pelo schema;
- **ElementId: u32 no 2023, u64 no 2024+**, e isso está NO dicionário
  (`Identifier.m_id` u32 → `Identifier.m_id64` u64). `Global/ElemTable` também
  muda (registro de 28 → 40 bytes, ver rvt-rs `elem_table.rs`). Downgrade
  2024→2023 = estreitar todo id (abortar se algum não couber em 32 bits);
- **tags de classe aparecem no dado** (registro da partição, ponteiros,
  cabeçalho do `ElemTable` = tag da classe `ElemTable`) → renumerar por nome a
  cada salto. `ClassDefinitionRef.m_ref` também muda por versão (`0xaf` no
  2023/2024, `0xb8` no 2025);
- registro da cadeia da partição: `id (u32|u64) ; u32 tam ; u16 tag ; corpo ;
  u32 tam` (tam conta do tag ao fim do corpo; o trailer repete — verificação
  forte de que a decodificação está certa);
- container (`classe/0x50`): `u32 n` + n itens; ponteiro (`classe/0x01..03`):
  `u16 tag` da classe REAL (`ffff` = nulo) + corpo;
- a cadeia inicial da partição é só `ElementHeader` (um por elemento):
  **2045/2066 (2023) e 2056/2077 (2024) decodificam exatamente até o
  trailer**. As 21 falhas são as mesmas nas duas versões.

**Aberto:** a espécie `0x0a` (`ClassDefinitionRef.m_ref`) NÃO tem 8 bytes
fixos (`af 00 00 00 00 00 ff ff` num registro, `86 10 ff ff ff ff 3c 01` em
outro) — explica a maior parte das 21 falhas. Depois disso: os corpos dos
elementos (a parte da partição depois da cadeia de headers, ~75% dos bytes),
começando por um `ReferencePlane` da fixture.

### Próximo passo (ver RELATORIO.md §6)

1. **Esboço ilegível** ("Sketch loops cannot be obtained") — defeito nº 1
   medido: causa os 0,72% da New SD E os +94% da Cisterna (o vazio interno é
   a única forma ilegível dela).
2. **Famílias aninhadas** — 20/27; 5 famílias são SÓ aninhadas.
3. **Conectores MEP** — 26/27.
4. **Materiais por nome.**
5. SweptBlend em famílias reais (21 ocorrências).

## 7. Armadilhas já pagas — NÃO repetir

### pyRevit CLI

1. **`pyrevit run` sempre exige um arquivo de modelo.** A forma sem modelo do
   `--help` falha com `Model does not exist at ""`.
2. **A detecção de versão do CLI é frágil.** Falha com
   `Can not detect the Revit version of model` em:
   - arquivos `.rft`
   - famílias da biblioteca do Revit (`ProgramData\...\Libraries`)
   - **`.rfa` gerado por `Document.SaveAs` da API**

   A mensagem é enganosa: o arquivo está intacto, o parser do CLI é que não o
   reconhece. O `--debug` mostra que ele lê o `PartAtom` mas não acha o campo de
   build no `BasicFileInfo`.

   **Solução adotada:** passar sempre uma família **portadora** (um `.rfa`
   qualquer salvo normalmente pelo Revit, versão ≤ a mais antiga do ciclo) só
   para dar boot, e **cada script abre ou cria o documento de que precisa**.
   Isso desacopla do CLI e espelha produção, onde o plugin recebe o caminho do
   input.
3. **Scripts não recebem argv.** Comunicação por variável de ambiente, herdada
   pelo processo do Revit.
4. **`--purge` apaga o log.** Ao depurar, rodar sem `--purge` — o traceback do
   IronPython só aparece no log da execução.
4b. **`pyrevit run` devolve exit 0 MESMO quando o script quebra.** Checar
   `$LASTEXITCODE` não detecta falha nenhuma. Pior: o arquivo de saída da
   etapa anterior continua no disco, então a etapa seguinte consome dado
   VELHO e o relatório final sai verde com números de outra execução — já
   quase virou um "FASE APROVADA" falso. **Sempre apagar os arquivos de saída
   antes de cada etapa e conferir que foram recriados.** O único sinal
   confiável de erro é o traceback no bloco `==> Execution Log`.
5. **Módulo irmão não é importável.** O CLI copia só o script alvo para a pasta
   temporária. O bootstrap de `sys.path` tem que estar **inline** em cada
   script, lendo `RFADG_ROOT`.

### Revit API

6. **`FamilyManager.Set` exige um tipo corrente.** Documento novo a partir de
   template não tem nenhum tipo → `There is no current type`. Chamar
   `NewType()` antes de qualquer `Set()`.
7. **`NewAlignment` precisa de `Options.ComputeReferences = True`**, senão
   `Face.Reference` vem nulo e não há o que travar.
8. **Ordem importa:** rotular a cota **antes** de alinhar a geometria. Alinhar
   primeiro faz o Revit resolver a restrição contra valor fixo, e a família não
   flexiona.
9. **`NewDimension`/`NewAlignment` exigem vista de planta.** Em 3D falham em
   silêncio.
10. **Layout de templates muda entre versões.** Revit 2023 põe
    `Metric_Generic_Model-ENU.rft` na raiz; 2024/2025 usam subpastas por idioma
    com `English/Metric Generic Model.rft`. Busca sempre recursiva e por padrão
    de nome — nunca caminho fixo.
11. **`ElementId.IntegerValue` foi deprecado no Revit 2024+** em favor de
    `.Value`. Usar helper com fallback, porque o código roda de 2023 a 2026.
12. **O sufixo de versão do ForgeTypeId muda entre versões do Revit.**
    `autodesk.spec.aec:length-2.0.0` no 2023, `...-2.0.1` no 2025. Identidade
    de tipo de dado compara a ESPÉCIE (`rfaspec.especie_forge`, sem o sufixo),
    nunca a string inteira. A comparação inteira fez o construtor pular os
    parâmetros dimensionais e o leitor gravar comprimentos em pés — pego pelo
    relatório de fidelidade na primeira rodada.
12b. **NUNCA acessar membro de enum/classe da API por atributo direto** em
    código que roda em várias versões — o conjunto de membros varia, e um
    único acesso a membro ausente derruba o script inteiro (no import, se for
    nível de módulo; antes do try, se for argumento — o Python avalia
    argumentos antes de chamar a função). Já mordeu DUAS vezes:
    `BuiltInParameter.REVOLVE_START_ANGLE` (não existe em lugar nenhum) e
    `SpecTypeId.NumberOfPoles` (não existe no 2023). Resolver sempre por nome
    com `getattr(..., None)` — ver `_builtin()` no leitor e
    `_montar_tipos_de_dado()` no construtor. O que não resolver na versão
    corrente vira lacuna honesta, não crash.
13. **`get_Geometry` é cacheado por elemento: a PRIMEIRA chamada manda.**
    Chamadas seguintes com `Options` diferentes devolvem o cache da primeira
    até a próxima regeneração. E `Options.View` em sessão headless
    (`pyrevit run`) devolve enumeração VAZIA sem erro — a vista nunca foi
    exibida, os gráficos dela nunca foram gerados. Combinado: uma chamada com
    `Options.View` primeiro envenenou todas as variantes seguintes do mesmo
    elemento e pareceu bug não-determinístico. Nunca usar `Options.View` na
    medição; uma chamada por elemento, com a variante boa primeiro.
14. **O corte de vazio (`doc.CombineElements`) NÃO aparece na geometria da
    forma membra.** A Extrusion cortada continua devolvendo o sólido CHEIO
    (594e6 mm³ em vez de 558e6). A geometria líquida mora no elemento
    `GeomCombination` criado pelo CombineElements. Medição correta: sólidos
    dos GeomCombination + formas sólidas fora de combinação; formas membras
    são puladas (senão conta o volume sem corte por cima do cortado).

### IronPython 2.7 / encoding

15. **`json.dumps` da stdlib é INUTILIZÁVEL no engine do `pyrevit run` com
    texto acentuado.** Causa raiz (diagnóstico via 4 iterações falhas):
    em IronPython 2.7 `str` e `unicode` são o MESMO tipo (System.String);
    o encoder da stdlib faz `isinstance(s, str)` + `s.decode('utf-8')` sobre
    qualquer string com caractere ≥ U+0080 — um decode sobre string que já é
    unicode. E o registry de codecs do engine embarcado é incompleto, então o
    lookup degrada para o codec 'unknown' e estoura
    `UnicodeDecodeError: 'unknown' codec ... byte 0xea` (`ê` de "Referência").
    `ensure_ascii=True/False` não muda nada; sanitizar os dados antes não muda
    nada — o decode fatal é DENTRO do encoder. **Solução: emissor JSON próprio
    em `rfaspec.py` (`json_para_texto`), zero codecs, escapes `\uXXXX` na mão.**
    Nunca reintroduzir `json.dumps` neste código.
16. **Nenhum `.decode()`/`.encode()` em código que roda no `pyrevit run`.**
    Qualquer um pode estourar no registry incompleto. Conversão de bytes para
    unicode é feita por `unichr(ord(c))` (semântica latin-1, sem codec).
17. Regras gerais: `# -*- coding: utf-8 -*-`, strings acentuadas como `u"..."`,
    sem f-strings, sem type hints, `super(Classe, self)`.

## 8. Decisões e porquês

| Decisão | Porquê |
|---|---|
| Regenerar, não converter | Único caminho que preserva flex. Validado pelo que a Autodesk faz. |
| APS Design Automation em produção | Escala, engines 2023–2026, sem Revit instalado. É o que a Atomatiq usa. |
| Protótipo Python → produção C# | Itera rápido onde o risco é conceitual; DA exige C# de qualquer forma. |
| FamilySpec em mm | Legível e neutro. Revit trabalha em pés internamente; toda conversão passa por `rfaspec`. |
| ForgeTypeId como string (`autodesk.spec.aec:length-2.0.0`) | Estável entre versões. Muito melhor que enum legado. |
| Categoria por id da BuiltInCategory | Nome é localizado, id é estável. |
| Portadora + script abre o próprio doc | Desacopla da detecção de versão do CLI e espelha produção. |
| Orquestrador resolve o `.rft` | No DA o template é input do workitem, não algo que o plugin procura no disco. |
| `lacunas` explícitas no FamilySpec | Conversor que devolve família incompleta em silêncio destrói a confiança no produto. |
| Repositório em `C:\Users\usuario\projetos` | Git em `G:\Meu Drive` corrompe o index no sync do Google Drive. |

## 9. Como rodar

```powershell
# Pré-requisito: copiar uma família .rfa qualquer (salva pelo Revit, versão <=
# a mais antiga do ciclo) para out\portadora.rfa

.\scripts\run_fase0.ps1                      # ciclo completo 2025 -> 2023
.\scripts\run_fase0.ps1 -Etapa fixture       # só uma etapa
.\scripts\run_fase0.ps1 -RevitOrigem 2025 -RevitDestino 2024
```

Ambiente verificado nesta máquina: Revit **2023, 2024, 2025** instalados
(2026 não), templates presentes nos três, pyRevit CLI **5.3.1**.

O par local `2025 → 2023` tem a mesma forma do problema `2026 → 2025` e prova a
tese sem depender de instalar o 2026.

### Critério de sucesso da Fase 0

Abrir o `.rfa` gerado no Revit de destino, entrar no Family Editor, trocar o
valor de um parâmetro dimensional e **ver a geometria flexionar**. Se sair
sólido estático, o problema é endereçamento de referência (seção 5) e o plano
precisa ser revisto antes de investir mais.

## 10. Fases

- **Fase 0** — prova de conceito: uma cota religada que flexiona. ← *aqui*
- **Fase 1** — núcleo: sólidos, parâmetros, cotas, alinhamentos + validador
- **Fase 2** — subcategorias, materiais, visibilidade, linhas
- **Fase 3** — famílias aninhadas (`GetSubComponentIds()` só reporta as
  compartilhadas; não-compartilhadas exigem iteração customizada)
- **Fase 4** — conectores MEP
- **Fase 5** — porte C# + APS Design Automation + backend + frontend

## 11. Modelo de negócio (resumo)

O custo marginal é **real** (tempo de engine Revit), então plano ilimitado é
armadilha e free tier generoso sangra dinheiro.

A âncora de valor não é "quanto custa um plugin" — é **quanto custa refazer a
família à mão**: 2 a 8 h, R$ 160 a R$ 1.200 por família.

A dor é **episódica** (aparece quando um cliente está em versão antiga), o que
torna assinatura por assento um formato ruim e créditos um formato bom.

- Free: 3 famílias/mês
- Créditos: R$ 99 / 20 conversões
- Studio: R$ 249/mês por escritório, 100 conversões/mês
- API/Enterprise: a partir de R$ 1.500/mês

Estratégia: landing page própria (dor específica e altamente pesquisável) como
ímã de aquisição, upsell para o pacote P-LAB.

**Pendência:** confirmar tarifa do APS após **17/08/2026** antes de fechar tabela.

## 12. Riscos abertos

1. **Endereçamento de referência** — risco nº 1, ainda não validado ponta a ponta.
2. **Redistribuição dos `.rft` da Autodesk** — o sample oficial entrega o
   template como input do workitem, mas para produto comercial isso precisa de
   confirmação jurídica. Alternativa: o cliente fornece o template.
3. **Cobertura, não kernel** — o limite do produto é quantos recursos de família
   o leitor/construtor cobre. O que não for coberto precisa falhar em voz alta.
4. **Custo APS muda em 17/08/2026.**
5. **Restrições do DA4R** — sem UI, sem `ActiveDocument`/`ActiveView`, escrita
   restrita ao diretório de trabalho. O núcleo tem que nascer livre de UI.

# plab-converter — conversor de versão de famílias Revit

> Contexto completo do projeto. Leia isto antes de escrever qualquer código aqui.
> Escrito para que uma conversa nova comece sem repetir pesquisa nem repetir erro.

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

## 6. Estado atual (Fase 0)

### Funciona — verificado rodando

O `criar_fixture.py` gerou uma família paramétrica completa no Revit 2025.
Isso valida **toda a superfície de API que o construtor vai precisar**:

- `NewFamilyDocument` a partir de template resolvido
- `FamilyManager.AddParameter` / `NewType` / `Set`
- `NewReferencePlane` com nomes canônicos
- **`NewDimension` + `dim.FamilyLabel = parâmetro`** ← a peça central
- `NewExtrusion`
- **`NewAlignment`** travando faces do sólido nos planos de referência
- `AssociateElementParameterToFamilyParameter` (altura da extrusão)
- `SaveAs`

### Em andamento

`leitor.py` — extração roda inteira; ajustando serialização.

### Ainda não escrito

`construtor.py`, `validador.py`.

### Não validado ainda

**A família reconstruída flexiona no destino?** Esse é o critério de sucesso da
Fase 0 e ainda não foi testado. Nada aqui prova a tese até que um `.rfa` gerado
pelo construtor abra no Revit 2023 e mude de geometria ao trocar de tipo.

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

### IronPython 2.7 / encoding

12. **`json.dumps` da stdlib é INUTILIZÁVEL no engine do `pyrevit run` com
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
13. **Nenhum `.decode()`/`.encode()` em código que roda no `pyrevit run`.**
    Qualquer um pode estourar no registry incompleto. Conversão de bytes para
    unicode é feita por `unichr(ord(c))` (semântica latin-1, sem codec).
14. Regras gerais: `# -*- coding: utf-8 -*-`, strings acentuadas como `u"..."`,
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

# RELATÓRIO — plab-converter

**Conversor de versão de famílias Revit (.rfa) por regeneração**
Período coberto: 2026-08-05 a 2026-08-07 · Repo: `plab-eng/plab-converter`

---

## 1. Resumo executivo

A tese do produto está **provada e demonstrada em família real**: uma família
Revit é lida na versão de origem, serializada num formato neutro (FamilySpec)
e **regenerada** num Revit da versão de destino — preservando parâmetros,
tipos, fórmulas, cotas rotuladas, alinhamentos e cortes de vazio. O `.rfa` de
saída é nativo do destino porque foi o Revit do destino que o escreveu.

É a mesma arquitetura que a Autodesk usa no Informed Design (Design Automation
no APS) e que sustenta o anúncio da Atomatiq. Nenhuma engenharia reversa de
formato binário; nenhuma malha morta.

Validado localmente no par **2025 → 2023**, que tem a mesma forma do problema
comercial **2026 → 2025**.

## 2. O que está PRONTO (validado rodando)

### Pipeline completo
`leitor.py` → FamilySpec JSON → `construtor.py` → `validador.py`, orquestrado
por `pyrevit run` com guardas de saída (o CLI devolve exit 0 até quando o
script quebra — cada etapa apaga sua saída antes e falha alto se não
reaparecer).

### Fidelidade paramétrica — o coração do produto
| Capacidade | Status |
|---|---|
| Parâmetros de família (22 espécies de tipo de dado, incl. MEP) | ✅ |
| Parâmetros de instância | ✅ |
| **Parâmetros compartilhados com o GUID da origem** (tabelas/etiquetas continuam funcionando) | ✅ |
| Tipos com valores por parâmetro | ✅ |
| Fórmulas, incl. normalização de locale pt-BR (`47,2 kg` → `47.2 kg`) | ✅ |
| **Cotas rotuladas religadas** (`Dimension.FamilyLabel`) — o que faz a família flexionar | ✅ |
| Alinhamentos travados (plano como âncora) | ✅ |
| Associações de parâmetro de elemento (builtin por nome + LookupParameter) | ✅ |
| Categoria da família ajustada via API (independe do template instalado no destino) | ✅ |

### Geometria
| Forma | Status | Ocorrências no acervo (amostra 27 famílias) |
|---|---|---|
| Extrusion (sólida e vazio) | ✅ | 194 |
| Revolution | ✅ | 54 |
| Sweep | ✅ | 81 |
| Blend | ✅ (altura via TopOffset/BottomOffset) | 5 |
| SweptBlend | ⚠️ leitura defensiva escrita; caminho de 1 segmento | 21 |
| Cortes de vazio (`GeomCombination` reaplicado) | ✅ | — |

### Validador (genérico — vira o relatório de fidelidade do cliente)
- Assinatura geométrica da origem (bounding box + volume) medida TIPO A TIPO
  e comparada com o destino; detecta até vazio inerte (bbox igual, volume não)
- Parâmetros: existência, natureza instância/tipo, fórmula (normalizada),
  valores por tipo (pulando ElementId, que não atravessa documentos)
- Toda lacuna sai NOMEADA — nada falha em silêncio

### Resultados medidos (bateria final, 2026-08-07)

| Caso | Formas lidas | Geometria | Divergências de parâmetro |
|---|---|---|---|
| **Fixture** (extrusão+vazio+revolução+sweep+blend, 4 tipos paramétricos) | 5/5 | **APROVADA — 0,00% nos 4 tipos** | 0 |
| **New SD 25-40 Sodramar** (29 formas, Mechanical Equipment) | 28/29 | 0,72% | 1 (`numberOfPoles` não existe na API 2023) |
| **Cisterna Fortlev** (42 formas, 31 sweeps) | 41/42 | +93,9% — ver nota | 0 |

**Nota da Cisterna — diagnóstico preciso:** a única forma ilegível é
exatamente o sweep de VAZIO que escava o interior do tanque ("Sweep sem
caminho ou perfil legível"); sem ele a combinação de corte não é reaplicada e
o tanque sai maciço. Não é dispersão de erro: é UMA lacuna, nomeada, com
efeito grande. 30 dos 31 sweeps reproduziram. As 892 lacunas de leitura são
cotas de esboço não endereçáveis (ruído conhecido, sem efeito na geometria
estática).

**Nota da New SD:** os 0,72% são a mesma classe de problema — UMA revolução
com esboço que o Revit não devolve ("Sketch loops cannot be obtained"),
provavelmente o furo interno. **Esboço ilegível é hoje o defeito nº 1 do
conversor em famílias reais** — os dois casos convergem para ele.

### Infraestrutura
- `inventario.py`: levanta o que N famílias usam numa só inicialização do
  Revit — foi ele que reordenou o roteiro com dados do acervo real
- `sonda_blend.py`: modelo de sonda exaustiva para quando a API esconde dado
- CLAUDE.md com ~20 armadilhas documentadas (pyRevit CLI, Revit API,
  IronPython) — nenhuma precisa ser paga de novo

## 3. O que PRECISA AJUSTAR (com dado, não palpite)

Prioridade ditada pelo inventário de 27 famílias reais de 6 bibliotecas:

| # | Item | Impacto medido | Esforço estimado |
|---|---|---|---|
| 1 | **Famílias aninhadas** | 20/27 famílias têm; **5/27 são SÓ aninhadas** (Tanque Fortlev, coletores Solaris, duchas) — para essas a cobertura hoje é zero | Grande: recursão de FamilySpec, reconstruir de dentro para fora, carregar e posicionar; não-compartilhadas exigem iteração customizada |
| 2 | **Conectores MEP** | 26/27 famílias têm; o acervo é de equipamento hidráulico/térmico — não é opcional | Médio: `ConnectorElement` + parâmetros de sistema |
| 3 | **Materiais por NOME** | Hoje ElementId vira lacuna explícita; New SD perde `Material Do Corpo`/`Do Visor` | Médio: transportar Material por nome, criar se não existir |
| 4 | **Esboços ilegíveis** ("Sketch loops...") — **defeito nº 1 medido** | Os 0,72% da New SD E os +94% da Cisterna (o vazio interno do tanque é a única forma ilegível). 2 de 2 famílias reais batem nisso | Investigar por sonda: por que o Revit recusa; alternativa é reconstruir o perfil pela geometria do sólido |
| 5 | **Curvas além de Line/Arc** (splines, elipses) | Aparecem em famílias de fabricante | Pequeno-médio por tipo de curva |
| 6 | **SweptBlend em famílias reais** | 21 ocorrências; caminho multi-segmento vira lacuna | Validar com as caixas d'água Fortlev |
| 7 | Tipo com nome inválido para a API (`" "`) | 1 caso real | Decidir política (renomear? pular?) — hoje pula com registro |
| 8 | Espécies sem equivalente na API antiga (`numberOfPoles` no 2023) | 1 caso real | Documentar como limitação de downgrade |

### Para produção (Fase 5 — inalterada no plano)
- Porte do núcleo validado para C# multi-target (.NET 4.8 / .NET 8)
- APS Design Automation: AppBundle leitor + construtor, workitems encadeados
- **Confirmar tarifa APS pós-17/08/2026** antes de fechar preço
- Confirmar juridicamente a redistribuição de templates `.rft`

## 4. Riscos e lições que valem dinheiro

1. **A fixture mente; o acervo não.** A Fase 1 "aprovada" na fixture cobria 0%
   das famílias reais. Todo marco de cobertura daqui em diante se mede contra
   famílias do acervo.
2. **Falhar em voz alta é o produto.** O relatório de fidelidade pegou, na
   primeira rodada de cada caso: ForgeTypeId com sufixo trocado, vazio inerte,
   âncora invertida, offset errado. Um conversor que devolve família
   incompleta em silêncio destrói a confiança — o nosso nomeia cada lacuna.
3. **Ordem de criação é semântica no Revit** (âncora de cota = plano criado
   primeiro). Custou 4 hipóteses erradas até instrumentar. Instrumentar antes
   da quinta hipótese.
4. **API multi-versão exige acesso defensivo** a enums/propriedades — 3
   mordidas da mesma cobra (`REVOLVE_START_ANGLE`, `SpecTypeId.NumberOfPoles`,
   `Blend.FirstEnd`). Quando candidatos falham: sonda exaustiva, não sexto
   palpite.
5. **Locale importa no Brasil**: fórmulas autoradas em pt-BR (`47,2 kg`)
   quebram em sessão EN. Tratado; vai reaparecer em outros campos.

## 5. Números do período

- **3 dias** de desenvolvimento (2026-08-05 → 07), protótipo em
  pyRevit/IronPython orquestrado por PowerShell
- **Fase 0 aprovada** (tese provada), **Fase 1 aprovada** (fixture completa a
  0,00%), **2 famílias reais** atravessando o pipeline com relatório nomeado
- Cobertura de formas: extrusão, vazio, revolução, sweep, blend — as espécies
  que somam **334 de 355 formas** da amostra real (94%); falta swept blend
  (21) e o caso de esboço ilegível
- 22 espécies de tipo de dado; compartilhados com GUID preservado; locale
  pt-BR tratado
- ~20 armadilhas de plataforma documentadas no CLAUDE.md — o custo pago uma
  vez que não se paga de novo
- Divergências de parâmetro na família real: **12 → 1**; itens não
  reproduzidos: **32 → 8**, todos com justificativa

## 6. Recomendação de sequência

1. **Esboço ilegível** — ataca os DOIS casos reais medidos de uma vez; é o
   maior retorno por esforço agora
2. **Famílias aninhadas** — destrava as 5 famílias "só aninhadas" e melhora
   20 de 27
3. **Conectores MEP** — requisito do acervo (26/27)
4. **Materiais por nome** — fecha as últimas lacunas da New SD
5. Só então: porte C# + APS (Fase 5), com o núcleo já validado contra o acervo

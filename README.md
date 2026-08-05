# plab-converter

Conversor de versão de famílias Revit (`.rfa`) — P-LAB Engenharia.

`plab-eng/plab-converter` · privado

Retrocede uma família de uma versão do Revit para outra **preservando
parâmetros, fórmulas, tipos e as cotas que fazem a família flexionar**.

O arquivo não é convertido: é **regenerado**. A definição paramétrica é lida na
versão de origem, guardada numa representação neutra (FamilySpec, JSON), e a
família é reconstruída dentro de um Revit da versão de destino. O `.rfa` de
saída é nativo porque foi o Revit de destino que o escreveu.

É por isso que não sai malha morta — ao contrário de todo workaround via IFC,
SAT, DWG ou STEP, que perde a inteligência da família.

## Estado

**Fase 0 — prova de conceito.** Não use em produção.

Validado rodando: geração programática de família paramétrica completa no
Revit 2025, incluindo cota rotulada (`Dimension.FamilyLabel`) e alinhamento
travado de faces do sólido em planos de referência.

Ainda não validado: se a família reconstruída na versão de destino flexiona.
Esse é o critério de sucesso da Fase 0.

## Como rodar

```powershell
# Pré-requisito: copiar uma família .rfa qualquer (salva pelo Revit, versão <=
# a mais antiga do ciclo) para out\portadora.rfa
.\scripts\run_fase0.ps1
```

## Estrutura

```
pylib/rfaspec.py          núcleo compartilhado (unidades, IO, endereçamento)
scripts/criar_fixture.py  gera a família de teste paramétrica
scripts/leitor.py         .rfa -> FamilySpec JSON
scripts/construtor.py     FamilySpec JSON -> .rfa            (a escrever)
scripts/validador.py      matriz de flex origem x destino     (a escrever)
scripts/run_fase0.ps1     orquestrador
```

## Contexto

**Leia [CLAUDE.md](CLAUDE.md)** antes de escrever código aqui. Contém a tese
técnica, a pesquisa consolidada, as decisões e — principalmente — as armadilhas
do pyRevit CLI, da Revit API e do IronPython que já custaram tempo de
depuração e não devem ser repetidas.

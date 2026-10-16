# PROMPT — Rota B: downgrade por tradução do binário (spike de viabilidade)

> Cole este prompt no Claude Code aberto na working copy
> `C:\Users\usuario\projetos\rfa-downgrader` (repo `plab-eng/plab-converter`).
> Escrito em 16/10/2026 a partir da análise do rvtconvert.com.

---

Leia o CLAUDE.md inteiro antes de começar. Este prompt **não substitui a tese
atual** (regenerar pela API, seções 2 e 8). Ele abre uma **segunda rota em
paralelo**, como spike com critério de parada, para decidirmos com dado qual
rota (ou combinação) vira produto.

## Contexto novo: o rvtconvert.com

Serviço gratuito e anônimo que converte `.rvt/.rfa/.rte/.rft` de 2024–2027 para
**Revit 2023**. Domínio registrado em **12/10/2026** (RDAP), hospedagem em
myglobalhost.in, sem código público. O plab-converter começou em 05/08/2026.

Testamos com um modelo real em 16/10/2026: `LINK 8 - TIPO ESGOTO TORRE B E C R00`
(VG 25145, Revit 2025, 89 mil elementos, 98 MB). O que a análise provou:

**Ele não reconstrói pela API. Ele traduz o binário.** Evidência, lendo o OLE dos
dois arquivos:

- mesmo GUID de documento, mesmo caminho de origem no `BasicFileInfo`, mesma
  contagem de saves (331);
- mesmas partições (`Partitions/308` a `330`), mesmo `Global/History`, mesma
  `DocumentIncrementTable` (tamanho descomprimido idêntico);
- só o **conteúdo** das partições muda: 10 a 24% menor descomprimido (campos
  do 2025 descartados);
- `Formats/Latest` trocado e cabeçalho reescrito para `2023 20220503_1030(x64)`;
- **89.180 UniqueIds preservados**; famílias (183, 175 editáveis), vistas,
  tabelas, cotas, tags, textos, sistemas e comprimento de tubo (5.222,9 m)
  iguais. Zero DirectShape.

**Onde ele falhou** (aberto no Revit 2024, que faz o upgrade do 2023):

- erro "Elements need to be disconnected" **6 vezes**, sempre em tubo + conexão
  (`AF_Soldavel_Luva com Rosca`, `ESG_Serie Normal_Te_Juncao`). Com isso foram
  **+12 conectores abertos** e redes divididas (EP 68/181/185/245/2100). Três
  desses sistemas já tinham aviso de sentido de fluxo no original;
- 25 elementos internos `HVAC Load Schedules` sumiram;
- abertura em 138 s, contra 19 s do original no 2025.

Leitura: um tradutor de formato copia os campos, mas não entende a regra por
trás deles. Quando o Revit de destino regenera a família, um campo de geometria
ou de conector que caiu com valor padrão faz o conector "andar", e a conexão
quebra. **O motor do Revit não valida nada durante a conversão.**

## Por que isso interessa ao plab-converter

As duas rotas falham em lugares complementares:

| | Rota A (atual): regenerar pela API | Rota B: traduzir o binário |
|---|---|---|
| Cobertura | só o que leitor e construtor cobrem (hoje: esboço ilegível, aninhadas e conectores pendentes) | tudo que existe no formato, de graça |
| Fidelidade | nativa, validada pelo Revit de destino | campo a campo, sem validação semântica |
| Falha típica | lacuna nomeada (forma ou parâmetro ausente) | quebra sutil ao regenerar (o caso dos conectores) |
| Precisa de Revit | sim, nas duas pontas (APS DA) | não |
| Risco jurídico | baixo | **alto** (ver Portão 0) |

Os três defeitos nº 1 da Rota A (esboço ilegível, aninhadas, conectores MEP)
são exatamente o que a Rota B preserva sem esforço. Daí vale medir.

## Portão 0 — jurídico (antes de qualquer código de produto)

A EULA do Revit proíbe engenharia reversa. O rvtconvert é anônimo provavelmente
por isso. **Este spike é pesquisa interna, com arquivos da própria P-LAB, sem
distribuir nada.** Registre no CLAUDE.md (seção 12, riscos) que a Rota B só vira
produto depois de parecer jurídico sobre engenharia reversa para
interoperabilidade (lei brasileira de software e EULA). Não envie arquivo de
cliente para o rvtconvert nem para nenhum serviço externo durante o spike.

## Spike B0 — objetivo e critério de sucesso

**Objetivo:** provar ou refutar, em até 3 sessões, que conseguimos traduzir
`fixture_origem.rfa` de **2025 para 2023** no nível do binário e que o resultado
abre no Revit 2023 e **flexiona**.

**Sucesso:** a família abre no 2023 sem erro, os 4 tipos flexionam e o
`validador.py` da Rota A aprova a geometria (mesma régua das duas rotas).

**Parada (kill):** se ao fim da 3ª sessão não conseguirmos nem decodificar o
`Formats/Latest` em classes e campos, encerrar o spike, registrar o que foi
aprendido e voltar 100% para a Rota A.

## Arquitetura: cadeia de saltos de uma versão

O tradutor precisa servir para **qualquer origem (2024 a 2027, e versões futuras) e
qualquer destino**, não só 2025 → 2023. Desenho obrigatório desde o spike:

- **Ler é genérico.** Cada arquivo carrega o próprio dicionário (`Formats/Latest`):
  o decodificador lê o que vier, sem tabela por versão.
- **Mapear é por salto de UMA versão:** `2027→2026`, `2026→2025`, `2025→2024`,
  `2024→2023`. Cada salto é um módulo com o seu `diff_schema_<N>_<N-1>.json` e o seu
  `mapa_classes_<N>_<N-1>.json`. A conversão encadeia os saltos até o destino pedido:
  2027→2023 são 4 saltos; 2026→2025, que é o caso comercial, é 1 salto.
- **Versão nova = um salto novo.** Quando sair o 2028, escreve-se só o `2028→2027`; nada
  do que já existe é tocado.
- **Representação intermediária em memória**, sem recomprimir entre um salto e outro.
  Serializar só no fim.
- **Cada salto tem os próprios testes** com o corpus daquele par de versões.

O spike B0 implementa **só os saltos que esta máquina consegue gerar e validar**
(`2025→2024` e `2024→2023`, encadeados). Mas o código já nasce no formato de cadeia.

**Corpus para 2026 e 2027:** esta máquina não tem esses Revit. O caminho é o
**APS Design Automation**, que já está no plano de produção e tem engines 2026: um
workitem que só abre o `.rfa` 2023/2024/2025 e salva. O upgrade é uma operação
legítima do Revit e gera os trios sem instalar nada. Alternativa: instalar o 2026/2027
numa máquina de teste. Registrar o custo em créditos APS antes de rodar em lote.

### Versões antigas (2022 e anteriores): fase B1, depois do spike

A cadeia continua para trás (`2023→2022`, `2022→2021`, `2021→2020`, `2020→2019`).
**Diferencial comercial:** o rvtconvert para no 2023, e há cliente brasileiro em 2021/2022
(plugins MRV instalados no Revit 2021).

- **Corpus:** salvar a família na versão MAIS ANTIGA e subir uma versão por vez. A
  máquina do Coordenador tem Revit 2021 e 2022 (gera `2022→2021` e `2023→2022` com o 2023
  da máquina do projeto). 2019/2020 exigem instalação numa máquina de teste; APS DA não
  cobre essas versões (engines 2023–2026).
- **Perdas acumulam:** cada salto descarta o que a versão anterior não conhece. O
  relatório tem que listar as lacunas **por salto**, para o cliente ver o que perdeu ao
  descer até 2019.
- **Salto pesado esperado: `2022→2021`**, troca do sistema de unidades (ForgeTypeId).
  Fazer esse salto antes dos outros da fase B1 para medir o pior caso cedo.
- Só começa se o spike B0 passar.

## Etapas

1. **Ferramenta de inspeção OLE em Python 3 puro** (fora do Revit, `olefile` +
   `zlib`), em `tools/rvtbin/`:
   - listar streams com tamanho comprimido e descomprimido;
   - descomprimir as partições. Elas são sequências de membros gzip: procurar
     `1f 8b 08` e usar `zlib.decompressobj(31)`. Confirmado no .rvt; conferir no `.rfa`;
   - **`Formats/Latest` NÃO abriu com essa busca de gzip:** descobrir o
     cabeçalho/compressão dele primeiro, porque ele é o dicionário de classes
     e campos que torna o resto viável.
   - Teste: rodar no `fixture_origem.rfa` e num `.rfa` real.

2. **Corpus diferencial, com o Revit fazendo o trabalho sujo.** O upgrade é
   legal e automático: salvar a MESMA família 2023 no 2024 e no 2025 gera trios
   alinhados (mesmo conteúdo, três formatos). Script `pyrevit run` que, para
   cada `.rfa` 2023 do acervo, abre no 2024 e salva cópia, depois no 2025.
   Começar com a fixture e 5 famílias reais (incluindo uma com conector MEP e
   uma aninhada).

3. **Decodificar o dicionário.** Com os trios, comparar o `Formats/Latest` de
   versões **vizinhas**: classes e campos que entram, saem ou mudam de tipo. Produzir
   `schema_<ano>.json` por versão e `diff_schema_<N>_<N-1>.json` por salto (no spike:
   `2025_2024` e `2024_2023`). Nunca gerar diff que pule versão: o diff 2025→2023 é a
   composição dos dois saltos.

4. **Tradutor mínimo: reproduzir os 5 passos que inferimos do rvtconvert**, aplicando
   o passo 3 uma vez **por salto** da cadeia (abaixo descrito para um salto; no spike,
   rodar `2025→2024` e depois `2024→2023`).
   1. **Ler o dicionário de origem**: o `Formats/Latest` do próprio arquivo, seja qual for a versão.
   2. **Decodificar cada elemento** de cada partição com esse dicionário.
   3. **Mapear classe a classe e campo a campo** para o dicionário da versão **N-1** (`schema_<N-1>.json`, vindo dos trios do corpus):
      - campo que só existe em N → descartar, registrando quais (é o que deixa as partições 10–24% menores);
      - campo que N-1 exige e N não tem → preencher com o **valor do gêmeo N-1 no corpus**. Valor padrão inventado só se não houver gêmeo, e sempre registrado no relatório: é o suspeito nº 1 dos conectores que quebraram no rvtconvert;
      - classe que não existe em N-1 → decidir **caso a caso, numa tabela versionada por salto** (`mapa_classes_<N>_<N-1>.json`): remover, trocar pela equivalente mais próxima ou abortar. Classe fora da tabela aborta a conversão com nome. Nunca descartar em silêncio: o rvtconvert sumiu com 25 `HVAC Load Schedules` assim.
   4. **Regravar** (só depois do último salto) as partições recomprimidas e trocar o `Formats/Latest` pelo da versão de destino. Trocar a versão e o build no `BasicFileInfo` por um **build real da versão de destino**: copiar do `BasicFileInfo` de um arquivo salvo naquela versão (um por versão, guardado no corpus), não digitar à mão. O rvtconvert usa `2023 20220503_1030(x64)`.
   5. **Manter intacto** o resto: GUID do documento, `Global/History`, `Global/DocumentIncrementTable`, `Global/PartitionTable` e UniqueIds. Conferir byte a byte que esses streams não mudaram (com exceção do que o schema obrigar a mudar), porque é isso que faz links, tabelas e histórico continuarem funcionando.

5. **Validar com régua dupla:**
   - `validador.py` da Rota A (flex, geometria tipo a tipo, parâmetros);
   - `comparar_modelos_revit.py` (está no espelho de docs no Drive): contagem por
     categoria, UniqueIds, conectores abertos, avisos. **Conectores abertos e o
     erro "Elements need to be disconnected" são a régua que pegou o
     rvtconvert:** o tradutor da P-LAB precisa sair com zero nesse critério.

6. **Relatório** em `RELATORIO.md` (nova seção "Rota B"): o que decodificou, o
   que traduziu, onde quebrou, e a recomendação: A, B ou **híbrido**.
   Exemplo de híbrido: B para levar o arquivo, e o Revit de destino abre,
   regenera e o validador da A confere; ou A para geometria e B como fallback
   do esboço ilegível.

## Regras deste spike

- Toda saída de teste em `out/rotaB/`; **nunca** sobrescrever `.rfa` de origem.
- Toda lacuna NOMEADA, como na Rota A: classe ou campo que não sabemos traduzir
  aborta a conversão com mensagem. Nunca gerar arquivo "quase certo" em silêncio.
- Python 3 fora do Revit para o binário; IronPython/pyRevit só para gerar o
  corpus e validar. Respeitar as armadilhas de pyRevit CLI do CLAUDE.md §7.
- Commits pequenos, em branch `spike/rota-b`. Não mexer no pipeline da Rota A.
- Ao final de cada sessão: atualizar CLAUDE.md §6 com o estado e o próximo passo.

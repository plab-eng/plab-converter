# Plano — famílias aninhadas e travas de esboço

> **Executado em 19/10/2026** (as duas partes). Resultado e achados em `docs/FIDELIDADE-referencias.md`.

> Escrito em 18/10/2026, ao fim da rodada de fidelidade contra as referências Solaris e Ultrapex
> (`docs/FIDELIDADE-referencias.md`). Decisão do José: aninhadas por último e **não executar nesta rodada**
> (muito trabalho); fica pronto para quando o plano for reiniciado.

## Por que importa

| Referência | Aninhadas | O que se perde sem elas |
|---|---|---|
| Solaris (reservatório térmico) | 9 `BOCAIS` + 1 `BOCAL2` + 2 `LOGO SOLIS` | os 9 bocais (e os 9 conectores, que estão neles), o logo; 12 alinhamentos e 12 cotas presos a eles |
| Ultrapex (luva, joelho, tê, redução) | 2 ou 3 `Anel Deslizante - ULTRAPEX` por peça | as bocas da conexão (na luva, o corpo próprio é só um separador de 3,5 mm) |
| Acervo Kamae (inventário de ago/2026) | 20 de 27 famílias; 5 são SÓ aninhadas | a família inteira, nessas 5 |

## Desenho proposto (conversão; o gerador reaproveita)

1. **Leitor**
   - `ler_aninhadas`: cada `FamilyInstance` do documento da família → `{familia, tipo, compartilhada,
     ponto (mm), rotacao (vetores X/Y da transformação), espelhada, hospedeiro (plano/face/nível), valores de
     instância, associacoes (parâmetro do aninhado -> parâmetro da família hospedeira)}`.
   - Para cada família aninhada distinta: `doc.EditFamily(familia)` → `SaveAs` num `.rfa` temporário → o
     próprio leitor roda sobre ele (recursão) → FamilySpec aninhada dentro da principal (`aninhadas_spec`).
     `GetSubComponentIds()` só devolve as compartilhadas; as não compartilhadas vêm do coletor de
     `FamilyInstance` (armadilha já anotada no CLAUDE.md §10).
   - Cotas/alinhamentos com referência na aninhada: endereço `{tipo: "aninhada", instancia: i, referencia:
     plano nomeado da aninhada (Left/Right/Front/Back/Top/Bottom/Center) ou face}`.
2. **Construtor** (de dentro para fora)
   - Constrói cada FamilySpec aninhada (recursão) → `.rfa` no destino → `doc.LoadFamily` na família
     hospedeira.
   - Coloca as instâncias: `doc.FamilyCreate.NewFamilyInstance(ponto, simbolo, ...)` com a rotação; hospedeiro
     por plano de trabalho quando houver.
   - Associações: `AssociateElementParameterToFamilyParameter(instancia.LookupParameter(p), param_hospedeiro)`
     (é isso que faz o bocal acompanhar o diâmetro da Solaris e o anel acompanhar o RN da Ultrapex).
   - Cotas e alinhamentos com a aninhada depois que ela existir.
   - Conector dentro da aninhada: ele já vem com a família aninhada (não é recriado na hospedeira).
3. **Validador**: a medição passa a incluir a geometria das instâncias aninhadas (`GeometryInstance`); a
   assinatura da origem também.

## Riscos

- Profundidade (aninhada dentro de aninhada): limitar a 3 níveis e registrar acima disso.
- Famílias compartilhadas: no projeto, o tipo carregado precisa casar pelo nome; conflito de versão.
- Custo: cada aninhada distinta abre e fecha documentos (Solaris: 3 famílias distintas; Ultrapex: 1).

## Critério de aceite

Ida e volta 2024 → 2023 das 5 referências com: geometria (incluindo aninhadas) igual por tipo; conectores em
número e posição; flexão nos extremos de cada tabela de consulta (Solaris: os 7 tipos; Ultrapex: DN 16 a 32
pela tabela) — aceite medido, não declarado.

---

## Travas de esboço (sonda S11): FEITA em 18/10

Resolvida, ver `docs/FIDELIDADE-referencias.md` (trava pela ponta, casamento pela geometria, EQ). Abaixo, o
registro do que estava pendente.

**O que falta:** o perfil da revolução da Solaris (corpo) é preso aos planos por 24 alinhamentos e 14 cotas
**dentro do esboço**. Sem eles o comprimento flexiona, mas o diâmetro não (6 de 7 tipos com a geometria do
tipo corrente: até +87% de volume).

**Tentativa de 18/10 (revertida):** criar esses alinhamentos fora do modo de esboço deu
"The two references are not geometrically aligned" em todos (20 na Solaris, 12 no tê) e piorou o joelho;
o código voltou ao commit 0f4060c.

**Hipótese a sondar (S11):** a trava de linha de esboço só existe dentro da edição do esboço. Caminhos:
1. `SketchEditScope` — já provado que não existe em família (S8-V2);
2. criar a forma com o perfil já desenhado sobre os planos e, em vez de alinhamento, rotular cotas entre os
   planos que definem o perfil (o perfil segue o plano se o esboço tiver a trava automática de "sobre o plano"
   na criação — a verificar);
3. trocar a revolução por extrusões/revoluções cujo tamanho é dirigido por cota radial/diametral no esboço
   (provado na S2-A2 e que a Solaris já usa em 4 cotas de diâmetro).

Medir com a mesma ida e volta da Solaris: os 7 tipos com geometria igual.

# G4 — fotos sem cota, padrões estáticos e mobiliário urbano (17/10/2026)

Spec: `docs/SPEC-geracao-familias.md` §9 e §10 (G4). Imagens recebidas do José em 17/10: banco de praça com
estrutura metálica e ripas, cadeira de balanço (foto de perfil) e o orelhão gigante de Itu com um poste de
globo ao lado (vivadecora.com.br).

## O que esta rodada mede, e o que não mede

As fotos **não têm cota nem medida real conhecida**. A régua de 96% (§9.2) precisa da medida verdadeira, então
**não foi aplicada**. O que foi feito:

1. a IA (o Claude Code, como o Assistant fará) estimou as medidas por escala humana e proporção, e registrou cada
   estimativa com o porquê na própria intenção (`perguntas[].por_que`, `preenchido_por: ia`);
2. a família foi gerada e validada no Revit (geometria igual ao que a intenção pede);
3. as medidas foram conferidas contra faixas usuais de mobiliário (tabela abaixo). Faixas de referência, não
   norma: nenhuma norma foi conferida para esta rodada.

Se o José souber a medida real de alguma peça, a régua roda com `gerador/regua.py` sem gerar de novo.

## Padrões novos (modo estático)

| Padrão | O quê | Assinatura esperada |
|---|---|---|
| `perfil_extrudado` | polígono num plano vertical (`yz` ou `xz`), extrudado com uma espessura | bbox do polígono + extrusão; volume = área × espessura |
| `revolucao` | perfil (raio, posição no eixo) girado 360° em torno de um eixo vertical (`z`) ou horizontal (`y`) | volume pelo teorema de Pappus (2π ∫∫ r dA), exato para perfil poligonal |

Só aceitam números (o validador da intenção recusa expressão). Cobrem o que caixa e cilindro não fazem: peça
inclinada, curva de balanço, globo, cúpula. A prévia desenha os dois (prisma e malha de revolução).

## Modelo novo `banco_ripado` (paramétrico)

Estrutura de tubo quadrado (pés da frente, montantes de trás até o topo do encosto, travessas laterais e
frontal), 3 ripas no assento e 2 tábuas no encosto. A largura das tábuas é **calculada** a partir da altura total:
na primeira rodada era pergunta, e as minhas respostas deixaram as tábuas 60 mm acima dos montantes (880 em vez
de 820); a fórmula das ripas também somava 12 mm na profundidade. As duas falhas eram de modelagem e foram
corrigidas no modelo.

## Resultado (Revit 2024)

| Peça | Modo | Medidas estimadas pela IA (L × P × A, mm) | Revit 2024 | Faixa usual conferida |
|---|---|---|---|---|
| `PLAB_MOB_Banco_Praca_Ripado` | paramétrico (`banco_ripado`) | 1800 × 550 × 820; assento 450 | APROVADA, 17/17 tipos de teste | assento 400–480 ✓; 3 lugares ≈ 1800 ✓ |
| `PLAB_MOB_Cadeira_Balanco` | estático (10 perfis extrudados) | 660 × 1000 × 860; assento 480 na frente | APROVADA, volume exato | poltrona 600–700 de largura ✓; assento 400–480 ✓ |
| `PLAB_URB_Orelhao_Gigante_Itu` | estático (cilindro + revolução horizontal) | 2200 × 1200 × 5400 | APROVADA, volume a 0,002% | escala pela foto (pessoas ~1,7 m ao fundo) |
| `PLAB_URB_Poste_Globo` | estático (2 cilindros + revolução vertical) | 450 × 450 × 4050 | APROVADA, volume a 0,002% | poste de praça 3,5–4,5 m ✓ |

Validação: extensão e volume medidos no Revit iguais à assinatura do compilador, zero divergência, zero item
não reproduzido.

## Lacunas declaradas

- **Banco:** encosto vertical (o da foto é levemente inclinado; caixa não inclina); tubo maciço (o real é
  oco); sem as ponteiras.
- **Cadeira de balanço:** modo estático (não flexiona); estofado como bloco; sem as travessas traseiras do
  encosto; o balanço é uma poligonal de 11 pontos, não um arco.
- **Orelhão:** a cúpula real é oval (mais alta que larga); a revolução dá seção circular. Sem o aparelho
  telefônico.
- **Poste:** sem luminária interna, conexão do globo e fiação.
- Categoria do orelhão e do poste: Generic Models (mobiliário urbano não tem categoria própria no catálogo do
  gerador).

## Próximo: G5 (conexões)

Depende de conector MEP, que ainda não existe no repo (roadmap do conversor, item 3). Começa por sondas S9:
mudar a categoria para Pipe Fittings, definir o Part Type, criar conectores de tubo nas faces e ligar o
diâmetro do conector a um parâmetro. As medidas virão da extração da ficha da Tigre (`out/fichas/`).

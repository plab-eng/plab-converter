"""Leitura e validação da intenção (spec §4).

Vocabulário fechado: chave, padrão ou espécie desconhecidos são recusados com
o nome do problema. A recusa é uma lista de problemas, não a primeira exceção,
para o usuário (ou a IA) corrigir tudo de uma vez.
"""

import json

from . import expressao

ESPECIES = ("length", "integer", "yesno", "number")
MODOS = ("parametrico", "estatico")
PREENCHIDO_POR = ("usuario", "regra", "ia", "ficha")

# Categoria -> id da BuiltInCategory (estável entre versões e idiomas).
CATEGORIAS = {
    "Generic Models": -2000151,
    "Furniture": -2000080,
    "Casework": -2001000,
    "Specialty Equipment": -2001350,
    "Plumbing Fixtures": -2001160,
    "Mechanical Equipment": -2001140,
}

PADROES = {
    "caixa": {"obrigatorios": ("largura", "profundidade", "altura"),
              "opcionais": ("base", "centro_x", "centro_y")},
    "cilindro": {"obrigatorios": ("diametro", "altura"),
                 "opcionais": ("base",)},
    # Cópias de um padrão simples. Os argumentos do item podem usar o índice
    # da cópia: k (1..n) no linear; i (1..linhas) e j (1..colunas) no retangular.
    "array_linear": {"obrigatorios": ("item", "n"), "opcionais": ("n_max",)},
    "array_retangular": {"obrigatorios": ("item", "linhas", "colunas"), "opcionais": ()},
}
SIMPLES = ("caixa", "cilindro")
INDICES = {"array_linear": ("k",), "array_retangular": ("i", "j")}

_CHAVES_RAIZ = {"versao_intencao", "modo", "categoria", "nome", "perfil", "entradas",
                "parametros", "componentes", "tipos", "perguntas", "lacunas_aceitas"}
_CHAVES_PARAMETRO = {"nome", "especie", "instancia", "padrao", "faixa", "origem"}
_CHAVES_COMPONENTE = {"id", "padrao", "args", "subcategoria", "material"}
_CHAVES_ENTRADAS = {"imagem", "ficha", "preenchido_por"}


def _conferir_expressoes(args, nomes_param, indices, onde, problemas):
    for chave, texto in args.items():
        try:
            for usado in expressao.nomes(str(texto)):
                if usado not in nomes_param and usado not in indices:
                    problemas.append(f"{onde}.{chave}: parâmetro {usado!r} não declarado")
        except expressao.ExpressaoInvalida as erro:
            problemas.append(f"{onde}.{chave}: {erro}")


def _conferir_array(padrao, args, nomes_param, onde, problemas):
    item = args.get("item") or {}
    if item.get("padrao") not in SIMPLES:
        problemas.append(f"{onde}.item: padrao deve ser um de {SIMPLES}")
        return
    regra = PADROES[item["padrao"]]
    item_args = item.get("args") or {}
    _sobra(item, {"padrao", "args"}, f"{onde}.item", problemas)
    _sobra(item_args, set(regra["obrigatorios"]) | set(regra["opcionais"]), f"{onde}.item.args", problemas)
    for chave in regra["obrigatorios"]:
        if chave not in item_args:
            problemas.append(f"{onde}.item.args: {chave!r} obrigatório no padrão {item['padrao']}")
    _conferir_expressoes(item_args, nomes_param, INDICES[padrao], f"{onde}.item.args", problemas)
    if padrao == "array_retangular":
        for chave in ("linhas", "colunas"):
            if not isinstance(args.get(chave), int) or args[chave] < 1:
                problemas.append(f"{onde}.{chave}: inteiro >= 1")
        return
    n = str(args.get("n"))
    if expressao.eh_nome(n) and n in nomes_param:
        if not isinstance(args.get("n_max"), int) or args["n_max"] < 1:
            problemas.append(f"{onde}.n_max: inteiro >= 1 obrigatório quando n é parâmetro")
    elif not n.isdigit() or int(n) < 1:
        problemas.append(f"{onde}.n: nome de parâmetro inteiro ou número >= 1 (veio {n!r})")


class IntencaoRecusada(ValueError):
    def __init__(self, problemas):
        self.problemas = problemas
        super().__init__("intenção recusada:\n- " + "\n- ".join(problemas))


def carregar(caminho):
    with open(caminho, encoding="utf-8") as arquivo:
        return validar(json.load(arquivo))


def _sobra(chaves, permitidas, onde, problemas):
    for chave in sorted(set(chaves) - permitidas):
        problemas.append(f"{onde}: chave desconhecida {chave!r}")


def validar(dados):
    problemas = []
    _sobra(dados, _CHAVES_RAIZ, "raiz", problemas)

    if dados.get("versao_intencao") != "0.1":
        problemas.append(f"versao_intencao deve ser '0.1' (veio {dados.get('versao_intencao')!r})")
    modo = dados.get("modo", "parametrico")
    if modo not in MODOS:
        problemas.append(f"modo {modo!r} fora de {MODOS}")
    if dados.get("categoria") not in CATEGORIAS:
        problemas.append(f"categoria {dados.get('categoria')!r} fora de {sorted(CATEGORIAS)}")
    if not dados.get("nome"):
        problemas.append("nome da família ausente")

    entradas = dados.get("entradas") or {}
    _sobra(entradas, _CHAVES_ENTRADAS, "entradas", problemas)
    # Decisão do José (16/10): toda geração começa com uma imagem.
    if not entradas.get("imagem"):
        problemas.append("entradas.imagem é obrigatória")
    if entradas.get("preenchido_por", "usuario") not in PREENCHIDO_POR:
        problemas.append(f"entradas.preenchido_por fora de {PREENCHIDO_POR}")

    nomes_param = set()
    for indice, item in enumerate(dados.get("parametros") or []):
        onde = f"parametros[{indice}]"
        _sobra(item, _CHAVES_PARAMETRO, onde, problemas)
        nome = item.get("nome")
        try:
            expressao.validar_nome(nome)
        except expressao.ExpressaoInvalida as erro:
            problemas.append(f"{onde}: {erro}")
            continue
        if nome in nomes_param:
            problemas.append(f"{onde}: parâmetro {nome!r} repetido")
        nomes_param.add(nome)
        if item.get("especie") not in ESPECIES:
            problemas.append(f"{onde} ({nome}): especie fora de {ESPECIES}")
        if not isinstance(item.get("padrao"), (int, float)) or isinstance(item.get("padrao"), bool):
            problemas.append(f"{onde} ({nome}): padrao numérico obrigatório")
        faixa = item.get("faixa")
        if modo == "parametrico" and item.get("especie") in ("length", "integer"):
            if not (isinstance(faixa, list) and len(faixa) == 2 and faixa[0] <= faixa[1]):
                problemas.append(f"{onde} ({nome}): faixa [min, max] obrigatória no modo paramétrico")
            elif isinstance(item.get("padrao"), (int, float)) and not faixa[0] <= item["padrao"] <= faixa[1]:
                problemas.append(f"{onde} ({nome}): padrao {item['padrao']} fora da faixa {faixa}")

    ids = set()
    for indice, comp in enumerate(dados.get("componentes") or []):
        onde = f"componentes[{indice}]"
        _sobra(comp, _CHAVES_COMPONENTE, onde, problemas)
        ident = comp.get("id")
        if not expressao.eh_nome(ident or ""):
            problemas.append(f"{onde}: id inválido {ident!r}")
        elif ident in ids:
            problemas.append(f"{onde}: id {ident!r} repetido")
        ids.add(ident)
        padrao = comp.get("padrao")
        if padrao not in PADROES:
            problemas.append(f"{onde}: padrao {padrao!r} fora de {sorted(PADROES)}")
            continue
        args = comp.get("args") or {}
        regra = PADROES[padrao]
        _sobra(args, set(regra["obrigatorios"]) | set(regra["opcionais"]), f"{onde}.args", problemas)
        for chave in regra["obrigatorios"]:
            if chave not in args:
                problemas.append(f"{onde}.args: {chave!r} obrigatório no padrão {padrao}")
        if padrao in SIMPLES:
            _conferir_expressoes(args, nomes_param, (), f"{onde}.args", problemas)
        else:
            _conferir_array(padrao, args, nomes_param, f"{onde}.args", problemas)
    if not ids:
        problemas.append("nenhum componente")

    nomes_tipo = set()
    for indice, tipo in enumerate(dados.get("tipos") or []):
        nome = tipo.get("nome")
        if not nome or nome.startswith("_t_"):
            problemas.append(f"tipos[{indice}]: nome vazio ou reservado ('_t_' é dos tipos de teste)")
        if nome in nomes_tipo:
            problemas.append(f"tipos[{indice}]: nome {nome!r} repetido")
        nomes_tipo.add(nome)
        for chave in tipo.get("valores") or {}:
            if chave not in nomes_param:
                problemas.append(f"tipos[{indice}] ({nome}): parâmetro {chave!r} não declarado")

    # O compilador não roda com pergunta aberta (spec §4.3).
    for pergunta in dados.get("perguntas") or []:
        if "resposta" not in pergunta:
            problemas.append(f"pergunta {pergunta.get('id')!r} sem resposta")

    if problemas:
        raise IntencaoRecusada(problemas)
    dados.setdefault("modo", "parametrico")
    return dados

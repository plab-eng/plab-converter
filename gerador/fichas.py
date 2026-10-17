"""Extração de medidas de ficha técnica em PDF, por REGRA (spec §3.2, entrada 2).

Sem IA: cada formato de documento tem um leitor próprio, e todo valor extraído
guarda a evidência (página e linha). O que a regra não decide sozinha vira
pergunta, no contrato das receitas, em vez de chute.

Formatos cobertos (os três recebidos em 17/10/2026):

- `tabela_por_bitola`: ficha de conexões (Tigre, Esgoto Série Normal). Por
  produto: título, lista de códigos, cabeçalho `BITOLA A B C ...` e uma linha
  por DN. Uma tabela pode atravessar a página: o texto é lido em sequência.
- `lista_de_pecas`: manual de montagem com as peças e as medidas no nome
  (`LATERAL1790X380X17`).
- `especificacao_texto`: memorial de compra com `60x210x42cm (LxAxP)`,
  "três prateleiras", "espessura mínima de 18mm".
"""

import re

_NUMEROS_POR_EXTENSO = {"uma": 1, "um": 1, "duas": 2, "dois": 2, "três": 3, "tres": 3, "quatro": 4,
                        "cinco": 5, "seis": 6}
_RE_PAGINA = re.compile(r"^P\S*gina \d+ de \d+$")
_RE_CODIGO = re.compile(r"^(\d{4,6}) (.+?) (\d+) ([\d.]+,\d+|[\d.]+) (\d{13}) (\d{13}|-)$")
_RE_LINHA_DN = re.compile(r"^DN\d")
_RE_PECA = re.compile(r"([A-Z][A-Z ]*?[A-Z])\s*(\d{2,4})\s*X\s*(\d{2,4})\s*X\s*(\d{1,3})")
_RE_LXAXP = re.compile(r"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*cm\s*\(\s*L\s*x\s*A\s*x\s*P\s*\)",
                       re.IGNORECASE)


def _numero(texto):
    """'1.188,0' -> 1188.0; '97,5' -> 97.5; 'DN40' fica texto."""
    if re.fullmatch(r"[\d.]+,\d+|\d+", texto):
        return float(texto.replace(".", "").replace(",", "."))
    return texto


def ler_paginas(caminho):
    import pdfplumber
    with pdfplumber.open(caminho) as pdf:
        return [pagina.extract_text() or "" for pagina in pdf.pages]


def _linhas(paginas):
    for numero, texto in enumerate(paginas, start=1):
        for linha in texto.split("\n"):
            linha = linha.strip()
            if linha and not _RE_PAGINA.match(linha):
                yield numero, linha


# --------------------------------------------------------------------------
# tabela_por_bitola
# --------------------------------------------------------------------------

def tabela_por_bitola(paginas):
    produtos = []
    atual = None
    colunas = None
    anterior = None
    for pagina, linha in _linhas(paginas):
        if linha.startswith("Peso unit") and anterior is not None:
            # A linha antes de "Peso unit" é o título do produto.
            atual = {"nome": anterior[1], "pagina": anterior[0], "codigos": [], "tabelas": []}
            produtos.append(atual)
        elif atual is not None and _RE_CODIGO.match(linha):
            m = _RE_CODIGO.match(linha)
            atual["codigos"].append({"codigo": m.group(1), "descricao": m.group(2), "pagina": pagina})
        elif linha.startswith("BITOLA "):
            colunas = linha.split()[1:]
            if atual is not None:
                atual["tabelas"].append({"colunas": colunas, "linhas": [], "pagina": pagina})
        elif colunas and _RE_LINHA_DN.match(linha) and atual is not None and atual["tabelas"]:
            valores = linha.split()
            registro = {"bitola": valores[0], "pagina": pagina, "texto": linha}
            if len(valores) - 1 != len(colunas):
                registro["problema"] = f"{len(valores) - 1} valores para {len(colunas)} colunas"
            for coluna, valor in zip(colunas, valores[1:]):
                registro[coluna] = _numero(valor)
            atual["tabelas"][-1]["linhas"].append(registro)
        elif linha.startswith("* medidas"):
            colunas = None
        anterior = (pagina, linha)
    produtos = [p for p in produtos if p["tabelas"]]
    for produto in produtos:
        if not produto["codigos"]:
            produto["problema"] = "tabela sem lista de códigos (formato da página fora da regra)"
    return {"formato": "tabela_por_bitola", "produtos": produtos, "unidade": "mm"}


# --------------------------------------------------------------------------
# lista_de_pecas
# --------------------------------------------------------------------------

def lista_de_pecas(paginas):
    pecas = []
    for pagina, linha in _linhas(paginas):
        for m in _RE_PECA.finditer(linha):
            nome = m.group(1).strip()
            pecas.append({"peca": nome, "medidas": [float(m.group(2)), float(m.group(3)), float(m.group(4))],
                          "pagina": pagina, "texto": linha})
    return {"formato": "lista_de_pecas", "pecas": pecas, "unidade": "mm"}


# --------------------------------------------------------------------------
# especificacao_texto
# --------------------------------------------------------------------------

def especificacao_texto(paginas):
    achados = {"formato": "especificacao_texto", "unidade": "mm", "itens": {}}
    secao = None
    for pagina, linha in _linhas(paginas):
        titulo = re.match(r"^(\d+)\.\s+(.+)$", linha)
        if titulo:
            secao = titulo.group(2).strip().upper()
        m = _RE_LXAXP.search(linha)
        if m and "dimensoes" not in achados["itens"]:
            cm = [float(v.replace(",", ".")) for v in m.groups()]
            achados["itens"]["dimensoes"] = {"L": cm[0] * 10, "A": cm[1] * 10, "P": cm[2] * 10,
                                             "pagina": pagina, "texto": linha}
        m = re.search(r"espessura m\S+nima de (\d+(?:[.,]\d+)?)\s*mm", linha, re.IGNORECASE)
        if m and secao:
            achados["itens"].setdefault("espessuras", {})[secao] = {
                "mm": float(m.group(1).replace(",", ".")), "pagina": pagina, "texto": linha}
        m = re.search(r"\b(\w+)\s+prateleiras\b", linha, re.IGNORECASE)
        if m and m.group(1).lower() in _NUMEROS_POR_EXTENSO and "prateleiras" not in achados["itens"]:
            achados["itens"]["prateleiras"] = {"n": _NUMEROS_POR_EXTENSO[m.group(1).lower()],
                                               "pagina": pagina, "texto": linha}
        m = re.search(r"\b(\w+)\s+portas\s+inferiores\b", linha, re.IGNORECASE)
        if m and m.group(1).lower() in _NUMEROS_POR_EXTENSO:
            achados["itens"]["portas_inferiores"] = {"n": _NUMEROS_POR_EXTENSO[m.group(1).lower()],
                                                     "pagina": pagina, "texto": linha}
    return achados


# --------------------------------------------------------------------------

def detectar(paginas):
    texto = "\n".join(paginas)
    if re.search(r"^BITOLA [A-Z]( [A-Z])+$", texto, re.MULTILINE):
        return "tabela_por_bitola"
    if _RE_LXAXP.search(texto):
        return "especificacao_texto"
    if len(_RE_PECA.findall(texto)) >= 3:
        return "lista_de_pecas"
    return None


LEITORES = {"tabela_por_bitola": tabela_por_bitola, "lista_de_pecas": lista_de_pecas,
            "especificacao_texto": especificacao_texto}


def extrair(paginas, formato=None):
    formato = formato or detectar(paginas)
    if formato is None:
        return {"formato": None, "problema": "nenhuma regra reconhece este documento (caminho da IA, opcional)"}
    return LEITORES[formato](paginas)


# --------------------------------------------------------------------------
# Ficha -> respostas de um modelo
# --------------------------------------------------------------------------

def _pergunta(ident, texto, opcoes, padrao, por_que, evidencia=None):
    item = {"id": ident, "pergunta": texto, "opcoes": opcoes, "padrao": padrao, "por_que": por_que}
    if evidencia:
        item["evidencia"] = evidencia
    return item


def para_estante_portas_inferiores(extracao):
    """Respostas (decididas pela regra) e perguntas (o que ela não decide)."""
    respostas, perguntas, evidencias = {}, [], {}
    if extracao["formato"] == "especificacao_texto":
        itens = extracao["itens"]
        if "dimensoes" in itens:
            d = itens["dimensoes"]
            respostas.update({"largura": d["L"], "altura": d["A"], "profundidade": d["P"]})
            evidencias.update({k: f"p.{d['pagina']}: {d['texto']}" for k in ("largura", "altura", "profundidade")})
        if "prateleiras" in itens:
            respostas["prateleiras"] = itens["prateleiras"]["n"]
            evidencias["prateleiras"] = f"p.{itens['prateleiras']['pagina']}: {itens['prateleiras']['texto']}"
        lateral = next((v for k, v in itens.get("espessuras", {}).items() if "LATERA" in k), None)
        if lateral:
            respostas["espessura"] = lateral["mm"]
            evidencias["espessura"] = f"p.{lateral['pagina']}: {lateral['texto']}"
        # O memorial não dá a altura das portas: é pergunta.
        perguntas.append(_pergunta("altura_portas", "Altura do balcão com as portas (mm)?", None, 800,
                                   "o memorial diz 'portas inferiores' mas não dá a altura"))
    elif extracao["formato"] == "lista_de_pecas":
        pecas = extracao["pecas"]

        def maior(prefixo, eixo):
            candidatas = [p for p in pecas if p["peca"].startswith(prefixo)]
            return max(candidatas, key=lambda p: p["medidas"][eixo]) if candidatas else None

        lateral = maior("LATERAL", 0)
        frente = maior("RODAPE", 0) if maior("RODAPE", 0) and "LATERAL" not in maior("RODAPE", 0)["peca"] else None
        frente = next((p for p in pecas if p["peca"] in ("RODAPE", "MOLDURASUPERIOR", "MOLDURA SUPERIOR")), frente)
        rodape_lateral = next((p for p in pecas if p["peca"].startswith("RODAPELATERAL")), None)
        porta = maior("PORTA", 0)
        prateleira = maior("PRATELEIRA", 0)
        if frente:
            respostas["largura"] = frente["medidas"][0]
            evidencias["largura"] = f"p.{frente['pagina']}: {frente['texto']}"
        if rodape_lateral:
            respostas["profundidade"] = rodape_lateral["medidas"][0]
            evidencias["profundidade"] = f"p.{rodape_lateral['pagina']}: {rodape_lateral['texto']}"
        if lateral:
            respostas["espessura"] = lateral["medidas"][2]
            evidencias["espessura"] = f"p.{lateral['pagina']}: {lateral['texto']}"
            # A lateral dá a altura do corpo; se rodapé e moldura somam por fora, a lista não diz.
            perguntas.append(_pergunta(
                "altura", "Altura total (mm)?", [lateral["medidas"][0], lateral["medidas"][0] + 35],
                lateral["medidas"][0], "a lateral mede 1790; a moldura superior (35) pode somar por cima",
                f"p.{lateral['pagina']}: {lateral['texto']}"))
        if porta:
            perguntas.append(_pergunta(
                "altura_portas", "Altura do balcão com as portas (mm)?", None,
                porta["medidas"][0] + 70, "porta de 614 + rodapé de 70; folgas não estão na lista",
                f"p.{porta['pagina']}: {porta['texto']}"))
        perguntas.append(_pergunta("prateleiras", "Quantas prateleiras acima das portas?", [1, 2, 3, 4], 2,
                                   "a lista não traz quantidade por peça (o desenho mostra 2 acima do balcão)",
                                   f"p.{prateleira['pagina']}: {prateleira['texto']}" if prateleira else None))
    return {"respostas": respostas, "perguntas": perguntas, "evidencias": evidencias}


def para_luva_simples(extracao, produto="Luva Simples"):
    """Tabela da ficha (A comprimento, B diâmetro da bolsa, C e D profundidades
    das bolsas, E = DN) -> um tipo por DN. Legenda conferida no desenho da p.21
    da Tigre FTC000021."""
    alvo = next((p for p in extracao.get("produtos", []) if p["nome"] == produto), None)
    if alvo is None:
        return {"respostas": {}, "perguntas": [], "evidencias": {}, "tipos": [],
                "problema": f"produto {produto!r} não encontrado na ficha"}
    tipos, evidencias, problemas = [], {}, []
    for linha in alvo["tabelas"][0]["linhas"]:
        if "problema" in linha:
            problemas.append(f"{linha['bitola']}: {linha['problema']}")
            continue
        dn = float(linha["bitola"][2:])
        tipos.append({"nome": linha["bitola"], "valores": {
            "DN": dn, "Comprimento": linha["A"], "Diametro_Bolsa": linha["B"],
            "Bolsa_Inferior": linha["C"], "Bolsa_Superior": linha["D"]}})
        evidencias[linha["bitola"]] = f"p.{linha['pagina']}: {linha['texto']}"
    return {"respostas": {}, "perguntas": [], "evidencias": evidencias, "tipos": tipos, "problemas": problemas,
            "codigos": alvo["codigos"]}

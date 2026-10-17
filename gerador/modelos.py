"""Modelos prontos: o formulário sem IA (spec §5.4 e §3.4).

Um modelo é uma intenção pré-montada mais as perguntas que a preenchem. As
perguntas usam o contrato de etapa das receitas (id, pergunta, opcoes, padrao,
por_que, imagem): quem responde é o usuário, uma regra ou, opcionalmente, a IA.
Pergunta sem resposta assume o padrão, e isso fica registrado.
"""

import copy
import glob
import json
import os

from . import intencao as intencao_mod

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos")


class RespostaInvalida(ValueError):
    pass


def listar():
    saida = []
    for caminho in sorted(glob.glob(os.path.join(PASTA, "*.json"))):
        with open(caminho, encoding="utf-8") as arquivo:
            modelo = json.load(arquivo)
        saida.append({"modelo": modelo["modelo"], "descricao": modelo["descricao"]})
    return saida


def carregar(nome):
    caminho = os.path.join(PASTA, f"{nome}.json")
    if not os.path.isfile(caminho):
        raise RespostaInvalida(f"modelo {nome!r} não existe; disponíveis: {[m['modelo'] for m in listar()]}")
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def perguntas(nome, imagem=None):
    """As perguntas no formato do contrato das receitas, prontas para responder."""
    saida = []
    for p in carregar(nome)["perguntas"]:
        item = {"id": p["id"], "pergunta": p["pergunta"], "padrao": p["padrao"], "por_que": p["por_que"]}
        if "opcoes" in p:
            item["opcoes"] = p["opcoes"]
        if imagem:
            item["imagem"] = imagem
        saida.append(item)
    return saida


def montar(nome, nome_familia, imagem, respostas=None, preenchido_por="usuario"):
    """Intenção validada a partir do modelo e das respostas ({id: valor})."""
    modelo = carregar(nome)
    respostas = dict(respostas or {})
    desconhecidas = sorted(set(respostas) - {p["id"] for p in modelo["perguntas"]})
    if desconhecidas:
        raise RespostaInvalida(f"respostas para perguntas que o modelo não tem: {desconhecidas}")

    dados = copy.deepcopy(modelo["intencao"])
    parametros = {p["nome"]: p for p in dados["parametros"]}
    registro = []
    problemas = []
    for p in modelo["perguntas"]:
        respondida = p["id"] in respostas
        valor = respostas.get(p["id"], p["padrao"])
        if not isinstance(valor, (int, float)) or isinstance(valor, bool):
            problemas.append(f"{p['id']}: resposta numérica esperada (veio {valor!r})")
            continue
        if "opcoes" in p and valor not in p["opcoes"]:
            problemas.append(f"{p['id']}: {valor} fora das opções {p['opcoes']}")
            continue
        minimo, maximo = p["faixa"]
        if not minimo <= valor <= maximo:
            problemas.append(f"{p['id']}: {valor} fora da faixa do modelo [{minimo}, {maximo}]")
            continue
        parametros[p["alvo"]]["padrao"] = valor
        parametros[p["alvo"]]["origem"] = preenchido_por if respondida else "regra"
        registro.append({"id": p["id"], "pergunta": p["pergunta"], "opcoes": p.get("opcoes"),
                         "padrao": p["padrao"], "por_que": p["por_que"], "resposta": valor,
                         "aceitou_padrao": not respondida})
    if problemas:
        raise RespostaInvalida("respostas recusadas:\n- " + "\n- ".join(problemas))

    dados.update({
        "versao_intencao": "0.1",
        "nome": nome_familia,
        "entradas": {"imagem": imagem, "ficha": None, "preenchido_por": preenchido_por},
        "tipos": [{"nome": "Padrao", "valores": {}}],
        "perguntas": registro,
        "lacunas_aceitas": [],
    })
    return intencao_mod.validar(dados)

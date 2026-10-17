"""Régua dos testes de ouro (spec §9.2): a família gerada bate com o objeto real?

Compara a extensão MEDIDA no Revit (relatório do validador da geração) com as
medidas conhecidas do objeto, eixo a eixo. Aprova quando todos os eixos têm
acerto >= 96% (desvio <= 4%), a régua decidida em 16/10/2026.

Quando a fonte só traz as medidas externas (foto com cotas), o volume real não
é conhecido e a régua fica no bbox; isso é dito no resultado.
"""

import json

REGUA = 0.96
EIXOS = ("largura", "profundidade", "altura")


def comparar(caminho_validacao, verdade_mm, tipo=None):
    with open(caminho_validacao, encoding="utf-8") as arquivo:
        validacao = json.load(arquivo)
    tipos = {t["tipo"]: t for t in validacao["tipos"]}
    escolhido = tipos[tipo] if tipo else next(iter(tipos.values()))
    medido = escolhido["medido"]["extensao_mm"]
    eixos = {}
    for indice, eixo in enumerate(EIXOS):
        if eixo not in verdade_mm:
            continue
        real = float(verdade_mm[eixo])
        acerto = 1.0 - abs(medido[indice] - real) / real
        eixos[eixo] = {"real_mm": real, "gerado_mm": round(medido[indice], 1), "acerto": round(acerto, 4),
                       "passa": acerto >= REGUA}
    return {"tipo": escolhido["tipo"], "eixos": eixos, "regua": REGUA,
            "aprovado": bool(eixos) and all(e["passa"] for e in eixos.values()),
            "base": "bbox medido no Revit (volume real desconhecido)"}

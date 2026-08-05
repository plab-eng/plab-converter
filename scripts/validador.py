# -*- coding: utf-8 -*-
u"""FASE 0 — validador: a família reconstruída flexiona?

Roda no Revit de DESTINO. Abre o .rfa reconstruído (RFADG_ENTRADA), percorre os
tipos e, para cada um, mede o bounding box do sólido. Se a geometria acompanha
os valores de Largura/Profundidade/Altura de cada tipo, o flex está vivo — que
é o critério de sucesso da Fase 0.

Compara com os valores esperados do FamilySpec (RFADG_SPEC) e grava o veredito
em RFADG_RELATORIO_FLEX.

    pyrevit run scripts/validador.py <portadora.rfa> --revit=2023
"""

import os
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida. Rode via scripts/run_fase0.ps1.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

from Autodesk.Revit.DB import (  # noqa: E402
    FilteredElementCollector, Extrusion, Options, Solid,
)

para_mm = rfaspec.interno_para_mm
log = rfaspec.log

# Tolerância da comparação, em mm. Regeneração envolve aritmética de ponto
# flutuante em pés; 0,1 mm é folgado o bastante para ruído numérico e apertado
# o bastante para pegar qualquer falha real de constraint.
TOLERANCIA_MM = 0.1


def _abrir_familia(caminho):
    if not os.path.isfile(caminho):
        raise IOError(u"Família não encontrada: {0}".format(caminho))
    return __revit__.Application.OpenDocumentFile(caminho)  # noqa: F821


def _bounding_box_solido(doc):
    u"""Extensões (dx, dy, dz) em mm do sólido da primeira extrusão."""
    opcoes = Options()
    opcoes.IncludeNonVisibleObjects = False

    for extrusao in FilteredElementCollector(doc).OfClass(Extrusion).ToElements():
        for objeto in extrusao.get_Geometry(opcoes):
            if isinstance(objeto, Solid) and objeto.Volume > 0:
                caixa = objeto.GetBoundingBox()
                return (
                    para_mm(caixa.Max.X - caixa.Min.X),
                    para_mm(caixa.Max.Y - caixa.Min.Y),
                    para_mm(caixa.Max.Z - caixa.Min.Z),
                )
    return None


def principal():
    entrada = rfaspec.env("RFADG_ENTRADA", obrigatorio=True)
    caminho_spec = rfaspec.env("RFADG_SPEC", obrigatorio=True)
    caminho_relatorio = rfaspec.env("RFADG_RELATORIO_FLEX", obrigatorio=True)

    especificacao = rfaspec.ler_json(caminho_spec)

    esperados = {}
    for tipo in especificacao[u"tipos"]:
        valores = tipo[u"valores"]
        if valores.get(u"Largura") is not None:
            esperados[tipo[u"nome"]] = (
                valores[u"Largura"], valores[u"Profundidade"], valores[u"Altura"]
            )

    doc = _abrir_familia(entrada)
    resultados = []
    try:
        from Autodesk.Revit.DB import Transaction
        gerenciador = doc.FamilyManager

        tipos_no_doc = {}
        for tipo in gerenciador.Types:
            if tipo.Name:
                tipos_no_doc[tipo.Name] = tipo

        for nome, (largura, profundidade, altura) in sorted(esperados.items()):
            tipo = tipos_no_doc.get(nome)
            if tipo is None:
                resultados.append({
                    u"tipo": nome, u"veredito": u"AUSENTE",
                    u"detalhe": u"tipo não existe na família reconstruída",
                })
                continue

            # Trocar o tipo corrente exige transação: é isso que regenera a
            # geometria com os valores do tipo — o flex acontecendo de fato.
            transacao = Transaction(doc, u"RFADG — flexionar para " + nome)
            transacao.Start()
            gerenciador.CurrentType = tipo
            doc.Regenerate()
            transacao.Commit()

            medido = _bounding_box_solido(doc)
            if medido is None:
                resultados.append({
                    u"tipo": nome, u"veredito": u"SEM_SOLIDO",
                    u"detalhe": u"nenhum sólido com volume encontrado",
                })
                continue

            desvios = (
                abs(medido[0] - largura),
                abs(medido[1] - profundidade),
                abs(medido[2] - altura),
            )
            flexionou = all(d <= TOLERANCIA_MM for d in desvios)

            resultados.append({
                u"tipo": nome,
                u"veredito": u"FLEXIONA" if flexionou else u"ESTATICO",
                u"esperado_mm": [largura, profundidade, altura],
                u"medido_mm": [medido[0], medido[1], medido[2]],
                u"desvio_mm": [desvios[0], desvios[1], desvios[2]],
            })
    finally:
        doc.Close(False)

    todos_flexionam = bool(resultados) and all(
        item[u"veredito"] == u"FLEXIONA" for item in resultados
    )

    rfaspec.gravar_json(caminho_relatorio, {
        u"fase0_aprovada": todos_flexionam,
        u"tolerancia_mm": TOLERANCIA_MM,
        u"resultados": resultados,
    })

    for item in resultados:
        log(u"{0}: {1}".format(item[u"tipo"], item[u"veredito"]))
    log(u"FASE 0: {0}".format(u"APROVADA" if todos_flexionam else u"REPROVADA"))


principal()

# -*- coding: utf-8 -*-
u"""Levantamento do que famílias REAIS usam — insumo para priorizar cobertura.

Abre cada .rfa listado em RFADG_LOTE (um caminho por linha) e conta os
construtos que o conversor precisaria reproduzir: classes de forma, famílias
aninhadas, conectores MEP, subcategorias, materiais, espécies de tipo de dado,
cotas rotuladas, alinhamentos e cortes.

Não converte nada. Serve para responder, com dado em vez de palpite, o que
implementar depois — e para dimensionar honestamente o quanto do acervo o
conversor já cobre hoje.

Saída: RFADG_INVENTARIO (JSON).

    pyrevit run scripts/inventario.py <portadora.rfa> --revit=2025
"""

import os
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

from Autodesk.Revit.DB import (  # noqa: E402
    FilteredElementCollector, GenericForm, GeomCombination, Dimension,
    FamilyInstance, ConnectorElement, ReferencePlane, Material,
    BuiltInCategory,
)

log = rfaspec.log


def _contar_por_classe(doc, classe):
    contagem = {}
    for elemento in FilteredElementCollector(doc).OfClass(classe).ToElements():
        nome = rfaspec.para_unicode(type(elemento).__name__)
        contagem[nome] = contagem.get(nome, 0) + 1
    return contagem


def _especies_de_parametro(doc):
    u"""Espécies de ForgeTypeId usadas, com contagem."""
    especies = {}
    for parametro in doc.FamilyManager.Parameters:
        try:
            bruto = parametro.Definition.GetDataType().TypeId
        except Exception:
            bruto = None
        especie = rfaspec.especie_forge(bruto) or u"(desconhecida)"
        especies[especie] = especies.get(especie, 0) + 1
    return especies


def _cotas(doc):
    u"""Separa cotas rotuladas, cotas soltas e restrições de alinhamento."""
    id_restricoes = int(BuiltInCategory.OST_Constraints)
    rotuladas = 0
    soltas = 0
    alinhamentos = 0

    for dimensao in FilteredElementCollector(doc).OfClass(Dimension).ToElements():
        categoria = dimensao.Category
        eh_restricao = (
            categoria is not None
            and rfaspec.id_inteiro(categoria.Id) == id_restricoes
        )
        if eh_restricao:
            alinhamentos += 1
            continue
        try:
            rotulo = dimensao.FamilyLabel
        except Exception:
            rotulo = None
        if rotulo is not None:
            rotuladas += 1
        else:
            soltas += 1

    return rotuladas, soltas, alinhamentos


def inventariar(doc, caminho):
    formas = _contar_por_classe(doc, GenericForm)
    rotuladas, soltas, alinhamentos = _cotas(doc)

    aninhadas = FilteredElementCollector(doc).OfClass(FamilyInstance).ToElements()
    conectores = FilteredElementCollector(doc).OfClass(ConnectorElement).ToElements()
    planos = FilteredElementCollector(doc).OfClass(ReferencePlane).ToElements()
    materiais = FilteredElementCollector(doc).OfClass(Material).ToElements()
    combinacoes = FilteredElementCollector(doc).OfClass(GeomCombination).ToElements()

    subcategorias = []
    try:
        for categoria in doc.OwnerFamily.FamilyCategory.SubCategories:
            subcategorias.append(rfaspec.para_unicode(categoria.Name))
    except Exception:
        pass

    return {
        u"arquivo": rfaspec.para_unicode(os.path.basename(caminho)),
        u"categoria": rfaspec.para_unicode(doc.OwnerFamily.FamilyCategory.Name),
        u"formas": formas,
        u"total_de_formas": sum(formas.values()),
        u"combinacoes": len(combinacoes),
        u"aninhadas": len(aninhadas),
        u"conectores_mep": len(conectores),
        u"planos_de_referencia": len(planos),
        u"materiais": len(materiais),
        u"subcategorias": len(subcategorias),
        u"tipos": doc.FamilyManager.Types.Size,
        u"parametros": doc.FamilyManager.Parameters.Size,
        u"especies_de_parametro": _especies_de_parametro(doc),
        u"cotas_rotuladas": rotuladas,
        u"cotas_soltas": soltas,
        u"alinhamentos": alinhamentos,
    }


def principal():
    lote = rfaspec.env("RFADG_LOTE", obrigatorio=True)
    destino = rfaspec.env("RFADG_INVENTARIO", obrigatorio=True)

    with open(lote, "rb") as arquivo:
        caminhos = [linha.strip() for linha in arquivo.read().splitlines()]
    caminhos = [c for c in caminhos if c and os.path.isfile(c)]

    app = __revit__.Application  # noqa: F821

    resultados = []
    for caminho in caminhos:
        try:
            doc = app.OpenDocumentFile(caminho)
        except Exception as erro:
            resultados.append({
                u"arquivo": rfaspec.para_unicode(os.path.basename(caminho)),
                u"erro_ao_abrir": rfaspec.para_unicode(str(erro))[:200],
            })
            continue

        try:
            if not doc.IsFamilyDocument:
                resultados.append({
                    u"arquivo": rfaspec.para_unicode(os.path.basename(caminho)),
                    u"erro": u"não é documento de família",
                })
            else:
                resultados.append(inventariar(doc, caminho))
        except Exception as erro:
            resultados.append({
                u"arquivo": rfaspec.para_unicode(os.path.basename(caminho)),
                u"erro": rfaspec.para_unicode(str(erro))[:200],
            })
        finally:
            doc.Close(False)

    # Agregado: é o que responde "o que implementar depois".
    formas_totais = {}
    especies_totais = {}
    com_aninhada = 0
    com_conector = 0
    so_extrusao = 0

    for item in resultados:
        for nome, quantidade in (item.get(u"formas") or {}).items():
            formas_totais[nome] = formas_totais.get(nome, 0) + quantidade
        for nome, quantidade in (item.get(u"especies_de_parametro") or {}).items():
            especies_totais[nome] = especies_totais.get(nome, 0) + quantidade
        if item.get(u"aninhadas"):
            com_aninhada += 1
        if item.get(u"conectores_mep"):
            com_conector += 1
        formas = item.get(u"formas")
        if formas and set(formas.keys()) == set([u"Extrusion"]):
            so_extrusao += 1

    rfaspec.gravar_json(destino, {
        u"familias": len(resultados),
        u"resumo": {
            u"formas_por_classe": formas_totais,
            u"especies_de_parametro": especies_totais,
            u"familias_com_aninhada": com_aninhada,
            u"familias_com_conector_mep": com_conector,
            u"familias_so_com_extrusao": so_extrusao,
        },
        u"detalhe": resultados,
    })

    log(u"Inventário de {0} famílias em {1}".format(len(resultados), destino))


principal()

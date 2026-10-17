# -*- coding: utf-8 -*-
u"""Inventário de uma referência (família ou template/projeto), só leitura.

Família: formas por classe, aninhadas, conectores, parâmetros (fórmula,
instância), tipos, cotas rotuladas, geometria importada, bbox e volume do tipo
corrente. Template/projeto: famílias por categoria; as de hidráulica (Pipe
Fittings, Pipe Accessories) são extraídas com EditFamily para RFADG_EXTRAIR.

    RFADG_ENTRADA=<arquivo> RFADG_RELATORIO=<json> [RFADG_EXTRAIR=<pasta>]
"""

import os
import sys
import traceback

_RAIZ = os.environ.get("RFADG_ROOT")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

import Autodesk.Revit.DB as DB  # noqa: E402
from Autodesk.Revit.DB import BuiltInParameter, FilteredElementCollector  # noqa: E402

para_mm = rfaspec.interno_para_mm
u = rfaspec.para_unicode
CATEGORIAS_A_EXTRAIR = (u"Pipe Fittings", u"Pipe Accessories", u"Conexões de tubo", u"Acessórios de tubo")


def _nome(elemento):
    try:
        return u(elemento.Name)
    except Exception:
        parametro = elemento.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        return u(parametro.AsString()) if parametro else u"?"


def inventario_familia(doc):
    gerenciador = doc.FamilyManager
    formas = {}
    for elemento in FilteredElementCollector(doc).OfClass(DB.GenericForm).ToElements():
        chave = type(elemento).__name__ + (u"" if elemento.IsSolid else u"(vazio)")
        formas[chave] = formas.get(chave, 0) + 1
    aninhadas = {}
    for instancia in FilteredElementCollector(doc).OfClass(DB.FamilyInstance).ToElements():
        nome = _nome(instancia.Symbol.Family)
        aninhadas[nome] = aninhadas.get(nome, 0) + 1
    conectores = []
    for conector in FilteredElementCollector(doc).OfClass(DB.ConnectorElement).ToElements():
        item = {u"dominio": u(str(conector.Domain)), u"sistema": u(str(conector.SystemClassification)),
                u"origem_mm": [round(para_mm(v), 1) for v in (conector.Origin.X, conector.Origin.Y, conector.Origin.Z)],
                u"direcao": [round(v, 3) for v in (conector.Direction.X, conector.Direction.Y, conector.Direction.Z)]}
        try:
            item[u"diametro_mm"] = round(para_mm(2 * conector.Radius), 1)
        except Exception:
            pass
        diametro = conector.get_Parameter(BuiltInParameter.CONNECTOR_DIAMETER)
        associado = gerenciador.GetAssociatedFamilyParameter(diametro) if diametro is not None else None
        item[u"diametro_rotulo"] = u(associado.Definition.Name) if associado is not None else None
        conectores.append(item)
    parametros = []
    for parametro in gerenciador.Parameters:
        definicao = parametro.Definition
        embutido = isinstance(definicao, DB.InternalDefinition) and \
            definicao.BuiltInParameter != BuiltInParameter.INVALID
        if embutido:
            continue
        parametros.append({u"nome": u(definicao.Name), u"instancia": bool(parametro.IsInstance),
                           u"formula": u(parametro.Formula) if parametro.Formula else None,
                           u"armazenamento": u(str(parametro.StorageType))})
    rotuladas = 0
    for cota in FilteredElementCollector(doc).OfClass(DB.Dimension).ToElements():
        try:
            if cota.FamilyLabel is not None:
                rotuladas += 1
        except Exception:
            pass
    tipo_peca = doc.OwnerFamily.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
    medida = rfaspec.medir_geometria(doc)
    return {
        u"categoria": u(doc.OwnerFamily.FamilyCategory.Name),
        u"part_type": tipo_peca.AsInteger() if tipo_peca else None,
        u"formas": formas,
        u"aninhadas": aninhadas,
        u"importadas": FilteredElementCollector(doc).OfClass(DB.ImportInstance).GetElementCount(),
        u"freeform": FilteredElementCollector(doc).OfClass(DB.FreeFormElement).GetElementCount(),
        u"conectores": conectores,
        u"parametros": parametros,
        u"tipos": [u(t.Name) for t in gerenciador.Types if t.Name],
        u"cotas_rotuladas": rotuladas,
        u"planos_de_referencia": FilteredElementCollector(doc).OfClass(DB.ReferencePlane).GetElementCount(),
        u"tipo_corrente": u(gerenciador.CurrentType.Name) if gerenciador.CurrentType else None,
        u"medida_tipo_corrente": {k: v for k, v in (medida or {}).items() if k != u"diagnostico"},
    }


def inventario_projeto(doc, pasta_extracao):
    familias = {}
    extraidas = []
    for familia in FilteredElementCollector(doc).OfClass(DB.Family).ToElements():
        categoria = u(familia.FamilyCategory.Name) if familia.FamilyCategory else u"?"
        nome = _nome(familia)
        tipos = [_nome(doc.GetElement(i)) for i in familia.GetFamilySymbolIds()]
        familias.setdefault(categoria, []).append({u"familia": nome, u"tipos": len(tipos),
                                                  u"exemplos": tipos[:6], u"editavel": familia.IsEditable})
        if pasta_extracao and categoria in CATEGORIAS_A_EXTRAIR and familia.IsEditable:
            try:
                documento = doc.EditFamily(familia)
                destino = os.path.join(pasta_extracao, u"".join(c if c.isalnum() or c in u" ._-" else u"_"
                                                                 for c in nome) + u".rfa")
                opcoes = DB.SaveAsOptions()
                opcoes.OverwriteExistingFile = True
                documento.SaveAs(destino, opcoes)
                documento.Close(False)
                extraidas.append(destino)
            except Exception as erro:
                extraidas.append(u"ERRO {0}: {1}".format(nome, u(unicode(erro))[:120]))  # noqa: F821
    return {u"familias_por_categoria": familias, u"extraidas": extraidas}


def principal():
    entrada = rfaspec.env("RFADG_ENTRADA", obrigatorio=True)
    saida = rfaspec.env("RFADG_RELATORIO", obrigatorio=True)
    pasta = os.environ.get("RFADG_EXTRAIR")
    if pasta and not os.path.isdir(pasta):
        os.makedirs(pasta)
    resultado = {u"arquivo": entrada}
    doc = __revit__.Application.OpenDocumentFile(entrada)  # noqa: F821
    try:
        if doc.IsFamilyDocument:
            resultado[u"familia"] = inventario_familia(doc)
        else:
            resultado[u"projeto"] = inventario_projeto(doc, pasta)
    except Exception as erro:
        resultado[u"erro"] = u(unicode(erro))[:300]  # noqa: F821
        resultado[u"traceback"] = u(traceback.format_exc())[-1500:]
    finally:
        doc.Close(False)
    rfaspec.gravar_json(saida, resultado)


principal()

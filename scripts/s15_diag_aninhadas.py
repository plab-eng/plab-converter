# -*- coding: utf-8 -*-
u"""Sonda S15 -- diagnostico das familias aninhadas (RFADG_ENTRADA).

Para cada FamilyInstance do documento da familia: familia, tipo, compartilhada,
ponto, eixos da transformacao, espelhada, hospedeiro (plano de trabalho),
parametros da instancia associados a parametros da hospedeira, e aninhadas
dentro dela (1 nivel). Para cada cota/alinhamento que toca uma instancia:
GetReferenceType / GetReferenceName da referencia e a representacao estavel.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402

para_mm = rfaspec.interno_para_mm


def _p(xyz):
    return [round(para_mm(xyz.X), 2), round(para_mm(xyz.Y), 2), round(para_mm(xyz.Z), 2)]


def _v(xyz):
    return [round(xyz.X, 4), round(xyz.Y, 4), round(xyz.Z, 4)]


def _nome(elemento):
    return rfaspec.para_unicode(DB.Element.Name.__get__(elemento))


def principal():
    app = __revit__.Application  # noqa: F821
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"instancias": [], u"referencias": {}}
    doc = app.OpenDocumentFile(rfaspec.env("RFADG_ENTRADA", obrigatorio=True))
    try:
        g = doc.FamilyManager
        instancias = list(DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).ToElements())
        ids = set(rfaspec.id_inteiro(i.Id) for i in instancias)
        for inst in instancias:
            simbolo = inst.Symbol
            familia = simbolo.Family
            t = inst.GetTransform()
            item = {u"id": rfaspec.id_inteiro(inst.Id), u"familia": _nome(familia), u"tipo": _nome(simbolo),
                    u"compartilhada": None, u"categoria": rfaspec.para_unicode(familia.FamilyCategory.Name)
                    if familia.FamilyCategory else None,
                    u"ponto": _p(t.Origin), u"x": _v(t.BasisX), u"y": _v(t.BasisY), u"z": _v(t.BasisZ),
                    u"espelhada": bool(inst.Mirrored), u"hospedeiro": None, u"associacoes": {},
                    u"visivel": None}
            try:
                p = familia.get_Parameter(DB.BuiltInParameter.FAMILY_SHARED)
                item[u"compartilhada"] = bool(p.AsInteger()) if p else None
            except Exception:
                pass
            try:
                face = inst.HostFace
                hosp = inst.Host
                item[u"hospedeiro"] = (type(hosp).__name__ + u" " + _nome(hosp)) if hosp is not None else None
                if face is not None:
                    item[u"hospedeiro_face"] = rfaspec.para_unicode(face.ConvertToStableRepresentation(doc))[-60:]
            except Exception as erro:
                item[u"hospedeiro_erro"] = rfaspec.para_unicode(unicode(erro))[:80]  # noqa: F821
            try:
                plano = doc.GetElement(inst.get_Parameter(DB.BuiltInParameter.SKETCH_PLANE_PARAM).AsElementId()) \
                    if inst.get_Parameter(DB.BuiltInParameter.SKETCH_PLANE_PARAM) else None
                item[u"plano_de_trabalho"] = _nome(plano) if plano is not None else None
            except Exception:
                pass
            for parametro in inst.Parameters:
                try:
                    associado = g.GetAssociatedFamilyParameter(parametro)
                except Exception:
                    associado = None
                if associado is not None:
                    item[u"associacoes"][rfaspec.para_unicode(parametro.Definition.Name)] = \
                        rfaspec.para_unicode(associado.Definition.Name)
            try:
                item[u"subcomponentes"] = len(list(inst.GetSubComponentIds()))
            except Exception:
                pass
            saida[u"instancias"].append(item)
        # familias distintas e aninhadas de 2o nivel
        distintas = {}
        for inst in instancias:
            distintas[_nome(inst.Symbol.Family)] = inst.Symbol.Family
        saida[u"familias_distintas"] = {}
        for nome, familia in distintas.items():
            info = {}
            try:
                sub = doc.EditFamily(familia)
                try:
                    internas = list(DB.FilteredElementCollector(sub).OfClass(DB.FamilyInstance).ToElements())
                    info[u"aninhadas_internas"] = len(internas)
                    info[u"tipos"] = [_nome(t) for t in sub.FamilyManager.Types]
                    info[u"parametros"] = len(list(sub.FamilyManager.Parameters))
                    info[u"conectores"] = len(list(DB.FilteredElementCollector(sub).OfClass(
                        DB.ConnectorElement).ToElements()))
                finally:
                    sub.Close(False)
            except Exception as erro:
                info[u"erro"] = rfaspec.para_unicode(unicode(erro))[:120]  # noqa: F821
            saida[u"familias_distintas"][nome] = info
        # referencias de cotas/alinhamentos a instancias
        contagem = {}
        for cota in DB.FilteredElementCollector(doc).OfClass(DB.Dimension).ToElements():
            for ref in cota.References:
                if rfaspec.id_inteiro(ref.ElementId) not in ids:
                    continue
                inst = doc.GetElement(ref.ElementId)
                try:
                    tipo_ref = str(inst.GetReferenceType(ref))
                except Exception as erro:
                    tipo_ref = u"erro " + rfaspec.para_unicode(unicode(erro))[:40]  # noqa: F821
                try:
                    nome_ref = rfaspec.para_unicode(inst.GetReferenceName(ref))
                except Exception:
                    nome_ref = None
                estavel = rfaspec.para_unicode(ref.ConvertToStableRepresentation(doc)).split(u":", 1)[-1]
                chave = u"{0} | {1} | {2}".format(tipo_ref, nome_ref, estavel[:50])
                contagem[chave] = contagem.get(chave, 0) + 1
        saida[u"referencias"] = contagem
    except Exception:
        saida[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-800:]
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

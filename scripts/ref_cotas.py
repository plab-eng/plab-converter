# -*- coding: utf-8 -*-
u"""Classifica as referências das cotas/alinhamentos de uma família (diagnóstico).

    RFADG_ENTRADA=<familia.rfa> RFADG_RELATORIO=<json>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402


def _classe(doc, referencia):
    elemento = doc.GetElement(referencia.ElementId)
    if elemento is None:
        return u"nulo"
    if isinstance(elemento, DB.ReferencePlane):
        return u"plano"
    if isinstance(elemento, DB.FamilyInstance):
        return u"aninhada"
    if isinstance(elemento, DB.CurveElement):
        # CurveElement.Sketch não existe em toda versão; o que vale é ser de esboço.
        return u"curva_de_esboco" if getattr(elemento, "IsSketchElement", False) or             getattr(elemento, "SketchPlane", None) is not None and type(elemento).__name__ != u"ModelLine"             else u"curva(" + type(elemento).__name__ + u")"
    if isinstance(elemento, DB.GenericForm):
        return u"forma(" + type(elemento).__name__ + u")"
    return type(elemento).__name__


def principal():
    doc = __revit__.Application.OpenDocumentFile(rfaspec.env("RFADG_ENTRADA", obrigatorio=True))  # noqa: F821
    contagem = {}
    try:
        for cota in DB.FilteredElementCollector(doc).OfClass(DB.Dimension).ToElements():
            restricao = cota.Category is not None and rfaspec.id_inteiro(cota.Category.Id) == int(DB.BuiltInCategory.OST_Constraints)
            classes = sorted(set(_classe(doc, r) for r in cota.References))
            rotulada = False
            try:
                rotulada = cota.FamilyLabel is not None
            except Exception:
                pass
            chave = u"{0}|{1}|{2}|{3}".format(u"alinhamento" if restricao else u"cota", str(cota.DimensionShape),
                                            u"rotulada" if rotulada else u"livre", u"+".join(classes))
            contagem[chave] = contagem.get(chave, 0) + 1
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), contagem)


principal()

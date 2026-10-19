# -*- coding: utf-8 -*-
u"""Sonda S17 -- quando o Revit cria as cotas automaticas do esboco?

Extrusao hexagonal pela API numa familia nova. Conta as cotas que tocam o
esboco: logo apos NewExtrusion, apos Regenerate, apos apagar, apos Commit,
apos uma transacao nova com Regenerate, e depois de SaveAs + reabrir.
"""
import math
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402

mm = rfaspec.mm_para_interno


def _contar(doc, extrusao):
    ids = set(rfaspec.id_inteiro(i) for i in extrusao.Sketch.GetAllElements())
    achadas = []
    for cota in DB.FilteredElementCollector(doc).OfClass(DB.Dimension).ToElements():
        if any(rfaspec.id_inteiro(r.ElementId) in ids for r in cota.References):
            achadas.append(cota.Id)
    return achadas


def principal():
    app = __revit__.Application  # noqa: F821
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"contagem": []}
    doc = app.NewFamilyDocument(rfaspec.env("RFADG_TEMPLATE", obrigatorio=True))
    try:
        t = DB.Transaction(doc, u"S17")
        t.Start()
        laco = DB.CurveArray()
        pts = [DB.XYZ(mm(25 * math.cos(math.radians(30 + 60 * i))), mm(25 * math.sin(math.radians(30 + 60 * i))), 0)
               for i in range(6)]
        for i in range(6):
            laco.Append(DB.Line.CreateBound(pts[i], pts[(i + 1) % 6]))
        perfil = DB.CurveArrArray()
        perfil.Append(laco)
        esboco = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ.Zero))
        extrusao = doc.FamilyCreate.NewExtrusion(True, perfil, esboco, mm(40))
        saida[u"contagem"].append([u"apos NewExtrusion", len(_contar(doc, extrusao))])
        doc.Regenerate()
        achadas = _contar(doc, extrusao)
        saida[u"contagem"].append([u"apos Regenerate", len(achadas)])
        for i in achadas:
            doc.Delete(i)
        doc.Regenerate()
        saida[u"contagem"].append([u"apos apagar", len(_contar(doc, extrusao))])
        t.Commit()
        saida[u"contagem"].append([u"apos Commit", len(_contar(doc, extrusao))])
        t = DB.Transaction(doc, u"S17b")
        t.Start()
        p = doc.FamilyManager.AddParameter(u"X", DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)
        doc.Regenerate()
        t.Commit()
        saida[u"contagem"].append([u"apos outra transacao", len(_contar(doc, extrusao))])
        caminho = os.path.join(tempfile.mkdtemp(), u"s17.rfa")
        doc.SaveAs(caminho)
        doc.Close(False)
        doc = app.OpenDocumentFile(caminho)
        extrusao = list(DB.FilteredElementCollector(doc).OfClass(DB.Extrusion).ToElements())[0]
        saida[u"contagem"].append([u"apos salvar e reabrir", len(_contar(doc, extrusao))])
    except Exception:
        saida[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-600:]
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

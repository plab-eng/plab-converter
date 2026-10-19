# -*- coding: utf-8 -*-
u"""Sonda S16 -- conector de tubo numa face de familia ANINHADA (bocais Solaris).

RFADG_ENTRADA = familia convertida (com as aninhadas); RFADG_SPEC = FamilySpec
da origem (conectores com face {"aninhada", "normal", "origem"}).
Para cada conector: acha a instancia pelo ponto da origem e a face plana que
contem a origem do conector, e tenta CreatePipeConnector com:
  A  face.Reference da geometria da INSTANCIA (GetInstanceGeometry)
  B  face.Reference da geometria do SIMBOLO posta na instancia
     ("<uid>:0:INSTANCE:<estavel>")
Tudo em transacao desfeita.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402
from Autodesk.Revit.DB.Plumbing import PipeSystemType  # noqa: E402

mm = rfaspec.mm_para_interno


def _xyz(lista):
    return DB.XYZ(mm(lista[0]), mm(lista[1]), mm(lista[2]))


def _instancia_no_ponto(doc, ponto):
    for inst in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).ToElements():
        if inst.GetTransform().Origin.DistanceTo(ponto) < mm(0.01):
            return inst
    return None


def _faces(inst, origem, normal):
    opcoes = DB.Options()
    opcoes.ComputeReferences = True
    achadas = {}
    for objeto in inst.get_Geometry(opcoes) or []:
        if not isinstance(objeto, DB.GeometryInstance):
            continue
        for solido in objeto.GetInstanceGeometry():
            if isinstance(solido, DB.Solid):
                for face in solido.Faces:
                    if isinstance(face, DB.PlanarFace) and face.FaceNormal.IsAlmostEqualTo(normal):
                        p = face.Project(origem)
                        if p is not None and p.Distance < 1e-6:
                            achadas[u"A"] = face.Reference
        t = objeto.Transform
        for solido in objeto.GetSymbolGeometry():
            if isinstance(solido, DB.Solid):
                for face in solido.Faces:
                    if isinstance(face, DB.PlanarFace) and t.OfVector(face.FaceNormal).IsAlmostEqualTo(normal):
                        p = face.Project(t.Inverse.OfPoint(origem))
                        if p is not None and p.Distance < 1e-6 and face.Reference is not None:
                            estavel = face.Reference.ConvertToStableRepresentation(inst.Document)
                            achadas[u"B"] = DB.Reference.ParseFromStableRepresentation(
                                inst.Document, u"{0}:0:INSTANCE:{1}".format(inst.UniqueId, estavel))
    return achadas


def principal():
    app = __revit__.Application  # noqa: F821
    spec = rfaspec.ler_json(rfaspec.env("RFADG_SPEC", obrigatorio=True))
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"conectores": []}
    doc = app.OpenDocumentFile(rfaspec.env("RFADG_ENTRADA", obrigatorio=True))
    try:
        for c in spec.get(u"conectores") or []:
            face = c[u"face"]
            if face.get(u"aninhada") is None:
                continue
            item = {u"aninhada": face[u"aninhada"]}
            saida[u"conectores"].append(item)
            inst = _instancia_no_ponto(doc, _xyz(spec[u"aninhadas"][face[u"aninhada"]][u"ponto"]))
            if inst is None:
                item[u"erro"] = u"instancia nao achada pelo ponto"
                continue
            origem = _xyz(face[u"origem"])
            normal = DB.XYZ(*face[u"normal"]).Normalize()
            achadas = _faces(inst, origem, normal)
            item[u"faces"] = sorted(achadas.keys())
            for chave, referencia in sorted(achadas.items()):
                t = DB.Transaction(doc, u"S16")
                t.Start()
                try:
                    if referencia is None:
                        item[chave] = u"referencia nula"
                        continue
                    conector = DB.ConnectorElement.CreatePipeConnector(doc, PipeSystemType.Fitting, referencia)
                    doc.Regenerate()
                    item[chave] = u"OK em " + str([round(rfaspec.interno_para_mm(v), 1) for v in
                                                   (conector.Origin.X, conector.Origin.Y, conector.Origin.Z)])
                except Exception as erro:
                    item[chave] = rfaspec.para_unicode(unicode(erro))[:120]  # noqa: F821
                finally:
                    t.RollBack()
    except Exception:
        saida[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-800:]
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

# -*- coding: utf-8 -*-
u"""Diagnóstico: em que elemento está a face hospedeira de cada conector."""
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402


def _faces(elemento, opcoes):
    for objeto in elemento.get_Geometry(opcoes):
        objetos = [objeto]
        if isinstance(objeto, DB.GeometryInstance):
            objetos = list(objeto.GetInstanceGeometry())
        for o in objetos:
            if isinstance(o, DB.Solid):
                for face in o.Faces:
                    if isinstance(face, DB.PlanarFace):
                        yield face


def principal():
    doc = __revit__.Application.OpenDocumentFile(rfaspec.env("RFADG_ENTRADA", obrigatorio=True))  # noqa: F821
    saida = []
    opcoes = DB.Options()
    opcoes.ComputeReferences = True
    try:
        candidatos = list(DB.FilteredElementCollector(doc).OfClass(DB.GenericForm).ToElements()) + \
            list(DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).ToElements())
        for conector in DB.FilteredElementCollector(doc).OfClass(DB.ConnectorElement).ToElements():
            achados = []
            for elemento in candidatos:
                for face in _faces(elemento, opcoes):
                    if not face.FaceNormal.IsAlmostEqualTo(conector.Direction) and \
                            not face.FaceNormal.IsAlmostEqualTo(conector.Direction.Negate()):
                        continue
                    projecao = face.Project(conector.Origin)
                    if projecao is not None and projecao.Distance < 1e-4:
                        achados.append(type(elemento).__name__)
            planos = [p.Name for p in DB.FilteredElementCollector(doc).OfClass(DB.ReferencePlane).ToElements()
                      if abs(abs(p.Normal.DotProduct(conector.Direction)) - 1) < 1e-6 and
                      abs((conector.Origin - p.BubbleEnd).DotProduct(p.Normal)) < 1e-6]
            saida.append({u"origem_mm": [round(rfaspec.interno_para_mm(v), 2) for v in
                                         (conector.Origin.X, conector.Origin.Y, conector.Origin.Z)],
                          u"faces_em": achados, u"planos_coincidentes": planos})
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

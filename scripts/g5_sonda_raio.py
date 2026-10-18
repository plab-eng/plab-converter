# -*- coding: utf-8 -*-
u"""Sonda S10: o raio do conector pode ser associado a quê? (tamanho pelo tubo)"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402
from Autodesk.Revit.DB.Plumbing import PipeSystemType  # noqa: E402

mm = rfaspec.mm_para_interno


def principal():
    app = __revit__.Application  # noqa: F821
    doc = app.NewFamilyDocument(rfaspec.env("RFADG_TEMPLATE", obrigatorio=True))
    saida = {}
    t = DB.Transaction(doc, u"S10")
    t.Start()
    try:
        doc.OwnerFamily.FamilyCategory = DB.Category.GetCategory(doc, DB.BuiltInCategory.OST_PipeFitting)
        gerenciador = doc.FamilyManager
        gerenciador.NewType(u"T")
        params = {}
        for nome, espec, instancia in ((u"RN_pipesize_inst", DB.SpecTypeId.PipeSize, True),
                                       (u"RN_pipesize_tipo", DB.SpecTypeId.PipeSize, False),
                                       (u"RN_length_inst", DB.SpecTypeId.Length, True),
                                       (u"RN_length_tipo", DB.SpecTypeId.Length, False)):
            params[nome] = gerenciador.AddParameter(nome, DB.GroupTypeId.Geometry, espec, instancia)
        plano = DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ.Zero)
        laco = DB.CurveArray()
        laco.Append(DB.Arc.Create(plano, mm(20), 0.0, 3.141592653589793))
        laco.Append(DB.Arc.Create(plano, mm(20), 3.141592653589793, 6.283185307179586))
        perfil = DB.CurveArrArray()
        perfil.Append(laco)
        extrusao = doc.FamilyCreate.NewExtrusion(True, perfil, DB.SketchPlane.Create(doc, plano), mm(50))
        doc.Regenerate()
        opcoes = DB.Options()
        opcoes.ComputeReferences = True
        face = [f for o in extrusao.get_Geometry(opcoes) if isinstance(o, DB.Solid) for f in o.Faces
                if isinstance(f, DB.PlanarFace) and f.FaceNormal.IsAlmostEqualTo(DB.XYZ.BasisZ)][0]
        conector = DB.ConnectorElement.CreatePipeConnector(doc, PipeSystemType.Fitting, face.Reference)
        doc.Regenerate()
        for bip in (u"CONNECTOR_RADIUS", u"CONNECTOR_DIAMETER", u"RBS_PIPE_DIAMETER_PARAM"):
            parametro = conector.get_Parameter(getattr(DB.BuiltInParameter, bip))
            item = {u"existe": parametro is not None}
            if parametro is not None:
                item[u"pode_associar"] = gerenciador.CanElementParameterBeAssociated(parametro)
                item[u"espec"] = rfaspec.para_unicode(parametro.Definition.GetDataType().TypeId)
                for nome, alvo in params.items():
                    sub = DB.SubTransaction(doc)
                    sub.Start()
                    try:
                        gerenciador.AssociateElementParameterToFamilyParameter(parametro, alvo)
                        item[nome] = u"ok"
                    except Exception as erro:
                        item[nome] = rfaspec.para_unicode(unicode(erro))[:70]  # noqa: F821
                    sub.RollBack()
            saida[bip] = item
    except Exception:
        saida[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-800:]
    finally:
        t.RollBack()
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

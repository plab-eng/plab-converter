# -*- coding: utf-8 -*-
u"""Sonda S12 -- conector de tubo preso a PLANO de referencia (te Ultrapex).

Familia Pipe Fittings com o plano PX (normal X, x = Comprimento, rotulado) e
um conector que precisa acompanhar o PX e ter diametro = DN.

C1  CreatePipeConnector com PX.GetReference()      (falha conhecida)
C1b CreatePipeConnector com Reference(SketchPlane do PX)
C2  disco SOLIDO INVISIVEL hospedado no PX (SketchPlane do PX), conector na
    face do disco
C3  disco VAZIO (void, sem corte) hospedado no PX, conector na face do disco

Para cada variante que cria o conector: flexiona Comprimento e DN e confere a
posicao e o diametro do conector; carrega num projeto, liga um tubo e confere
IsConnected e o volume visivel da instancia.
"""
import math
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import clr  # noqa: E402
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402
from Autodesk.Revit.DB.Plumbing import PipeSystemType  # noqa: E402

mm = rfaspec.mm_para_interno
para_mm = rfaspec.interno_para_mm
_ABERTOS = []
_DISCO_FACES = []


class _Pre(DB.IFailuresPreprocessor):
    def __init__(self, registro):
        self.registro = registro

    def PreprocessFailures(self, acessor):
        erro = False
        for mensagem in acessor.GetFailureMessages():
            texto = rfaspec.para_unicode(mensagem.GetDescriptionText())
            if mensagem.GetSeverity() == DB.FailureSeverity.Warning:
                self.registro.append(u"AVISO: " + texto)
                acessor.DeleteWarning(mensagem)
            else:
                self.registro.append(u"ERRO: " + texto)
                erro = True
        if erro:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def _t(doc, nome, registro):
    transacao = DB.Transaction(doc, nome)
    opcoes = transacao.GetFailureHandlingOptions()
    opcoes.SetFailuresPreprocessor(_Pre(registro))
    opcoes.SetClearAfterRollback(True)
    transacao.SetFailureHandlingOptions(opcoes)
    _ABERTOS.append(transacao)
    return transacao


def _fechar(doc, registro):
    for aberto in reversed(_ABERTOS):
        try:
            if aberto.HasStarted() and not aberto.HasEnded():
                aberto.RollBack()
                registro.append(u"transacao aberta desfeita")
        except Exception:
            pass
    del _ABERTOS[:]
    doc.Close(False)


def _texto(erro):
    return rfaspec.para_unicode(unicode(erro))[:200]  # noqa: F821


def _vista(doc, tipo):
    for vista in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements():
        if not vista.IsTemplate and vista.ViewType == tipo:
            return vista
    return None


def _plano_centro_x(doc):
    for plano in DB.FilteredElementCollector(doc).OfClass(DB.ReferencePlane).ToElements():
        if abs(abs(plano.Normal.X) - 1) < 1e-6 and abs(plano.BubbleEnd.X) < 1e-6:
            return plano
    return None


def _disco(doc, px, solido):
    u"""Disco de 1 mm no plano PX, centrado em (x=PX, 0, 0), hospedado no PX."""
    esboco = DB.SketchPlane.Create(doc, px.Id)
    plano = esboco.GetPlane()
    raio = mm(10)
    laco = DB.CurveArray()
    laco.Append(DB.Arc.Create(DB.XYZ(px.BubbleEnd.X, 0, 0), raio, 0.0, math.pi,
                              plano.XVec, plano.YVec))
    laco.Append(DB.Arc.Create(DB.XYZ(px.BubbleEnd.X, 0, 0), raio, math.pi, 2 * math.pi, plano.XVec, plano.YVec))
    perfil = DB.CurveArrArray()
    perfil.Append(laco)
    # o disco fica do lado de dentro (x < PX): a face em PX aponta para +X
    sentido = -1.0 if plano.Normal.X > 0 else 1.0
    if not solido:
        # vazio tem as normais invertidas: o disco vai para fora (x > PX)
        sentido = -sentido
    extrusao = doc.FamilyCreate.NewExtrusion(solido, perfil, esboco, mm(sentido))
    if solido:
        # Visible e so leitura no IronPython: pelo parametro
        extrusao.get_Parameter(DB.BuiltInParameter.IS_VISIBLE_PARAM).Set(0)
    doc.Regenerate()
    opcoes = DB.Options()
    opcoes.ComputeReferences = True
    opcoes.IncludeNonVisibleObjects = True
    vistas = []
    geometria = extrusao.get_Geometry(opcoes)
    for objeto in (geometria or []):
        vistas.append(type(objeto).__name__)
        if isinstance(objeto, DB.Solid):
            for face in objeto.Faces:
                if isinstance(face, DB.PlanarFace):
                    vistas.append(str([round(para_mm(face.Origin.X), 2), round(face.FaceNormal.X, 3)]))
                    if abs(face.Origin.X - px.BubbleEnd.X) < 1e-6 and face.FaceNormal.X > 0.999:
                        return extrusao, face
    _DISCO_FACES[:] = [u"geometria nula" if geometria is None else u" ".join(vistas)]
    return extrusao, None


def _medir_conector(doc):
    saida = []
    for c in DB.FilteredElementCollector(doc).OfClass(DB.ConnectorElement).ToElements():
        saida.append({u"x_mm": round(para_mm(c.Origin.X), 2), u"y_mm": round(para_mm(c.Origin.Y), 2),
                      u"z_mm": round(para_mm(c.Origin.Z), 2), u"dir_x": round(c.Direction.X, 3),
                      u"diametro_mm": round(2 * para_mm(c.Radius), 2)})
    return saida


def familia(app, template, pasta, nome, resultado):
    registro = resultado[u"registro"]
    doc = app.NewFamilyDocument(template)
    try:
        t = _t(doc, nome, registro)
        t.Start()
        doc.OwnerFamily.FamilyCategory = DB.Category.GetCategory(doc, DB.BuiltInCategory.OST_PipeFitting)
        g = doc.FamilyManager
        g.NewType(u"T")
        dn = g.AddParameter(u"DN", DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)
        comp = g.AddParameter(u"Comprimento", DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)
        planta = _vista(doc, DB.ViewType.FloorPlan)
        px = doc.FamilyCreate.NewReferencePlane(DB.XYZ(mm(100), 0, 0), DB.XYZ(mm(100), mm(100), 0),
                                                DB.XYZ(0, 0, 1), planta)
        px.Name = u"PX"
        doc.Regenerate()
        ra = DB.ReferenceArray()
        ra.Append(_plano_centro_x(doc).GetReference())
        ra.Append(px.GetReference())
        cota = doc.FamilyCreate.NewDimension(planta, DB.Line.CreateBound(DB.XYZ(0, mm(-50), 0),
                                                                          DB.XYZ(mm(10), mm(-50), 0)), ra)
        cota.FamilyLabel = comp
        g.Set(dn, mm(32))
        g.Set(comp, mm(100))
        # corpo: cilindro de x=0 a x=100 (para ter alguma geometria visivel)
        esboco_corpo = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisX, DB.XYZ.Zero))
        pc = esboco_corpo.GetPlane()
        laco = DB.CurveArray()
        laco.Append(DB.Arc.Create(DB.XYZ.Zero, mm(20), 0.0, math.pi, pc.XVec, pc.YVec))
        laco.Append(DB.Arc.Create(DB.XYZ.Zero, mm(20), math.pi, 2 * math.pi, pc.XVec, pc.YVec))
        perfil = DB.CurveArrArray()
        perfil.Append(laco)
        doc.FamilyCreate.NewExtrusion(True, perfil, esboco_corpo, mm(60))
        doc.Regenerate()

        if nome in (u"C1", u"C1m"):
            hospedeira = px.GetReference()
        elif nome == u"C1b":
            hospedeira = DB.Reference(DB.SketchPlane.Create(doc, px.Id))
        else:
            _, face = _disco(doc, px, nome == u"C2")
            if face is None:
                resultado[u"erro"] = u"face do disco nao encontrada: " + u"".join(_DISCO_FACES)
                t.RollBack()
                return None
            hospedeira = face.Reference
        conector = DB.ConnectorElement.CreatePipeConnector(doc, PipeSystemType.Fitting, hospedeira)
        g.AssociateElementParameterToFamilyParameter(conector.get_Parameter(DB.BuiltInParameter.CONNECTOR_DIAMETER), dn)
        doc.Regenerate()
        registro.append(u"nasceu em " + str([round(para_mm(v), 2) for v in
                                             (conector.Origin.X, conector.Origin.Y, conector.Origin.Z)]))
        if nome == u"C1m":
            # leva o conector para (PX, 0, 0) dentro do plano
            alvo = DB.XYZ(conector.Origin.X, 0, 0)
            DB.ElementTransformUtils.MoveElement(doc, conector.Id, alvo - conector.Origin)
            doc.Regenerate()
            registro.append(u"movido para " + str([round(para_mm(v), 2) for v in
                                                   (conector.Origin.X, conector.Origin.Y, conector.Origin.Z)]))
        if t.Commit() != DB.TransactionStatus.Committed:
            resultado[u"erro"] = u"transacao desfeita"
            return None

        flex = []
        tudo = True
        for valor_dn, valor_c in ((32.0, 100.0), (50.0, 160.0), (20.0, 80.0)):
            t = _t(doc, u"flex", registro)
            t.Start()
            try:
                g.Set(dn, mm(valor_dn))
                g.Set(comp, mm(valor_c))
                doc.Regenerate()
                medidos = _medir_conector(doc)
                ok = len(medidos) == 1 and abs(medidos[0][u"x_mm"] - valor_c) < 0.01 and \
                    abs(medidos[0][u"diametro_mm"] - valor_dn) < 0.01
                tudo = tudo and ok
                flex.append({u"dn": valor_dn, u"comp": valor_c, u"ok": ok, u"conector": medidos})
            finally:
                t.RollBack()
        resultado[u"flex"] = flex
        resultado[u"flex_ok"] = tudo
        caminho = os.path.join(pasta, u"S12_{0}.rfa".format(nome))
        opcoes = DB.SaveAsOptions()
        opcoes.OverwriteExistingFile = True
        doc.SaveAs(caminho, opcoes)
        return caminho
    finally:
        _fechar(doc, registro)


def projeto(app, template_projeto, caminho, resultado):
    registro = resultado[u"registro"]
    doc = app.NewProjectDocument(template_projeto)
    try:
        t = _t(doc, u"projeto", registro)
        t.Start()
        carregada = clr.Reference[DB.Family]()
        if not doc.LoadFamily(caminho, carregada):
            resultado[u"projeto"] = u"LoadFamily falhou"
            t.RollBack()
            return
        simbolo = doc.GetElement(list(carregada.Value.GetFamilySymbolIds())[0])
        simbolo.Activate()
        nivel = DB.FilteredElementCollector(doc).OfClass(DB.Level).FirstElement()
        instancia = doc.Create.NewFamilyInstance(DB.XYZ(0, 0, mm(1000)), simbolo, nivel,
                                                 DB.Structure.StructuralType.NonStructural)
        doc.Regenerate()
        conector = [c for c in instancia.MEPModel.ConnectorManager.Connectors][0]
        tipo_tubo = DB.FilteredElementCollector(doc).OfClass(DB.Plumbing.PipeType).FirstElement()
        sistema = DB.FilteredElementCollector(doc).OfClass(DB.Plumbing.PipingSystemType).FirstElement()
        tubo = DB.Plumbing.Pipe.Create(doc, sistema.Id, tipo_tubo.Id, nivel.Id, conector.Origin,
                                       conector.Origin + conector.CoordinateSystem.BasisZ.Multiply(mm(500)))
        tubo.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(mm(32))
        doc.Regenerate()
        ponta = sorted([c for c in tubo.ConnectorManager.Connectors],
                       key=lambda c: c.Origin.DistanceTo(conector.Origin))[0]
        ponta.ConnectTo(conector)
        doc.Regenerate()
        volume = 0.0
        opcoes = DB.Options()
        for objeto in instancia.get_Geometry(opcoes):
            if isinstance(objeto, DB.GeometryInstance):
                for o in objeto.GetInstanceGeometry():
                    if isinstance(o, DB.Solid):
                        volume += o.Volume
        resultado[u"projeto"] = {u"conectado": bool(conector.IsConnected),
                                 u"volume_visivel_mm3": round(rfaspec.interno_para_mm3(volume), 1),
                                 u"volume_corpo_esperado_mm3": round(math.pi * 20 * 20 * 60, 1)}
        t.RollBack()
    except Exception as erro:
        resultado[u"projeto"] = u"ERRO: " + _texto(erro)
    finally:
        _fechar(doc, registro)


def principal():
    app = __revit__.Application  # noqa: F821
    template = rfaspec.env("RFADG_TEMPLATE", obrigatorio=True)
    template_projeto = rfaspec.env("RFADG_TEMPLATE_PROJETO", obrigatorio=True)
    pasta = os.path.dirname(rfaspec.env("RFADG_RELATORIO", obrigatorio=True))
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"variantes": []}
    for nome in rfaspec.env("RFADG_S12_VARIANTES", u"C1,C1m").split(u","):
        resultado = {u"variante": nome, u"registro": []}
        saida[u"variantes"].append(resultado)
        try:
            caminho = familia(app, template, pasta, nome, resultado)
            if caminho:
                projeto(app, template_projeto, caminho, resultado)
        except Exception as erro:
            resultado[u"erro"] = _texto(erro)
            resultado[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-500:]
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

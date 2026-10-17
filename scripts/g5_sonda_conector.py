# -*- coding: utf-8 -*-
u"""Sonda S9 — conector MEP e conexão de tubo pela API (G5).

V1  família: Generic Model -> categoria Pipe Fittings, Part Type = Union
    (luva), cilindro com raio por cota radial no esboço e comprimento por
    associação, dois conectores de tubo nas faces planas das pontas
    (PipeSystemType.Fitting), ligados entre si, com CONNECTOR_DIAMETER
    associado ao parâmetro Diametro_Nominal. Tipos DN40/DN50/DN75.
    Mede por tipo: posição, direção e diâmetro de cada conector.
V2  projeto (Plumbing-Default_Metric.rte): carrega a família, coloca uma
    instância DN50, cria um tubo de DN50 que termina no conector e liga os
    dois (Connector.ConnectTo). Confere IsConnected.

Toda transação com preprocessador que desfaz diante de erro.

    pyrevit run scripts/g5_sonda_conector.py <portadora.rfa> --revit=2024
"""

import os
import sys
import traceback

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

import Autodesk.Revit.DB as DB  # noqa: E402
from Autodesk.Revit.DB import (  # noqa: E402
    Arc, BuiltInCategory, BuiltInParameter, Category, CurveArray, CurveArrArray,
    FailureProcessingResult, FailureSeverity, FilteredElementCollector,
    IFailuresPreprocessor, Options, PlanarFace, Plane, SaveAsOptions,
    SketchPlane, Solid, Transaction, TransactionStatus, View, ViewType, XYZ,
)
from Autodesk.Revit.DB.Plumbing import PipeSystemType  # noqa: E402

mm = rfaspec.mm_para_interno
para_mm = rfaspec.interno_para_mm
TIPOS = {u"DN40": (40.0, 80.0), u"DN50": (50.0, 100.0), u"DN75": (75.0, 120.0)}
_ABERTOS = []


class _Pre(IFailuresPreprocessor):
    def __init__(self, registro):
        self.registro = registro

    def PreprocessFailures(self, acessor):
        erro = False
        for mensagem in acessor.GetFailureMessages():
            texto = rfaspec.para_unicode(mensagem.GetDescriptionText())
            if mensagem.GetSeverity() == FailureSeverity.Warning:
                self.registro.append(u"AVISO: " + texto)
                acessor.DeleteWarning(mensagem)
            else:
                self.registro.append(u"ERRO: " + texto)
                erro = True
        return FailureProcessingResult.ProceedWithRollBack if erro else FailureProcessingResult.Continue


def _t(doc, nome, registro):
    transacao = Transaction(doc, nome)
    opcoes = transacao.GetFailureHandlingOptions()
    opcoes.SetFailuresPreprocessor(_Pre(registro))
    opcoes.SetClearAfterRollback(True)
    transacao.SetFailureHandlingOptions(opcoes)
    _ABERTOS.append(transacao)
    return transacao


def _texto(erro):
    return rfaspec.para_unicode(unicode(erro))  # noqa: F821


def _vista(doc):
    for vista in FilteredElementCollector(doc).OfClass(View).ToElements():
        if not vista.IsTemplate and vista.ViewType == ViewType.FloorPlan:
            return vista


def _param(doc, nome):
    return doc.FamilyManager.AddParameter(nome, DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)


def _faces_das_pontas(extrusao):
    opcoes = Options()
    opcoes.ComputeReferences = True
    baixo = cima = None
    for objeto in extrusao.get_Geometry(opcoes):
        if isinstance(objeto, Solid):
            for face in objeto.Faces:
                if isinstance(face, PlanarFace):
                    if face.FaceNormal.IsAlmostEqualTo(XYZ(0, 0, -1)):
                        baixo = face
                    elif face.FaceNormal.IsAlmostEqualTo(XYZ(0, 0, 1)):
                        cima = face
    return baixo, cima


def _conectores_da_familia(doc):
    saida = []
    for conector in FilteredElementCollector(doc).OfClass(DB.ConnectorElement).ToElements():
        origem = conector.Origin
        saida.append({u"z_mm": round(para_mm(origem.Z), 2), u"x_mm": round(para_mm(origem.X), 2),
                      u"diametro_mm": round(2 * para_mm(conector.Radius), 2),
                      u"direcao_z": round(conector.Direction.Z, 3)})
    return sorted(saida, key=lambda c: c[u"z_mm"])


def v1_familia(app, template, pasta, resultado):
    registro = resultado[u"registro"]
    doc = app.NewFamilyDocument(template)
    try:
        t = _t(doc, u"S9 luva", registro)
        t.Start()
        gerenciador = doc.FamilyManager
        gerenciador.NewType(u"DN50")
        categoria = Category.GetCategory(doc, BuiltInCategory.OST_PipeFitting)
        doc.OwnerFamily.FamilyCategory = categoria
        doc.Regenerate()
        resultado[u"categoria"] = rfaspec.para_unicode(doc.OwnerFamily.FamilyCategory.Name)

        tipo_peca = doc.OwnerFamily.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
        if tipo_peca is None:
            resultado[u"part_type"] = u"parâmetro ausente"
        else:
            tipo_peca.Set(int(DB.PartType.Union))
            resultado[u"part_type"] = tipo_peca.AsInteger()

        dn = _param(doc, u"Diametro_Nominal")
        comprimento = _param(doc, u"Comprimento")
        raio = _param(doc, u"Raio_Externo")
        gerenciador.Set(dn, mm(50))
        gerenciador.Set(comprimento, mm(100))
        gerenciador.Set(raio, mm(31))

        plano = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero)
        laco = CurveArray()
        laco.Append(Arc.Create(plano, mm(31), 0.0, 3.141592653589793))
        laco.Append(Arc.Create(plano, mm(31), 3.141592653589793, 6.283185307179586))
        perfil = CurveArrArray()
        perfil.Append(laco)
        extrusao = doc.FamilyCreate.NewExtrusion(True, perfil, SketchPlane.Create(doc, plano), mm(100))
        doc.Regenerate()
        curva = list(list(extrusao.Sketch.Profile)[0])[0]
        cota = doc.FamilyCreate.NewRadialDimension(_vista(doc), curva.Reference, XYZ(mm(20), mm(20), 0))
        cota.FamilyLabel = raio
        gerenciador.AssociateElementParameterToFamilyParameter(
            extrusao.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM), comprimento)
        doc.Regenerate()

        baixo, cima = _faces_das_pontas(extrusao)
        conectores = []
        for face in (baixo, cima):
            conector = DB.ConnectorElement.CreatePipeConnector(doc, PipeSystemType.Fitting, face.Reference)
            gerenciador.AssociateElementParameterToFamilyParameter(
                conector.get_Parameter(BuiltInParameter.CONNECTOR_DIAMETER), dn)
            conectores.append(conector)
        conectores[0].SetLinkedConnectorElement(conectores[1])
        conectores[1].SetLinkedConnectorElement(conectores[0])
        doc.Regenerate()

        gerenciador.SetFormula(raio, u"Diametro_Nominal / 2 + 6")
        for nome in (u"DN40", u"DN75"):
            gerenciador.NewType(nome)
            gerenciador.Set(dn, mm(TIPOS[nome][0]))
            gerenciador.Set(comprimento, mm(TIPOS[nome][1]))
        if t.Commit() != TransactionStatus.Committed:
            resultado[u"erro"] = u"transação desfeita"
            return None

        tipos = []
        tudo = True
        t = _t(doc, u"medir", registro)
        t.Start()
        try:
            for tipo in list(gerenciador.Types):
                nome = rfaspec.para_unicode(tipo.Name)
                if nome not in TIPOS:
                    continue
                gerenciador.CurrentType = tipo
                doc.Regenerate()
                d, l = TIPOS[nome]
                medidos = _conectores_da_familia(doc)
                ok = (len(medidos) == 2 and all(abs(c[u"diametro_mm"] - d) < 0.1 for c in medidos)
                      and abs(medidos[0][u"z_mm"]) < 0.1 and abs(medidos[1][u"z_mm"] - l) < 0.1
                      and medidos[0][u"direcao_z"] == -1.0 and medidos[1][u"direcao_z"] == 1.0)
                tudo = tudo and ok
                tipos.append({u"tipo": nome, u"ok": ok, u"conectores": medidos})
        finally:
            t.RollBack()
        resultado[u"tipos"] = tipos
        resultado[u"veredito"] = u"SIM" if tudo and tipos else u"NAO"
        caminho = os.path.join(pasta, u"S9_luva.rfa")
        opcoes = SaveAsOptions()
        opcoes.OverwriteExistingFile = True
        doc.SaveAs(caminho, opcoes)
        return caminho
    finally:
        _fechar(doc, resultado)


def v2_projeto(app, familia, template_projeto, pasta, resultado):
    registro = resultado[u"registro"]
    doc = app.NewProjectDocument(template_projeto)
    try:
        t = _t(doc, u"S9 projeto", registro)
        t.Start()
        carregada = clr_ref()
        if not doc.LoadFamily(familia, carregada):
            resultado[u"erro"] = u"LoadFamily falhou"
            t.RollBack()
            return
        familia_obj = carregada.Value
        resultado[u"categoria_no_projeto"] = rfaspec.para_unicode(familia_obj.FamilyCategory.Name)
        simbolo = None
        for simbolo_id in familia_obj.GetFamilySymbolIds():
            candidato = doc.GetElement(simbolo_id)
            # IronPython não enxerga FamilySymbol.Name (AttributeError): pelo parâmetro.
            nome = candidato.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
            if rfaspec.para_unicode(nome) == u"DN50":
                simbolo = candidato
        simbolo.Activate()
        nivel = FilteredElementCollector(doc).OfClass(DB.Level).FirstElement()
        instancia = doc.Create.NewFamilyInstance(XYZ(0, 0, mm(1000)), simbolo, nivel,
                                                 DB.Structure.StructuralType.NonStructural)
        doc.Regenerate()
        conectores = [c for c in instancia.MEPModel.ConnectorManager.Connectors]
        resultado[u"conectores_na_instancia"] = [
            {u"diametro_mm": round(2 * para_mm(c.Radius), 2), u"z_mm": round(para_mm(c.Origin.Z), 1),
             u"dominio": rfaspec.para_unicode(str(c.Domain))} for c in conectores]

        tipo_tubo = FilteredElementCollector(doc).OfClass(DB.Plumbing.PipeType).FirstElement()
        sistema = FilteredElementCollector(doc).OfClass(DB.Plumbing.PipingSystemType).FirstElement()
        baixo = sorted(conectores, key=lambda c: c.Origin.Z)[0]
        tubo = DB.Plumbing.Pipe.Create(doc, sistema.Id, tipo_tubo.Id, nivel.Id,
                                       baixo.Origin - XYZ(0, 0, mm(800)), baixo.Origin)
        tubo.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(mm(50))
        doc.Regenerate()
        ponta = sorted([c for c in tubo.ConnectorManager.Connectors],
                       key=lambda c: c.Origin.DistanceTo(baixo.Origin))[0]
        ponta.ConnectTo(baixo)
        doc.Regenerate()
        resultado[u"tubo_diametro_mm"] = round(para_mm(tubo.Diameter), 2)
        resultado[u"conectado"] = bool(baixo.IsConnected)
        if t.Commit() != TransactionStatus.Committed:
            resultado[u"erro"] = u"transação desfeita"
            return
        resultado[u"veredito"] = u"SIM" if resultado[u"conectado"] else u"NAO"
        opcoes = SaveAsOptions()
        opcoes.OverwriteExistingFile = True
        doc.SaveAs(os.path.join(pasta, u"S9_projeto.rvt"), opcoes)
    finally:
        _fechar(doc, resultado)


def clr_ref():
    import clr
    return clr.Reference[DB.Family]()


def _fechar(doc, resultado):
    for aberto in reversed(_ABERTOS):
        try:
            if aberto.HasStarted() and not aberto.HasEnded():
                aberto.RollBack()
                resultado[u"registro"].append(u"transação aberta desfeita")
        except Exception:
            pass
    del _ABERTOS[:]
    doc.Close(False)


def principal():
    template = rfaspec.env("RFADG_TEMPLATE", obrigatorio=True)
    template_projeto = rfaspec.env("RFADG_TEMPLATE_PROJETO", obrigatorio=True)
    pasta = rfaspec.env("RFADG_G0_SAIDA", obrigatorio=True)
    if not os.path.isdir(pasta):
        os.makedirs(pasta)
    app = __revit__.Application  # noqa: F821
    resultados = []
    familia = None
    r1 = {u"sonda": u"S9_V1_familia_luva", u"registro": [], u"veredito": u"ERRO"}
    try:
        familia = v1_familia(app, template, pasta, r1)
    except Exception as erro:
        r1[u"erro"] = _texto(erro)[:300]
        r1[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-1200:]
    resultados.append(r1)
    r2 = {u"sonda": u"S9_V2_projeto_tubo", u"registro": [], u"veredito": u"ERRO"}
    if familia:
        try:
            v2_projeto(app, familia, template_projeto, pasta, r2)
        except Exception as erro:
            r2[u"erro"] = _texto(erro)[:300]
            r2[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-1200:]
    else:
        r2[u"erro"] = u"V1 não gerou a família"
    resultados.append(r2)
    rfaspec.gravar_json(os.path.join(pasta, u"resultado_s9.json"),
                        {u"revit": rfaspec.para_unicode(app.VersionNumber), u"sondas": resultados})


principal()

# -*- coding: utf-8 -*-
u"""Uso real de uma família de conexão gerada (G5): carrega num projeto de
hidráulica, coloca uma instância do tipo pedido e liga um tubo em CADA conector.

    RFADG_ENTRADA=<familia.rfa> RFADG_TIPO=DN100 RFADG_TEMPLATE_PROJETO=<.rte>
    RFADG_RELATORIO=<saida.json>
"""

import os
import sys
import traceback

_RAIZ = os.environ.get("RFADG_ROOT")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

import clr  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402
from Autodesk.Revit.DB import (  # noqa: E402
    BuiltInParameter, FailureProcessingResult, FailureSeverity, FilteredElementCollector,
    IFailuresPreprocessor, Transaction, TransactionStatus, XYZ,
)

mm = rfaspec.mm_para_interno


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


def principal():
    familia = rfaspec.env("RFADG_ENTRADA", obrigatorio=True)
    nome_tipo = rfaspec.env("RFADG_TIPO", obrigatorio=True)
    saida = rfaspec.env("RFADG_RELATORIO", obrigatorio=True)
    resultado = {u"familia": familia, u"tipo": nome_tipo, u"registro": [], u"aprovado": False}
    doc = __revit__.Application.NewProjectDocument(rfaspec.env("RFADG_TEMPLATE_PROJETO", obrigatorio=True))  # noqa: F821
    t = Transaction(doc, u"teste de conexão")
    opcoes = t.GetFailureHandlingOptions()
    opcoes.SetFailuresPreprocessor(_Pre(resultado[u"registro"]))
    t.SetFailureHandlingOptions(opcoes)
    try:
        t.Start()
        carregada = clr.Reference[DB.Family]()
        doc.LoadFamily(familia, carregada)
        simbolo = None
        for simbolo_id in carregada.Value.GetFamilySymbolIds():
            candidato = doc.GetElement(simbolo_id)
            if candidato.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == nome_tipo:
                simbolo = candidato
        simbolo.Activate()
        resultado[u"categoria"] = rfaspec.para_unicode(carregada.Value.FamilyCategory.Name)
        nivel = FilteredElementCollector(doc).OfClass(DB.Level).FirstElement()
        instancia = doc.Create.NewFamilyInstance(XYZ(0, 0, mm(1000)), simbolo, nivel,
                                                 DB.Structure.StructuralType.NonStructural)
        doc.Regenerate()
        tipo_tubo = FilteredElementCollector(doc).OfClass(DB.Plumbing.PipeType).FirstElement()
        sistema = FilteredElementCollector(doc).OfClass(DB.Plumbing.PipingSystemType).FirstElement()
        ligacoes = []
        for conector in instancia.MEPModel.ConnectorManager.Connectors:
            fim = conector.Origin + conector.CoordinateSystem.BasisZ.Multiply(mm(600))
            tubo = DB.Plumbing.Pipe.Create(doc, sistema.Id, tipo_tubo.Id, nivel.Id, conector.Origin, fim)
            tubo.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(conector.Radius * 2)
            doc.Regenerate()
            ponta = sorted([c for c in tubo.ConnectorManager.Connectors],
                           key=lambda c: c.Origin.DistanceTo(conector.Origin))[0]
            ponta.ConnectTo(conector)
            doc.Regenerate()
            ligacoes.append({u"diametro_conector_mm": round(rfaspec.interno_para_mm(2 * conector.Radius), 1),
                             u"diametro_tubo_mm": round(rfaspec.interno_para_mm(tubo.Diameter), 1),
                             u"conectado": bool(conector.IsConnected)})
        resultado[u"ligacoes"] = ligacoes
        status = t.Commit()
        resultado[u"aprovado"] = status == TransactionStatus.Committed and bool(ligacoes) and all(
            l[u"conectado"] and abs(l[u"diametro_conector_mm"] - l[u"diametro_tubo_mm"]) < 0.5 for l in ligacoes)
        caminho = os.path.splitext(saida)[0] + u".rvt"
        opcoes_salvar = DB.SaveAsOptions()
        opcoes_salvar.OverwriteExistingFile = True
        doc.SaveAs(caminho, opcoes_salvar)
    except Exception as erro:
        resultado[u"erro"] = rfaspec.para_unicode(unicode(erro))[:300]  # noqa: F821
        resultado[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-1000:]
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
    finally:
        doc.Close(False)
    rfaspec.gravar_json(saida, resultado)


principal()

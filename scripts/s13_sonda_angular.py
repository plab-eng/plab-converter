# -*- coding: utf-8 -*-
u"""Sonda S13 -- cota ANGULAR rotulada no esboco, fora do modo de esboco.

Extrusao triangular na planta: lado A no eixo X (alinhado ao Center Front/Back,
ponta em x=0 travada no Center Left/Right), lado B saindo da origem. Cota
angular entre A e B rotulada "Angulo" (NewAngularDimension com arco centrado no
cruzamento, como o construtor faz). Flexiona 30/45/60 graus e mede o angulo real
entre as curvas do esboco depois do Regenerate.
"""
import math
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402

mm = rfaspec.mm_para_interno


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
    return transacao


def _plano(doc, normal):
    for plano in DB.FilteredElementCollector(doc).OfClass(DB.ReferencePlane).ToElements():
        if abs(abs(plano.Normal.DotProduct(normal)) - 1) < 1e-6 and abs(plano.BubbleEnd.DotProduct(normal)) < 1e-6:
            return plano
    return None


def _angulo_real(extrusao):
    curvas = list(list(extrusao.Sketch.Profile)[0])
    eixo = [c for c in curvas if abs(c.GetEndPoint(0).Y) < 1e-6 and abs(c.GetEndPoint(1).Y) < 1e-6][0]
    outras = [c for c in curvas if c is not eixo and
              (c.GetEndPoint(0).GetLength() < 1e-6 or c.GetEndPoint(1).GetLength() < 1e-6)]
    b = outras[0]
    ponta = b.GetEndPoint(1) if b.GetEndPoint(0).GetLength() < 1e-6 else b.GetEndPoint(0)
    return math.degrees(math.atan2(ponta.Y, ponta.X))


def principal():
    app = __revit__.Application  # noqa: F821
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"registro": []}
    registro = saida[u"registro"]
    doc = app.NewFamilyDocument(rfaspec.env("RFADG_TEMPLATE", obrigatorio=True))
    try:
        t = _t(doc, u"S13", registro)
        t.Start()
        g = doc.FamilyManager
        g.NewType(u"T")
        angulo = g.AddParameter(u"Angulo", DB.GroupTypeId.Geometry, DB.SpecTypeId.Angle, False)
        g.Set(angulo, math.radians(45))
        planta = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
                  if not v.IsTemplate and v.ViewType == DB.ViewType.FloorPlan][0]
        L = mm(300)
        a = math.radians(45)
        pts = [DB.XYZ(0, 0, 0), DB.XYZ(L, 0, 0), DB.XYZ(L * math.cos(a), L * math.sin(a), 0)]
        laco = DB.CurveArray()
        for i in range(3):
            laco.Append(DB.Line.CreateBound(pts[i], pts[(i + 1) % 3]))
        perfil = DB.CurveArrArray()
        perfil.Append(laco)
        esboco = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ.Zero))
        extrusao = doc.FamilyCreate.NewExtrusion(True, perfil, esboco, mm(50))
        doc.Regenerate()
        curvas = list(list(extrusao.Sketch.Profile)[0])
        eixo = [c for c in curvas if abs(c.GetEndPoint(0).Y) < 1e-6 and abs(c.GetEndPoint(1).Y) < 1e-6][0]
        lado_b = [c for c in curvas if c is not eixo and
                  (c.GetEndPoint(0).GetLength() < 1e-6 or c.GetEndPoint(1).GetLength() < 1e-6)][0]
        doc.FamilyCreate.NewAlignment(planta, _plano(doc, DB.XYZ.BasisY).GetReference(), eixo.Reference)
        ponta = 0 if eixo.GetEndPoint(0).GetLength() < 1e-6 else 1
        doc.FamilyCreate.NewAlignment(planta, _plano(doc, DB.XYZ.BasisX).GetReference(),
                                      eixo.GetEndPointReference(ponta))
        r = mm(40)
        bis = DB.XYZ(math.cos(a / 2), math.sin(a / 2), 0)
        arco = DB.Arc.Create(DB.XYZ(r, 0, 0), DB.XYZ(r * math.cos(a), r * math.sin(a), 0), bis.Multiply(r))
        cota = doc.FamilyCreate.NewAngularDimension(planta, arco, eixo.Reference, lado_b.Reference)
        cota.FamilyLabel = angulo
        doc.Regenerate()
        if t.Commit() != DB.TransactionStatus.Committed:
            saida[u"erro"] = u"transacao desfeita"
        else:
            medidas = []
            for graus in (30.0, 45.0, 60.0):
                t = _t(doc, u"flex", registro)
                t.Start()
                try:
                    g.Set(angulo, math.radians(graus))
                    doc.Regenerate()
                    medidas.append({u"pedido": graus, u"real": round(_angulo_real(extrusao), 3)})
                except Exception as erro:
                    medidas.append({u"pedido": graus, u"erro": rfaspec.para_unicode(unicode(erro))[:120]})  # noqa: F821
                finally:
                    t.RollBack()
            saida[u"flex"] = medidas
            saida[u"veredito"] = u"SIM" if all(abs(m.get(u"real", 999) - m[u"pedido"]) < 0.01 for m in medidas) \
                else u"NAO"
    except Exception as erro:
        saida[u"erro"] = rfaspec.para_unicode(unicode(erro))[:200]  # noqa: F821
        saida[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-600:]
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

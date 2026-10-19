# -*- coding: utf-8 -*-
u"""Sonda S18 -- cotas automaticas de esboco x cota rotulada.

A  ha cota rotulada (plano PX rotulado) antes da extrusao hexagonal: conta as
   cotas automaticas do hexagono apos Regenerate.
B  idem A, e depois trava (alinhamento) duas linhas do hexagono nos planos
   centrais: as automaticas somem ou ficam?
C  extrusao criada ANTES de qualquer rotulo, rotulo criado depois: conta.
D  hexagono criado com os rotulos temporariamente removidos (FamilyLabel =
   None), rotulos recolocados depois: conta, e flexiona PX para ver se o
   hexagono se move.
"""
import math
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402

mm = rfaspec.mm_para_interno


def _contar(doc, extrusao):
    ids = set(rfaspec.id_inteiro(i) for i in extrusao.Sketch.GetAllElements())
    return [c for c in DB.FilteredElementCollector(doc).OfClass(DB.Dimension).ToElements()
            if any(rfaspec.id_inteiro(r.ElementId) in ids for r in c.References)]


def _plano(doc, normal):
    for p in DB.FilteredElementCollector(doc).OfClass(DB.ReferencePlane).ToElements():
        if abs(abs(p.Normal.DotProduct(normal)) - 1) < 1e-6 and abs(p.BubbleEnd.DotProduct(normal)) < 1e-6:
            return p
    return None


def _rotulo(doc, planta, g):
    p = g.AddParameter(u"L", DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)
    px = doc.FamilyCreate.NewReferencePlane(DB.XYZ(mm(30), 0, 0), DB.XYZ(mm(30), mm(10), 0), DB.XYZ.BasisZ, planta)
    doc.Regenerate()
    ra = DB.ReferenceArray()
    ra.Append(_plano(doc, DB.XYZ.BasisX).GetReference())
    ra.Append(px.GetReference())
    cota = doc.FamilyCreate.NewDimension(planta, DB.Line.CreateBound(DB.XYZ(0, mm(-60), 0), DB.XYZ(mm(1), mm(-60), 0)),
                                         ra)
    g.Set(p, mm(30))
    cota.FamilyLabel = p
    doc.Regenerate()
    return p, cota


def _hexagono(doc):
    laco = DB.CurveArray()
    pts = [DB.XYZ(mm(25 * math.cos(math.radians(30 + 60 * i))), mm(25 * math.sin(math.radians(30 + 60 * i))), 0)
           for i in range(6)]
    for i in range(6):
        laco.Append(DB.Line.CreateBound(pts[i], pts[(i + 1) % 6]))
    perfil = DB.CurveArrArray()
    perfil.Append(laco)
    esboco = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ.Zero))
    e = doc.FamilyCreate.NewExtrusion(True, perfil, esboco, mm(40))
    doc.Regenerate()
    return e


def _largura(e):
    caixa = e.get_BoundingBox(None)
    return round(rfaspec.interno_para_mm(caixa.Max.X - caixa.Min.X), 2)


def variante(app, template, nome, saida):
    r = {u"variante": nome}
    saida.append(r)
    doc = app.NewFamilyDocument(template)
    t = DB.Transaction(doc, nome)
    t.Start()
    try:
        g = doc.FamilyManager
        g.NewType(u"T")
        planta = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
                  if not v.IsTemplate and v.ViewType == DB.ViewType.FloorPlan][0]
        if nome in (u"A", u"B"):
            p, cota = _rotulo(doc, planta, g)
            e = _hexagono(doc)
            r[u"automaticas"] = len(_contar(doc, e))
            if nome == u"B":
                curvas = list(list(e.Sketch.Profile)[0])
                verticais = [c for c in curvas if abs(c.Direction.X) < 1e-6]
                doc.FamilyCreate.NewAlignment(planta, _plano(doc, DB.XYZ.BasisY).GetReference(),
                                              verticais[0].GetEndPointReference(0)) if False else None
                # trava: linha vertical da direita a uma distancia fixa do centro (cota travada)
                ra = DB.ReferenceArray()
                ra.Append(_plano(doc, DB.XYZ.BasisX).GetReference())
                ra.Append(verticais[0].Reference)
                c2 = doc.FamilyCreate.NewDimension(planta, DB.Line.CreateBound(DB.XYZ(0, mm(40), 0),
                                                                                DB.XYZ(mm(1), mm(40), 0)), ra)
                c2.IsLocked = True
                doc.Regenerate()
                r[u"automaticas_apos_trava"] = len(_contar(doc, e))
        elif nome == u"C":
            e = _hexagono(doc)
            r[u"antes_do_rotulo"] = len(_contar(doc, e))
            p, cota = _rotulo(doc, planta, g)
            r[u"automaticas"] = len(_contar(doc, e))
        elif nome == u"E":
            p, cota = _rotulo(doc, planta, g)
            e = _hexagono(doc)
            r[u"automaticas_antes"] = len(_contar(doc, e))
            centro_x = _plano(doc, DB.XYZ.BasisX)
            centro_y = _plano(doc, DB.XYZ.BasisY)
            criadas, erros = 0, []
            vistos = []
            for curva in list(list(e.Sketch.Profile)[0]):
                for ponta in (0, 1):
                    ponto = curva.GetEndPoint(ponta)
                    if any(ponto.DistanceTo(v) < 1e-6 for v in vistos):
                        continue
                    vistos.append(ponto)
                    for plano, eixo in ((centro_x, DB.XYZ.BasisX), (centro_y, DB.XYZ.BasisY)):
                        distancia = (ponto - plano.BubbleEnd).DotProduct(plano.Normal)
                        try:
                            if abs(distancia) < 1e-6:
                                doc.FamilyCreate.NewAlignment(planta, plano.GetReference(),
                                                              curva.GetEndPointReference(ponta))
                            else:
                                ra = DB.ReferenceArray()
                                ra.Append(plano.GetReference())
                                ra.Append(curva.GetEndPointReference(ponta))
                                c = doc.FamilyCreate.NewDimension(planta, DB.Line.CreateBound(ponto, ponto + eixo), ra)
                                c.IsLocked = True
                            criadas += 1
                        except Exception as erro:
                            erros.append(rfaspec.para_unicode(unicode(erro))[:60])  # noqa: F821
            doc.Regenerate()
            r[u"travas_criadas"] = criadas
            r[u"erros"] = erros[:3]
            r[u"automaticas"] = len(_contar(doc, e)) - criadas
        elif nome == u"D":
            p, cota = _rotulo(doc, planta, g)
            cota.FamilyLabel = None
            doc.Regenerate()
            e = _hexagono(doc)
            r[u"sem_rotulo"] = len(_contar(doc, e))
            cota.FamilyLabel = p
            doc.Regenerate()
            r[u"automaticas"] = len(_contar(doc, e))
        largura = _largura(e)
        g.Set(p, mm(60))
        doc.Regenerate()
        r[u"hexagono_largura_L30_L60"] = [largura, _largura(e)]
    except Exception:
        r[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-500:]
    finally:
        t.RollBack()
        doc.Close(False)


def principal():
    app = __revit__.Application  # noqa: F821
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"variantes": []}
    for nome in (u"E",):
        variante(app, rfaspec.env("RFADG_TEMPLATE", obrigatorio=True), nome, saida[u"variantes"])
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

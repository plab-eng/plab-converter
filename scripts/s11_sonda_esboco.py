# -*- coding: utf-8 -*-
u"""Sonda S11 -- travas de linha de esboco fora do modo de esboco.

D   diagnostico da Solaris (RFADG_ENTRADA): para cada revolucao, o plano do
    esboco e cada cota/alinhamento que toca uma curva do esboco: forma, rotulo,
    trava, vista, e a distancia da curva ao plano da outra referencia.
V1  revolucao (eixo X, esboco no plano Front) com a linha de cima ALINHADA a
    um plano horizontal rotulado (Raio) e a da direita a um plano vertical
    (Comprimento), na elevacao Front. Flexiona e mede o volume.
V2  idem, alinhamento criado na PLANTA (vista errada).
V3  sem alinhamento: cota linear Ref. Level -> linha de cima ROTULADA Raio.
V4  idem V1, mas o plano ja foi movido (Raio != desenho) antes do alinhamento:
    reproduz "not geometrically aligned"?

Toda transacao com preprocessador que desfaz diante de erro.
"""
import math
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402

mm = rfaspec.mm_para_interno
para_mm = rfaspec.interno_para_mm
_ABERTOS = []


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


def _v(xyz):
    return [round(xyz.X, 4), round(xyz.Y, 4), round(xyz.Z, 4)]


def _p(xyz):
    return [round(para_mm(xyz.X), 2), round(para_mm(xyz.Y), 2), round(para_mm(xyz.Z), 2)]


# ---------------------------------------------------------------- diagnostico

def _elementos_do_esboco(doc, esboco):
    ids = set()
    try:
        for i in esboco.GetAllElements():
            ids.add(rfaspec.id_inteiro(i))
    except Exception:
        pass
    for laco in esboco.Profile:
        for curva in laco:
            if curva.Reference is not None:
                ids.add(rfaspec.id_inteiro(curva.Reference.ElementId))
    return ids


def _descrever_referencia(doc, referencia, ids_esboco):
    elemento = doc.GetElement(referencia.ElementId)
    if elemento is None:
        return {u"classe": u"nulo"}
    saida = {u"classe": type(elemento).__name__, u"no_esboco": rfaspec.id_inteiro(elemento.Id) in ids_esboco}
    try:
        saida[u"estavel"] = rfaspec.para_unicode(referencia.ConvertToStableRepresentation(doc)).split(u":", 1)[-1]
        saida[u"tipo_ref"] = str(referencia.ElementReferenceType)
    except Exception as erro:
        saida[u"estavel"] = _texto(erro)
    if isinstance(elemento, DB.ReferencePlane):
        saida[u"plano"] = rfaspec.para_unicode(elemento.Name)
        saida[u"normal"] = _v(elemento.Normal)
        saida[u"ponto"] = _p(elemento.BubbleEnd)
    elif isinstance(elemento, DB.CurveElement):
        curva = elemento.GeometryCurve
        saida[u"curva"] = type(curva).__name__
        saida[u"ini"] = _p(curva.GetEndPoint(0))
        saida[u"fim"] = _p(curva.GetEndPoint(1))
    elif isinstance(elemento, DB.Level):
        saida[u"nivel"] = rfaspec.para_unicode(elemento.Name)
    return saida


def diagnostico(app, caminho, saida):
    registro = saida.setdefault(u"registro", [])
    doc = app.OpenDocumentFile(caminho)
    try:
        revolucoes = list(DB.FilteredElementCollector(doc).OfClass(DB.Revolution).ToElements()) + \
            list(DB.FilteredElementCollector(doc).OfClass(DB.Extrusion).ToElements())
        cotas = list(DB.FilteredElementCollector(doc).OfClass(DB.Dimension).ToElements())
        id_restricoes = int(DB.BuiltInCategory.OST_Constraints)
        lista = []
        for revolucao in revolucoes:
            esboco = revolucao.Sketch
            plano = esboco.SketchPlane.GetPlane()
            ids = _elementos_do_esboco(doc, esboco)
            item = {u"id": rfaspec.id_inteiro(revolucao.Id), u"normal_do_esboco": _v(plano.Normal),
                    u"origem_do_esboco": _p(plano.Origin), u"n_curvas": len(ids), u"travas": []}
            for cota in cotas:
                refs = list(cota.References)
                if not any(rfaspec.id_inteiro(r.ElementId) in ids for r in refs):
                    continue
                try:
                    rotulo = cota.FamilyLabel
                    rotulo = rfaspec.para_unicode(rotulo.Definition.Name) if rotulo is not None else None
                except Exception:
                    rotulo = u"(ilegivel)"
                try:
                    travada = bool(cota.IsLocked)
                except Exception:
                    travada = None
                vista = cota.View
                item[u"travas"].append({
                    u"tipo": u"alinhamento" if cota.Category is not None and
                    rfaspec.id_inteiro(cota.Category.Id) == id_restricoes else u"cota",
                    u"forma": str(cota.DimensionShape), u"rotulo": rotulo, u"travada": travada,
                    u"valor_mm": round(para_mm(cota.Value), 2) if cota.Value is not None else None,
                    u"vista": (str(vista.ViewType) + u" " + rfaspec.para_unicode(vista.Name)) if vista else None,
                    u"vista_dir": _v(vista.ViewDirection) if vista else None,
                    u"dono_e_o_esboco": rfaspec.id_inteiro(cota.OwnerViewId) if cota.OwnerViewId else None,
                    u"refs": [_descrever_referencia(doc, r, ids) for r in refs]})
            lista.append(item)
        saida[u"revolucoes"] = lista
    except Exception:
        saida[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-1200:]
    finally:
        _fechar(doc, registro)


# ---------------------------------------------------------------- sonda

def _vista(doc, tipo, direcao=None):
    for vista in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements():
        if vista.IsTemplate or vista.ViewType != tipo:
            continue
        if direcao is None or abs(abs(vista.ViewDirection.DotProduct(direcao)) - 1) < 1e-6:
            return vista
    return None


def _plano_existente(doc, normal):
    for plano in DB.FilteredElementCollector(doc).OfClass(DB.ReferencePlane).ToElements():
        if abs(abs(plano.Normal.DotProduct(normal)) - 1) < 1e-6 and \
                abs(plano.BubbleEnd.DotProduct(normal)) < 1e-6:
            return plano
    return None


def _volume(doc):
    total = 0.0
    opcoes = DB.Options()
    for forma in DB.FilteredElementCollector(doc).OfClass(DB.GenericForm).ToElements():
        for objeto in forma.get_Geometry(opcoes):
            if isinstance(objeto, DB.Solid):
                total += objeto.Volume
    return rfaspec.interno_para_mm3(total)


def _montar(doc, registro, raio_desenho, raio_param):
    u"""Planos rotulados + revolucao desenhada com raio_desenho. Devolve contexto."""
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"T")
    p_raio = gerenciador.AddParameter(u"Raio", DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)
    p_comp = gerenciador.AddParameter(u"Comprimento", DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)
    frente = _vista(doc, DB.ViewType.Elevation, DB.XYZ.BasisY)
    planta = _vista(doc, DB.ViewType.FloorPlan)
    nivel = DB.FilteredElementCollector(doc).OfClass(DB.Level).FirstElement()
    centro_lr = _plano_existente(doc, DB.XYZ.BasisX)
    L = 800.0
    # plano horizontal (normal Z) visto na Front; plano vertical (normal X) na planta
    pz = doc.FamilyCreate.NewReferencePlane(DB.XYZ(0, 0, mm(raio_desenho)), DB.XYZ(mm(L), 0, mm(raio_desenho)),
                                            DB.XYZ(0, 1, 0), frente)
    pz.Name = u"PZ"
    px = doc.FamilyCreate.NewReferencePlane(DB.XYZ(mm(L), 0, 0), DB.XYZ(mm(L), mm(100), 0),
                                            DB.XYZ(0, 0, 1), planta)
    px.Name = u"PX"
    doc.Regenerate()
    ra = DB.ReferenceArray()
    ra.Append(nivel.GetPlaneReference())
    ra.Append(pz.GetReference())
    cota_r = doc.FamilyCreate.NewDimension(frente, DB.Line.CreateBound(DB.XYZ(mm(-100), 0, 0),
                                                                        DB.XYZ(mm(-100), 0, mm(10))), ra)
    cota_r.FamilyLabel = p_raio
    rb = DB.ReferenceArray()
    rb.Append(centro_lr.GetReference())
    rb.Append(px.GetReference())
    cota_c = doc.FamilyCreate.NewDimension(planta, DB.Line.CreateBound(DB.XYZ(0, mm(-200), 0),
                                                                        DB.XYZ(mm(10), mm(-200), 0)), rb)
    cota_c.FamilyLabel = p_comp
    gerenciador.Set(p_raio, mm(raio_param))
    gerenciador.Set(p_comp, mm(L))
    doc.Regenerate()
    R = raio_desenho
    pts = [DB.XYZ(0, 0, 0), DB.XYZ(mm(L), 0, 0), DB.XYZ(mm(L), 0, mm(R)), DB.XYZ(0, 0, mm(R))]
    laco = DB.CurveArray()
    for i in range(4):
        laco.Append(DB.Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    perfil = DB.CurveArrArray()
    perfil.Append(laco)
    plano_esboco = DB.SketchPlane.Create(doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisY, DB.XYZ.Zero))
    eixo = doc.FamilyCreate.NewModelCurve(DB.Line.CreateBound(DB.XYZ(0, 0, 0), DB.XYZ(mm(L), 0, 0)), plano_esboco)
    revolucao = doc.FamilyCreate.NewRevolution(True, perfil, plano_esboco, eixo.GeometryCurve, 0.0, 2 * math.pi)
    doc.Regenerate()
    curvas = list(list(revolucao.Sketch.Profile)[0])
    cima = [c for c in curvas if abs(c.GetEndPoint(0).Z - mm(R)) < 1e-6 and abs(c.GetEndPoint(1).Z - mm(R)) < 1e-6][0]
    direita = [c for c in curvas if abs(c.GetEndPoint(0).X - mm(L)) < 1e-6 and abs(c.GetEndPoint(1).X - mm(L)) < 1e-6][0]
    registro.append(u"distancia cima-PZ antes: {0:.3f} mm".format(
        para_mm(abs(cima.GetEndPoint(0).Z - pz.BubbleEnd.Z))))
    return {u"g": gerenciador, u"p_raio": p_raio, u"p_comp": p_comp, u"frente": frente, u"planta": planta,
            u"nivel": nivel, u"pz": pz, u"px": px, u"rev": revolucao, u"cima": cima, u"direita": direita, u"L": L}


def _flexionar(doc, ctx, registro):
    medidas = []
    g = ctx[u"g"]
    for raio, comp in ((300.0, 800.0), (500.0, 800.0), (200.0, 1200.0)):
        t = _t(doc, u"flex", registro)
        t.Start()
        try:
            g.Set(ctx[u"p_raio"], mm(raio))
            g.Set(ctx[u"p_comp"], mm(comp))
            doc.Regenerate()
            esperado = math.pi * raio * raio * comp
            obtido = _volume(doc)
            medidas.append({u"raio": raio, u"comp": comp, u"desvio_vol_pct":
                            round(100.0 * (obtido - esperado) / esperado, 3)})
        except Exception as erro:
            medidas.append({u"raio": raio, u"comp": comp, u"erro": _texto(erro)})
        finally:
            t.RollBack()
    ok = all(u"desvio_vol_pct" in m and abs(m[u"desvio_vol_pct"]) < 0.5 for m in medidas)
    return medidas, ok


def variante(app, template, nome, saida):
    resultado = {u"variante": nome, u"registro": [], u"veredito": u"ERRO"}
    saida.append(resultado)
    registro = resultado[u"registro"]
    doc = app.NewFamilyDocument(template)
    try:
        t = _t(doc, nome, registro)
        t.Start()
        raio_param = 400.0 if nome == u"V4" else 300.0
        ctx = _montar(doc, registro, 300.0, raio_param)
        if nome in (u"V1", u"V4"):
            doc.FamilyCreate.NewAlignment(ctx[u"frente"], ctx[u"pz"].GetReference(), ctx[u"cima"].Reference)
            doc.FamilyCreate.NewAlignment(ctx[u"frente"], ctx[u"px"].GetReference(), ctx[u"direita"].Reference)
        elif nome == u"V2":
            doc.FamilyCreate.NewAlignment(ctx[u"planta"], ctx[u"pz"].GetReference(), ctx[u"cima"].Reference)
            doc.FamilyCreate.NewAlignment(ctx[u"planta"], ctx[u"px"].GetReference(), ctx[u"direita"].Reference)
        elif nome == u"V5":
            # plano vertical PX (x=L) travado na PONTA da linha de cima (fim em x=L)
            cima = ctx[u"cima"]
            indice = 0 if abs(cima.GetEndPoint(0).X - mm(ctx[u"L"])) < 1e-6 else 1
            ponta = cima.GetEndPointReference(indice)
            registro.append(u"ponta estavel: " + rfaspec.para_unicode(ponta.ConvertToStableRepresentation(doc)))
            registro.append(u"curva estavel: " + rfaspec.para_unicode(cima.Reference.ConvertToStableRepresentation(doc)))
            doc.FamilyCreate.NewAlignment(ctx[u"frente"], ctx[u"pz"].GetReference(), cima.Reference)
            doc.FamilyCreate.NewAlignment(ctx[u"frente"], ctx[u"px"].GetReference(), ponta)
        elif nome == u"V3":
            ra = DB.ReferenceArray()
            ra.Append(ctx[u"nivel"].GetPlaneReference())
            ra.Append(ctx[u"cima"].Reference)
            cota = doc.FamilyCreate.NewDimension(ctx[u"frente"], DB.Line.CreateBound(
                DB.XYZ(mm(400), 0, 0), DB.XYZ(mm(400), 0, mm(10))), ra)
            cota.FamilyLabel = ctx[u"p_raio"]
            doc.FamilyCreate.NewAlignment(ctx[u"frente"], ctx[u"px"].GetReference(), ctx[u"direita"].Reference)
        doc.Regenerate()
        if t.Commit() != DB.TransactionStatus.Committed:
            resultado[u"erro"] = u"transacao desfeita"
            return
        medidas, ok = _flexionar(doc, ctx, registro)
        resultado[u"flex"] = medidas
        resultado[u"veredito"] = u"SIM" if ok else u"NAO"
    except Exception as erro:
        resultado[u"erro"] = _texto(erro)
        resultado[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-600:]
    finally:
        _fechar(doc, registro)


def principal():
    app = __revit__.Application  # noqa: F821
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber)}
    entrada = rfaspec.env("RFADG_ENTRADA")
    if entrada:
        saida[u"diagnostico"] = {}
        try:
            diagnostico(app, entrada, saida[u"diagnostico"])
        except Exception:
            saida[u"diagnostico"][u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-800:]
    template = rfaspec.env("RFADG_TEMPLATE", obrigatorio=True)
    saida[u"variantes"] = []
    for nome in [n for n in rfaspec.env("RFADG_S11_VARIANTES", u"V1,V2,V3,V4,V5").split(u",") if n.strip() and n != u"-"]:
        variante(app, template, nome, saida[u"variantes"])
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

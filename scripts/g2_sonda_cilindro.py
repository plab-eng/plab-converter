# -*- coding: utf-8 -*-
u"""Sonda S8 — cilindro FORA do centro (docs/G2-resultado.md, pendências).

O raio já é paramétrico pela cota radial na curva do esboço (S2-A2). Falta
travar a POSIÇÃO do centro num plano. Duas variantes, cada uma numa família
própria:

  V1  cota entre o plano Center (Left/Right) e o centro do arco
      (ModelArc.CenterPointReference), criada FORA do modo de esboço;
  V2  a mesma cota criada DENTRO de um SketchEditScope (Revit 2022+).

Mede por tipo o mínimo e a extensão em X pela malha: se o centro acompanha
`Pos_X`, a sonda passa.

    pyrevit run scripts/g2_sonda_cilindro.py <portadora.rfa> --revit=2024
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
    Arc, CurveArray, CurveArrArray, FailureProcessingResult, FailureSeverity,
    FilteredElementCollector, GenericForm, IFailuresPreprocessor, Line, Plane,
    ReferenceArray, ReferencePlane, SaveAsOptions, SketchPlane, Transaction,
    TransactionStatus, View, ViewType, XYZ,
)

mm = rfaspec.mm_para_interno
log = rfaspec.log
POSICOES = {u"X200": 200.0, u"X350": 350.0, u"X600": 600.0}
RAIO = 100.0
ALTURA = 400.0


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


_ABERTOS = []


def _transacao(doc, nome, registro):
    t = Transaction(doc, nome)
    _ABERTOS.append(t)
    opcoes = t.GetFailureHandlingOptions()
    opcoes.SetFailuresPreprocessor(_Pre(registro))
    opcoes.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opcoes)
    return t


def _texto(erro):
    return rfaspec.para_unicode(unicode(erro))  # noqa: F821


def _vista(doc):
    for vista in FilteredElementCollector(doc).OfClass(View).ToElements():
        if not vista.IsTemplate and vista.ViewType == ViewType.FloorPlan:
            return vista


def _centro_lr(doc):
    for plano in FilteredElementCollector(doc).OfClass(ReferencePlane).ToElements():
        if abs(abs(plano.Normal.X) - 1.0) < 1e-9 and abs(plano.BubbleEnd.X) < 1e-9:
            return plano


def _parametro(doc, nome):
    return doc.FamilyManager.AddParameter(nome, DB.GroupTypeId.Geometry, DB.SpecTypeId.Length, False)


def _cilindro(doc, x):
    plano = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(mm(x), 0, 0))
    laco = CurveArray()
    laco.Append(Arc.Create(plano, mm(RAIO), 0.0, 3.141592653589793))
    laco.Append(Arc.Create(plano, mm(RAIO), 3.141592653589793, 6.283185307179586))
    perfil = CurveArrArray()
    perfil.Append(laco)
    esboco = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero))
    return doc.FamilyCreate.NewExtrusion(True, perfil, esboco, mm(ALTURA))


def _arco_do_esboco(doc, extrusao):
    u"""Primeiro ModelArc do esboço (o elemento por trás da curva do perfil)."""
    for laco in extrusao.Sketch.Profile:
        for curva in laco:
            if curva.Reference is not None:
                elemento = doc.GetElement(curva.Reference.ElementId)
                if elemento is not None and hasattr(elemento, "CenterPointReference"):
                    return elemento, curva
    return None, None


def _cota_de_posicao(doc, vista, centro, arco, pos):
    referencias = ReferenceArray()
    referencias.Append(centro.GetReference())
    referencias.Append(arco.CenterPointReference)
    linha = Line.CreateBound(XYZ(0, mm(-600), 0), XYZ(mm(300), mm(-600), 0))
    cota = doc.FamilyCreate.NewDimension(vista, linha, referencias)
    cota.FamilyLabel = pos
    return cota


def _medir(doc, registro):
    gerenciador = doc.FamilyManager
    tipos = [(rfaspec.para_unicode(t.Name), t) for t in gerenciador.Types if t.Name]
    medidas = {}
    t = _transacao(doc, u"medir", registro)
    t.Start()
    try:
        for nome, tipo in tipos:
            gerenciador.CurrentType = tipo
            doc.Regenerate()
            minimo = None
            maximo = None
            for forma in FilteredElementCollector(doc).OfClass(GenericForm).ToElements():
                encontrados, _ = rfaspec._solidos_da_forma(forma)
                for solido in encontrados:
                    for face in solido.Faces:
                        for ponto in face.Triangulate(1.0).Vertices:
                            minimo = ponto.X if minimo is None else min(minimo, ponto.X)
                            maximo = ponto.X if maximo is None else max(maximo, ponto.X)
            medidas[nome] = [rfaspec.interno_para_mm(minimo), rfaspec.interno_para_mm(maximo)]
    finally:
        t.RollBack()
    return medidas


def _avaliar(resultado, medidas):
    tudo = True
    tipos = []
    for nome, x in POSICOES.items():
        medido = medidas.get(nome)
        esperado = [x - RAIO, x + RAIO]
        ok = medido is not None and all(abs(a - b) < 0.5 for a, b in zip(medido, esperado))
        tudo = tudo and ok
        tipos.append({u"tipo": nome, u"ok": ok, u"esperado_x": esperado, u"medido_x": medido})
    resultado[u"tipos"] = tipos
    resultado[u"veredito"] = u"SIM" if tudo else u"NAO"


def _base(doc, registro):
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"X200")
    pos = _parametro(doc, u"Pos_X")
    raio = _parametro(doc, u"Raio")
    gerenciador.Set(pos, mm(200.0))
    gerenciador.Set(raio, mm(RAIO))
    vista = _vista(doc)
    centro = _centro_lr(doc)
    extrusao = _cilindro(doc, 200.0)
    doc.Regenerate()
    arco, curva = _arco_do_esboco(doc, extrusao)
    cota_raio = doc.FamilyCreate.NewRadialDimension(vista, curva.Reference, XYZ(mm(260), mm(60), 0))
    cota_raio.FamilyLabel = raio
    doc.Regenerate()
    return gerenciador, pos, vista, centro, extrusao, arco


def _tipos(gerenciador, pos):
    for nome in (u"X350", u"X600"):
        gerenciador.NewType(nome)
        gerenciador.Set(pos, mm(POSICOES[nome]))


def v1_fora_do_esboco(doc, resultado):
    registro = resultado[u"registro"]
    t = _transacao(doc, u"V1", registro)
    t.Start()
    gerenciador, pos, vista, centro, extrusao, arco = _base(doc, registro)
    _cota_de_posicao(doc, vista, centro, arco, pos)
    doc.Regenerate()
    _tipos(gerenciador, pos)
    if t.Commit() != TransactionStatus.Committed:
        resultado[u"erro"] = u"transação desfeita"
        return
    _avaliar(resultado, _medir(doc, registro))


def v2_sketch_edit_scope(doc, resultado):
    registro = resultado[u"registro"]
    escopo_cls = getattr(DB, "SketchEditScope", None)
    if escopo_cls is None:
        resultado[u"erro"] = u"SketchEditScope não existe nesta versão"
        return
    t = _transacao(doc, u"V2 base", registro)
    t.Start()
    gerenciador, pos, vista, centro, extrusao, arco = _base(doc, registro)
    if t.Commit() != TransactionStatus.Committed:
        resultado[u"erro"] = u"base desfeita"
        return

    escopo = escopo_cls(doc, u"posição do centro")
    _ABERTOS.append(escopo)
    escopo.Start(extrusao.Sketch.Id)
    t = _transacao(doc, u"V2 cota no esboço", registro)
    t.Start()
    _cota_de_posicao(doc, vista, centro, arco, pos)
    t.Commit()
    escopo.Commit(_Pre(registro))

    t = _transacao(doc, u"V2 tipos", registro)
    t.Start()
    _tipos(gerenciador, pos)
    if t.Commit() != TransactionStatus.Committed:
        resultado[u"erro"] = u"tipos desfeitos"
        return
    _avaliar(resultado, _medir(doc, registro))


def _ref_do_solido(extrusao, tipo):
    opcoes = DB.Options()
    opcoes.ComputeReferences = True
    for objeto in extrusao.get_Geometry(opcoes):
        if not isinstance(objeto, DB.Solid):
            continue
        if tipo == u"face":
            for face in objeto.Faces:
                if isinstance(face, DB.CylindricalFace):
                    return face.Reference
        else:
            for aresta in objeto.Edges:
                curva = aresta.AsCurve()
                if isinstance(curva, Arc) and abs(curva.Center.Z) < 1e-6:
                    return aresta.Reference
    return None


def _v_solido(tipo):
    def variante(doc, resultado):
        registro = resultado[u"registro"]
        t = _transacao(doc, u"V-" + tipo, registro)
        t.Start()
        gerenciador, pos, vista, centro, extrusao, arco = _base(doc, registro)
        referencias = ReferenceArray()
        referencias.Append(centro.GetReference())
        referencias.Append(_ref_do_solido(extrusao, tipo))
        linha = Line.CreateBound(XYZ(0, mm(-600), 0), XYZ(mm(300), mm(-600), 0))
        cota = doc.FamilyCreate.NewDimension(vista, linha, referencias)
        resultado[u"valor_da_cota_mm"] = rfaspec.interno_para_mm(cota.Value) if cota.Value is not None else None
        cota.FamilyLabel = pos
        doc.Regenerate()
        _tipos(gerenciador, pos)
        if t.Commit() != TransactionStatus.Committed:
            resultado[u"erro"] = u"transação desfeita"
            return
        _avaliar(resultado, _medir(doc, registro))
    return variante


# V5: centro em (-x, +y), raio variando; cotas Center -> face cilíndrica nos dois
# eixos, rotuladas com |c| + r (a cota mede até a tangente do lado de fora).
V5_TIPOS = {u"T1": (-300.0, 250.0, 100.0), u"T2": (-450.0, 400.0, 150.0), u"T3": (-200.0, 120.0, 60.0)}


def _centro_fb(doc):
    for plano in FilteredElementCollector(doc).OfClass(ReferencePlane).ToElements():
        if abs(abs(plano.Normal.Y) - 1.0) < 1e-9 and abs(plano.BubbleEnd.Y) < 1e-9:
            return plano


def v5_dois_eixos(doc, resultado, y_primeiro=False):
    registro = resultado[u"registro"]
    t = _transacao(doc, u"V5", registro)
    t.Start()
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"T1")
    tx, ty, raio = _parametro(doc, u"Tx"), _parametro(doc, u"Ty"), _parametro(doc, u"Raio")
    cx, cy, r = V5_TIPOS[u"T1"]
    gerenciador.Set(tx, mm(abs(cx) + r))
    gerenciador.Set(ty, mm(abs(cy) + r))
    gerenciador.Set(raio, mm(r))
    vista = _vista(doc)
    plano = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(mm(cx), mm(cy), 0))
    laco = CurveArray()
    laco.Append(Arc.Create(plano, mm(r), 0.0, 3.141592653589793))
    laco.Append(Arc.Create(plano, mm(r), 3.141592653589793, 6.283185307179586))
    perfil = CurveArrArray()
    perfil.Append(laco)
    esboco = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero))
    extrusao = doc.FamilyCreate.NewExtrusion(True, perfil, esboco, mm(ALTURA))
    doc.Regenerate()
    arco, curva = _arco_do_esboco(doc, extrusao)
    cota_raio = doc.FamilyCreate.NewRadialDimension(vista, curva.Reference, XYZ(mm(cx + 60), mm(cy + 60), 0))
    cota_raio.FamilyLabel = raio
    doc.Regenerate()
    face = _ref_do_solido(extrusao, u"face")
    eixos = [
        (_centro_lr(doc), Line.CreateBound(XYZ(0, mm(-900), 0), XYZ(mm(-500), mm(-900), 0)), tx),
        (_centro_fb(doc), Line.CreateBound(XYZ(mm(-900), 0, 0), XYZ(mm(-900), mm(500), 0)), ty)]
    if y_primeiro:
        eixos.reverse()
    for centro_plano, linha, rotulo in eixos:
        referencias = ReferenceArray()
        referencias.Append(centro_plano.GetReference())
        referencias.Append(face)
        cota = doc.FamilyCreate.NewDimension(vista, linha, referencias)
        resultado.setdefault(u"valores_das_cotas_mm", []).append(rfaspec.interno_para_mm(cota.Value))
        cota.FamilyLabel = rotulo
        doc.Regenerate()
    for nome in (u"T2", u"T3"):
        cx, cy, r = V5_TIPOS[nome]
        gerenciador.NewType(nome)
        gerenciador.Set(raio, mm(r))
        gerenciador.Set(tx, mm(abs(cx) + r))
        gerenciador.Set(ty, mm(abs(cy) + r))
    if t.Commit() != TransactionStatus.Committed:
        resultado[u"erro"] = u"transação desfeita"
        return

    tipos_doc = [(rfaspec.para_unicode(tp.Name), tp) for tp in gerenciador.Types if tp.Name]
    t = _transacao(doc, u"medir", registro)
    t.Start()
    tipos = []
    tudo = True
    try:
        for nome, tipo in tipos_doc:
            gerenciador.CurrentType = tipo
            doc.Regenerate()
            xs, ys = [], []
            for forma in FilteredElementCollector(doc).OfClass(GenericForm).ToElements():
                for solido in rfaspec._solidos_da_forma(forma)[0]:
                    for f in solido.Faces:
                        for ponto in f.Triangulate(1.0).Vertices:
                            xs.append(ponto.X)
                            ys.append(ponto.Y)
            cx, cy, r = V5_TIPOS[nome]
            medido = [rfaspec.interno_para_mm(v) for v in (min(xs), max(xs), min(ys), max(ys))]
            esperado = [cx - r, cx + r, cy - r, cy + r]
            ok = all(abs(a - b) < 0.6 for a, b in zip(medido, esperado))
            tudo = tudo and ok
            tipos.append({u"tipo": nome, u"ok": ok, u"esperado": esperado, u"medido_x": medido})
    finally:
        t.RollBack()
    resultado[u"tipos"] = tipos
    resultado[u"veredito"] = u"SIM" if tudo else u"NAO"


def principal():
    template = rfaspec.env("RFADG_TEMPLATE", obrigatorio=True)
    pasta = rfaspec.env("RFADG_G0_SAIDA", obrigatorio=True)
    if not os.path.isdir(pasta):
        os.makedirs(pasta)
    app = __revit__.Application  # noqa: F821
    resultados = []
    for nome, funcao in ((u"S8_V5_dois_eixos_raio_variando", v5_dois_eixos),
                         (u"S8_V6_y_primeiro", lambda d, r: v5_dois_eixos(d, r, y_primeiro=True))):
        resultado = {u"sonda": nome, u"registro": [], u"veredito": u"ERRO"}
        doc = app.NewFamilyDocument(template)
        try:
            funcao(doc, resultado)
        except Exception as erro:
            resultado[u"erro"] = _texto(erro)[:300]
            resultado[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-1200:]
        # Variante que quebrou no meio deixa transação ou escopo abertos.
        for aberto in reversed(_ABERTOS):
            try:
                if hasattr(aberto, "IsActive"):
                    if aberto.IsActive:
                        aberto.Cancel()
                elif aberto.HasStarted() and not aberto.HasEnded():
                    aberto.RollBack()
            except Exception:
                pass
        del _ABERTOS[:]
        try:
            opcoes = SaveAsOptions()
            opcoes.OverwriteExistingFile = True
            doc.SaveAs(os.path.join(pasta, nome + u".rfa"), opcoes)
        except Exception as erro:
            resultado[u"registro"].append(u"SaveAs: " + _texto(erro)[:120])
        doc.Close(False)
        resultados.append(resultado)
    rfaspec.gravar_json(os.path.join(pasta, u"resultado_s8.json"), {
        u"revit": rfaspec.para_unicode(app.VersionNumber), u"sondas": resultados})


principal()

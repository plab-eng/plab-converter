# -*- coding: utf-8 -*-
u"""Diagnostico: extensao (bbox do solido) e volume de CADA forma, em cada tipo.

RFADG_ENTRADA = familia. Para achar qual forma diverge entre origem e destino
quando a assinatura total diverge num tipo. Transacao desfeita por tipo.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402

para_mm = rfaspec.interno_para_mm


def _medir(forma):
    opcoes = DB.Options()
    opcoes.ComputeReferences = True
    opcoes.DetailLevel = DB.ViewDetailLevel.Fine
    volume, mn, mx = 0.0, None, None
    objetos = forma if isinstance(forma, list) else (forma.get_Geometry(opcoes) or [])
    for objeto in objetos:
        if not isinstance(objeto, DB.Solid) or objeto.Volume <= 0:
            continue
        volume += objeto.Volume
        caixa = objeto.GetBoundingBox()
        for x in (caixa.Min.X, caixa.Max.X):
            for y in (caixa.Min.Y, caixa.Max.Y):
                for z in (caixa.Min.Z, caixa.Max.Z):
                    p = caixa.Transform.OfPoint(DB.XYZ(x, y, z))
                    if mn is None:
                        mn, mx = [p.X, p.Y, p.Z], [p.X, p.Y, p.Z]
                    for i, v in enumerate((p.X, p.Y, p.Z)):
                        mn[i], mx[i] = min(mn[i], v), max(mx[i], v)
    if mn is None:
        return None
    return {u"min": [round(para_mm(v), 2) for v in mn], u"max": [round(para_mm(v), 2) for v in mx],
            u"vol": round(rfaspec.interno_para_mm3(volume), 1)}


def principal():
    app = __revit__.Application  # noqa: F821
    doc = app.OpenDocumentFile(rfaspec.env("RFADG_ENTRADA", obrigatorio=True))
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"tipos": {}}
    try:
        g = doc.FamilyManager
        formas = sorted(DB.FilteredElementCollector(doc).OfClass(DB.GenericForm).ToElements(),
                        key=lambda e: rfaspec.id_inteiro(e.Id))
        for tipo in list(g.Types):
            if not tipo.Name:
                continue
            t = DB.Transaction(doc, u"diag")
            t.Start()
            try:
                g.CurrentType = tipo
                doc.Regenerate()
                # opcional: forca um parametro (para medir o flex fora do tipo)
                nome_param = rfaspec.env("RFADG_PARAM")
                if nome_param:
                    alvo = [p for p in g.Parameters if p.Definition.Name == nome_param][0]
                    if alvo.IsDeterminedByFormula:
                        g.SetFormula(alvo, None)
                    g.Set(alvo, rfaspec.mm_para_interno(float(rfaspec.env("RFADG_VALOR_MM"))))
                    doc.Regenerate()
                saida.setdefault(u"total", {})[rfaspec.para_unicode(tipo.Name)] =                     _medir(list(rfaspec._coletar_solidos(doc)[0]))
                saida[u"tipos"][rfaspec.para_unicode(tipo.Name)] = [
                    {u"ordem": i, u"classe": type(f).__name__, u"solido": bool(f.IsSolid), u"medida": _medir(f)}
                    for i, f in enumerate(formas)]
            finally:
                t.RollBack()
    except Exception:
        saida[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-600:]
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

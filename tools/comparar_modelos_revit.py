# -*- coding: utf-8 -*-
import json, time
from Autodesk.Revit.DB import *
def asc(t):
    try: t = unicode(t)
    except: t = str(t)
    return "".join(c if ord(c) < 128 else "?" for c in t)

def coletar(d):
    r = {}
    inst = list(FilteredElementCollector(d).WhereElementIsNotElementType())
    r["elementos"] = len(inst)
    cats = {}
    for e in inst:
        c = e.Category
        if c is None: continue
        k = asc(c.Name); cats[k] = cats.get(k, 0) + 1
    r["por_categoria"] = cats
    r["tipos"] = FilteredElementCollector(d).WhereElementIsElementType().GetElementCount()
    r["directshape"] = FilteredElementCollector(d).OfClass(DirectShape).GetElementCount()
    fams = list(FilteredElementCollector(d).OfClass(Family))
    r["familias"] = len(fams)
    r["familias_editaveis"] = sum(1 for f in fams if f.IsEditable)
    fi = list(FilteredElementCollector(d).OfClass(FamilyInstance))
    r["familyinstances"] = len(fi)
    r["hospedadas"] = sum(1 for x in fi if x.Host is not None)
    # conectores MEP abertos
    abertos = 0; total_con = 0
    for e in inst:
        cm = None
        try:
            if isinstance(e, MEPCurve): cm = e.ConnectorManager
            elif isinstance(e, FamilyInstance) and e.MEPModel is not None: cm = e.MEPModel.ConnectorManager
        except: cm = None
        if cm is None: continue
        for cn in cm.Connectors:
            if cn.ConnectorType != ConnectorType.End: continue
            total_con += 1
            if not cn.IsConnected: abertos += 1
    r["conectores_end"] = total_con; r["conectores_abertos"] = abertos
    r["cotas"] = FilteredElementCollector(d).OfClass(Dimension).GetElementCount()
    r["tags"] = FilteredElementCollector(d).OfClass(IndependentTag).GetElementCount()
    r["textos"] = FilteredElementCollector(d).OfClass(TextNote).GetElementCount()
    vs = [v for v in FilteredElementCollector(d).OfClass(View) if not v.IsTemplate]
    r["vistas"] = len(vs)
    r["templates"] = FilteredElementCollector(d).OfClass(View).GetElementCount() - len(vs)
    r["folhas"] = FilteredElementCollector(d).OfClass(ViewSheet).GetElementCount()
    r["tabelas"] = FilteredElementCollector(d).OfClass(ViewSchedule).GetElementCount()
    r["links_rvt"] = FilteredElementCollector(d).OfClass(RevitLinkInstance).GetElementCount()
    r["imports_cad"] = FilteredElementCollector(d).OfClass(ImportInstance).GetElementCount()
    r["sistemas_tubulacao"] = FilteredElementCollector(d).OfClass(Plumbing.PipingSystem).GetElementCount()
    r["shared_params"] = FilteredElementCollector(d).OfClass(SharedParameterElement).GetElementCount()
    r["filtros"] = FilteredElementCollector(d).OfClass(ParameterFilterElement).GetElementCount()
    r["materiais"] = FilteredElementCollector(d).OfClass(Material).GetElementCount()
    ws = d.GetWarnings(); wc = {}
    for w in ws:
        k = asc(w.GetDescriptionText()); wc[k] = wc.get(k, 0) + 1
    r["avisos_total"] = len(ws); r["avisos"] = wc
    # amostra de UniqueId + comprimento de tubos para comparar 1 a 1
    pipes = list(FilteredElementCollector(d).OfClass(Plumbing.Pipe))
    r["tubos_comprimento_total_m"] = round(sum(p.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() for p in pipes) * 0.3048, 3)
    r["uid"] = dict((x.UniqueId, asc(x.Category.Name if x.Category else "")) for x in inst)
    return r

def rodar(path, saida, workshared):
    t = time.time()
    mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
    op = OpenOptions()
    if workshared: op.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets
    d = __revit__.Application.OpenDocumentFile(mp, op)
    t_open = time.time() - t
    try:
        r = coletar(d); r["t_abrir_s"] = round(t_open, 1); r["titulo"] = asc(d.Title)
    finally:
        d.Close(False)
    f = open(saida, "w")
    try:
        f.write(json.dumps(r))
    finally:
        f.close()   # sem close o IronPython so grava no GC
    uid = r.pop("uid")
    r["n_uid"] = len(uid); r.pop("por_categoria"); r.pop("avisos")
    print(json.dumps(r, sort_keys=True))

# -*- coding: utf-8 -*-
u"""Sonda S14 -- nome de tipo "invisivel" e Type Image da Ultrapex.

A  le a Type Image do unico tipo da familia (RFADG_ENTRADA): classe do
   elemento, nome, e se GetImage() + Save(PNG) funciona.
B  numa familia nova: NewType com cada candidato a nome "em branco"
   (U+00A0, U+2007, U+202F, U+2800, U+3000, U+200B, U+3164) e o nome lido de volta.
"""
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import clr  # noqa: E402
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402


def parte_a(app, caminho, saida):
    doc = app.OpenDocumentFile(caminho)
    try:
        g = doc.FamilyManager
        p = g.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_IMAGE)
        saida[u"parametro"] = p is not None
        tipo = list(g.Types)[0]
        ident = tipo.AsElementId(p) if p is not None else None
        saida[u"id"] = rfaspec.id_inteiro(ident) if ident is not None else None
        el = doc.GetElement(ident) if ident is not None else None
        saida[u"classe"] = type(el).__name__ if el is not None else None
        if el is not None:
            saida[u"nome"] = rfaspec.para_unicode(DB.Element.Name.__get__(el))
            try:
                clr.AddReference("System.Drawing")
                from System.Drawing.Imaging import ImageFormat
                destino = os.path.join(tempfile.mkdtemp(), u"img.png")
                el.GetImage().Save(destino, ImageFormat.Png)
                saida[u"png_bytes"] = os.path.getsize(destino)
            except Exception as erro:
                saida[u"get_image"] = rfaspec.para_unicode(unicode(erro))[:200]  # noqa: F821
                saida[u"tb"] = rfaspec.para_unicode(traceback.format_exc())[-400:]
    finally:
        doc.Close(False)


def parte_b(app, template, saida):
    doc = app.NewFamilyDocument(template)
    t = DB.Transaction(doc, u"S14")
    t.Start()
    try:
        g = doc.FamilyManager
        for codigo in (0x00A0, 0x2007, 0x202F, 0x2800, 0x3000, 0x200B, 0x3164):
            nome = unichr(codigo)  # noqa: F821
            try:
                tipo = g.NewType(nome)
                lido = tipo.Name
                saida[hex(codigo)] = u"OK lido=" + u",".join(hex(ord(c)) for c in lido)
            except Exception as erro:
                saida[hex(codigo)] = rfaspec.para_unicode(unicode(erro))[:80]  # noqa: F821
    finally:
        t.RollBack()
        doc.Close(False)


def principal():
    app = __revit__.Application  # noqa: F821
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"a": {}, u"b": {}}
    try:
        parte_a(app, rfaspec.env("RFADG_ENTRADA", obrigatorio=True), saida[u"a"])
    except Exception:
        saida[u"a"][u"tb"] = rfaspec.para_unicode(traceback.format_exc())[-500:]
    try:
        parte_b(app, rfaspec.env("RFADG_TEMPLATE", obrigatorio=True), saida[u"b"])
    except Exception:
        saida[u"b"][u"tb"] = rfaspec.para_unicode(traceback.format_exc())[-500:]
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

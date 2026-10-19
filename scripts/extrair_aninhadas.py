# -*- coding: utf-8 -*-
u"""Salva cada familia aninhada distinta de RFADG_ENTRADA em RFADG_PASTA (.rfa).

Para depurar uma aninhada sozinha (ida e volta propria). Usa EditFamily e
SaveAs; o documento de entrada nao e alterado.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402
import Autodesk.Revit.DB as DB  # noqa: E402


def principal():
    app = __revit__.Application  # noqa: F821
    pasta = rfaspec.env("RFADG_PASTA", obrigatorio=True)
    if not os.path.isdir(pasta):
        os.makedirs(pasta)
    doc = app.OpenDocumentFile(rfaspec.env("RFADG_ENTRADA", obrigatorio=True))
    saida = []
    try:
        vistas = {}
        for inst in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).ToElements():
            familia = inst.Symbol.Family
            nome = rfaspec.para_unicode(DB.Element.Name.__get__(familia))
            if nome in vistas:
                continue
            vistas[nome] = True
            sub = doc.EditFamily(familia)
            try:
                opcoes = DB.SaveAsOptions()
                opcoes.OverwriteExistingFile = True
                caminho = os.path.join(pasta, nome + u".rfa")
                sub.SaveAs(caminho, opcoes)
                saida.append(caminho)
            finally:
                sub.Close(False)
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

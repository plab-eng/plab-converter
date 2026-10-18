# -*- coding: utf-8 -*-
u"""Diagnostico: parametros da familia (RFADG_ENTRADA) com o BuiltInParameter.

Lista nome, BuiltInParameter e se e de usuario. Serve para provar que um
parametro "AUSENTE" pelo nome no validador existe pelo BuiltInParameter (nome
traduzido no Revit em portugues) e que nao ha duplicata em ingles.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.environ.get("RFADG_ROOT"), "pylib"))
import rfaspec  # noqa: E402


def principal():
    app = __revit__.Application  # noqa: F821
    doc = app.OpenDocumentFile(rfaspec.env("RFADG_ENTRADA", obrigatorio=True))
    saida = {u"revit": rfaspec.para_unicode(app.VersionNumber), u"idioma": str(app.Language), u"parametros": []}
    try:
        for p in doc.FamilyManager.Parameters:
            try:
                embutido = str(p.Definition.BuiltInParameter)
            except Exception:
                embutido = None
            saida[u"parametros"].append({u"nome": rfaspec.para_unicode(p.Definition.Name), u"embutido": embutido,
                                         u"id": rfaspec.id_inteiro(p.Id)})
    finally:
        doc.Close(False)
    rfaspec.gravar_json(rfaspec.env("RFADG_RELATORIO", obrigatorio=True), saida)


principal()

# -*- coding: utf-8 -*-
u"""Sonda descartável: despeja propriedades e parâmetros de cada Blend.

Existe porque nem FirstEnd/SecondEnd nem os candidatos de builtin devolveram a
altura do blend — em vez de um quinto palpite, uma leitura exaustiva.
Saída: RFADG_SONDA (JSON).
"""

import os
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

from Autodesk.Revit.DB import FilteredElementCollector, Blend, StorageType  # noqa: E402


def principal():
    doc = __revit__.Application.OpenDocumentFile(  # noqa: F821
        rfaspec.env("RFADG_ENTRADA", obrigatorio=True))
    try:
        saida = []
        for mescla in FilteredElementCollector(doc).OfClass(Blend).ToElements():
            registro = {u"id": rfaspec.id_inteiro(mescla.Id), u"propriedades": {},
                        u"parametros": []}

            for nome in ("FirstEnd", "SecondEnd", "TopOffset", "BottomOffset",
                         "StartOffset", "EndOffset"):
                try:
                    valor = getattr(mescla, nome)
                    registro[u"propriedades"][nome] = (
                        rfaspec.interno_para_mm(float(valor))
                        if valor is not None else None)
                except Exception as erro:
                    registro[u"propriedades"][nome] = u"ERRO: " + \
                        rfaspec.para_unicode(str(erro))[:60]

            for parametro in mescla.Parameters:
                item = {u"nome": parametro.Definition.Name,
                        u"armazenamento": rfaspec.para_unicode(str(parametro.StorageType))}
                try:
                    item[u"builtin"] = rfaspec.para_unicode(
                        str(parametro.Definition.BuiltInParameter))
                except Exception:
                    item[u"builtin"] = None
                if parametro.StorageType == StorageType.Double:
                    item[u"valor_mm"] = rfaspec.interno_para_mm(parametro.AsDouble())
                registro[u"parametros"].append(item)

            saida.append(registro)

        rfaspec.gravar_json(rfaspec.env("RFADG_SONDA", obrigatorio=True), saida)
    finally:
        doc.Close(False)


principal()

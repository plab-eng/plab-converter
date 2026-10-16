# -*- coding: utf-8 -*-
"""Rota B, etapa 2: gera o corpus por UPGRADE (IronPython, dentro do Revit).

Abre cada .rfa de `origem` em segundo plano no Revit corrente, salva uma copia
em `destino` (o Revit grava no formato DELE) e fecha sem salvar o original.
Feito para rodar pelo pyRevit Routes (execute_code):

    execfile('C:/.../tools/rvtbin/corpus_upgrade.py')
    gerar('C:/.../out/rotaB/corpus/2023', 'C:/.../out/rotaB/corpus/2024')

Caminhos so com '/', sem acento (ver CLAUDE.md, armadilhas de IronPython).
"""
import os
from Autodesk.Revit.DB import ModelPathUtils, OpenOptions, SaveAsOptions


def gerar(origem, destino):
    app = __revit__.Application
    if not os.path.isdir(destino):
        os.makedirs(destino)
    print("MARCADOR-CORPUS-PLAB Revit " + app.VersionNumber + " build " + app.VersionBuild)
    for nome in sorted(os.listdir(origem)):
        if not nome.lower().endswith(".rfa"):
            continue
        src = origem + "/" + nome
        dst = destino + "/" + nome
        if os.path.exists(dst):
            os.remove(dst)       # saida velha nunca pode se passar por nova
        doc = None
        try:
            mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(src)
            doc = app.OpenDocumentFile(mp, OpenOptions())
            op = SaveAsOptions()
            op.OverwriteExistingFile = True
            doc.SaveAs(dst, op)
            print("ok   " + nome + " -> " + str(os.path.getsize(dst)) + " bytes")
        except Exception as e:
            print("ERRO " + nome + ": " + str(e))
        finally:
            if doc is not None:
                doc.Close(False)

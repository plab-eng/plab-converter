# -*- coding: utf-8 -*-
u"""FASE 0 — cria a família de teste paramétrica.

Roda no Revit de ORIGEM. Gera uma família Generic Model que exercita os dois
mecanismos de flex que um conversor precisa reproduzir:

  1. CONSTRAINT  — planos de referência + cota rotulada + alinhamento travado.
                   É o mecanismo que nenhuma rota SAT/IFC consegue preservar.
  2. ASSOCIAÇÃO  — parâmetro do elemento associado a parâmetro de família
                   (altura da extrusão).

O `pyrevit run` exige um modelo de entrada e recusa .rft, então o orquestrador
abre uma família qualquer da biblioteca do Revit só como PORTADORA — ela é
ignorada aqui. O documento de verdade nasce de NewFamilyDocument sobre o
template que o orquestrador resolveu e passou em RFADG_TEMPLATE.
Ver a nota de desenho em scripts/run_fase0.ps1.

Saída: o .rfa em RFADG_FIXTURE.

    pyrevit run scripts/criar_fixture.py <portadora.rfa> --revit=2025
"""

import os
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida. Rode via scripts/run_fase0.ps1.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

from Autodesk.Revit.DB import (  # noqa: E402
    Transaction, XYZ, Line, Plane, SketchPlane,
    CurveArray, CurveArrArray, ReferenceArray,
    FilteredElementCollector, View, ViewType,
    Options, Solid, PlanarFace,
    BuiltInParameter, SpecTypeId, GroupTypeId,
)

mm = rfaspec.mm_para_interno
log = rfaspec.log


# --------------------------------------------------------------------------
# Geometria nominal da fixture, em milímetros.
# --------------------------------------------------------------------------
LARGURA_NOMINAL = 600.0
PROFUNDIDADE_NOMINAL = 400.0
ALTURA_NOMINAL = 900.0

TIPOS = [
    (u"Pequeno", 400.0, 300.0, 700.0),
    (u"Medio", 600.0, 400.0, 900.0),
    (u"Grande", 900.0, 550.0, 1200.0),
]

TOLERANCIA = 1.0e-6


def _obter_app():
    u"""Application do Revit, no contexto do pyrevit run."""
    return __revit__.Application  # noqa: F821 (injetado pelo pyRevit)


def _resolver_template(app):
    u"""Template .rft a usar.

    Preferimos o que o orquestrador resolveu e passou por variável de ambiente
    — no Design Automation o .rft também chega como input do workitem, não é o
    plugin que sai procurando no disco. A busca local é só rede de segurança.
    """
    do_orquestrador = rfaspec.env("RFADG_TEMPLATE")
    if do_orquestrador and os.path.isfile(do_orquestrador):
        log(u"Template recebido do orquestrador: {0}".format(do_orquestrador))
        return do_orquestrador
    return rfaspec.resolver_template_generic_model(app)


def _vista_de_planta(doc):
    u"""Vista de planta do documento de família, para cotas e alinhamentos.

    NewDimension e NewAlignment exigem uma vista onde ambas as referências
    sejam visíveis. Em família Generic Model isso é a planta do nível de
    referência — em 3D o alinhamento falha silenciosamente.
    """
    for vista in FilteredElementCollector(doc).OfClass(View).ToElements():
        if vista.IsTemplate:
            continue
        if vista.ViewType == ViewType.FloorPlan:
            return vista
    raise ValueError(u"Nenhuma vista de planta encontrada no template.")


def _criar_plano_referencia(doc, vista, rotulo, eixo, deslocamento_mm):
    u"""Cria plano de referência nomeado canonicamente.

    `eixo` é "X" para um plano cuja normal aponta em X (usado para largura),
    ou "Y" para normal em Y (usado para profundidade).
    """
    metade = mm(2000.0)
    posicao = mm(deslocamento_mm)

    if eixo == u"X":
        # Linha ao longo de Y, corte em Z -> normal resultante em X.
        inicio = XYZ(posicao, -metade, 0.0)
        fim = XYZ(posicao, metade, 0.0)
    else:
        # Linha ao longo de X, corte em Z -> normal resultante em Y.
        inicio = XYZ(-metade, posicao, 0.0)
        fim = XYZ(metade, posicao, 0.0)

    plano = doc.FamilyCreate.NewReferencePlane(inicio, fim, XYZ.BasisZ, vista)
    plano.Name = rfaspec.nome_canonico_plano(rotulo)
    return plano


def _cotar_e_rotular(doc, vista, plano_a, plano_b, parametro, linha):
    u"""Cria cota entre dois planos e rotula com o parâmetro de família.

    `dim.FamilyLabel = parametro` é a peça central do projeto: é o que faz a
    família flexionar de verdade. Só é gravável dentro de family document.
    """
    referencias = ReferenceArray()
    referencias.Append(plano_a.GetReference())
    referencias.Append(plano_b.GetReference())

    cota = doc.FamilyCreate.NewDimension(vista, linha, referencias)
    cota.FamilyLabel = parametro
    return cota


def _faces_planares_por_normal(extrusao, normal_alvo):
    u"""Faces planares da extrusão cuja normal casa com `normal_alvo`.

    Options.ComputeReferences precisa ser True, senão Face.Reference vem nulo
    e o alinhamento não tem o que travar.
    """
    opcoes = Options()
    opcoes.ComputeReferences = True
    opcoes.IncludeNonVisibleObjects = False

    encontradas = []
    for objeto in extrusao.get_Geometry(opcoes):
        if not isinstance(objeto, Solid):
            continue
        for face in objeto.Faces:
            if not isinstance(face, PlanarFace):
                continue
            if face.FaceNormal.IsAlmostEqualTo(normal_alvo):
                encontradas.append(face)
    return encontradas


def _alinhar_face_ao_plano(doc, vista, plano, extrusao, normal):
    u"""Trava a face da extrusão no plano de referência.

    Sem isso a cota rotulada existe mas não move a geometria: o parâmetro muda
    e o sólido fica parado. É exatamente o sintoma de "família que não flexiona".
    """
    faces = _faces_planares_por_normal(extrusao, normal)
    if not faces:
        raise ValueError(
            u"Nenhuma face planar com normal {0} na extrusão.".format(normal)
        )
    doc.FamilyCreate.NewAlignment(vista, plano.GetReference(), faces[0].Reference)


def _perfil_retangular(largura_mm, profundidade_mm):
    u"""Perfil retangular centrado na origem, no plano XY."""
    meia_largura = mm(largura_mm / 2.0)
    meia_profundidade = mm(profundidade_mm / 2.0)

    cantos = [
        XYZ(-meia_largura, -meia_profundidade, 0.0),
        XYZ(meia_largura, -meia_profundidade, 0.0),
        XYZ(meia_largura, meia_profundidade, 0.0),
        XYZ(-meia_largura, meia_profundidade, 0.0),
    ]

    curvas = CurveArray()
    for indice in range(len(cantos)):
        curvas.Append(Line.CreateBound(cantos[indice], cantos[(indice + 1) % len(cantos)]))

    perfil = CurveArrArray()
    perfil.Append(curvas)
    return perfil


def _adicionar_parametro_comprimento(gerenciador, nome):
    u"""Parâmetro de família de tipo, categoria Comprimento, grupo Cotas."""
    return gerenciador.AddParameter(nome, GroupTypeId.Geometry, SpecTypeId.Length, False)


def construir(doc):
    gerenciador = doc.FamilyManager
    vista = _vista_de_planta(doc)

    # 1. Parâmetros. Criados antes de tudo porque a cota precisa deles para
    #    receber o rótulo no mesmo passo em que é criada.
    par_largura = _adicionar_parametro_comprimento(gerenciador, u"Largura")
    par_profundidade = _adicionar_parametro_comprimento(gerenciador, u"Profundidade")
    par_altura = _adicionar_parametro_comprimento(gerenciador, u"Altura")

    # Um documento recém-criado a partir de template NÃO tem nenhum tipo, e
    # FamilyManager.Set exige um tipo corrente ("There is no current type").
    # NewType já deixa o tipo criado como corrente.
    gerenciador.NewType(u"Padrao")

    gerenciador.Set(par_largura, mm(LARGURA_NOMINAL))
    gerenciador.Set(par_profundidade, mm(PROFUNDIDADE_NOMINAL))
    gerenciador.Set(par_altura, mm(ALTURA_NOMINAL))

    # 2. Esqueleto: os planos de referência que a geometria vai seguir.
    plano_esq = _criar_plano_referencia(doc, vista, u"Esq", u"X", -LARGURA_NOMINAL / 2.0)
    plano_dir = _criar_plano_referencia(doc, vista, u"Dir", u"X", LARGURA_NOMINAL / 2.0)
    plano_frente = _criar_plano_referencia(doc, vista, u"Frente", u"Y", -PROFUNDIDADE_NOMINAL / 2.0)
    plano_tras = _criar_plano_referencia(doc, vista, u"Tras", u"Y", PROFUNDIDADE_NOMINAL / 2.0)
    doc.Regenerate()

    # 3. Cotas rotuladas. A partir daqui os parâmetros dirigem os planos.
    linha_largura = Line.CreateBound(
        XYZ(mm(-LARGURA_NOMINAL / 2.0), mm(-800.0), 0.0),
        XYZ(mm(LARGURA_NOMINAL / 2.0), mm(-800.0), 0.0),
    )
    _cotar_e_rotular(doc, vista, plano_esq, plano_dir, par_largura, linha_largura)

    linha_profundidade = Line.CreateBound(
        XYZ(mm(-800.0), mm(-PROFUNDIDADE_NOMINAL / 2.0), 0.0),
        XYZ(mm(-800.0), mm(PROFUNDIDADE_NOMINAL / 2.0), 0.0),
    )
    _cotar_e_rotular(doc, vista, plano_frente, plano_tras, par_profundidade, linha_profundidade)
    doc.Regenerate()

    # 4. Sólido.
    plano_esboco = SketchPlane.Create(
        doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero)
    )
    extrusao = doc.FamilyCreate.NewExtrusion(
        True,
        _perfil_retangular(LARGURA_NOMINAL, PROFUNDIDADE_NOMINAL),
        plano_esboco,
        mm(ALTURA_NOMINAL),
    )
    doc.Regenerate()

    # 5. Trava a geometria no esqueleto. Ordem importa: alinhar só depois de a
    #    cota já estar rotulada, senão o Revit resolve a restrição contra um
    #    valor fixo em vez do parâmetro.
    _alinhar_face_ao_plano(doc, vista, plano_esq, extrusao, XYZ(-1.0, 0.0, 0.0))
    _alinhar_face_ao_plano(doc, vista, plano_dir, extrusao, XYZ(1.0, 0.0, 0.0))
    _alinhar_face_ao_plano(doc, vista, plano_frente, extrusao, XYZ(0.0, -1.0, 0.0))
    _alinhar_face_ao_plano(doc, vista, plano_tras, extrusao, XYZ(0.0, 1.0, 0.0))
    doc.Regenerate()

    # 6. Altura pelo outro mecanismo: associação direta de parâmetro do
    #    elemento ao parâmetro de família.
    par_fim = extrusao.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM)
    gerenciador.AssociateElementParameterToFamilyParameter(par_fim, par_altura)
    doc.Regenerate()

    # 7. Tipos.
    for nome, largura, profundidade, altura in TIPOS:
        gerenciador.NewType(nome)
        gerenciador.Set(par_largura, mm(largura))
        gerenciador.Set(par_profundidade, mm(profundidade))
        gerenciador.Set(par_altura, mm(altura))

    doc.Regenerate()
    log(u"Fixture construída: {0} tipos, 4 planos, 1 extrusão.".format(len(TIPOS)))


def principal():
    destino = rfaspec.env("RFADG_FIXTURE", obrigatorio=True)
    app = _obter_app()

    doc = app.NewFamilyDocument(_resolver_template(app))

    transacao = Transaction(doc, u"RFADG — criar fixture")
    transacao.Start()
    try:
        construir(doc)
        transacao.Commit()
    except Exception:
        transacao.RollBack()
        doc.Close(False)
        raise

    pasta = os.path.dirname(destino)
    if pasta and not os.path.isdir(pasta):
        os.makedirs(pasta)
    if os.path.isfile(destino):
        os.remove(destino)

    doc.SaveAs(destino)
    doc.Close(False)
    log(u"Fixture salva em {0}".format(destino))


principal()

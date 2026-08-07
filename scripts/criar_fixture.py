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

import math
import os
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida. Rode via scripts/run_fase0.ps1.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

from Autodesk.Revit.DB import (  # noqa: E402
    Transaction, XYZ, Line, Arc, Plane, SketchPlane,
    CurveArray, CurveArrArray, ReferenceArray, CombinableElementArray,
    FilteredElementCollector, View, ViewType,
    Options, Solid, PlanarFace, ProfilePlaneLocation,
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

# Vazio central: atravessa o sólido em Z mas não encosta nas faces laterais,
# então o bounding box não muda e só o volume denuncia se o corte sumiu na
# reconstrução. É de propósito — separa "geometria certa" de "corte aplicado".
VAZIO_LARGURA = 200.0
VAZIO_PROFUNDIDADE = 150.0
VAZIO_BASE = -100.0
VAZIO_TOPO = 1400.0


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


ANEL_RAIO_INTERNO = 300.0
ANEL_RAIO_EXTERNO = 400.0
ANEL_BASE = 0.0
ANEL_TOPO = 100.0


def _criar_anel(doc):
    u"""Revolução de 360°: retângulo no plano XZ girado em torno do eixo Z.

    Fica FORA da combinação de corte — é uma forma sólida solta, para o
    medidor exercitar também o caminho "GenericForm sem combinação".
    """
    plano_xz = Plane.CreateByNormalAndOrigin(XYZ.BasisY, XYZ.Zero)
    plano_esboco = SketchPlane.Create(doc, plano_xz)

    cantos = [
        XYZ(mm(ANEL_RAIO_INTERNO), 0.0, mm(ANEL_BASE)),
        XYZ(mm(ANEL_RAIO_EXTERNO), 0.0, mm(ANEL_BASE)),
        XYZ(mm(ANEL_RAIO_EXTERNO), 0.0, mm(ANEL_TOPO)),
        XYZ(mm(ANEL_RAIO_INTERNO), 0.0, mm(ANEL_TOPO)),
    ]
    curvas = CurveArray()
    for indice in range(len(cantos)):
        curvas.Append(Line.CreateBound(cantos[indice], cantos[(indice + 1) % len(cantos)]))
    perfil = CurveArrArray()
    perfil.Append(curvas)

    eixo = Line.CreateBound(XYZ.Zero, XYZ(0.0, 0.0, mm(1000.0)))

    doc.FamilyCreate.NewRevolution(
        True, perfil, plano_esboco, eixo, 0.0, 2.0 * math.pi
    )
    doc.Regenerate()


VARREDURA_RAIO = 900.0        # raio do arco do caminho
VARREDURA_LADO = 60.0         # lado do perfil quadrado


def _criar_varredura(doc):
    u"""Sweep: perfil quadrado ao longo de um quarto de arco no plano do piso.

    O perfil vai para NewCurveLoopsProfile em coordenadas XY LOCAIS — o Revit
    o transporta para o plano do caminho. Perfil em coordenadas de mundo aqui
    produziria geometria em lugar nenhum.
    """
    plano_piso = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, mm(1600.0)))
    plano_esboco = SketchPlane.Create(doc, plano_piso)

    caminho = CurveArray()
    caminho.Append(Arc.Create(
        XYZ(mm(VARREDURA_RAIO), 0, mm(1600.0)),
        XYZ(0, mm(VARREDURA_RAIO), mm(1600.0)),
        XYZ(mm(VARREDURA_RAIO * 0.7071), mm(VARREDURA_RAIO * 0.7071), mm(1600.0)),
    ))

    metade = mm(VARREDURA_LADO / 2.0)
    cantos = [
        XYZ(-metade, -metade, 0), XYZ(metade, -metade, 0),
        XYZ(metade, metade, 0), XYZ(-metade, metade, 0),
    ]
    curvas = CurveArray()
    for indice in range(4):
        curvas.Append(Line.CreateBound(cantos[indice], cantos[(indice + 1) % 4]))
    lacos = CurveArrArray()
    lacos.Append(curvas)
    perfil = doc.Application.Create.NewCurveLoopsProfile(lacos)

    doc.FamilyCreate.NewSweep(
        True, caminho, plano_esboco, perfil, 0, ProfilePlaneLocation.Start)
    doc.Regenerate()


MESCLA_BASE = 160.0
MESCLA_TOPO = 80.0
MESCLA_ALTURA = 120.0


def _criar_mescla(doc):
    u"""Blend: quadrado grande na base -> quadrado pequeno no topo.

    O perfil de topo vai em coordenadas de MUNDO, já na altura real — é assim
    que o NewBlend funciona (exemplo canônico do Building Coder, 0470). Os
    dois perfis no mesmo plano produzem blend de altura zero e o Revit
    responde "Unexpected internal error: code 1", sem explicar.
    """
    centro_x, centro_y = mm(-900.0), mm(-900.0)
    plano = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(centro_x, centro_y, 0))
    plano_esboco = SketchPlane.Create(doc, plano)

    def _quadrado(lado, altura_z):
        metade = mm(lado / 2.0)
        cota = mm(altura_z)
        cantos = [
            XYZ(centro_x - metade, centro_y - metade, cota),
            XYZ(centro_x + metade, centro_y - metade, cota),
            XYZ(centro_x + metade, centro_y + metade, cota),
            XYZ(centro_x - metade, centro_y + metade, cota),
        ]
        curvas = CurveArray()
        for indice in range(4):
            curvas.Append(Line.CreateBound(cantos[indice], cantos[(indice + 1) % 4]))
        return curvas

    doc.FamilyCreate.NewBlend(
        True,
        _quadrado(MESCLA_TOPO, MESCLA_ALTURA),
        _quadrado(MESCLA_BASE, 0.0),
        plano_esboco,
    )
    doc.Regenerate()


def _cortar(doc, solido, vazio):
    u"""Aplica o vazio sobre o sólido (equivalente ao Cut Geometry da UI).

    Uma forma de vazio criada pela API não corta automaticamente: sem esta
    combinação a família fica com o vazio presente porém inerte, e o volume
    sai igual ao do sólido cheio.
    """
    combinaveis = CombinableElementArray()
    combinaveis.Append(solido)
    combinaveis.Append(vazio)
    doc.CombineElements(combinaveis)
    doc.Regenerate()


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


def _adicionar_parametro_comprimento(gerenciador, nome, de_instancia=False):
    u"""Parâmetro de família, categoria Comprimento, grupo Cotas."""
    return gerenciador.AddParameter(
        nome, GroupTypeId.Geometry, SpecTypeId.Length, de_instancia
    )


def _criar_parametros_variados(gerenciador):
    u"""Parâmetros não-dimensionais que a Fase 1 precisa saber reproduzir.

    Cada um exercita um caminho diferente do construtor: tipo de dado distinto,
    parâmetro de instância, e fórmula (que não pode receber Set direto).
    """
    criados = {}

    criados[u"Espessura"] = gerenciador.AddParameter(
        u"Espessura", GroupTypeId.Geometry, SpecTypeId.Length, True  # instância
    )
    criados[u"Fabricante"] = gerenciador.AddParameter(
        u"Fabricante", GroupTypeId.IdentityData, SpecTypeId.String.Text, False
    )
    criados[u"Estrutural"] = gerenciador.AddParameter(
        u"Estrutural", GroupTypeId.Constraints, SpecTypeId.Boolean.YesNo, False
    )
    criados[u"Quantidade"] = gerenciador.AddParameter(
        u"Quantidade", GroupTypeId.IdentityData, SpecTypeId.Int.Integer, False
    )
    criados[u"Area_Base"] = gerenciador.AddParameter(
        u"Area_Base", GroupTypeId.Geometry, SpecTypeId.Area, False
    )

    return criados


def construir(doc):
    gerenciador = doc.FamilyManager
    vista = _vista_de_planta(doc)

    # 1. Parâmetros. Criados antes de tudo porque a cota precisa deles para
    #    receber o rótulo no mesmo passo em que é criada.
    par_largura = _adicionar_parametro_comprimento(gerenciador, u"Largura")
    par_profundidade = _adicionar_parametro_comprimento(gerenciador, u"Profundidade")
    par_altura = _adicionar_parametro_comprimento(gerenciador, u"Altura")
    variados = _criar_parametros_variados(gerenciador)

    # Um documento recém-criado a partir de template NÃO tem nenhum tipo, e
    # FamilyManager.Set exige um tipo corrente ("There is no current type").
    # NewType já deixa o tipo criado como corrente.
    gerenciador.NewType(u"Padrao")

    gerenciador.Set(par_largura, mm(LARGURA_NOMINAL))
    gerenciador.Set(par_profundidade, mm(PROFUNDIDADE_NOMINAL))
    gerenciador.Set(par_altura, mm(ALTURA_NOMINAL))

    # Fórmula depois dos parâmetros que ela referencia existirem.
    gerenciador.SetFormula(variados[u"Area_Base"], u"Largura * Profundidade")

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

    # 7. Vazio. Criado depois do sólido para que o corte tenha o que cortar.
    vazio = doc.FamilyCreate.NewExtrusion(
        False,  # isSolid=False -> forma de vazio
        _perfil_retangular(VAZIO_LARGURA, VAZIO_PROFUNDIDADE),
        SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero)),
        mm(VAZIO_TOPO),
    )
    vazio.get_Parameter(BuiltInParameter.EXTRUSION_START_PARAM).Set(mm(VAZIO_BASE))
    doc.Regenerate()

    # Vazio criado pela API não corta sozinho: é preciso combinar explicitamente
    # com o sólido, equivalente ao "Cut Geometry" do Family Editor.
    _cortar(doc, extrusao, vazio)

    # 8. Revolução — anel, para exercitar o caminho de NewRevolution.
    #    Perfil no plano XZ girado em torno do eixo Z. O eixo PRECISA estar no
    #    mesmo plano do perfil, senão o Revit recusa.
    _criar_anel(doc)

    # 9. Sweep e Blend, soltos, para exercitar os caminhos novos.
    _criar_varredura(doc)
    _criar_mescla(doc)

    # 10. Tipos.
    for nome, largura, profundidade, altura in TIPOS:
        gerenciador.NewType(nome)
        gerenciador.Set(par_largura, mm(largura))
        gerenciador.Set(par_profundidade, mm(profundidade))
        gerenciador.Set(par_altura, mm(altura))
        gerenciador.Set(variados[u"Espessura"], mm(25.0))
        gerenciador.Set(variados[u"Fabricante"], u"P-LAB Engenharia")
        gerenciador.Set(variados[u"Estrutural"], 1)
        gerenciador.Set(variados[u"Quantidade"], len(nome))

    doc.Regenerate()
    log(u"Fixture construída: {0} tipos, 4 planos, 1 sólido, 1 vazio.".format(
        len(TIPOS) + 1))


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

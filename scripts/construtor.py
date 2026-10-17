# -*- coding: utf-8 -*-
u"""FASE 0 — construtor: FamilySpec JSON -> .rfa nativo da versão de DESTINO.

Roda no Revit de DESTINO. Cria um family document novo a partir do template
recebido em RFADG_TEMPLATE e reconstrói a família descrita no FamilySpec:
planos de referência, parâmetros, cotas rotuladas, formas, alinhamentos,
associações e tipos.

A ordem de reconstrução importa e espelha a da fixture PASSO A PASSO:
  parâmetros -> tipo corrente da origem (com valores) -> planos ->
  cotas rotuladas -> [por forma, na ordem da origem: forma -> alinhamentos ->
  associações] -> combinações -> demais tipos -> fórmulas
Rotular a cota ANTES de alinhar a geometria: alinhar primeiro faz o Revit
resolver a restrição contra valor fixo e a família não flexiona. E cada forma
é travada e associada ANTES de a próxima nascer: o esboço de uma forma sem
restrições explícitas é posicionado por restrições automáticas que o solver
cria conforme o estado do documento no instante da criação — criar o vazio num
modelo ainda solto deixava o corte encolher no flex (ver construir_formas).

O modelo da linha de comando é só a portadora que dá boot no Revit.

    pyrevit run scripts/construtor.py <portadora.rfa> --revit=2023
"""

import os
import re
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida. Rode via scripts/run_fase0.ps1.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

from Autodesk.Revit.DB import (  # noqa: E402
    Transaction, XYZ, Line, Arc, Plane, SketchPlane,
    CurveArray, CurveArrArray, ReferenceArray, CombinableElementArray,
    FilteredElementCollector, View, ViewType, ReferencePlane,
    Options, Solid, PlanarFace, Category, StorageType, Transform,
    BuiltInParameter, BuiltInCategory, SpecTypeId, GroupTypeId,
    ExternalDefinitionCreationOptions, ProfilePlaneLocation,
)
from System import Enum, Guid  # noqa: E402

mm = rfaspec.mm_para_interno
log = rfaspec.log

# Vírgula decimal entre dígitos — usado na repetição de SetFormula.
_RE_VIRGULA_DECIMAL = re.compile(r"(\d),(\d)")


def _obter_app():
    return __revit__.Application  # noqa: F821 (injetado pelo pyRevit)


def _xyz(lista_mm):
    u"""Lista em mm (FamilySpec) -> XYZ interno."""
    return XYZ(mm(lista_mm[0]), mm(lista_mm[1]), mm(lista_mm[2]))


def _vetor(lista):
    u"""Lista adimensional (normal, direção) -> XYZ cru."""
    return XYZ(lista[0], lista[1], lista[2])


def _vista_de_planta(doc):
    u"""Vista de planta — cotas e alinhamentos exigem uma (em 3D falham)."""
    for vista in FilteredElementCollector(doc).OfClass(View).ToElements():
        if vista.IsTemplate:
            continue
        if vista.ViewType == ViewType.FloorPlan:
            return vista
    raise ValueError(u"Nenhuma vista de planta encontrada no template de destino.")


# --------------------------------------------------------------------------
# Registro do que não foi reproduzido. Cobertura incompleta NUNCA é silenciosa:
# tudo que ficar de fora vai para o relatório e para o log.
# --------------------------------------------------------------------------
_NAO_REPRODUZIDO = []


def _pular(o_que, motivo):
    _NAO_REPRODUZIDO.append({u"item": o_que, u"motivo": motivo})
    log(u"NÃO REPRODUZIDO: {0} — {1}".format(o_que, motivo))


# --------------------------------------------------------------------------
# 1. Parâmetros
# --------------------------------------------------------------------------

# Tipos de dado cobertos. Chaves por ESPÉCIE (sem o sufixo de versão, que muda
# entre versões do Revit). Um tipo fora desta tabela NUNCA é aceito em silêncio:
# vai para o relatório de fidelidade.
#
# A tabela é montada DEFENSIVAMENTE, resolvendo cada SpecTypeId por caminho de
# atributos: o conjunto de specs varia entre versões (`SpecTypeId.NumberOfPoles`
# não existe no 2023) e um único acesso direto a atributo ausente derrubava o
# script inteiro no import — mesma família de armadilha do REVOLVE_START_ANGLE
# no leitor. O que não existir na versão corrente fica fora da cobertura e o
# parâmetro correspondente vira lacuna honesta no relatório.

def _resolver_spec(caminho):
    u"""'Reference.Material' -> SpecTypeId.Reference.Material, ou None."""
    alvo = SpecTypeId
    for parte in caminho.split(u"."):
        alvo = getattr(alvo, parte, None)
        if alvo is None:
            return None
    return alvo


def _montar_tipos_de_dado():
    tabela = {}
    # Atenção ao prefixo: o Revit usa `aec:number` e `aec:material` em
    # famílias reais, NÃO `spec.number` nem `reference:material`. As duas
    # grafias ficam. Espécies de MEP não são exóticas aqui: aparecem em 26 de
    # 27 famílias reais inventariadas do acervo P-LAB.
    candidatos = [
        (u"autodesk.spec.aec:length", u"Length"),
        (u"autodesk.spec.aec:area", u"Area"),
        (u"autodesk.spec.aec:volume", u"Volume"),
        (u"autodesk.spec.aec:angle", u"Angle"),
        (u"autodesk.spec.aec:number", u"Number"),
        (u"autodesk.spec:spec.number", u"Number"),
        (u"autodesk.spec.aec:material", u"Reference.Material"),
        (u"autodesk.spec.reference:material", u"Reference.Material"),
        (u"autodesk.spec:spec.string", u"String.Text"),
        (u"autodesk.spec.string:url", u"String.Url"),
        (u"autodesk.spec:spec.bool", u"Boolean.YesNo"),
        # O Revit grava inteiro de família como int64, não como int.
        (u"autodesk.spec:spec.int64", u"Int.Integer"),
        (u"autodesk.spec:spec.int", u"Int.Integer"),
        (u"autodesk.spec.measurable:currency", u"Currency"),
        (u"autodesk.spec.reference:image", u"Reference.Image"),
        (u"autodesk.spec.aec.piping:pipeSize", u"PipeSize"),
        (u"autodesk.spec.aec.piping:flow", u"Flow"),
        (u"autodesk.spec.aec.piping:temperature", u"PipingTemperature"),
        (u"autodesk.spec.aec.electrical:frequency", u"ElectricalFrequency"),
        (u"autodesk.spec.aec.electrical:potential", u"ElectricalPotential"),
        (u"autodesk.spec.aec.electrical:power", u"ElectricalPower"),
        (u"autodesk.spec.aec:numberOfPoles", u"NumberOfPoles"),
        (u"autodesk.spec.aec.structural:mass", u"Mass"),
    ]
    for especie, caminho in candidatos:
        spec = _resolver_spec(caminho)
        if spec is not None and especie not in tabela:
            tabela[especie] = spec
    return tabela


_TIPOS_DE_DADO = _montar_tipos_de_dado()

# Grupos de parâmetro, por espécie de ForgeTypeId. Cosmético (só afeta onde o
# parâmetro aparece na paleta), então cair no padrão é aceitável e não vira
# item de relatório.
_GRUPOS = {
    u"autodesk.parameter.group:geometry": GroupTypeId.Geometry,
    u"autodesk.parameter.group:constraints": GroupTypeId.Constraints,
    u"autodesk.parameter.group:identityData": GroupTypeId.IdentityData,
    u"autodesk.parameter.group:general": GroupTypeId.General,
    u"autodesk.parameter.group:graphics": GroupTypeId.Graphics,
    u"autodesk.parameter.group:materials": GroupTypeId.Materials,
    u"autodesk.parameter.group:text": GroupTypeId.Text,
    u"autodesk.parameter.group:visibility": GroupTypeId.Visibility,
}

# Parâmetros builtin do template (Model, Manufacturer, ...) já existem no
# destino; só os de família criados pelo autor precisam ser recriados.
_GRUPO_PADRAO = GroupTypeId.Geometry


def ajustar_categoria(doc, especificacao):
    u"""Põe a família na categoria da origem, seja qual for o template usado.

    O template de destino nem sempre existe: esta máquina só tem os Generic
    Model instalados para o Revit 2023, então uma família de Mechanical
    Equipment sairia com a categoria errada. Trocar `OwnerFamily.FamilyCategory`
    resolve sem depender do que está instalado — e o id de BuiltInCategory é
    estável entre versões, ao contrário do nome, que é localizado.

    Categoria errada não é detalhe: muda agendamento, filtros, visibilidade e
    o comportamento de conectores MEP.
    """
    identidade = especificacao.get(u"identidade") or {}
    id_categoria = identidade.get(u"categoria_id")
    if id_categoria is None:
        return

    atual = doc.OwnerFamily.FamilyCategory
    if atual is not None and rfaspec.id_inteiro(atual.Id) == id_categoria:
        return  # o template já nasceu na categoria certa

    try:
        builtin = Enum.ToObject(BuiltInCategory, id_categoria)
        categoria = Category.GetCategory(doc, builtin)
        if categoria is None:
            raise ValueError(u"categoria não existe neste documento")
        doc.OwnerFamily.FamilyCategory = categoria
        doc.Regenerate()
    except Exception as erro:
        _pular(
            u"categoria da família ({0})".format(
                identidade.get(u"categoria_nome") or id_categoria),
            u"não foi possível aplicar: {0}".format(unicode(erro)[:120]),  # noqa: F821
        )


def _grupo_compartilhado(app, estado):
    u"""Abre (uma vez) o arquivo temporário de shared parameters e devolve o
    grupo RFADG dentro dele.

    A API só cria parâmetro compartilhado a partir de um arquivo de shared
    parameters ativo, então um TEMPORÁRIO é forjado só para isto — e fica
    ativo durante TODO o lote de AddParameter. Restaurar o arquivo do usuário
    antes do AddParameter deixava a ExternalDefinition órfã e o Revit
    respondia "Shared parameter creation failed." nos 6 parâmetros — a
    restauração agora acontece uma única vez, no fim do lote
    (_restaurar_arquivo_compartilhado).

    Nome único por processo: um arquivo reaproveitado entre execuções poderia
    conter um homônimo de OUTRA família com outro GUID, e o get_Item o
    devolveria em silêncio — contaminação cruzada é inaceitável num conversor.
    """
    if u"grupo" in estado:
        return estado[u"grupo"]

    pasta = os.environ.get("TEMP") or os.environ.get("TMP") or u"."
    caminho = os.path.join(pasta, u"rfadg_shared_{0}.txt".format(os.getpid()))

    estado[u"anterior"] = app.SharedParametersFilename
    if not os.path.isfile(caminho):
        with open(caminho, "wb") as arquivo:
            arquivo.write(b"")  # DefinitionFile exige arquivo existente

    app.SharedParametersFilename = caminho
    arquivo_definicoes = app.OpenSharedParameterFile()
    if arquivo_definicoes is None:
        raise ValueError(u"não foi possível abrir o arquivo temporário")

    grupo = arquivo_definicoes.Groups.get_Item(u"RFADG")
    if grupo is None:
        grupo = arquivo_definicoes.Groups.Create(u"RFADG")
    estado[u"grupo"] = grupo
    return grupo


def _restaurar_arquivo_compartilhado(app, estado):
    u"""Devolve o SharedParametersFilename do usuário — deixá-lo apontando
    para o nosso temporário seria grosseria."""
    if u"anterior" not in estado:
        return
    try:
        app.SharedParametersFilename = estado[u"anterior"] or u""
    except Exception:
        pass


def _definicao_compartilhada(app, estado, item, tipo_de_dado):
    u"""ExternalDefinition com o GUID da ORIGEM.

    O GUID é o ponto inegociável: é ele que faz tabelas, etiquetas e filtros
    de projeto continuarem enxergando o parâmetro depois da conversão.
    Recriar com GUID novo produziria um homônimo que quebra todo agendamento.
    """
    guid = item.get(u"guid")
    if not guid:
        raise ValueError(u"spec sem GUID do parâmetro compartilhado")

    grupo = _grupo_compartilhado(app, estado)
    definicao = grupo.Definitions.get_Item(item[u"nome"])
    if definicao is None:
        opcoes = ExternalDefinitionCreationOptions(item[u"nome"], tipo_de_dado)
        opcoes.GUID = Guid(guid)
        definicao = grupo.Definitions.Create(opcoes)
    return definicao


def construir_parametros(doc, especificacao):
    u"""Cria os parâmetros de família do spec. Retorna nome -> FamilyParameter."""
    gerenciador = doc.FamilyManager

    existentes = {}
    for parametro in gerenciador.Parameters:
        existentes[parametro.Definition.Name] = parametro

    mapa = dict(existentes)
    estado_compartilhado = {}

    try:
        for item in especificacao[u"parametros"]:
            nome = item[u"nome"]
            if nome in existentes:
                continue  # builtin do template, nada a criar

            tipo_de_dado = _TIPOS_DE_DADO.get(
                rfaspec.especie_forge(item.get(u"tipo_de_dado")))
            if tipo_de_dado is None:
                _pular(u"parâmetro '{0}'".format(nome),
                       u"tipo de dado fora da cobertura: {0}".format(
                           item.get(u"tipo_de_dado")))
                continue

            grupo = _GRUPOS.get(rfaspec.especie_forge(item.get(u"grupo")), _GRUPO_PADRAO)
            de_instancia = bool(item.get(u"de_instancia"))

            try:
                if item.get(u"compartilhado"):
                    definicao = _definicao_compartilhada(
                        doc.Application, estado_compartilhado, item, tipo_de_dado)
                    criado = gerenciador.AddParameter(definicao, grupo, de_instancia)
                else:
                    criado = gerenciador.AddParameter(
                        nome, grupo, tipo_de_dado, de_instancia)
            except Exception as erro:
                _pular(u"parâmetro '{0}'".format(nome), unicode(erro)[:140])  # noqa: F821
                continue

            mapa[nome] = criado
    finally:
        _restaurar_arquivo_compartilhado(doc.Application, estado_compartilhado)

    return mapa


def aplicar_formulas(doc, especificacao, parametros):
    u"""Aplica as fórmulas. Precisa rodar DEPOIS de existir pelo menos um tipo.

    `SetFormula` num documento sem tipo nenhum falha com "There is no valid
    family type" — mesma família de armadilha do `FamilyManager.Set`. E depois
    de todos os parâmetros existirem, porque uma fórmula referencia outras.
    """
    gerenciador = doc.FamilyManager

    for item in especificacao[u"parametros"]:
        formula = item.get(u"formula")
        if not formula:
            continue
        parametro = parametros.get(item[u"nome"])
        if parametro is None:
            continue
        try:
            gerenciador.SetFormula(parametro, formula)
        except Exception as erro_original:
            # Fórmula autorada em Revit pt-BR chega com vírgula decimal
            # ('47,2 kg') e a sessão de destino a recusa. A repetição troca
            # dígito,dígito por dígito.dígito — mas SÓ em fórmula sem chamada
            # de função: em if(a>1,2,3) a vírgula é separador de argumento e a
            # troca corromperia a fórmula (possivelmente para algo VÁLIDO e
            # errado, o pior desfecho). Se falhar, lacuna com o erro ORIGINAL.
            normalizada = formula
            if u"(" not in formula:
                normalizada = _RE_VIRGULA_DECIMAL.sub(r"\1.\2", formula)
            if normalizada != formula:
                try:
                    gerenciador.SetFormula(parametro, normalizada)
                    continue
                except Exception:
                    pass
            _pular(u"fórmula de '{0}'".format(item[u"nome"]),
                   unicode(erro_original)[:140])  # noqa: F821

    doc.Regenerate()


# --------------------------------------------------------------------------
# 2. Planos de referência
# --------------------------------------------------------------------------

def construir_planos(doc, vista, especificacao):
    u"""Recria os planos de referência canônicos. Retorna nome -> ReferencePlane.

    Planos do template (Center Front/Back etc.) já existem no destino e são
    reaproveitados pelo nome. Só os canônicos (RFADG_) são recriados.
    """
    mapa = {}
    for plano in FilteredElementCollector(doc).OfClass(ReferencePlane).ToElements():
        nome = getattr(plano, "Name", None)
        if nome:
            mapa[nome] = plano

    for item in especificacao[u"planos_de_referencia"]:
        nome = item[u"nome"]
        if nome in mapa:
            continue
        if not item[u"canonico"]:
            # Plano do template com nome diferente no idioma do destino.
            # Fase 0 tolera; a geometria da fixture não depende deles.
            _pular(u"plano '{0}'".format(nome),
                   u"plano não-canônico ausente no template de destino")
            continue

        plano = doc.FamilyCreate.NewReferencePlane(
            _xyz(item[u"inicio"]), _xyz(item[u"fim"]), XYZ.BasisZ, vista
        )
        plano.Name = nome
        mapa[nome] = plano

    doc.Regenerate()
    return mapa


# --------------------------------------------------------------------------
# 3. Formas
# --------------------------------------------------------------------------

def _curva_do_spec(item):
    if item[u"tipo"] == u"linha":
        return Line.CreateBound(_xyz(item[u"inicio"]), _xyz(item[u"fim"]))
    if item[u"tipo"] == u"arco":
        return Arc.Create(_xyz(item[u"inicio"]), _xyz(item[u"fim"]), _xyz(item[u"meio"]))
    raise ValueError(u"Curva fora da cobertura: {0}".format(item[u"tipo"]))


def _curva_2d(item):
    u"""Curva de perfil local (2D, mm) -> curva no plano XY interno."""
    def _xy(par):
        return XYZ(mm(par[0]), mm(par[1]), 0.0)
    if item[u"tipo"] == u"linha":
        return Line.CreateBound(_xy(item[u"inicio"]), _xy(item[u"fim"]))
    if item[u"tipo"] == u"arco":
        return Arc.Create(_xy(item[u"inicio"]), _xy(item[u"fim"]), _xy(item[u"meio"]))
    raise ValueError(u"curva 2D fora da cobertura: {0}".format(item[u"tipo"]))


def _perfil_2d(lacos):
    u"""Perfil local do spec -> CurveArrArray no plano XY (o que
    NewCurveLoopsProfile exige — ele mesmo transporta para o plano certo)."""
    perfil = CurveArrArray()
    for laco in lacos:
        curvas = CurveArray()
        for item in laco:
            curvas.Append(_curva_2d(item))
        perfil.Append(curvas)
    return perfil


def _criar_varredura(doc, item, plano_esboco):
    u"""Sweep: NewSweep(isSolid, caminho, planoDoCaminho, SweepProfile, 0, Start).

    O caminho vem em coordenadas de mundo; o perfil, em 2D local — o
    NewCurveLoopsProfile exige o perfil no plano XY e o transporta sozinho.
    Índice/posição do perfil não são legíveis na origem; 0/Start é o padrão do
    Family Editor e qualquer desvio aparece no volume do validador.
    """
    caminho = CurveArray()
    for curva in item[u"caminho"][0]:
        caminho.Append(_curva_do_spec(curva))

    perfil = doc.Application.Create.NewCurveLoopsProfile(
        _perfil_2d(item[u"perfil_local"]))

    return doc.FamilyCreate.NewSweep(
        bool(item[u"solido"]), caminho, plano_esboco,
        perfil, 0, ProfilePlaneLocation.Start,
    )


def _criar_mescla(doc, item, plano_esboco):
    u"""Blend: perfis do spec vêm no plano da base; a altura vem dos offsets.

    O Revit normaliza SEMPRE os dois esboços para o plano da base, com as
    alturas em FirstEnd/SecondEnd — o leitor grava assim. Mas o NewBlend
    exige o perfil de topo já na cota real (dois perfis no mesmo plano =
    altura zero = "Unexpected internal error: code 1"). Então cada perfil é
    TRANSLADADO ao longo da normal do plano pelo seu offset antes da criação;
    o Revit renormaliza ao ingerir e FirstEnd/SecondEnd saem certos.
    """
    normal = _vetor(item[u"plano_de_esboco"][u"normal"])
    deslocamento_topo = item.get(u"deslocamento_topo")
    deslocamento_base = item.get(u"deslocamento_base") or 0.0

    if deslocamento_topo is None:
        _pular(u"forma #{0} (mescla)".format(item[u"indice"]),
               u"spec sem SecondEnd — altura do blend indeterminável")
        return None
    if abs(deslocamento_topo - deslocamento_base) < 1e-9:
        _pular(u"forma #{0} (mescla)".format(item[u"indice"]),
               u"blend de altura zero (SecondEnd == FirstEnd)")
        return None

    base = _laco_transladado(
        item[u"perfil_base"], normal, deslocamento_base,
        u"mescla/base", item[u"indice"])
    topo = _laco_transladado(
        item[u"perfil_topo"], normal, deslocamento_topo,
        u"mescla/topo", item[u"indice"])
    if base is None or topo is None:
        return None

    return doc.FamilyCreate.NewBlend(
        bool(item[u"solido"]), topo, base, plano_esboco)


def _laco_transladado(perfil_spec, normal, deslocamento_mm, rotulo, indice):
    u"""CurveArray do laço único, transladado pela normal * offset."""
    if len(perfil_spec) != 1:
        _pular(u"forma #{0} ({1})".format(indice, rotulo),
               u"perfil com {0} laços; Blend exige 1".format(len(perfil_spec)))
        return None
    vetor = normal.Multiply(mm(deslocamento_mm)) if deslocamento_mm else None
    transformacao = Transform.CreateTranslation(vetor) if vetor is not None else None
    curvas = CurveArray()
    for item in perfil_spec[0]:
        curva = _curva_do_spec(item)
        if transformacao is not None:
            curva = curva.CreateTransformed(transformacao)
        curvas.Append(curva)
    return curvas


def _criar_varredura_mesclada(doc, item, plano_esboco):
    u"""SweptBlend: NewSweptBlend(isSolid, curva, plano, perfilBase, perfilTopo)."""
    caminho = _curva_do_spec(item[u"caminho"][0][0])
    base = doc.Application.Create.NewCurveLoopsProfile(
        _perfil_2d(item[u"perfil_base"]))
    topo = doc.Application.Create.NewCurveLoopsProfile(
        _perfil_2d(item[u"perfil_topo"]))
    return doc.FamilyCreate.NewSweptBlend(
        bool(item[u"solido"]), caminho, plano_esboco, base, topo)


def _criar_revolucao(doc, item, perfil, plano_esboco):
    u"""Revolução a partir do spec.

    `NewRevolution(isSolid, profile, sketchPlane, axis, startAngle, endAngle)`
    — ângulos em RADIANOS (adimensionais, não passam por conversão de unidade)
    e o eixo precisa estar no mesmo plano dos laços do perfil.
    """
    eixo = item.get(u"eixo")
    if not eixo:
        _pular(u"forma #{0} (revolucao)".format(item[u"indice"]),
               u"spec sem eixo — o leitor não conseguiu lê-lo")
        return None

    angulo_inicial = item.get(u"angulo_inicial")
    angulo_final = item.get(u"angulo_final")
    if angulo_inicial is None or angulo_final is None:
        _pular(u"forma #{0} (revolucao)".format(item[u"indice"]),
               u"spec sem ângulo inicial ou final")
        return None

    try:
        return doc.FamilyCreate.NewRevolution(
            bool(item[u"solido"]),
            perfil,
            plano_esboco,
            Line.CreateBound(_xyz(eixo[u"inicio"]), _xyz(eixo[u"fim"])),
            float(angulo_inicial),
            float(angulo_final),
        )
    except Exception as erro:
        _pular(u"forma #{0} (revolucao)".format(item[u"indice"]),
               unicode(erro)[:160])  # noqa: F821
        return None


def _perfil_do_spec(lacos):
    perfil = CurveArrArray()
    for laco in lacos:
        curvas = CurveArray()
        for item in laco:
            curvas.Append(_curva_do_spec(item))
        perfil.Append(curvas)
    return perfil


def construir_formas(doc, vista, especificacao, planos, parametros):
    u"""Recria as formas NA ORDEM da origem, travando e associando cada uma
    antes de criar a próxima. Retorna índice -> elemento.

    Replay fiel da linha do tempo da fixture: sólido -> alinhamentos do
    sólido -> associação da altura -> vazio -> (combinação, fora daqui).

    Por que o entrelaçamento importa (bug do corte que encolhia no flex):
    o esboço de uma forma sem restrições explícitas é posicionado por
    restrições AUTOMÁTICAS que o solver cria com base no estado do documento
    no instante em que a forma nasce — estado que o FamilySpec não captura,
    porque não é legível pela API como elemento. Na fixture o vazio nasce num
    modelo já resolvido (sólido alinhado aos planos, altura associada); na
    versão anterior deste construtor ele nascia num modelo solto (sólido sem
    alinhamento, parâmetros sem valor), e as âncoras automáticas do seu
    esboço caíam em referências que se movem no flex. Resultado medido, com
    FamilySpec idêntico ao da origem: corte inteiro num tipo, meio corte no
    Medio, corte nenhum no Pequeno.
    """
    mapa = {}
    aplicados = set()

    # Alinhamentos que só referenciam planos (nenhuma face de forma) vêm
    # antes de qualquer forma, como teriam vindo na origem.
    _aplicar_alinhamentos_elegiveis(doc, vista, especificacao, planos, mapa, aplicados)

    for item in especificacao[u"formas"]:
        plano_geometrico = Plane.CreateByNormalAndOrigin(
            _vetor(item[u"plano_de_esboco"][u"normal"]),
            _xyz(item[u"plano_de_esboco"][u"origem"]),
        )
        plano_esboco = SketchPlane.Create(doc, plano_geometrico)

        # Uma forma que falhe na reconstrução NÃO derruba a família: vira
        # lacuna com o erro real — mesma regra do leitor.
        try:
            if item[u"tipo"] == u"extrusao":
                # O último argumento de NewExtrusion é o OFFSET FINAL, não a
                # altura. Passar a diferença (final - inicial) fazia o vazio
                # terminar em 1500 onde a origem terminava em 1400.
                forma = doc.FamilyCreate.NewExtrusion(
                    bool(item[u"solido"]),
                    _perfil_do_spec(item[u"perfil"]),
                    plano_esboco,
                    mm(item[u"deslocamento_final"]),
                )
                if item[u"deslocamento_inicial"]:
                    parametro = forma.get_Parameter(
                        BuiltInParameter.EXTRUSION_START_PARAM)
                    if parametro:
                        parametro.Set(mm(item[u"deslocamento_inicial"]))

            elif item[u"tipo"] == u"revolucao":
                forma = _criar_revolucao(
                    doc, item, _perfil_do_spec(item[u"perfil"]), plano_esboco)

            elif item[u"tipo"] == u"varredura":
                forma = _criar_varredura(doc, item, plano_esboco)

            elif item[u"tipo"] == u"mescla":
                forma = _criar_mescla(doc, item, plano_esboco)

            elif item[u"tipo"] == u"varredura_mesclada":
                forma = _criar_varredura_mesclada(doc, item, plano_esboco)

            else:
                _pular(u"forma #{0} ({1})".format(item[u"indice"], item[u"tipo"]),
                       u"tipo de forma ainda sem suporte no construtor")
                continue
        except Exception as erro:
            _pular(u"forma #{0} ({1})".format(item[u"indice"], item[u"tipo"]),
                   unicode(erro)[:160])  # noqa: F821
            continue

        if forma is None:
            continue

        mapa[item[u"indice"]] = forma
        _aplicar_subcategoria_e_visibilidade(doc, item, forma)
        doc.Regenerate()

        # Trava e associa ESTA forma antes de a próxima nascer, como na
        # fixture. As cotas já estão rotuladas (armadilha conhecida: rotular
        # antes de alinhar), e a associação vem depois do alinhamento —
        # exatamente a sequência comprovadamente boa.
        _aplicar_alinhamentos_elegiveis(doc, vista, especificacao, planos, mapa, aplicados)
        _associar_parametros_da_forma(doc, item, forma, parametros)
        doc.Regenerate()

    # Nunca silencioso: alinhamento que ficou sem vez é porque referencia
    # forma que não foi reconstruída.
    for indice, item in enumerate(especificacao[u"alinhamentos"]):
        if indice not in aplicados:
            _pular(u"alinhamento #{0}".format(indice),
                   u"referencia forma que não foi reconstruída")

    return mapa


# --------------------------------------------------------------------------
# 4. Resolução de endereços — o inverso exato do leitor
# --------------------------------------------------------------------------

def _face_por_endereco(elemento, endereco):
    u"""Reencontra a face planar pela normal gravada no spec."""
    normal_alvo = _vetor(endereco[u"normal"])

    opcoes = Options()
    opcoes.ComputeReferences = True  # sem isso Face.Reference vem nulo
    opcoes.IncludeNonVisibleObjects = False

    for objeto in elemento.get_Geometry(opcoes):
        if not isinstance(objeto, Solid):
            continue
        for face in objeto.Faces:
            if isinstance(face, PlanarFace) and face.FaceNormal.IsAlmostEqualTo(normal_alvo):
                return face
    return None


def _resolver_referencia(endereco, planos, formas):
    u"""Endereço portável do spec -> Reference no documento novo."""
    if endereco[u"tipo"] == u"plano":
        plano = planos.get(endereco[u"nome"])
        return plano.GetReference() if plano else None

    if endereco[u"tipo"] == u"face":
        elemento = formas.get(endereco[u"forma"])
        if elemento is None:
            return None
        face = _face_por_endereco(elemento, endereco)
        return face.Reference if face is not None else None

    return None


# --------------------------------------------------------------------------
# 5. Cotas rotuladas e alinhamentos
# --------------------------------------------------------------------------

def _linha_para_cota(referencias_spec, planos):
    u"""Linha de posicionamento da cota, derivada dos planos que ela mede.

    A posição exata é estética; o que importa é a direção correta. Desloca
    800 mm para fora para não sobrepor a geometria.
    """
    pontos = []
    normal = None
    for endereco in referencias_spec:
        if endereco[u"tipo"] == u"plano":
            plano = planos.get(endereco[u"nome"])
            if plano is not None:
                pontos.append(plano.BubbleEnd)
                normal = normal or plano.Normal
    if len(pontos) < 2:
        return None

    afastamento = mm(800.0)
    inicio, fim = pontos[0], pontos[1]
    # A direção sai da NORMAL dos planos (paralelos), não da posição das
    # pontas de bolha: o plano Center do template tem a bolha onde o template
    # quis, e comparar pontas de planos de origens diferentes podia escolher a
    # direção errada (cota entre o Center e um plano gerado pelo gerador).
    if abs(normal.X) >= abs(normal.Y):
        # Planos afastados em X -> cota horizontal, deslocada em -Y.
        return Line.CreateBound(
            XYZ(inicio.X, -afastamento, 0.0), XYZ(fim.X, -afastamento, 0.0)
        )
    return Line.CreateBound(
        XYZ(-afastamento, inicio.Y, 0.0), XYZ(-afastamento, fim.Y, 0.0)
    )


def construir_cotas(doc, vista, especificacao, planos, parametros):
    u"""Cotas rotuladas: onde o flex é religado (dim.FamilyLabel)."""
    for indice, item in enumerate(especificacao[u"cotas"]):
        if item.get(u"forma") in (u"Radial", u"Diameter"):
            continue  # nasce depois da forma (construir_cotas_radiais)
        rotulo = item.get(u"rotulo")

        referencias = ReferenceArray()
        completo = True
        for endereco in item[u"referencias"]:
            referencia = _resolver_referencia(endereco, planos, {})
            if referencia is None:
                completo = False
                break
            referencias.Append(referencia)

        if not completo:
            _pular(u"cota #{0} (rótulo={1})".format(indice, rotulo),
                   u"referência não reencontrada no destino")
            continue

        linha = _linha_para_cota(item[u"referencias"], planos)
        if linha is None:
            _pular(u"cota #{0} (rótulo={1})".format(indice, rotulo),
                   u"não foi possível derivar a linha de posicionamento")
            continue

        cota = doc.FamilyCreate.NewDimension(vista, linha, referencias)

        if rotulo:
            parametro = parametros.get(rotulo)
            if parametro is not None:
                cota.FamilyLabel = parametro  # <- a peça central do projeto
            else:
                _pular(u"rótulo da cota #{0}".format(indice),
                       u"parâmetro '{0}' não existe no destino".format(rotulo))

    doc.Regenerate()


def _aplicar_subcategoria_e_visibilidade(doc, item, forma):
    u"""Subcategoria pelo NOME (criada se não existir) e visibilidade fixa.

    O leitor sempre gravou os dois campos e o construtor os ignorava: a forma
    saía na subcategoria padrão e visível. A API foi provada na sonda S6 da G0.
    A visibilidade dirigida por parâmetro continua vindo das associações.
    """
    nome = item.get(u"subcategoria")
    if nome:
        try:
            categoria = doc.OwnerFamily.FamilyCategory
            subcategoria = None
            for existente in categoria.SubCategories:
                if existente.Name == nome:
                    subcategoria = existente
                    break
            if subcategoria is None:
                subcategoria = doc.Settings.Categories.NewSubcategory(categoria, nome)
            forma.Subcategory = subcategoria
        except Exception as erro:
            _pular(u"subcategoria '{0}' da forma #{1}".format(nome, item[u"indice"]),
                   unicode(erro)[:140])  # noqa: F821
    # Visibilidade associada a parâmetro (cópia de array do gerador, ou família
    # real com "Visible" ligado a sim/não) vem pela associação; fixar o valor
    # aqui é recusado pelo Revit e não muda nada.
    associada = any((a or {}).get(u"builtin") == u"IS_VISIBLE_PARAM"
                    for a in (item.get(u"associacoes") or {}).values())
    if item.get(u"visivel") is False and not associada:
        try:
            forma.Visible = False
        except Exception as erro:
            _pular(u"visibilidade da forma #{0}".format(item[u"indice"]),
                   unicode(erro)[:140])  # noqa: F821


def construir_cotas_radiais(doc, vista, especificacao, formas, parametros):
    u"""Cota radial rotulada na curva do ESBOÇO de uma forma (schema 0.2.0).

    Provado na sonda S2-A2 da G0 (docs/G0-resultado.md): a cota na aresta do
    sólido dá "Constraints are not satisfied", e a revolução não alinha com
    plano. A referência que funciona é `Extrusion.Sketch.Profile[laço][curva]`.
    """
    for indice, item in enumerate(especificacao[u"cotas"]):
        if item.get(u"forma") not in (u"Radial", u"Diameter"):
            continue
        rotulo = item.get(u"rotulo")
        endereco = item[u"referencias"][0]
        if endereco.get(u"tipo") != u"esboco":
            _pular(u"cota {0} #{1} (rótulo={2})".format(item[u"forma"], indice, rotulo),
                   u"referência fora do esboço (só a curva do esboço é endereçável)")
            continue
        forma = formas.get(endereco[u"forma"])
        if forma is None:
            _pular(u"cota radial #{0} (rótulo={1})".format(indice, rotulo),
                   u"forma não foi reconstruída")
            continue
        try:
            laco = list(forma.Sketch.Profile)[endereco[u"laco"]]
            curva = list(laco)[endereco[u"curva"]]
            centro = curva.Center
            origem = XYZ(centro.X + curva.Radius * 0.7, centro.Y + curva.Radius * 0.7, 0.0)
            if item[u"forma"] == u"Diameter":
                cota = doc.FamilyCreate.NewDiameterDimension(vista, curva.Reference, origem)
            else:
                cota = doc.FamilyCreate.NewRadialDimension(vista, curva.Reference, origem)
            parametro = parametros.get(rotulo)
            if parametro is None:
                _pular(u"rótulo da cota radial #{0}".format(indice),
                       u"parâmetro '{0}' não existe no destino".format(rotulo))
                continue
            cota.FamilyLabel = parametro
        except Exception as erro:
            _pular(u"cota radial #{0} (rótulo={1})".format(indice, rotulo),
                   unicode(erro)[:160])  # noqa: F821

    doc.Regenerate()


def construir_combinacoes(doc, especificacao, formas):
    u"""Reaplica os cortes de vazio da origem.

    Recriar a forma de vazio não basta: sem o CombineElements o vazio fica
    INERTE, e a família sai com o bounding box certo e o volume errado — o
    sintoma que o validador reporta como VOLUME_DIVERGE.
    """
    for indice, item in enumerate(especificacao.get(u"combinacoes", [])):
        elementos = [formas.get(posicao) for posicao in item[u"formas"]]
        if any(elemento is None for elemento in elementos) or len(elementos) < 2:
            _pular(u"combinação #{0}".format(indice),
                   u"forma membro não foi reconstruída")
            continue

        combinaveis = CombinableElementArray()
        for elemento in elementos:
            combinaveis.Append(elemento)

        try:
            doc.CombineElements(combinaveis)
        except Exception as erro:
            _pular(u"combinação #{0}".format(indice), unicode(erro))  # noqa: F821

    doc.Regenerate()


def _aplicar_alinhamentos_elegiveis(doc, vista, especificacao, planos, formas, aplicados):
    u"""Aplica os alinhamentos cujas formas referenciadas já foram criadas.

    Trava as faces das formas nos planos — sem isso o parâmetro muda e o
    sólido fica parado. Chamada uma vez após cada forma nascer: assim cada
    alinhamento é criado o mais cedo possível, imediatamente depois da última
    forma de que depende — a mesma posição relativa que ele ocupava na linha
    do tempo de criação da origem. `aplicados` acumula os índices já
    tratados entre as chamadas.
    """
    aplicou = False
    for indice, item in enumerate(especificacao[u"alinhamentos"]):
        if indice in aplicados:
            continue

        pendente = False
        for endereco in item[u"referencias"]:
            if endereco[u"tipo"] == u"face" and endereco[u"forma"] not in formas:
                pendente = True
                break
        if pendente:
            continue  # a forma de que depende ainda não nasceu

        aplicados.add(indice)

        # A ORDEM das referências decide quem é âncora e quem se move:
        # NewAlignment(vista, ancora, movel). E `Dimension.References` do
        # leitor NÃO devolve a ordem de criação — o Revit guarda numa ordem
        # própria, que varia entre alinhamentos da mesma família.
        #
        # Reproduzir a ordem lida invertia a âncora em parte dos alinhamentos:
        # o sólido passava a encolher pela esquerda em vez de pela direita, o
        # vazio (parado) deixava de intersectar, e o corte sumia nos tipos
        # menores. Por isso a ordem é NORMALIZADA aqui: o plano de referência é
        # sempre a âncora, a face do sólido é sempre quem se alinha — que é a
        # semântica correta de datum e a que a origem usa.
        enderecos = sorted(
            item[u"referencias"],
            key=lambda endereco: 0 if endereco[u"tipo"] == u"plano" else 1,
        )

        resolvidas = []
        for endereco in enderecos:
            referencia = _resolver_referencia(endereco, planos, formas)
            if referencia is None:
                resolvidas = None
                break
            resolvidas.append(referencia)

        if not resolvidas or len(resolvidas) < 2:
            _pular(u"alinhamento #{0}".format(indice),
                   u"referência não reencontrada no destino")
            continue

        doc.FamilyCreate.NewAlignment(vista, resolvidas[0], resolvidas[1])
        aplicou = True

    if aplicou:
        doc.Regenerate()


# --------------------------------------------------------------------------
# 6. Associações e 7. Tipos
# --------------------------------------------------------------------------

def _parametro_do_elemento(elemento, nome_localizado, nome_builtin):
    u"""Reencontra no elemento reconstruído o parâmetro a associar.

    Dois caminhos, na ordem de confiabilidade:

    1. BuiltInParameter resolvido POR NOME ("MATERIAL_ID_PARAM" etc.), que o
       leitor gravou. É estável entre idiomas e versões. Era uma whitelist de
       2 entradas — 17 dos 32 itens do primeiro relatório real eram
       associações recusadas por ela.
    2. LookupParameter pelo nome localizado, para o que não é builtin. Vale
       porque origem e destino usam templates no mesmo idioma; se divergirem,
       cai na lacuna e o relatório mostra.
    """
    if nome_builtin and nome_builtin != u"INVALID":
        builtin = getattr(BuiltInParameter, nome_builtin, None)
        if builtin is not None:
            parametro = elemento.get_Parameter(builtin)
            if parametro is not None:
                return parametro

    if nome_localizado:
        try:
            return elemento.LookupParameter(nome_localizado)
        except Exception:
            return None
    return None


def _associar_parametros_da_forma(doc, item, elemento, parametros):
    u"""Associações de parâmetro de UMA forma (o 2º mecanismo de flex).

    Roda logo após a forma nascer e ser alinhada, espelhando a fixture — na
    origem a altura do sólido foi associada ANTES de o vazio existir.
    """
    gerenciador = doc.FamilyManager
    for nome_parametro, associacao in item.get(u"associacoes", {}).items():
        alvo = parametros.get(associacao[u"parametro_de_familia"])
        if alvo is None:
            _pular(u"associação '{0}' da forma #{1}".format(
                    nome_parametro, item[u"indice"]),
                   u"parâmetro de família '{0}' não existe no destino".format(
                       associacao[u"parametro_de_familia"]))
            continue

        parametro_elemento = _parametro_do_elemento(
            elemento, nome_parametro, associacao.get(u"builtin"))
        if parametro_elemento is None:
            _pular(u"associação '{0}' da forma #{1}".format(
                    nome_parametro, item[u"indice"]),
                   u"parâmetro do elemento não encontrado no destino")
            continue

        try:
            gerenciador.AssociateElementParameterToFamilyParameter(
                parametro_elemento, alvo
            )
        except Exception as erro:
            _pular(u"associação '{0}' da forma #{1}".format(
                    nome_parametro, item[u"indice"]),
                   unicode(erro)[:140])  # noqa: F821


def _nomes_de_comprimento(especificacao):
    u"""Nomes dos parâmetros de comprimento — o spec grava esses em mm."""
    nomes = set()
    for item in especificacao[u"parametros"]:
        if rfaspec.eh_comprimento(item.get(u"tipo_de_dado")):
            nomes.add(item[u"nome"])
    return nomes


def _aplicar_valores_do_tipo(gerenciador, tipo, parametros, de_comprimento):
    u"""Aplica os valores de um tipo ao tipo CORRENTE (mm -> interno).

    O despacho é pelo StorageType REAL do parâmetro no destino, não pelo tipo
    Python do valor. Despachar pelo valor mandava um int para parâmetro de
    Material (StorageType.ElementId) e estourava "The storage type of family
    parameter is not a double type or integer type" — 4 itens do primeiro
    relatório real.

    ElementId é pulado de propósito, com registro: o valor da origem é um id
    de Material/Imagem daquele documento, e ids não atravessam documentos.
    Reproduzir materiais de verdade é transportá-los por NOME — trabalho
    próprio, futuro, não um Set.
    """
    for nome, valor in tipo[u"valores"].items():
        if valor is None:
            continue
        parametro = parametros.get(nome)
        if parametro is None or parametro.IsDeterminedByFormula:
            continue

        armazenamento = parametro.StorageType
        try:
            if armazenamento == StorageType.Double:
                if nome in de_comprimento:
                    gerenciador.Set(parametro, mm(valor))
                elif isinstance(valor, (int, long, float)):  # noqa: F821
                    gerenciador.Set(parametro, float(valor))
                else:
                    _pular(u"valor '{0}' do tipo '{1}'".format(nome, tipo[u"nome"]),
                           u"esperava número, spec trouxe {0}".format(
                               type(valor).__name__))
            elif armazenamento == StorageType.Integer:
                if isinstance(valor, (int, long, float)):  # noqa: F821
                    gerenciador.Set(parametro, int(valor))
                else:
                    _pular(u"valor '{0}' do tipo '{1}'".format(nome, tipo[u"nome"]),
                           u"esperava inteiro, spec trouxe {0}".format(
                               type(valor).__name__))
            elif armazenamento == StorageType.String:
                gerenciador.Set(parametro, unicode(valor))  # noqa: F821
            else:
                # StorageType.ElementId (Material, Imagem...)
                _pular(u"valor '{0}' do tipo '{1}'".format(nome, tipo[u"nome"]),
                       u"referência a elemento (id não atravessa documentos); "
                       u"transporte por nome fica para a fase de materiais")
        except Exception as erro:
            _pular(u"valor '{0}' do tipo '{1}'".format(nome, tipo[u"nome"]),
                   unicode(erro)[:140])  # noqa: F821


def estabelecer_tipo_corrente(doc, especificacao, parametros):
    u"""Cria PRIMEIRO o tipo corrente da origem, com valores, antes da geometria.

    Espelha o passo 1 da fixture (NewType + Set antes de planos, cotas e
    formas) e garante duas coisas:

    - FamilyManager.Set exige tipo corrente (armadilha conhecida), então o
      documento passa a aceitar valores desde já;
    - o leitor serializa TODA a geometria (planos, perfis, deslocamentos) na
      configuração do tipo corrente da origem. Reconstruir essa geometria num
      documento parado na MESMA configuração faz plano, cota e face nascerem
      consistentes entre si — nada flexiona durante a construção. Antes, a
      geometria nascia num documento sem tipo nenhum e as cotas eram
      rotuladas sobre parâmetros sem valor: um estado que a fixture nunca
      exercitou e que deixava o solver livre para ancorar esboços onde
      quisesse.

    Retorna o nome do tipo criado, ou None se o spec não tem tipos.
    """
    tipos = especificacao[u"tipos"]
    if not tipos:
        return None

    nome = especificacao.get(u"tipo_corrente")
    tipo = None
    for candidato in tipos:
        if candidato[u"nome"] == nome:
            tipo = candidato
            break
    if tipo is None:
        # Spec antigo (sem tipo_corrente) ou nome não reencontrado: usar o
        # primeiro tipo é melhor esforço — e nunca silencioso.
        tipo = tipos[0]
        _pular(u"tipo corrente '{0}'".format(nome),
               u"não identificado no spec; geometria construída no tipo "
               u"'{0}'".format(tipo[u"nome"]))

    gerenciador = doc.FamilyManager
    gerenciador.NewType(tipo[u"nome"])  # vira o tipo corrente
    _aplicar_valores_do_tipo(gerenciador, tipo, parametros,
                             _nomes_de_comprimento(especificacao))
    doc.Regenerate()
    return tipo[u"nome"]


def construir_tipos(doc, especificacao, parametros, ja_criado=None):
    u"""Recria os DEMAIS tipos com os valores por parâmetro (mm -> interno).

    O tipo corrente da origem já foi criado antes da geometria (ver
    estabelecer_tipo_corrente) e é pulado aqui — NewType com nome repetido
    falha.
    """
    gerenciador = doc.FamilyManager
    de_comprimento = _nomes_de_comprimento(especificacao)

    for tipo in especificacao[u"tipos"]:
        if tipo[u"nome"] == ja_criado:
            continue

        # Um tipo ruim não pode derrubar a família inteira. Caso real do
        # acervo: uma família da Sodramar tem um tipo chamado " " (um espaço).
        # O Revit deixa esse tipo EXISTIR mas recusa criá-lo pela API, com
        # "The value cannot be empty. Parameter name: typeName".
        try:
            gerenciador.NewType(tipo[u"nome"])  # vira o tipo corrente
        except Exception as erro:
            _pular(u"tipo {0!r}".format(tipo[u"nome"]), unicode(erro)[:120])  # noqa: F821
            continue

        _aplicar_valores_do_tipo(gerenciador, tipo, parametros, de_comprimento)

    doc.Regenerate()


def _restaurar_tipo_corrente(doc, nome):
    u"""Deixa o documento salvo na mesma configuração da origem.

    Cosmético para o flex, essencial para diff: o leitor rodado sobre a
    família reconstruída serializa a geometria na configuração do tipo
    corrente — se o destino salvar parado em outro tipo, todas as coordenadas
    divergem e o diff de FamilySpec contra a origem vira ruído.
    """
    if not nome:
        return
    gerenciador = doc.FamilyManager
    for tipo in gerenciador.Types:
        if tipo.Name == nome:
            gerenciador.CurrentType = tipo
            doc.Regenerate()
            return


# --------------------------------------------------------------------------

def principal():
    caminho_spec = rfaspec.env("RFADG_SPEC", obrigatorio=True)
    destino = rfaspec.env("RFADG_SAIDA", obrigatorio=True)
    template = rfaspec.env("RFADG_TEMPLATE", obrigatorio=True)

    especificacao = rfaspec.ler_json(caminho_spec)

    if especificacao[u"versao_schema"] not in rfaspec.SCHEMAS_ACEITOS:
        raise ValueError(u"Schema {0} não suportado (aceitos: {1}).".format(
            especificacao[u"versao_schema"], u", ".join(rfaspec.SCHEMAS_ACEITOS)))

    app = _obter_app()
    doc = app.NewFamilyDocument(template)

    transacao = Transaction(doc, u"RFADG — reconstruir família")
    transacao.Start()
    try:
        vista = _vista_de_planta(doc)

        # Categoria antes de tudo: trocá-la depois de existir geometria e
        # parâmetros é bem mais arriscado.
        ajustar_categoria(doc, especificacao)

        parametros = construir_parametros(doc, especificacao)
        # Tipo corrente da origem PRIMEIRO: a geometria do spec foi
        # serializada nessa configuração e é reconstruída nela — o documento
        # nunca fica sem tipo/valores durante a construção, como na fixture.
        tipo_corrente = estabelecer_tipo_corrente(doc, especificacao, parametros)
        planos = construir_planos(doc, vista, especificacao)
        construir_cotas(doc, vista, especificacao, planos, parametros)
        # Cada forma nasce, é alinhada e associada antes de a próxima
        # existir — replay da linha do tempo da fixture (ver
        # construir_formas). O vazio só nasce com o sólido já resolvido.
        formas = construir_formas(doc, vista, especificacao, planos, parametros)
        construir_cotas_radiais(doc, vista, especificacao, formas, parametros)
        construir_combinacoes(doc, especificacao, formas)
        construir_tipos(doc, especificacao, parametros, tipo_corrente)
        # Fórmulas por último: exigem um tipo válido já existente.
        aplicar_formulas(doc, especificacao, parametros)
        # Salva na mesma configuração da origem, para o diff de FamilySpec
        # comparar coordenadas maçã com maçã.
        _restaurar_tipo_corrente(doc, tipo_corrente)

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

    log(u"Família reconstruída salva em {0}".format(destino))
    log(u"Itens não reproduzidos: {0}".format(len(_NAO_REPRODUZIDO)))

    relatorio = rfaspec.env("RFADG_RELATORIO")
    if relatorio:
        rfaspec.gravar_json(relatorio, {
            u"nao_reproduzido": _NAO_REPRODUZIDO,
            u"lacunas_da_origem": especificacao.get(u"lacunas", []),
        })


principal()

# -*- coding: utf-8 -*-
u"""FASE 0 — construtor: FamilySpec JSON -> .rfa nativo da versão de DESTINO.

Roda no Revit de DESTINO. Cria um family document novo a partir do template
recebido em RFADG_TEMPLATE e reconstrói a família descrita no FamilySpec:
planos de referência, parâmetros, cotas rotuladas, formas, alinhamentos,
associações e tipos.

A ordem de reconstrução importa e espelha a da fixture:
  parâmetros -> planos -> cotas rotuladas -> formas -> alinhamentos ->
  associações -> tipos
Rotular a cota ANTES de alinhar a geometria: alinhar primeiro faz o Revit
resolver a restrição contra valor fixo e a família não flexiona.

O modelo da linha de comando é só a portadora que dá boot no Revit.

    pyrevit run scripts/construtor.py <portadora.rfa> --revit=2023
"""

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
    FilteredElementCollector, View, ViewType, ReferencePlane,
    Options, Solid, PlanarFace,
    BuiltInParameter, SpecTypeId, GroupTypeId,
)

mm = rfaspec.mm_para_interno
log = rfaspec.log


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
_TIPOS_DE_DADO = {
    u"autodesk.spec.aec:length": SpecTypeId.Length,
    u"autodesk.spec.aec:area": SpecTypeId.Area,
    u"autodesk.spec.aec:volume": SpecTypeId.Volume,
    u"autodesk.spec.aec:angle": SpecTypeId.Angle,
    u"autodesk.spec:spec.string": SpecTypeId.String.Text,
    u"autodesk.spec:spec.bool": SpecTypeId.Boolean.YesNo,
    # O Revit grava inteiro de família como int64, não como int.
    u"autodesk.spec:spec.int64": SpecTypeId.Int.Integer,
    u"autodesk.spec:spec.int": SpecTypeId.Int.Integer,
    u"autodesk.spec:spec.number": SpecTypeId.Number,
    u"autodesk.spec.measurable:currency": SpecTypeId.Currency,
    u"autodesk.spec.reference:material": SpecTypeId.Reference.Material,
}

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


def construir_parametros(doc, especificacao):
    u"""Cria os parâmetros de família do spec. Retorna nome -> FamilyParameter."""
    gerenciador = doc.FamilyManager

    existentes = {}
    for parametro in gerenciador.Parameters:
        existentes[parametro.Definition.Name] = parametro

    mapa = dict(existentes)

    for item in especificacao[u"parametros"]:
        nome = item[u"nome"]
        if nome in existentes:
            continue  # builtin do template, nada a criar

        if item.get(u"compartilhado"):
            _pular(u"parâmetro compartilhado '{0}'".format(nome),
                   u"shared parameters ficam para a Fase 1")
            continue

        tipo_de_dado = _TIPOS_DE_DADO.get(rfaspec.especie_forge(item.get(u"tipo_de_dado")))
        if tipo_de_dado is None:
            _pular(u"parâmetro '{0}'".format(nome),
                   u"tipo de dado fora da cobertura da Fase 0: {0}".format(
                       item.get(u"tipo_de_dado")))
            continue

        grupo = _GRUPOS.get(rfaspec.especie_forge(item.get(u"grupo")), _GRUPO_PADRAO)

        criado = gerenciador.AddParameter(
            nome, grupo, tipo_de_dado, bool(item.get(u"de_instancia"))
        )
        mapa[nome] = criado

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
        except Exception as erro:
            _pular(u"fórmula de '{0}'".format(item[u"nome"]), unicode(erro))  # noqa: F821

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


def _perfil_do_spec(lacos):
    perfil = CurveArrArray()
    for laco in lacos:
        curvas = CurveArray()
        for item in laco:
            curvas.Append(_curva_do_spec(item))
        perfil.Append(curvas)
    return perfil


def construir_formas(doc, especificacao):
    u"""Recria as formas. Retorna índice -> elemento."""
    mapa = {}
    for item in especificacao[u"formas"]:
        if item[u"tipo"] != u"extrusao":
            _pular(u"forma #{0} ({1})".format(item[u"indice"], item[u"tipo"]),
                   u"Fase 0 cobre apenas extrusões")
            continue

        plano_geometrico = Plane.CreateByNormalAndOrigin(
            _vetor(item[u"plano_de_esboco"][u"normal"]),
            _xyz(item[u"plano_de_esboco"][u"origem"]),
        )
        plano_esboco = SketchPlane.Create(doc, plano_geometrico)

        # Altura provisória = a extensão nominal da origem; a associação de
        # parâmetro (passo 6) assume o controle em seguida.
        altura = mm(item[u"deslocamento_final"]) - mm(item[u"deslocamento_inicial"])

        extrusao = doc.FamilyCreate.NewExtrusion(
            bool(item[u"solido"]),
            _perfil_do_spec(item[u"perfil"]),
            plano_esboco,
            altura,
        )
        if item[u"deslocamento_inicial"]:
            parametro = extrusao.get_Parameter(BuiltInParameter.EXTRUSION_START_PARAM)
            if parametro:
                parametro.Set(mm(item[u"deslocamento_inicial"]))

        mapa[item[u"indice"]] = extrusao

    doc.Regenerate()
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
    for endereco in referencias_spec:
        if endereco[u"tipo"] == u"plano":
            plano = planos.get(endereco[u"nome"])
            if plano is not None:
                pontos.append(plano.BubbleEnd)
    if len(pontos) < 2:
        return None

    afastamento = mm(800.0)
    inicio, fim = pontos[0], pontos[1]
    if abs(inicio.X - fim.X) > abs(inicio.Y - fim.Y):
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


def construir_alinhamentos(doc, vista, especificacao, planos, formas):
    u"""Trava as faces das formas nos planos — sem isso o parâmetro muda e o
    sólido fica parado."""
    for indice, item in enumerate(especificacao[u"alinhamentos"]):
        resolvidas = []
        for endereco in item[u"referencias"]:
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

    doc.Regenerate()


# --------------------------------------------------------------------------
# 6. Associações e 7. Tipos
# --------------------------------------------------------------------------

_BUILTIN_ASSOCIAVEIS = {
    u"EXTRUSION_END_PARAM": BuiltInParameter.EXTRUSION_END_PARAM,
    u"EXTRUSION_START_PARAM": BuiltInParameter.EXTRUSION_START_PARAM,
}


def construir_associacoes(doc, especificacao, formas, parametros):
    gerenciador = doc.FamilyManager
    for item in especificacao[u"formas"]:
        elemento = formas.get(item[u"indice"])
        if elemento is None:
            continue
        for nome_parametro, associacao in item.get(u"associacoes", {}).items():
            builtin = _BUILTIN_ASSOCIAVEIS.get(associacao.get(u"builtin"))
            alvo = parametros.get(associacao[u"parametro_de_familia"])
            if builtin is None or alvo is None:
                _pular(u"associação '{0}' da forma #{1}".format(
                        nome_parametro, item[u"indice"]),
                       u"builtin fora da cobertura ou parâmetro ausente")
                continue
            parametro_elemento = elemento.get_Parameter(builtin)
            if parametro_elemento is None:
                _pular(u"associação '{0}'".format(nome_parametro),
                       u"parâmetro do elemento não encontrado no destino")
                continue
            gerenciador.AssociateElementParameterToFamilyParameter(
                parametro_elemento, alvo
            )
    doc.Regenerate()


def construir_tipos(doc, especificacao, parametros):
    u"""Recria os tipos com os valores por parâmetro (mm -> interno)."""
    gerenciador = doc.FamilyManager

    de_comprimento = set()
    for item in especificacao[u"parametros"]:
        if rfaspec.eh_comprimento(item.get(u"tipo_de_dado")):
            de_comprimento.add(item[u"nome"])

    for tipo in especificacao[u"tipos"]:
        gerenciador.NewType(tipo[u"nome"])  # vira o tipo corrente
        for nome, valor in tipo[u"valores"].items():
            if valor is None:
                continue
            parametro = parametros.get(nome)
            if parametro is None or parametro.IsDeterminedByFormula:
                continue
            try:
                if nome in de_comprimento:
                    gerenciador.Set(parametro, mm(valor))
                elif isinstance(valor, float):
                    gerenciador.Set(parametro, valor)
                elif isinstance(valor, (int, long)):  # noqa: F821
                    gerenciador.Set(parametro, valor)
                elif isinstance(valor, unicode):  # noqa: F821
                    gerenciador.Set(parametro, valor)
            except Exception as erro:
                _pular(u"valor '{0}' do tipo '{1}'".format(nome, tipo[u"nome"]),
                       unicode(erro))  # noqa: F821

    doc.Regenerate()


# --------------------------------------------------------------------------

def principal():
    caminho_spec = rfaspec.env("RFADG_SPEC", obrigatorio=True)
    destino = rfaspec.env("RFADG_SAIDA", obrigatorio=True)
    template = rfaspec.env("RFADG_TEMPLATE", obrigatorio=True)

    especificacao = rfaspec.ler_json(caminho_spec)

    if especificacao[u"versao_schema"] != rfaspec.SCHEMA_VERSION:
        raise ValueError(u"Schema {0} não suportado (esperado {1}).".format(
            especificacao[u"versao_schema"], rfaspec.SCHEMA_VERSION))

    app = _obter_app()
    doc = app.NewFamilyDocument(template)

    transacao = Transaction(doc, u"RFADG — reconstruir família")
    transacao.Start()
    try:
        vista = _vista_de_planta(doc)

        parametros = construir_parametros(doc, especificacao)
        planos = construir_planos(doc, vista, especificacao)
        construir_cotas(doc, vista, especificacao, planos, parametros)
        formas = construir_formas(doc, especificacao)
        construir_alinhamentos(doc, vista, especificacao, planos, formas)
        # Associar ANTES de combinar, espelhando a ordem da fixture (que é
        # comprovadamente correta). Combinar primeiro deixa a geometria da
        # combinação sem acompanhar o parâmetro associado depois: o corte
        # encolhe conforme o tipo em vez de atravessar o sólido inteiro.
        construir_associacoes(doc, especificacao, formas, parametros)
        construir_combinacoes(doc, especificacao, formas)
        construir_tipos(doc, especificacao, parametros)
        # Fórmulas por último: exigem um tipo válido já existente.
        aplicar_formulas(doc, especificacao, parametros)

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

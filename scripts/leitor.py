# -*- coding: utf-8 -*-
u"""FASE 0 — leitor: .rfa da versão de origem -> FamilySpec JSON neutro.

Roda no Revit de ORIGEM, com a família aberta como modelo ativo.

Princípio de endereçamento: objetos `Reference` do Revit não atravessam
documentos. Nada aqui grava ElementId como identidade. Planos de referência são
endereçados pelo NOME; faces de sólido, pelo par (índice da forma, normal).
É esse contrato que o construtor precisa conseguir reencontrar do outro lado.

O modelo passado na linha de comando é apenas a PORTADORA que dá boot no Revit;
a família de verdade chega em RFADG_ENTRADA e é aberta aqui. Isso existe porque
a detecção de versão do pyrevit CLI falha em .rfa gerado por API — e também
espelha produção, onde o plugin recebe o caminho do input e abre por conta.

    pyrevit run scripts/leitor.py <portadora.rfa> --revit=2025
"""

import os
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida. Rode via scripts/run_fase0.ps1.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

from Autodesk.Revit.DB import (  # noqa: E402
    FilteredElementCollector, ReferencePlane, Dimension, Extrusion, Revolution,
    GenericForm, GeomCombination, Line, Arc, PlanarFace, BuiltInCategory,
    BuiltInParameter, StorageType,
)

para_mm = rfaspec.interno_para_mm
log = rfaspec.log


def _abrir_familia(caminho):
    u"""Abre o .rfa alvo, ignorando o documento portadora."""
    if not os.path.isfile(caminho):
        raise IOError(u"Família de entrada não encontrada: {0}".format(caminho))
    return __revit__.Application.OpenDocumentFile(caminho)  # noqa: F821


def _id_valor(element_id):
    u"""Valor numérico de um ElementId.

    Revit 2024+ expõe `.Value` (long) e deprecou `.IntegerValue`. Os dois
    precisam funcionar porque o mesmo código roda de 2023 a 2026.
    """
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def _ponto(xyz):
    u"""XYZ interno -> lista de milímetros."""
    return [para_mm(xyz.X), para_mm(xyz.Y), para_mm(xyz.Z)]


def _vetor(xyz):
    u"""XYZ adimensional (normal, direção) -> lista crua, sem conversão."""
    return [xyz.X, xyz.Y, xyz.Z]


def _forge_id(forge_type_id):
    u"""ForgeTypeId -> string estável entre versões do Revit.

    São strings versionadas do tipo 'autodesk.spec.aec:length-2.0.0', que a
    Autodesk mantém compatíveis. É o que torna o FamilySpec neutro de versão —
    muito melhor que gravar o enum legado.
    """
    if forge_type_id is None:
        return None
    try:
        identificador = forge_type_id.TypeId
    except AttributeError:
        return None
    return identificador if identificador else None


# --------------------------------------------------------------------------
# Identidade da família
# --------------------------------------------------------------------------

_SINALIZADORES = [
    (u"work_plane_based", BuiltInParameter.FAMILY_WORK_PLANE_BASED),
    (u"sempre_vertical", BuiltInParameter.FAMILY_ALWAYS_VERTICAL),
    (u"corta_com_vazios", BuiltInParameter.FAMILY_ALLOW_CUT_WITH_VOIDS),
    (u"compartilhada", BuiltInParameter.FAMILY_SHARED),
]


def ler_identidade(doc):
    familia = doc.OwnerFamily
    categoria = familia.FamilyCategory

    sinalizadores = {}
    for rotulo, builtin in _SINALIZADORES:
        parametro = familia.get_Parameter(builtin)
        if parametro is not None:
            sinalizadores[rotulo] = bool(parametro.AsInteger())

    return {
        # O id da BuiltInCategory é estável entre versões; o nome é localizado
        # e não serve como identidade.
        u"categoria_id": _id_valor(categoria.Id),
        u"categoria_nome": categoria.Name,
        u"tipo_de_posicionamento": str(familia.FamilyPlacementType),
        u"sinalizadores": sinalizadores,
    }


# --------------------------------------------------------------------------
# Parâmetros e tipos
# --------------------------------------------------------------------------

def _valor_do_tipo(tipo_familia, parametro_familia):
    u"""Valor de um parâmetro num tipo, sem trocar o tipo corrente.

    FamilyType.As*() lê direto, então o leitor não precisa de transação nem
    de mexer em CurrentType — o documento fica intocado.
    """
    if not tipo_familia.HasValue(parametro_familia):
        return None

    armazenamento = parametro_familia.StorageType
    if armazenamento == StorageType.Double:
        valor = tipo_familia.AsDouble(parametro_familia)
        if valor is None:
            return None
        # Comprimentos viram mm; os demais Double (ângulo, número) ficam crus.
        # Comparação por espécie: o sufixo de versão do ForgeTypeId muda entre
        # versões do Revit (2.0.0 no 2023, 2.0.1 no 2025).
        if rfaspec.eh_comprimento(_forge_id(parametro_familia.Definition.GetDataType())):
            return para_mm(valor)
        return valor
    if armazenamento == StorageType.Integer:
        return tipo_familia.AsInteger(parametro_familia)
    if armazenamento == StorageType.String:
        return tipo_familia.AsString(parametro_familia)
    if armazenamento == StorageType.ElementId:
        identificador = tipo_familia.AsElementId(parametro_familia)
        return _id_valor(identificador) if identificador is not None else None
    return None


def _grupo_do_parametro(definicao):
    u"""Grupo do parâmetro como ForgeTypeId, com queda para o enum legado."""
    try:
        return _forge_id(definicao.GetGroupTypeId())
    except AttributeError:
        return None


def ler_parametros(doc):
    gerenciador = doc.FamilyManager

    parametros = []
    for parametro in gerenciador.Parameters:
        definicao = parametro.Definition
        parametros.append({
            u"nome": definicao.Name,
            u"tipo_de_dado": _forge_id(definicao.GetDataType()),
            u"grupo": _grupo_do_parametro(definicao),
            u"armazenamento": str(parametro.StorageType),
            u"de_instancia": bool(parametro.IsInstance),
            u"compartilhado": bool(parametro.IsShared),
            u"formula": parametro.Formula,
            u"dirigido_por_formula": bool(parametro.IsDeterminedByFormula),
            u"reporta": bool(parametro.IsReporting),
        })

    tipos = []
    for tipo_familia in gerenciador.Types:
        # O template traz um tipo anônimo que não deve virar tipo de verdade.
        if not tipo_familia.Name:
            continue
        valores = {}
        for parametro in gerenciador.Parameters:
            valores[parametro.Definition.Name] = _valor_do_tipo(tipo_familia, parametro)
        tipos.append({u"nome": tipo_familia.Name, u"valores": valores})

    return parametros, tipos


def ler_tipo_corrente(doc):
    u"""Nome do tipo corrente — a configuração em que o spec é serializado.

    Todos os valores geométricos do FamilySpec (posições de plano, perfis,
    deslocamentos de extrusão) são lidos no estado corrente do documento, ou
    seja, na configuração do tipo corrente. O construtor precisa recriar ESTE
    tipo e aplicar seus valores ANTES de construir a geometria, senão
    reconstrói coordenadas de uma configuração num documento parado em outra
    (ou em nenhuma — documento novo não tem tipo, e foi nesse vácuo que o
    corte de vazio perdeu o flex). Campo aditivo do schema; None quando o
    documento não tem tipo corrente nomeado.
    """
    try:
        tipo = doc.FamilyManager.CurrentType
    except Exception:
        return None
    if tipo is None:
        return None
    nome = tipo.Name
    return nome if nome else None


# --------------------------------------------------------------------------
# Esqueleto: planos de referência
# --------------------------------------------------------------------------

def ler_planos_de_referencia(doc):
    planos = []
    coletor = FilteredElementCollector(doc).OfClass(ReferencePlane)

    for plano in coletor.ToElements():
        # .Name protegido: em alguns contextos o acesso direto lança.
        nome = getattr(plano, "Name", None)
        if not nome:
            continue

        parametro_referencia = plano.get_Parameter(BuiltInParameter.ELEM_REFERENCE_NAME)
        planos.append({
            u"_id": _id_valor(plano.Id),  # só para ordenar; removido no fim
            u"nome": nome,
            u"canonico": rfaspec.eh_plano_canonico(nome),
            u"inicio": _ponto(plano.BubbleEnd),
            u"fim": _ponto(plano.FreeEnd),
            u"normal": _vetor(plano.Normal),
            u"eh_referencia": (
                parametro_referencia.AsInteger() if parametro_referencia else None
            ),
        })

    # Ordem de CRIAÇÃO (ElementId crescente), nunca alfabética. Numa cota
    # rotulada entre dois planos, o Revit mantém parado o plano criado antes e
    # move o outro. Ordenar por nome punha RFADG_Dir antes de RFADG_Esq no
    # destino, invertendo a âncora: o sólido encolhia pela esquerda em vez de
    # pela direita, e o vazio (parado) deixava de intersectá-lo.
    planos.sort(key=lambda item: item[u"_id"])
    for item in planos:
        del item[u"_id"]
    return planos


# --------------------------------------------------------------------------
# Formas sólidas
# --------------------------------------------------------------------------

def _curva_para_dicionario(curva):
    u"""Serializa uma curva do perfil. Fase 0 cobre Line e Arc."""
    if isinstance(curva, Line):
        return {
            u"tipo": u"linha",
            u"inicio": _ponto(curva.GetEndPoint(0)),
            u"fim": _ponto(curva.GetEndPoint(1)),
        }
    if isinstance(curva, Arc):
        return {
            u"tipo": u"arco",
            u"inicio": _ponto(curva.GetEndPoint(0)),
            u"fim": _ponto(curva.GetEndPoint(1)),
            u"meio": _ponto(curva.Evaluate(0.5, True)),
        }
    # Falha em voz alta: uma curva silenciosamente ignorada vira família errada.
    raise ValueError(
        u"Curva de perfil não suportada na Fase 0: {0}".format(type(curva).__name__)
    )


def _perfil_para_lista(perfil):
    u"""CurveArrArray -> lista de laços, cada laço uma lista de curvas."""
    lacos = []
    for laco in perfil:
        lacos.append([_curva_para_dicionario(curva) for curva in laco])
    return lacos


def _associacoes_de_parametro(gerenciador, elemento):
    u"""Parâmetros do elemento associados a parâmetros de família.

    É o segundo mecanismo de flex (o primeiro é a cota rotulada). A altura da
    extrusão normalmente chega por aqui.
    """
    associacoes = {}
    for parametro in elemento.Parameters:
        try:
            associado = gerenciador.GetAssociatedFamilyParameter(parametro)
        except Exception:
            continue
        if associado is None:
            continue
        definicao = parametro.Definition
        try:
            builtin = str(definicao.BuiltInParameter)
        except AttributeError:
            builtin = None
        associacoes[definicao.Name] = {
            u"parametro_de_familia": associado.Definition.Name,
            u"builtin": builtin,
        }
    return associacoes


def ler_formas(doc):
    u"""Formas do documento (sólidas e de vazio), em ordem determinística.

    A ordem importa: o índice na lista é a identidade da forma para o
    endereçamento de faces nas cotas e alinhamentos. Ordenar por ElementId dá
    a ordem de criação, então o vazio sai depois do sólido que ele corta — que
    é a ordem em que o construtor precisa recriá-los.

    Coleta TODA `GenericForm`, não só as suportadas. As sem suporte entram como
    lacuna em vez de sumir: coletar só extrusão fazia uma família cheia de
    sweeps virar um FamilySpec quase vazio, sem nada no relatório — exatamente
    o silêncio que o projeto promete nunca produzir.
    """
    gerenciador = doc.FamilyManager
    coletor = FilteredElementCollector(doc).OfClass(GenericForm)
    todas = sorted(coletor.ToElements(), key=lambda e: _id_valor(e.Id))

    formas = []
    indice_por_id = {}
    lacunas = []

    for elemento in todas:
        indice = len(formas)

        if isinstance(elemento, Extrusion):
            registro = _ler_extrusao(elemento)
        elif isinstance(elemento, Revolution):
            registro = _ler_revolucao(elemento)
        else:
            registro = None

        if registro is None:
            lacunas.append({
                u"elemento_id": _id_valor(elemento.Id),
                u"motivo": u"forma sem suporte: {0}".format(type(elemento).__name__),
            })
            continue

        subcategoria = elemento.Subcategory
        registro.update({
            u"indice": indice,
            u"solido": bool(elemento.IsSolid),
            u"visivel": bool(elemento.Visible),
            u"subcategoria": subcategoria.Name if subcategoria else None,
            u"associacoes": _associacoes_de_parametro(gerenciador, elemento),
        })
        formas.append(registro)
        indice_por_id[_id_valor(elemento.Id)] = indice

    return formas, indice_por_id, lacunas


def _plano_de_esboco(esboco):
    plano = esboco.SketchPlane.GetPlane()
    return {
        u"origem": _ponto(plano.Origin),
        u"normal": _vetor(plano.Normal),
    }


def _ler_extrusao(extrusao):
    esboco = extrusao.Sketch
    return {
        u"tipo": u"extrusao",
        u"deslocamento_inicial": para_mm(extrusao.StartOffset),
        u"deslocamento_final": para_mm(extrusao.EndOffset),
        u"plano_de_esboco": _plano_de_esboco(esboco),
        u"perfil": _perfil_para_lista(esboco.Profile),
    }


def _builtin(*nomes):
    u"""Resolve o primeiro BuiltInParameter que existir, pelo NOME.

    Enums de BuiltInParameter variam entre versões do Revit e nem todo nome
    plausível existe: `REVOLVE_START_ANGLE` não existe e derrubava o leitor
    inteiro com AttributeError — o Python avalia o argumento antes de chamar a
    função, então nem o fallback interno chegava a rodar. Resolver por nome,
    tarde, transforma isso num None inofensivo.
    """
    for nome in nomes:
        valor = getattr(BuiltInParameter, nome, None)
        if valor is not None:
            return valor
    return None


def _angulo_da_revolucao(revolucao, propriedade, *nomes_builtin):
    u"""Ângulo em radianos, pela propriedade ou pelo parâmetro builtin."""
    try:
        valor = getattr(revolucao, propriedade, None)
        if valor is not None:
            return float(valor)
    except Exception:
        pass

    builtin = _builtin(*nomes_builtin)
    if builtin is None:
        return None
    try:
        parametro = revolucao.get_Parameter(builtin)
    except Exception:
        return None
    return float(parametro.AsDouble()) if parametro is not None else None


def _eixo_da_revolucao(revolucao):
    u"""Eixo como par de pontos. Aceita Line ou elemento com GeometryCurve."""
    try:
        eixo = revolucao.Axis
    except Exception:
        return None
    if eixo is None:
        return None

    curva = eixo
    if not hasattr(curva, "GetEndPoint"):
        # Em algumas versões o eixo vem como ModelLine (elemento), não Line.
        curva = getattr(eixo, "GeometryCurve", None)
    if curva is None or not hasattr(curva, "GetEndPoint"):
        return None

    return {
        u"inicio": _ponto(curva.GetEndPoint(0)),
        u"fim": _ponto(curva.GetEndPoint(1)),
    }


def _ler_revolucao(revolucao):
    u"""Revolução: perfil girado em torno de um eixo no mesmo plano.

    Retorna None (vira lacuna) se o eixo não for legível — sem eixo não há
    como reconstruir, e inventar um produziria geometria errada em silêncio.
    """
    eixo = _eixo_da_revolucao(revolucao)
    if eixo is None:
        return None

    esboco = revolucao.Sketch
    return {
        u"tipo": u"revolucao",
        u"plano_de_esboco": _plano_de_esboco(esboco),
        u"perfil": _perfil_para_lista(esboco.Profile),
        u"eixo": eixo,
        # Radianos, adimensional — não passa por conversão de unidade.
        u"angulo_inicial": _angulo_da_revolucao(
            revolucao, "StartAngle",
            "REVOLUTION_START_ANGLE", "REVOLVE_START_ANGLE"),
        u"angulo_final": _angulo_da_revolucao(
            revolucao, "EndAngle",
            "REVOLUTION_END_ANGLE", "REVOLVE_END_ANGLE"),
    }


# --------------------------------------------------------------------------
# Cotas, rótulos e alinhamentos — o coração do flex
# --------------------------------------------------------------------------

def _endereco_da_referencia(doc, referencia, indice_por_id):
    u"""Traduz um Reference do Revit num endereço portável.

    Este é o ponto mais delicado do projeto: se o endereço não for reencontrável
    no documento de destino, a cota não é religada e a família não flexiona.
    Retorna None quando não há como endereçar — o chamador reporta como lacuna.
    """
    elemento = doc.GetElement(referencia.ElementId)
    if elemento is None:
        return None

    if isinstance(elemento, ReferencePlane):
        nome = getattr(elemento, "Name", None)
        if not nome:
            return None
        return {u"tipo": u"plano", u"nome": nome}

    indice_forma = indice_por_id.get(_id_valor(elemento.Id))
    if indice_forma is None:
        return None

    try:
        geometria = elemento.GetGeometryObjectFromReference(referencia)
    except Exception:
        return None

    if isinstance(geometria, PlanarFace):
        return {
            u"tipo": u"face",
            u"forma": indice_forma,
            u"normal": _vetor(geometria.FaceNormal),
            u"origem": _ponto(geometria.Origin),
        }

    return None


def ler_combinacoes(doc, indice_por_id):
    u"""Cortes de vazio (GeomCombination) como listas de índices de forma.

    Um vazio criado por API não corta sozinho: quem aplica o corte é
    `doc.CombineElements`, que cria um GeomCombination. Sem gravar isso aqui, o
    construtor recria o vazio mas ele fica INERTE no destino — a família sai
    com o bounding box certo e o volume errado.
    """
    combinacoes = []
    lacunas = []

    for combinacao in FilteredElementCollector(doc).OfClass(GeomCombination):
        try:
            membros = [_id_valor(membro.Id) for membro in combinacao.AllMembers]
        except Exception as erro:
            lacunas.append({
                u"elemento_id": _id_valor(combinacao.Id),
                u"motivo": u"AllMembers falhou: {0}".format(erro),
            })
            continue

        indices = [indice_por_id.get(identificador) for identificador in membros]
        if any(indice is None for indice in indices):
            lacunas.append({
                u"elemento_id": _id_valor(combinacao.Id),
                u"motivo": u"combinação inclui forma fora da cobertura do leitor",
            })
            continue

        combinacoes.append({u"formas": indices})

    return combinacoes, lacunas


def ler_cotas(doc, indice_por_id):
    u"""Cotas rotuladas e restrições de alinhamento.

    No Revit as duas coisas são elementos `Dimension`; o que as separa é a
    categoria — alinhamentos ficam em OST_Constraints.
    """
    id_restricoes = int(BuiltInCategory.OST_Constraints)

    cotas = []
    alinhamentos = []
    lacunas = []

    for dimensao in FilteredElementCollector(doc).OfClass(Dimension).ToElements():
        enderecos = []
        incompleta = False
        for referencia in dimensao.References:
            endereco = _endereco_da_referencia(doc, referencia, indice_por_id)
            if endereco is None:
                incompleta = True
                break
            enderecos.append(endereco)

        categoria = dimensao.Category
        eh_restricao = (
            categoria is not None and _id_valor(categoria.Id) == id_restricoes
        )

        if incompleta or len(enderecos) < 2:
            lacunas.append({
                u"elemento_id": _id_valor(dimensao.Id),
                u"eh_restricao": eh_restricao,
                u"motivo": u"referência não endereçável de forma portável",
            })
            continue

        if eh_restricao:
            # Alinhamentos travam pares de referências.
            alinhamentos.append({u"referencias": enderecos})
            continue

        rotulo = dimensao.FamilyLabel
        cotas.append({
            u"referencias": enderecos,
            u"rotulo": rotulo.Definition.Name if rotulo is not None else None,
            u"forma": str(dimensao.DimensionShape),
        })

    return cotas, alinhamentos, lacunas


# --------------------------------------------------------------------------

def principal():
    entrada = rfaspec.env("RFADG_ENTRADA", obrigatorio=True)
    destino = rfaspec.env("RFADG_SPEC", obrigatorio=True)

    doc = _abrir_familia(entrada)
    try:
        especificacao = extrair(doc)
    finally:
        doc.Close(False)

    rfaspec.gravar_json(destino, especificacao)
    _relatar(destino, especificacao)


def extrair(doc):
    if not doc.IsFamilyDocument:
        raise ValueError(
            u"O documento aberto não é uma família. Recebido: {0}".format(doc.Title)
        )

    parametros, tipos = ler_parametros(doc)
    formas, indice_por_id, lacunas_de_forma = ler_formas(doc)
    cotas, alinhamentos, lacunas = ler_cotas(doc, indice_por_id)
    combinacoes, lacunas_de_corte = ler_combinacoes(doc, indice_por_id)
    lacunas = lacunas_de_forma + lacunas + lacunas_de_corte

    especificacao = {
        u"versao_schema": rfaspec.SCHEMA_VERSION,
        u"origem": {
            u"arquivo": doc.Title,
            u"versao_revit": rfaspec.env("RFADG_ORIGEM_VERSAO", u"desconhecida"),
        },
        u"identidade": ler_identidade(doc),
        u"parametros": parametros,
        u"tipos": tipos,
        # Configuração em que TODA a geometria abaixo foi serializada.
        u"tipo_corrente": ler_tipo_corrente(doc),
        u"planos_de_referencia": ler_planos_de_referencia(doc),
        u"formas": formas,
        u"cotas": cotas,
        u"alinhamentos": alinhamentos,
        u"combinacoes": combinacoes,
        # Assinatura geométrica da origem, tipo a tipo. É contra ISTO que o
        # validador compara no destino — assim ele não precisa saber nada
        # sobre a geometria da família, só se ela reproduz a mesma coisa.
        u"medicoes": rfaspec.medir_por_tipo(doc),
        # Tudo que o leitor viu mas não soube endereçar. Nunca silencioso:
        # uma lacuna não reportada vira família incompleta entregue como boa.
        u"lacunas": lacunas,
    }

    return especificacao


def _relatar(destino, especificacao):
    parametros = especificacao[u"parametros"]
    tipos = especificacao[u"tipos"]
    formas = especificacao[u"formas"]
    cotas = especificacao[u"cotas"]
    alinhamentos = especificacao[u"alinhamentos"]
    lacunas = especificacao[u"lacunas"]

    log(u"FamilySpec gravado em {0}".format(destino))
    log(u"  parâmetros={0} tipos={1} planos={2} formas={3}".format(
        len(parametros), len(tipos),
        len(especificacao[u"planos_de_referencia"]), len(formas)))
    log(u"  cotas={0} alinhamentos={1} lacunas={2}".format(
        len(cotas), len(alinhamentos), len(lacunas)))

    if lacunas:
        log(u"ATENÇÃO: {0} referência(s) não endereçável(is).".format(len(lacunas)))


principal()

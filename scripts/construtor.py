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
    # Atenção ao prefixo: o Revit usa `aec:number` e `aec:material` em famílias
    # reais, NÃO `spec.number` nem `reference:material`. Confundir os dois fazia
    # o construtor pular parâmetros que existiam. As duas grafias ficam.
    u"autodesk.spec.aec:number": SpecTypeId.Number,
    u"autodesk.spec:spec.number": SpecTypeId.Number,
    u"autodesk.spec.aec:material": SpecTypeId.Reference.Material,
    u"autodesk.spec.reference:material": SpecTypeId.Reference.Material,
    u"autodesk.spec:spec.string": SpecTypeId.String.Text,
    u"autodesk.spec.string:url": SpecTypeId.String.Url,
    u"autodesk.spec:spec.bool": SpecTypeId.Boolean.YesNo,
    # O Revit grava inteiro de família como int64, não como int.
    u"autodesk.spec:spec.int64": SpecTypeId.Int.Integer,
    u"autodesk.spec:spec.int": SpecTypeId.Int.Integer,
    u"autodesk.spec.measurable:currency": SpecTypeId.Currency,
    u"autodesk.spec.reference:image": SpecTypeId.Reference.Image,
    # Espécies de MEP — o acervo P-LAB é de equipamento hidráulico, então
    # estas não são exóticas: aparecem em 25 de 25 famílias inventariadas.
    u"autodesk.spec.aec.piping:pipeSize": SpecTypeId.PipeSize,
    u"autodesk.spec.aec.piping:flow": SpecTypeId.Flow,
    u"autodesk.spec.aec.piping:temperature": SpecTypeId.PipingTemperature,
    u"autodesk.spec.aec.electrical:frequency": SpecTypeId.ElectricalFrequency,
    u"autodesk.spec.aec.electrical:potential": SpecTypeId.ElectricalPotential,
    u"autodesk.spec.aec.electrical:power": SpecTypeId.ElectricalPower,
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
        if item[u"tipo"] != u"extrusao":
            _pular(u"forma #{0} ({1})".format(item[u"indice"], item[u"tipo"]),
                   u"Fase 0 cobre apenas extrusões")
            continue

        plano_geometrico = Plane.CreateByNormalAndOrigin(
            _vetor(item[u"plano_de_esboco"][u"normal"]),
            _xyz(item[u"plano_de_esboco"][u"origem"]),
        )
        plano_esboco = SketchPlane.Create(doc, plano_geometrico)

        # O último argumento de NewExtrusion é o OFFSET FINAL, não a altura.
        # Passar a diferença (final - inicial) fazia o vazio terminar em 1500
        # onde a origem terminava em 1400.
        extrusao = doc.FamilyCreate.NewExtrusion(
            bool(item[u"solido"]),
            _perfil_do_spec(item[u"perfil"]),
            plano_esboco,
            mm(item[u"deslocamento_final"]),
        )
        if item[u"deslocamento_inicial"]:
            parametro = extrusao.get_Parameter(BuiltInParameter.EXTRUSION_START_PARAM)
            if parametro:
                parametro.Set(mm(item[u"deslocamento_inicial"]))

        mapa[item[u"indice"]] = extrusao
        doc.Regenerate()

        # Trava e associa ESTA forma antes de a próxima nascer, como na
        # fixture. As cotas já estão rotuladas (armadilha conhecida: rotular
        # antes de alinhar), e a associação vem depois do alinhamento —
        # exatamente a sequência comprovadamente boa.
        _aplicar_alinhamentos_elegiveis(doc, vista, especificacao, planos, mapa, aplicados)
        _associar_parametros_da_forma(doc, item, extrusao, parametros)
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

_BUILTIN_ASSOCIAVEIS = {
    u"EXTRUSION_END_PARAM": BuiltInParameter.EXTRUSION_END_PARAM,
    u"EXTRUSION_START_PARAM": BuiltInParameter.EXTRUSION_START_PARAM,
}


def _associar_parametros_da_forma(doc, item, elemento, parametros):
    u"""Associações de parâmetro de UMA forma (o 2º mecanismo de flex).

    Rodava em passada única depois de todas as formas existirem; agora roda
    logo após a forma nascer e ser alinhada, espelhando a fixture — na origem
    a altura do sólido foi associada ANTES de o vazio existir.
    """
    gerenciador = doc.FamilyManager
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


def _nomes_de_comprimento(especificacao):
    u"""Nomes dos parâmetros de comprimento — o spec grava esses em mm."""
    nomes = set()
    for item in especificacao[u"parametros"]:
        if rfaspec.eh_comprimento(item.get(u"tipo_de_dado")):
            nomes.add(item[u"nome"])
    return nomes


def _aplicar_valores_do_tipo(gerenciador, tipo, parametros, de_comprimento):
    u"""Aplica os valores de um tipo ao tipo CORRENTE (mm -> interno)."""
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
        gerenciador.NewType(tipo[u"nome"])  # vira o tipo corrente
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

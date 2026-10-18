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

import math
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


# Adaptação: o item EXISTE no destino com o mesmo comportamento, por outro
# caminho que a API exige (raio do conector pelo diâmetro, nome de tipo " ").
# Vai para o relatório, separado do que não foi reproduzido.
_ADAPTADO = []


def _adaptar(o_que, como):
    _ADAPTADO.append({u"item": o_que, u"como": como})
    log(u"ADAPTADO: {0} — {1}".format(o_que, como))


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
        # Comprimento de folha (OffsetHeight/OffsetWidth da luva de redução).
        (u"autodesk.spec.aec:sheetLength", u"SheetLength"),
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
            if item.get(u"embutido") and item[u"embutido"] != u"INVALID":
                # Parâmetro da categoria, com nome traduzido no destino: o
                # mesmo BuiltInParameter, achado pelo id, responde pelo nome
                # da origem (rótulos, fórmulas e valores seguem funcionando).
                achado = None
                for existente in gerenciador.Parameters:
                    try:
                        if str(existente.Definition.BuiltInParameter) == item[u"embutido"]:
                            achado = existente
                            break
                    except Exception:
                        pass
                if achado is not None:
                    mapa[nome] = achado
                else:
                    _pular(u"parâmetro '{0}'".format(nome),
                           u"embutido {0} não existe no destino (categoria?)".format(item[u"embutido"]))
                continue

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


def _csv_com_aspas_escapadas(conteudo):
    u"""Campo com aspa vai entre aspas, com a aspa interna dobrada.

    O Revit exporta bitola em polegada sem escapar (`1"`, `3/4"`) e, na volta,
    lê a aspa como delimitador: "IncorrectNumberOfColumns" na tabela da
    Solaris. Campo sem aspa fica byte a byte como veio.
    """
    linhas = []
    for linha in conteudo.split(u"\n"):
        fim = u"\r" if linha.endswith(u"\r") else u""
        campos = linha[:-1].split(u",") if fim else linha.split(u",")
        campos = [u'"' + c.replace(u'"', u'""') + u'"' if u'"' in c else c for c in campos]
        linhas.append(u",".join(campos) + fim)
    return u"\n".join(linhas)


def importar_tabelas_de_consulta(doc, especificacao):
    u"""Regrava cada CSV com os bytes da origem e importa (antes das fórmulas).

    ImportSizeTable usa o nome do ARQUIVO como nome da tabela, então cada uma
    vai para uma pasta própria com o nome exato.
    """
    tabelas = especificacao.get(u"tabelas_de_consulta") or []
    if not tabelas:
        return
    import tempfile
    from Autodesk.Revit.DB import FamilySizeTableErrorInfo, FamilySizeTableManager
    gerenciador = FamilySizeTableManager.GetFamilySizeTableManager(doc, doc.OwnerFamily.Id)
    if gerenciador is None:
        FamilySizeTableManager.CreateFamilySizeTableManager(doc, doc.OwnerFamily.Id)
        gerenciador = FamilySizeTableManager.GetFamilySizeTableManager(doc, doc.OwnerFamily.Id)
    for tabela in tabelas:
        pasta = tempfile.mkdtemp(prefix=u"rfadg_importar_")
        caminho = os.path.join(pasta, tabela[u"nome"] + u".csv")
        try:
            with open(caminho, "wb") as arquivo:
                arquivo.write(_csv_com_aspas_escapadas(tabela[u"conteudo"]))
            erro_info = FamilySizeTableErrorInfo()
            if not gerenciador.ImportSizeTable(doc, caminho, erro_info):
                _pular(u"tabela de consulta '{0}'".format(tabela[u"nome"]),
                       u"ImportSizeTable recusou: {0}".format(erro_info.FamilySizeTableErrorType))
        except Exception as erro:
            _pular(u"tabela de consulta '{0}'".format(tabela[u"nome"]), unicode(erro)[:140])  # noqa: F821


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

def _vista_para_normal(doc, normal, planta):
    u"""Vista em que um plano de normal `normal` aparece como LINHA.

    Plano vertical: a planta. Plano horizontal ou inclinado: a elevação cuja
    direção de vista é perpendicular à normal. Cota e alinhamento só nascem
    numa vista dessas (armadilha 9: em 3D falham em silêncio).
    """
    if abs(normal.Z) < 1e-6:
        return planta
    for vista in FilteredElementCollector(doc).OfClass(View).ToElements():
        if vista.IsTemplate or vista.ViewType != ViewType.Elevation:
            continue
        if abs(vista.ViewDirection.DotProduct(normal)) < 1e-6:
            return vista
    return None


def _plano_coincidente(candidatos, item):
    u"""Plano já existente com a mesma normal e passando pelo mesmo ponto."""
    normal = _vetor(item[u"normal"]).Normalize()
    ponto = _xyz(item[u"inicio"])
    for plano in candidatos:
        if abs(abs(plano.Normal.DotProduct(normal)) - 1.0) > 1e-6:
            continue
        if abs((ponto - plano.BubbleEnd).DotProduct(plano.Normal)) < mm(0.01):
            return plano
    return None


def construir_planos(doc, vista, especificacao):
    u"""Recria os planos de referência. Retorna endereço -> ReferencePlane.

    - mesmo nome de um plano existente: reaproveita (template no mesmo idioma);
    - mesma geometria de um plano do TEMPLATE: reaproveita. Família feita em
      template em português ("Centro (Esquerda/Direita)") convertida num
      template em inglês achava o plano pelo nome e falhava;
    - o resto é criado, em qualquer orientação, na vista em que aparece como
      linha. O nome original é mantido quando é único no documento.
    """
    mapa = {}
    do_template = list(FilteredElementCollector(doc).OfClass(ReferencePlane).ToElements())
    por_nome = {}
    for plano in do_template:
        nome = getattr(plano, "Name", None)
        if nome:
            por_nome[nome] = plano
    usados = set(por_nome)

    for item in especificacao[u"planos_de_referencia"]:
        endereco = item.get(u"endereco") or item[u"nome"]
        nome = item.get(u"nome") or u""
        if nome in por_nome:
            mapa[endereco] = por_nome[nome]
            continue
        coincidente = _plano_coincidente(do_template, item)
        if coincidente is not None:
            mapa[endereco] = coincidente
            continue
        normal = _vetor(item[u"normal"]).Normalize()
        vista_do_plano = _vista_para_normal(doc, normal, vista)
        if vista_do_plano is None:
            _pular(u"plano '{0}'".format(endereco), u"sem vista em que o plano apareça como linha")
            continue
        inicio, fim = _xyz(item[u"inicio"]), _xyz(item[u"fim"])
        direcao = (fim - inicio).Normalize()
        corte = normal.CrossProduct(direcao).Normalize()
        try:
            plano = doc.FamilyCreate.NewReferencePlane(inicio, fim, corte, vista_do_plano)
        except Exception as erro:
            _pular(u"plano '{0}'".format(endereco), unicode(erro)[:140])  # noqa: F821
            continue
        if nome and nome not in usados and endereco == nome:
            plano.Name = nome
            usados.add(nome)
        mapa[endereco] = plano

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
    if item[u"tipo"] == u"elipse":
        from Autodesk.Revit.DB import Ellipse
        return Ellipse.CreateCurve(_xyz(item[u"centro"]), mm(item[u"raio_x"]), mm(item[u"raio_y"]),
                                   _vetor(item[u"eixo_x"]), _vetor(item[u"eixo_y"]),
                                   item[u"parametro_inicial"], item[u"parametro_final"])
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

    if endereco[u"tipo"] == u"esboco":
        curva = _curva_de_esboco(formas, endereco)
        if curva is None:
            return None
        if endereco.get(u"ponta") is not None:
            return curva.GetEndPointReference(_indice_da_ponta(curva, endereco))
        return curva.Reference

    return None


def _curva_de_esboco(formas, endereco):
    u"""Curva do esboço reencontrada pelas PONTAS (S11); laço/curva é o recurso.

    O Revit recria o esboço com outra ordem e outro sentido de curvas: pelo
    índice, a trava caía na curva errada ("not geometrically aligned").
    """
    elemento = formas.get(endereco[u"forma"])
    if elemento is None:
        return None
    try:
        lacos = [list(laco) for laco in elemento.Sketch.Profile]
    except Exception:
        return None
    pontas = endereco.get(u"pontas_mm")
    if pontas:
        a, b = _xyz(pontas[0]), _xyz(pontas[1])
        meio = _xyz(endereco[u"meio_mm"]) if endereco.get(u"meio_mm") else None
        tolerancia = mm(0.01)
        for laco in lacos:
            for curva in laco:
                p, q = curva.GetEndPoint(0), curva.GetEndPoint(1)
                if not ((p.DistanceTo(a) < tolerancia and q.DistanceTo(b) < tolerancia) or
                        (p.DistanceTo(b) < tolerancia and q.DistanceTo(a) < tolerancia)):
                    continue
                if meio is None or curva.Evaluate(0.5, True).DistanceTo(meio) < tolerancia:
                    return curva
        return None
    try:
        return lacos[endereco[u"laco"]][endereco[u"curva"]]
    except Exception:
        return None


def _indice_da_ponta(curva, endereco):
    u"""Ponta da curva no destino: a mais próxima do ponto gravado."""
    if endereco.get(u"ponto_mm"):
        alvo = _xyz(endereco[u"ponto_mm"])
        return 0 if curva.GetEndPoint(0).DistanceTo(alvo) <= curva.GetEndPoint(1).DistanceTo(alvo) else 1
    return int(endereco[u"ponta"])


def _normal_do_esboco(formas, enderecos):
    for endereco in enderecos:
        if endereco[u"tipo"] == u"esboco" and endereco[u"forma"] in formas:
            return formas[endereco[u"forma"]].Sketch.SketchPlane.GetPlane().Normal
    return None


def _vista_paralela_ao_esboco(doc, formas, enderecos, planta):
    u"""Vista paralela ao esboço da 1ª referência de esboço (planta ou elevação).

    Trava de curva de esboço só nasce na vista em que o esboço aparece em
    verdadeira grandeza (sonda S11: na planta, um esboço da Front recusa).
    """
    normal = _normal_do_esboco(formas, enderecos)
    if normal is None:
        return None
    if abs(abs(normal.Z) - 1.0) < 1e-6:
        return planta
    for vista in FilteredElementCollector(doc).OfClass(View).ToElements():
        if not vista.IsTemplate and vista.ViewType == ViewType.Elevation and \
                abs(abs(vista.ViewDirection.DotProduct(normal)) - 1.0) < 1e-6:
            return vista
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
    if abs(normal.Z) > 0.9:
        # Planos horizontais: cota vertical, numa elevação (ver _vista_para_normal).
        return Line.CreateBound(XYZ(-afastamento, 0.0, inicio.Z), XYZ(-afastamento, 0.0, fim.Z))
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
        if item.get(u"forma") in (u"Radial", u"Diameter") or \
                any(e.get(u"tipo") == u"esboco" for e in item[u"referencias"]):
            continue  # nasce depois da forma (construir_cotas_radiais / _de_esboco)
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

        primeiro = planos.get(item[u"referencias"][0].get(u"nome")) if item[u"referencias"] else None
        vista_da_cota = _vista_para_normal(doc, primeiro.Normal, vista) if primeiro is not None else vista
        try:
            cota = doc.FamilyCreate.NewDimension(vista_da_cota or vista, linha, referencias)
        except Exception as erro:
            _pular(u"cota #{0} (rótulo={1})".format(indice, rotulo), unicode(erro)[:140])  # noqa: F821
            continue

        if rotulo:
            parametro = parametros.get(rotulo)
            if parametro is not None:
                cota.FamilyLabel = parametro  # <- a peça central do projeto
            else:
                _pular(u"rótulo da cota #{0}".format(indice),
                       u"parâmetro '{0}' não existe no destino".format(rotulo))
        _aplicar_igualdade(cota, item, indice)

    doc.Regenerate()


def _aplicar_igualdade(cota, item, indice):
    if not item.get(u"iguais"):
        return
    try:
        cota.AreSegmentsEqual = True
    except Exception as erro:
        _pular(u"igualdade (EQ) da cota #{0}".format(indice), unicode(erro)[:140])  # noqa: F821


_DOC_EM_CONSTRUCAO = [None]


def _aplicar_subcategoria_e_visibilidade(doc, item, forma):
    u"""Subcategoria pelo NOME (criada se não existir) e visibilidade fixa.

    O leitor sempre gravou os dois campos e o construtor os ignorava: a forma
    saía na subcategoria padrão e visível. A API foi provada na sonda S6 da G0.
    A visibilidade dirigida por parâmetro continua vindo das associações.
    """
    material = item.get(u"material")
    if material and not any((a or {}).get(u"builtin") == u"MATERIAL_ID_PARAM"
                            for a in (item.get(u"associacoes") or {}).values()):
        try:
            forma.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM).Set(_material_por_nome(doc, material))
        except Exception as erro:
            _pular(u"material '{0}' da forma #{1}".format(material, item[u"indice"]), unicode(erro)[:140])  # noqa: F821
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


def _ponto_da_referencia_de_esboco(formas, endereco):
    curva = _curva_de_esboco(formas, endereco)
    if curva is None:
        return None, None
    if endereco.get(u"ponta") is not None:
        return curva, curva.GetEndPoint(_indice_da_ponta(curva, endereco))
    return curva, curva.Evaluate(0.5, True)


def _reta_da_referencia(endereco, planos, formas, normal_do_esboco):
    u"""(ponto, direção) da referência dentro do plano do esboço."""
    if endereco[u"tipo"] == u"plano":
        plano = planos.get(endereco[u"nome"])
        return plano.BubbleEnd, plano.Normal.CrossProduct(normal_do_esboco).Normalize()
    curva = _curva_de_esboco(formas, endereco)
    if curva is None or not isinstance(curva, Line):
        return None
    return curva.GetEndPoint(0), curva.Direction


def _cota_angular_de_esboco(doc, vista, item, indice, nome, enderecos, referencias, planos, formas, parametros):
    u"""Cota angular (travada ou rotulada) entre duas retas do esboço / planos.

    `FamilyItemFactory.NewAngularDimension(vista, arco, ref1, ref2)`: o arco só
    posiciona a cota e tem centro no cruzamento das duas retas.
    """
    normal = _normal_do_esboco(formas, enderecos)
    retas = [_reta_da_referencia(e, planos, formas, normal) for e in enderecos]
    if normal is None or any(r is None for r in retas):
        _pular(nome, u"cota angular: reta da referência não reencontrada")
        return
    origem = None
    for endereco in enderecos:
        if endereco[u"tipo"] == u"esboco":
            origem = formas[endereco[u"forma"]].Sketch.SketchPlane.GetPlane().Origin
    # leva os pontos para o plano do esboço (a bolha do plano pode estar fora dele)
    retas = [(p - normal.Multiply((p - origem).DotProduct(normal)), d) for p, d in retas]
    (p1, d1), (p2, d2) = retas
    # cruzamento: p1 + s*d1 = p2 + t*d2, resolvido no plano do esboço
    cruz = d1.CrossProduct(d2)
    if cruz.GetLength() < 1e-9:
        _pular(nome, u"cota angular entre retas paralelas")
        return
    s = (p2 - p1).CrossProduct(d2).DotProduct(cruz) / cruz.DotProduct(cruz)
    centro = p1 + d1.Multiply(s)
    # cada raio aponta para o lado onde a curva do esboço está (não para trás)
    raios = []
    for endereco, (ponto, direcao) in zip(enderecos, retas):
        if endereco[u"tipo"] == u"esboco":
            curva = _curva_de_esboco(formas, endereco)
            meio = curva.Evaluate(0.5, True)
            if (meio - centro).DotProduct(direcao) < 0:
                direcao = direcao.Negate()
        raios.append(direcao)
    if (raios[0] + raios[1]).GetLength() < 1e-9:
        _pular(nome, u"cota angular de 180 graus")
        return
    raio = mm(20.0)
    bissetriz = (raios[0] + raios[1]).Normalize()
    try:
        arco = Arc.Create(centro + raios[0].Multiply(raio), centro + raios[1].Multiply(raio),
                          centro + bissetriz.Multiply(raio))
        cota = doc.FamilyCreate.NewAngularDimension(vista, arco, referencias.get_Item(0), referencias.get_Item(1))
        rotulo = item.get(u"rotulo")
        if rotulo and parametros.get(rotulo) is not None:
            cota.FamilyLabel = parametros[rotulo]
        if item.get(u"travada"):
            cota.IsLocked = True
    except Exception as erro:
        _pular(nome, unicode(erro)[:140])  # noqa: F821


def construir_cotas_de_esboco(doc, vista, especificacao, formas, planos, parametros):
    u"""Cota LINEAR que toca curva de esboço (rotulada ou travada), sonda S11.

    Nasce depois das formas, com a geometria ainda na configuração serializada
    (se o plano já tivesse se movido, o Revit recusaria). A linha da cota sai
    da normal do plano medido; sem plano (duas curvas do esboço), da
    perpendicular à curva dentro do esboço.
    """
    for indice, item in enumerate(especificacao[u"cotas"]):
        if item.get(u"forma") in (u"Radial", u"Diameter"):
            continue
        enderecos = item[u"referencias"]
        if not any(e.get(u"tipo") == u"esboco" for e in enderecos):
            continue
        rotulo = item.get(u"rotulo")
        nome = u"cota de esboço #{0} (rótulo={1})".format(indice, rotulo)
        referencias = ReferenceArray()
        plano = None
        curva = ponto = None
        for endereco in enderecos:
            referencia = _resolver_referencia(endereco, planos, formas)
            if referencia is None:
                referencias = None
                break
            referencias.Append(referencia)
            if endereco[u"tipo"] == u"plano":
                plano = plano or planos.get(endereco[u"nome"])
            elif endereco[u"tipo"] == u"esboco" and curva is None:
                curva, ponto = _ponto_da_referencia_de_esboco(formas, endereco)
        vista_da_cota = _vista_paralela_ao_esboco(doc, formas, enderecos, vista)
        if referencias is None or curva is None or vista_da_cota is None:
            _pular(nome, u"referência, curva ou vista não reencontradas")
            continue
        if item.get(u"forma") == u"Angular":
            _cota_angular_de_esboco(doc, vista_da_cota, item, indice, nome, enderecos, referencias,
                                    planos, formas, parametros)
            continue
        if plano is not None:
            direcao = plano.Normal
        else:
            normal = _normal_do_esboco(formas, enderecos)
            tangente = curva.ComputeDerivatives(0.5, True).BasisX.Normalize()
            direcao = normal.CrossProduct(tangente)
        try:
            cota = doc.FamilyCreate.NewDimension(
                vista_da_cota, Line.CreateBound(ponto, ponto + direcao.Normalize().Multiply(mm(100))), referencias)
            if rotulo and parametros.get(rotulo) is not None:
                cota.FamilyLabel = parametros[rotulo]
            if item.get(u"travada"):
                cota.IsLocked = True
            _aplicar_igualdade(cota, item, indice)
        except Exception as erro:
            _pular(nome, unicode(erro)[:140])  # noqa: F821
    doc.Regenerate()


def _com_geometria_do_spec(endereco, especificacao):
    u"""Endereço de esboço sem as pontas gravadas (o leitor nem sempre consegue):
    completa com a curva do PERFIL do spec, para o casamento pela geometria."""
    if endereco.get(u"pontas_mm"):
        return endereco
    try:
        curva = especificacao[u"formas"][endereco[u"forma"]][u"perfil"][endereco[u"laco"]][endereco[u"curva"]]
    except Exception:
        return endereco
    if not curva.get(u"inicio") or not curva.get(u"fim"):
        return endereco
    completo = dict(endereco)
    completo[u"pontas_mm"] = [curva[u"inicio"], curva[u"fim"]]
    if curva.get(u"meio"):
        completo[u"meio_mm"] = curva[u"meio"]
    return completo


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
        if not rotulo and not item.get(u"travada"):
            # Só anotação (sem rótulo, sem trava): não muda o flex, e criá-la
            # desfez as travas das faces da forma na Solaris (formas 6 e 7:
            # +8 mm no comprimento). Fica de fora de propósito.
            continue
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
            endereco = _com_geometria_do_spec(endereco, especificacao)
            curva = _curva_de_esboco(formas, endereco)
            if curva is None or not isinstance(curva, Arc):
                raise ValueError(u"arco do esboço não reencontrado pela geometria")
            # Esboço vertical (Solaris: bocais no plano de normal X) só aceita a
            # cota na vista paralela a ele; na planta: "One of the conditions
            # for the inputs was not satisfied" (6 cotas da Solaris).
            vista_da_cota = _vista_paralela_ao_esboco(doc, formas, [endereco], vista) or vista
            plano = forma.Sketch.SketchPlane.GetPlane()
            origem = curva.Center + (plano.XVec + plano.YVec).Multiply(curva.Radius * 0.5)
            if item[u"forma"] == u"Diameter":
                cota = doc.FamilyCreate.NewDiameterDimension(vista_da_cota, curva.Reference, origem)
            else:
                cota = doc.FamilyCreate.NewRadialDimension(vista_da_cota, curva.Reference, origem)
            if item.get(u"travada"):
                cota.IsLocked = True
            if not rotulo:
                continue
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


def aplicar_tipo_de_peca(doc, especificacao):
    u"""Part Type da conexão (Union, Wye, Tee...), resolvido pelo NOME do enum."""
    nome = (especificacao.get(u"identidade") or {}).get(u"part_type")
    if not nome:
        return
    import Autodesk.Revit.DB as DB
    valor = getattr(DB.PartType, nome, None)
    parametro = doc.OwnerFamily.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
    if valor is None or parametro is None:
        _pular(u"part type '{0}'".format(nome), u"não existe nesta versão ou nesta categoria")
        return
    try:
        parametro.Set(int(valor))
    except Exception as erro:
        _pular(u"part type '{0}'".format(nome), unicode(erro)[:140])  # noqa: F821


def _associar_raio_pelo_diametro(doc, conector, alvo_raio, nome_raio, parametros):
    u"""Raio do conector dirigindo um parâmetro (família de roteamento).

    Sonda S10: em conector de tubo criado pela API o RAIO não pode ser associado
    a nada (CanElementParameterBeAssociated = False); o DIÂMETRO pode. Adaptação
    que preserva o comportamento: um parâmetro '<raio>_D' recebe o diâmetro do
    conector e o raio vira fórmula '<raio>_D / 2'. O tamanho continua vindo do
    tubo. Fica no relatório como adaptação, não como cópia literal.
    """
    gerenciador = doc.FamilyManager
    nome_d = nome_raio + u"_D"
    alvo_d = parametros.get(nome_d)
    if alvo_d is None:
        alvo_d = gerenciador.AddParameter(nome_d, alvo_raio.Definition.GetGroupTypeId(),
                                          alvo_raio.Definition.GetDataType(), alvo_raio.IsInstance)
        parametros[nome_d] = alvo_d
        try:
            if alvo_raio.Formula is None:
                # O diâmetro nasce com o valor atual (2 x raio): a fórmula não
                # pode zerar a geometria já construída.
                gerenciador.Set(alvo_d, 2 * gerenciador.CurrentType.AsDouble(alvo_raio))
                gerenciador.SetFormula(alvo_raio, u"{0} / 2".format(nome_d))
        except Exception as erro:
            _pular(u"fórmula de '{0}'".format(nome_raio), unicode(erro)[:140])  # noqa: F821
    gerenciador.AssociateElementParameterToFamilyParameter(
        conector.get_Parameter(BuiltInParameter.CONNECTOR_DIAMETER), alvo_d)
    _adaptar(u"raio do conector -> '{0}'".format(nome_raio),
           u"a API não associa o raio; diâmetro -> '{0}' e '{1}' = '{0}' / 2".format(nome_d, nome_raio))


def _face_de_apoio_no_plano(doc, plano, face_spec):
    u"""Face para o conector que a origem prendia num PLANO de referência (S12).

    No Revit 2023 `CreatePipeConnector` com a referência do plano falha
    ("oEdgeLoopRef.ptr() is NULL"); no 2024 nasce, mas na ponta do plano, e
    não no ponto da origem. Caminho que funcionou nas duas versões: um disco
    VAZIO de 1 mm hospedado no próprio plano (acompanha o plano no flex), no
    ponto da origem, do lado para onde o conector aponta (o vazio tem as
    normais invertidas). Vazio não corta nada sem CombineElements, não entra
    na medição de volume e não aparece no projeto.
    """
    esboco = SketchPlane.Create(doc, plano.Id)
    geometrico = esboco.GetPlane()
    direcao = _vetor(face_spec[u"normal"]).Normalize()
    centro = _xyz(face_spec[u"origem"])
    centro = centro - geometrico.Normal.Multiply((centro - geometrico.Origin).DotProduct(geometrico.Normal))
    raio = mm(1.0)
    laco = CurveArray()
    laco.Append(Arc.Create(centro, raio, 0.0, math.pi, geometrico.XVec, geometrico.YVec))
    laco.Append(Arc.Create(centro, raio, math.pi, 2 * math.pi, geometrico.XVec, geometrico.YVec))
    perfil = CurveArrArray()
    perfil.Append(laco)
    sentido = 1.0 if geometrico.Normal.DotProduct(direcao) > 0 else -1.0
    disco = doc.FamilyCreate.NewExtrusion(False, perfil, esboco, mm(sentido))
    doc.Regenerate()
    opcoes = Options()
    opcoes.ComputeReferences = True
    for objeto in disco.get_Geometry(opcoes):
        if not isinstance(objeto, Solid):
            continue
        for face in objeto.Faces:
            if isinstance(face, PlanarFace) and face.FaceNormal.IsAlmostEqualTo(direcao) and \
                    abs((face.Origin - geometrico.Origin).DotProduct(geometrico.Normal)) < mm(0.01):
                return face.Reference
    doc.Delete(disco.Id)
    return None


def construir_conectores(doc, especificacao, formas, parametros, planos=None):
    u"""Conectores de tubo nas faces planas (schema 0.3.0; sonda S9 da G5).

    Diâmetro: associado ao parâmetro do rótulo, ou fixado no valor do spec.
    Os pares `ligado_a` são ligados nos dois sentidos (conexão de passagem).
    """
    import Autodesk.Revit.DB as DB
    from Autodesk.Revit.DB.Plumbing import PipeSystemType
    gerenciador = doc.FamilyManager
    criados = {}
    for indice, item in enumerate(especificacao.get(u"conectores") or []):
        rotulo = u"conector #{0}".format(indice)
        if item.get(u"dominio") != u"tubo":
            _pular(rotulo, u"domínio fora da cobertura: {0}".format(item.get(u"dominio")))
            continue
        if item[u"face"].get(u"plano"):
            plano = (planos or {}).get(item[u"face"][u"plano"])
            referencia_hospedeira = _face_de_apoio_no_plano(doc, plano, item[u"face"]) \
                if plano is not None else None
        else:
            forma = formas.get(item[u"face"][u"forma"])
            face = _face_por_endereco(forma, item[u"face"]) if forma is not None else None
            referencia_hospedeira = face.Reference if face is not None else None
        if referencia_hospedeira is None:
            _pular(rotulo, u"face ou plano hospedeiro não reencontrado")
            continue
        sistema = getattr(PipeSystemType, item.get(u"sistema") or u"Fitting", None)
        if sistema is None:
            _pular(rotulo, u"sistema '{0}' não existe; usado Fitting".format(item.get(u"sistema")))
            sistema = PipeSystemType.Fitting
        try:
            conector = DB.ConnectorElement.CreatePipeConnector(doc, sistema, referencia_hospedeira)
            diametro = conector.get_Parameter(BuiltInParameter.CONNECTOR_DIAMETER)
            alvo = parametros.get(item.get(u"diametro_rotulo") or u"")
            alvo_raio = parametros.get(item.get(u"raio_rotulo") or u"")
            if alvo is not None:
                gerenciador.AssociateElementParameterToFamilyParameter(diametro, alvo)
            elif alvo_raio is not None:
                _associar_raio_pelo_diametro(doc, conector, alvo_raio, item[u"raio_rotulo"], parametros)
            elif item.get(u"diametro_mm"):
                diametro.Set(mm(item[u"diametro_mm"]))
            criados[indice] = conector
        except Exception as erro:
            _pular(rotulo, unicode(erro)[:160])  # noqa: F821
    for indice, item in enumerate(especificacao.get(u"conectores") or []):
        par = item.get(u"ligado_a")
        if par is None or indice not in criados or par not in criados:
            continue
        try:
            criados[indice].SetLinkedConnectorElement(criados[par])
        except Exception as erro:
            _pular(u"ligação do conector #{0}".format(indice), unicode(erro)[:140])  # noqa: F821
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
            if endereco[u"tipo"] in (u"face", u"esboco") and endereco[u"forma"] not in formas:
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

        # Vista em que o datum aparece como linha (plano horizontal: elevação).
        datum = enderecos[0]
        if datum[u"tipo"] == u"plano" and planos.get(datum[u"nome"]) is not None:
            normal_datum = planos[datum[u"nome"]].Normal
        else:
            normal_datum = _vetor(datum.get(u"normal") or [1.0, 0.0, 0.0])
        vista_do_alinhamento = _vista_paralela_ao_esboco(doc, formas, enderecos, vista) or \
            _vista_para_normal(doc, normal_datum, vista) or vista
        try:
            doc.FamilyCreate.NewAlignment(vista_do_alinhamento, resolvidas[0], resolvidas[1])
        except Exception as erro:
            _pular(u"alinhamento #{0}".format(indice), unicode(erro)[:140])  # noqa: F821
            continue
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


_MATERIAIS_DO_SPEC = {}


_IMAGENS_DO_SPEC = {}
_IMAGENS_CRIADAS = {}


def _imagem_por_nome(doc, nome):
    u"""ImageType do destino com os bytes da origem (spec `imagens`)."""
    if nome in _IMAGENS_CRIADAS:
        return _IMAGENS_CRIADAS[nome]
    dados = _IMAGENS_DO_SPEC.get(nome)
    if not dados:
        raise ValueError(u"imagem '{0}' sem bytes no spec".format(nome))
    import base64
    import tempfile
    import Autodesk.Revit.DB as DB
    pasta = tempfile.mkdtemp(prefix=u"rfadg_img_")
    # O nome do arquivo vira o nome do ImageType: o mesmo da origem.
    seguro = u"".join(c if c.isalnum() or c in u" ._-()" else u"_" for c in nome) or u"imagem"
    if not os.path.splitext(seguro)[1]:
        seguro += u".png"
    caminho = os.path.join(pasta, seguro)
    with open(caminho, "wb") as arquivo:
        arquivo.write(base64.b64decode(dados))
    imagem = DB.ImageType.Create(doc, DB.ImageTypeOptions(caminho, False, DB.ImageTypeSource.Import))
    _IMAGENS_CRIADAS[nome] = imagem.Id
    return imagem.Id


def _material_por_nome(doc, nome):
    u"""Material do destino com esse nome; criado (com a cor da origem) se faltar."""
    from Autodesk.Revit.DB import Color, Material
    for material in FilteredElementCollector(doc).OfClass(Material).ToElements():
        if material.Name == nome:
            return material.Id
    novo = doc.GetElement(Material.Create(doc, nome))
    definicao = _MATERIAIS_DO_SPEC.get(nome) or {}
    cor = definicao.get(u"cor")
    if cor:
        novo.Color = Color(cor[0], cor[1], cor[2])
    if definicao.get(u"transparencia"):
        novo.Transparency = int(definicao[u"transparencia"])
    return novo.Id


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
        if parametro is not None and parametro.IsDeterminedByFormula and \
                parametros.get(nome + u"_D") is not None and isinstance(valor, (int, long, float)):  # noqa: F821
            # Raio adaptado (ver _associar_raio_pelo_diametro): o valor do tipo
            # vai para o diâmetro que dirige o raio.
            try:
                gerenciador.Set(parametros[nome + u"_D"], mm(2 * valor) if nome in de_comprimento else 2 * valor)
            except Exception as erro:
                _pular(u"valor '{0}' do tipo '{1}'".format(nome, tipo[u"nome"]), unicode(erro)[:140])  # noqa: F821
            continue
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
            elif isinstance(valor, dict) and valor.get(u"material"):
                gerenciador.Set(parametro, _material_por_nome(_DOC_EM_CONSTRUCAO[0], valor[u"material"]))
            elif isinstance(valor, dict) and valor.get(u"imagem"):
                gerenciador.Set(parametro, _imagem_por_nome(_DOC_EM_CONSTRUCAO[0], valor[u"imagem"]))
            else:
                # StorageType.ElementId (Imagem, outro elemento...)
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
    original = tipo[u"nome"]
    if not (tipo[u"nome"] or u"").strip():
        # Caso real (famílias de roteamento da Ultrapex): o único tipo se chama
        # " ". O Revit deixa existir, mas a API recusa criar ("The value cannot
        # be empty"). Sonda S14: o Revit apara U+00A0, U+2007, U+202F e
        # U+3000, mas aceita o "Braille em branco" (U+2800), que aparece como
        # um espaço. Se até ele for recusado, nasce "Padrao".
        tipo = dict(tipo)
        tipo[u"nome"] = unichr(0x2800) * max(1, len(original or u""))  # noqa: F821
        try:
            gerenciador.NewType(tipo[u"nome"])
            _adaptar(u"nome do tipo {0!r}".format(original), u"Braille em branco (U+2800), aparece como espaço")
        except Exception:
            tipo[u"nome"] = u"Padrao"
            gerenciador.NewType(tipo[u"nome"])
            _pular(u"nome do tipo {0!r}".format(original), u"a API recusa nome vazio; criado como 'Padrao'")
        _NOME_NO_DESTINO[original] = tipo[u"nome"]
        _aplicar_valores_do_tipo(gerenciador, tipo, parametros, _nomes_de_comprimento(especificacao))
        doc.Regenerate()
        return tipo[u"nome"]
    gerenciador.NewType(tipo[u"nome"])  # vira o tipo corrente
    _aplicar_valores_do_tipo(gerenciador, tipo, parametros,
                             _nomes_de_comprimento(especificacao))
    doc.Regenerate()
    return tipo[u"nome"]


_NOME_NO_DESTINO = {}


def construir_tipos(doc, especificacao, parametros, ja_criado=None):
    u"""Recria os DEMAIS tipos com os valores por parâmetro (mm -> interno).

    O tipo corrente da origem já foi criado antes da geometria (ver
    estabelecer_tipo_corrente) e é pulado aqui — NewType com nome repetido
    falha.
    """
    gerenciador = doc.FamilyManager
    de_comprimento = _nomes_de_comprimento(especificacao)

    for tipo in especificacao[u"tipos"]:
        if tipo[u"nome"] == ja_criado or tipo[u"nome"] in _NOME_NO_DESTINO:
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


def aplicar_imagem_do_tipo(doc, especificacao):
    u"""Grava a imagem da intenção como Type Image de TODOS os tipos.

    API provada na sonda S7 da G0 (ImageTypeOptions + ALL_MODEL_TYPE_IMAGE).
    Vem do gerador; famílias convertidas não trazem este campo (o valor de
    origem é um ElementId, que não atravessa documentos).
    """
    imagem = (especificacao.get(u"imagem_do_tipo") or {}).get(u"arquivo")
    if not imagem:
        return
    if not os.path.isfile(imagem):
        _pular(u"imagem do tipo", u"arquivo não encontrado: {0}".format(imagem))
        return
    try:
        import Autodesk.Revit.DB as DB
        opcoes = DB.ImageTypeOptions(imagem, False, DB.ImageTypeSource.Import)
        tipo_imagem = DB.ImageType.Create(doc, opcoes)
        gerenciador = doc.FamilyManager
        parametro = gerenciador.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_IMAGE)
        for tipo in list(gerenciador.Types):
            if not tipo.Name:
                continue
            gerenciador.CurrentType = tipo
            gerenciador.Set(parametro, tipo_imagem.Id)
        doc.Regenerate()
    except Exception as erro:
        _pular(u"imagem do tipo", unicode(erro)[:160])  # noqa: F821


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
    _DOC_EM_CONSTRUCAO[0] = doc
    _MATERIAIS_DO_SPEC.clear()
    _MATERIAIS_DO_SPEC.update(especificacao.get(u"materiais") or {})
    _IMAGENS_DO_SPEC.clear()
    _IMAGENS_DO_SPEC.update(especificacao.get(u"imagens") or {})
    _IMAGENS_CRIADAS.clear()

    transacao = Transaction(doc, u"RFADG — reconstruir família")
    transacao.Start()
    try:
        vista = _vista_de_planta(doc)

        # Categoria antes de tudo: trocá-la depois de existir geometria e
        # parâmetros é bem mais arriscado.
        ajustar_categoria(doc, especificacao)
        # Part Type antes dos parâmetros: os embutidos de Transição (Offset
        # Width/Height da luva de redução) só passam a existir depois dele.
        aplicar_tipo_de_peca(doc, especificacao)

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
        construir_cotas_de_esboco(doc, vista, especificacao, formas, planos, parametros)
        aplicar_tipo_de_peca(doc, especificacao)
        construir_conectores(doc, especificacao, formas, parametros, planos)
        construir_combinacoes(doc, especificacao, formas)
        construir_tipos(doc, especificacao, parametros, tipo_corrente)
        aplicar_imagem_do_tipo(doc, especificacao)
        # Fórmulas por último: exigem um tipo válido já existente. As tabelas de
        # consulta entram antes delas, que é onde size_lookup procura.
        importar_tabelas_de_consulta(doc, especificacao)
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
            u"adaptado": _ADAPTADO,
            u"lacunas_da_origem": especificacao.get(u"lacunas", []),
        })


principal()

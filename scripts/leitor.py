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
    Sweep, Blend, SweptBlend, GenericForm, GeomCombination, Line, Arc,
    PlanarFace, BuiltInCategory, BuiltInParameter, StorageType,
    ConnectorElement, ElementId, Options, PartType, Solid, FamilyInstance, XYZ,
)
from System import Enum  # noqa: E402

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

# Documento em leitura (para resolver material por id) e materiais vistos.
_DOC = [None]
_MATERIAIS = {}
_IMAGENS = {}


def _imagem(identificador):
    u"""ElementId de ImageType -> {"imagem": nome}, guardando o PNG em base64.

    A Type Image é um elemento do documento (o id não atravessa). Vai pelos
    BYTES da imagem: ImageType.GetImage() -> Bitmap -> PNG.
    """
    doc = _DOC[0]
    elemento = doc.GetElement(identificador) if doc is not None and identificador is not None else None
    if elemento is None or type(elemento).__name__ != "ImageType":
        return None
    # ImageType.Name não é acessível no IronPython (como FamilySymbol.Name).
    from Autodesk.Revit.DB import Element
    nome = rfaspec.para_unicode(Element.Name.__get__(elemento))
    if nome not in _IMAGENS:
        import base64
        import tempfile
        import clr
        clr.AddReference("System.Drawing")
        from System.Drawing.Imaging import ImageFormat
        # No formato do nome original: o PNG de um JPG de 1 MB passava de 4 MB.
        extensao = os.path.splitext(nome)[1].lower()
        formato = ImageFormat.Jpeg if extensao in (u".jpg", u".jpeg") else             ImageFormat.Bmp if extensao == u".bmp" else ImageFormat.Png
        caminho = os.path.join(tempfile.mkdtemp(prefix=u"rfadg_img_"), u"imagem" + (extensao or u".png"))
        elemento.GetImage().Save(caminho, formato)
        with open(caminho, "rb") as arquivo:
            _IMAGENS[nome] = base64.b64encode(arquivo.read())
    return {u"imagem": nome}


def _material(identificador):
    u"""ElementId de material -> {"material": nome}, registrando a definição."""
    doc = _DOC[0]
    elemento = doc.GetElement(identificador) if doc is not None and identificador is not None else None
    if elemento is None or type(elemento).__name__ != "Material":
        return None
    nome = rfaspec.para_unicode(elemento.Name)
    if nome not in _MATERIAIS:
        cor = elemento.Color
        _MATERIAIS[nome] = {
            # Color.Red etc. são System.Byte: int() para o JSON.
            u"cor": [int(cor.Red), int(cor.Green), int(cor.Blue)] if cor is not None and cor.IsValid else None,
            u"transparencia": int(elemento.Transparency),
        }
    return {u"material": nome}


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
        # Material atravessa documentos pelo NOME (o id não atravessa).
        material = _material(identificador)
        if material is not None:
            return material
        try:
            imagem = _imagem(identificador)
        except Exception:
            imagem = None
        if imagem is not None:
            return imagem
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

        # GUID só existe (e só importa) em parâmetro compartilhado: é a
        # identidade que faz tabelas e etiquetas continuarem enxergando o
        # parâmetro depois da conversão. Recriar compartilhado com outro GUID
        # produziria um homônimo que quebra todo agendamento existente.
        guid = None
        if parametro.IsShared:
            try:
                guid = str(parametro.GUID)
            except Exception:
                pass

        # Parâmetro embutido da categoria (Loss Method, K Coefficient Table nas
        # conexões de tubo): o nome é traduzido conforme o idioma do Revit, o
        # BuiltInParameter não. O construtor casa por ele.
        embutido = None
        try:
            if parametro.Id is not None and _id_valor(parametro.Id) < 0:
                embutido = str(definicao.BuiltInParameter)
        except Exception:
            embutido = None

        parametros.append({
            u"embutido": embutido,
            u"nome": definicao.Name,
            u"tipo_de_dado": _forge_id(definicao.GetDataType()),
            u"grupo": _grupo_do_parametro(definicao),
            u"armazenamento": str(parametro.StorageType),
            u"de_instancia": bool(parametro.IsInstance),
            u"compartilhado": bool(parametro.IsShared),
            u"guid": guid,
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

# Endereço portável de cada plano (id do elemento -> endereço). Preenchido por
# ler_planos_de_referencia ANTES das cotas, que endereçam planos por ele.
_ENDERECO_DO_PLANO = {}


def ler_planos_de_referencia(doc):
    u"""Todos os planos, cada um com um ENDEREÇO único.

    Famílias reais têm dezenas de planos com o nome padrão ("Reference Plane")
    e planos sem nome: endereçar pelo nome mandava a cota para o plano errado
    ou para nenhum (82 lacunas na Solaris, 45 no joelho da Ultrapex). O
    endereço é o nome quando ele é único; senão, RFADG_P<ordem de criação>.
    """
    planos = []
    coletor = FilteredElementCollector(doc).OfClass(ReferencePlane)

    for plano in coletor.ToElements():
        # .Name protegido: em alguns contextos o acesso direto lança.
        nome = getattr(plano, "Name", None) or u""

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
    contagem = {}
    for item in planos:
        contagem[item[u"nome"]] = contagem.get(item[u"nome"], 0) + 1
    _ENDERECO_DO_PLANO.clear()
    for ordem, item in enumerate(planos):
        unico = item[u"nome"] and contagem[item[u"nome"]] == 1
        item[u"endereco"] = item[u"nome"] if unico else u"RFADG_P{0}".format(ordem)
        _ENDERECO_DO_PLANO[item[u"_id"]] = item[u"endereco"]
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
    if type(curva).__name__ == "Ellipse":
        # Tampa abaulada de reservatório (Solaris): meia elipse no perfil da
        # revolução. Raios em mm, direções adimensionais, parâmetros em radianos.
        return {
            u"tipo": u"elipse",
            u"centro": _ponto(curva.Center),
            u"raio_x": para_mm(curva.RadiusX),
            u"raio_y": para_mm(curva.RadiusY),
            u"eixo_x": _vetor(curva.XDirection),
            u"eixo_y": _vetor(curva.YDirection),
            u"parametro_inicial": curva.GetEndParameter(0),
            u"parametro_final": curva.GetEndParameter(1),
        }
    if type(curva).__name__ == "NurbSpline":
        # Logo da Solaris: letras em NURBS. Grau, nós, pontos de controle e
        # pesos reproduzem a curva exata (não uma aproximação por pontos).
        return {
            u"tipo": u"nurbs",
            u"grau": int(curva.Degree),
            u"nos": [float(v) for v in curva.Knots],
            u"controle": [_ponto(p) for p in curva.CtrlPoints],
            u"pesos": [float(v) for v in curva.Weights],
            u"parametro_inicial": curva.GetEndParameter(0),
            u"parametro_final": curva.GetEndParameter(1),
            u"inicio": _ponto(curva.GetEndPoint(0)),
            u"fim": _ponto(curva.GetEndPoint(1)),
            u"meio": _ponto(curva.Evaluate(0.5, True)),
        }
    # Falha em voz alta: uma curva silenciosamente ignorada vira família errada.
    # Quem chama isola a forma e transforma isto em lacuna — famílias reais têm
    # splines e elipses, e perder a forma inteira com registro é honesto;
    # aproximá-la por reta não seria.
    raise ValueError(
        u"curva de perfil sem suporte: {0}".format(type(curva).__name__)
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
    # Curvas de esboço endereçáveis (schema 0.2.0): id do elemento de curva ->
    # (forma, laço, curva). É o que permite ler uma cota radial rotulada no
    # esboço, o único caminho de raio paramétrico que a G0 provou.
    curvas_de_esboco = {}

    for elemento in todas:
        indice = len(formas)
        classe = type(elemento).__name__

        # Uma forma ilegível NUNCA pode derrubar a leitura da família inteira.
        # Famílias reais têm esboços que o Revit se recusa a devolver como
        # laços ("Sketch loops cannot be obtained") e curvas fora da cobertura
        # (splines, elipses). Cada forma é isolada: falha vira lacuna, com o
        # motivo real, e o resto da família continua sendo lido.
        registro = None
        motivo = u"forma sem suporte: {0}".format(classe)
        try:
            if isinstance(elemento, Extrusion):
                registro = _ler_extrusao(elemento)
                motivo = u"Extrusion sem dados suficientes para reconstruir"
            elif isinstance(elemento, Revolution):
                registro = _ler_revolucao(elemento)
                motivo = u"Revolution sem eixo legível"
            elif isinstance(elemento, Sweep):
                registro = _ler_varredura(elemento)
                motivo = u"Sweep sem caminho ou perfil legível"
            elif isinstance(elemento, SweptBlend):
                # Antes do Blend: SweptBlend NÃO herda de Blend, mas a ordem
                # explícita documenta a intenção.
                registro = _ler_varredura_mesclada(elemento)
                motivo = u"SweptBlend sem caminho ou perfis legíveis"
            elif isinstance(elemento, Blend):
                registro = _ler_mescla(elemento)
                motivo = u"Blend sem esboços legíveis"
        except Exception as erro:
            registro = None
            motivo = u"{0} ilegível: {1}".format(
                classe, rfaspec.para_unicode(str(erro))[:120])

        if registro is None:
            lacunas.append({
                u"elemento_id": _id_valor(elemento.Id),
                u"classe": classe,
                u"motivo": motivo,
            })
            continue

        subcategoria = elemento.Subcategory
        parametro_material = elemento.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM)
        material_fixo = _material(parametro_material.AsElementId()) if parametro_material is not None else None
        registro.update({
            u"material": material_fixo[u"material"] if material_fixo else None,
            u"indice": indice,
            u"solido": bool(elemento.IsSolid),
            u"visivel": bool(elemento.Visible),
            u"subcategoria": subcategoria.Name if subcategoria else None,
            u"associacoes": _associacoes_de_parametro(gerenciador, elemento),
        })
        formas.append(registro)
        indice_por_id[_id_valor(elemento.Id)] = indice
        if isinstance(elemento, (Extrusion, Revolution)):
            _mapear_curvas_de_esboco(elemento, indice, curvas_de_esboco)

    return formas, indice_por_id, lacunas, curvas_de_esboco


def _mapear_curvas_de_esboco(extrusao, indice, mapa):
    try:
        for numero_laco, laco in enumerate(list(extrusao.Sketch.Profile)):
            for numero_curva, curva in enumerate(list(laco)):
                referencia = curva.Reference
                if referencia is not None:
                    mapa[_id_valor(referencia.ElementId)] = (indice, numero_laco, numero_curva)
    except Exception:
        pass  # esboço ilegível já virou lacuna na leitura da forma
    # O EIXO da revolução é uma linha do esboço fora do perfil. Cotado a um
    # plano, ele move a revolução inteira (revolução pequena dos bocais da
    # Solaris, a 12,5 mm de P3). Laço -1: o construtor casa pela geometria.
    try:
        for identificador in extrusao.Sketch.GetAllElements():
            chave = _id_valor(identificador)
            if chave not in mapa and isinstance(extrusao, Revolution):
                elemento = extrusao.Document.GetElement(identificador)
                if elemento is not None and type(elemento).__name__ in ("ModelLine", "ModelCurve"):
                    mapa[chave] = (indice, -1, -1)
    except Exception:
        pass


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


def _perfil_local(esboco):
    u"""Perfil em coordenadas 2D LOCAIS do plano do esboço, em mm.

    Sweep e SweptBlend exigem o perfil "no plano XY" (NewCurveLoopsProfile o
    transporta para o plano do caminho), então gravar coordenadas de mundo —
    como a extrusão faz — produziria perfil no lugar errado. A projeção usa
    XVec/YVec do plano: u = (p-origem)·XVec, v = (p-origem)·YVec.
    """
    plano = esboco.SketchPlane.GetPlane()
    origem, eixo_u, eixo_v = plano.Origin, plano.XVec, plano.YVec

    def _2d(ponto):
        delta = ponto - origem
        return [para_mm(delta.DotProduct(eixo_u)), para_mm(delta.DotProduct(eixo_v))]

    lacos = []
    for laco in esboco.Profile:
        curvas = []
        for curva in laco:
            if isinstance(curva, Line):
                curvas.append({
                    u"tipo": u"linha",
                    u"inicio": _2d(curva.GetEndPoint(0)),
                    u"fim": _2d(curva.GetEndPoint(1)),
                })
            elif isinstance(curva, Arc):
                curvas.append({
                    u"tipo": u"arco",
                    u"inicio": _2d(curva.GetEndPoint(0)),
                    u"fim": _2d(curva.GetEndPoint(1)),
                    u"meio": _2d(curva.Evaluate(0.5, True)),
                })
            else:
                raise ValueError(
                    u"curva de perfil sem suporte: {0}".format(type(curva).__name__))
        curvas and lacos.append(curvas)
    return lacos


def _ler_varredura(varredura):
    u"""Sweep: perfil transportado ao longo de um caminho.

    O caminho fica em coordenadas de mundo (reconstruído sobre o plano do
    esboço do caminho); o perfil fica em 2D local (ver _perfil_local).
    Índice e posição do perfil não são legíveis pela API — a reconstrução usa
    0/Start, e qualquer desvio disso aparece no volume do validador.
    """
    esboco_caminho = varredura.PathSketch
    esboco_perfil = varredura.ProfileSketch
    if esboco_caminho is None or esboco_perfil is None:
        return None

    return {
        u"tipo": u"varredura",
        u"plano_de_esboco": _plano_de_esboco(esboco_caminho),
        u"caminho": _perfil_para_lista(esboco_caminho.Profile),
        u"perfil_local": _perfil_local(esboco_perfil),
    }


def _ler_mescla(mescla):
    u"""Blend: perfil base transita para o perfil de topo.

    Os dois perfis ficam em coordenadas de MUNDO — o NewBlend os aceita assim,
    com o topo já na altura real (Building Coder 0470). Os offsets são lidos à
    parte porque blend autorado na UI pode guardar a altura em parâmetro
    ("Second End") com os dois esboços no mesmo plano — nesse caso o construtor
    reaplica o offset.
    """
    esboco_base = mescla.BottomSketch
    esboco_topo = mescla.TopSketch
    if esboco_base is None or esboco_topo is None:
        return None

    # O Revit normaliza SEMPRE os dois esboços para o plano da base e guarda
    # as alturas nas propriedades FirstEnd/SecondEnd — até blend criado via
    # API com o topo em z real é relido assim (verificado na fixture: topo
    # criado em z=120 voltou com curvas em z=0). A altura mora nos offsets.
    return {
        u"tipo": u"mescla",
        u"plano_de_esboco": _plano_de_esboco(esboco_base),
        u"perfil_base": _perfil_para_lista(esboco_base.Profile),
        u"perfil_topo": _perfil_para_lista(esboco_topo.Profile),
        # Nomes REAIS, achados por sonda exaustiva (sonda_blend.py) depois de
        # cinco candidatos errados: propriedades TopOffset/BottomOffset,
        # builtins BLEND_END_PARAM/BLEND_START_PARAM ("Second End"/"First End"
        # na UI). FirstEnd/SecondEnd como propriedade NÃO existem.
        u"deslocamento_topo": _primeiro_nao_nulo(
            _duplo_propriedade(mescla, "TopOffset"),
            _duplo_builtin(mescla, "BLEND_END_PARAM")),
        u"deslocamento_base": _primeiro_nao_nulo(
            _duplo_propriedade(mescla, "BottomOffset"),
            _duplo_builtin(mescla, "BLEND_START_PARAM")),
    }


def _primeiro_nao_nulo(*valores):
    u"""Primeiro valor que não é None — 0.0 é valor legítimo, `or` o perderia."""
    for valor in valores:
        if valor is not None:
            return valor
    return None


def _ler_varredura_mesclada(elemento):
    u"""SweptBlend: dois perfis transportados ao longo de UM segmento.

    Leitura inteiramente defensiva (getattr): a superfície da API varia e o
    que faltar vira lacuna, nunca crash.
    """
    esboco_caminho = getattr(elemento, "PathSketch", None)
    esboco_base = getattr(elemento, "BottomSketch", None)
    esboco_topo = getattr(elemento, "TopSketch", None)
    if esboco_caminho is None or esboco_base is None or esboco_topo is None:
        return None

    caminho = _perfil_para_lista(esboco_caminho.Profile)
    # NewSweptBlend aceita UMA curva de caminho; mais que isso é lacuna.
    if len(caminho) != 1 or len(caminho[0]) != 1:
        return None

    return {
        u"tipo": u"varredura_mesclada",
        u"plano_de_esboco": _plano_de_esboco(esboco_caminho),
        u"caminho": caminho,
        u"perfil_base": _perfil_local(esboco_base),
        u"perfil_topo": _perfil_local(esboco_topo),
    }


def _duplo_propriedade(elemento, nome):
    u"""Propriedade Double de um elemento, em mm; None se ausente/ilegível."""
    try:
        valor = getattr(elemento, nome, None)
        return para_mm(float(valor)) if valor is not None else None
    except Exception:
        return None


def _duplo_builtin(elemento, *nomes):
    u"""Valor Double de um parâmetro builtin resolvido por nome, em mm."""
    builtin = _builtin(*nomes)
    if builtin is None:
        return None
    try:
        parametro = elemento.get_Parameter(builtin)
    except Exception:
        return None
    if parametro is None:
        return None
    return para_mm(parametro.AsDouble())


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

def _endereco_da_referencia(doc, referencia, indice_por_id, curvas_de_esboco=None):
    u"""Traduz um Reference do Revit num endereço portável.

    Este é o ponto mais delicado do projeto: se o endereço não for reencontrável
    no documento de destino, a cota não é religada e a família não flexiona.
    Retorna None quando não há como endereçar — o chamador reporta como lacuna.
    """
    elemento = doc.GetElement(referencia.ElementId)
    if elemento is None:
        return None

    if isinstance(elemento, ReferencePlane):
        endereco = _ENDERECO_DO_PLANO.get(_id_valor(elemento.Id))
        if not endereco:
            return None
        return {u"tipo": u"plano", u"nome": endereco}

    if type(elemento).__name__ == "Level":
        # O template de família tem um nível só (Ref. Level / Nível de referência).
        return {u"tipo": u"nivel"}

    if isinstance(elemento, FamilyInstance):
        indice = _INDICE_ANINHADA.get(_id_valor(elemento.Id))
        if indice is None:
            return None
        # Plano nomeado da aninhada (Center Left/Right...) pelo tipo de
        # referência; o nome cobre os planos "Strong/Weak Reference".
        try:
            tipo_referencia = str(elemento.GetReferenceType(referencia))
        except Exception:
            tipo_referencia = None
        try:
            nome_referencia = rfaspec.para_unicode(elemento.GetReferenceName(referencia))
        except Exception:
            nome_referencia = None
        if not tipo_referencia or tipo_referencia == u"NotAReference" and not nome_referencia:
            return None
        # Vários planos do mesmo tipo (Weak Reference sem nome, no anel da
        # Ultrapex): a posição na lista de GetReferences, que segue a ordem de
        # criação; o construtor recria os planos da aninhada na mesma ordem.
        ordem = None
        try:
            from Autodesk.Revit.DB import FamilyInstanceReferenceType
            estavel = referencia.ConvertToStableRepresentation(doc)
            candidatas = list(elemento.GetReferences(getattr(FamilyInstanceReferenceType, tipo_referencia)))
            for posicao, candidata in enumerate(candidatas):
                if candidata.ConvertToStableRepresentation(doc) == estavel:
                    ordem = posicao
        except Exception:
            ordem = None
        return {u"tipo": u"aninhada", u"instancia": indice, u"ref_tipo": tipo_referencia,
                u"ref_nome": nome_referencia or None, u"ref_ordem": ordem}

    no_esboco = (curvas_de_esboco or {}).get(_id_valor(elemento.Id))
    if no_esboco is not None:
        endereco = {u"tipo": u"esboco", u"forma": no_esboco[0],
                    u"laco": no_esboco[1], u"curva": no_esboco[2]}
        # A trava pode ser na PONTA da curva, não na curva (sonda S11: a
        # Solaris prende o perfil assim). A representação estável termina em
        # "LINEAR/0" ou "LINEAR/1" nesse caso; tratar como a curva inteira dá
        # "not geometrically aligned" no destino.
        # O destino recria o esboço com outra ordem e outro sentido de curvas
        # (S11): o construtor casa pela GEOMETRIA (pontas da curva e ponto da
        # trava), e laço/curva ficam só como pista.
        try:
            curva = elemento.GeometryCurve
            endereco[u"pontas_mm"] = [_ponto(curva.GetEndPoint(0)), _ponto(curva.GetEndPoint(1))]
            # Arco e corda de um semicírculo têm as mesmas pontas: o meio desempata.
            endereco[u"meio_mm"] = _ponto(curva.Evaluate(0.5, True))
            estavel = referencia.ConvertToStableRepresentation(doc)
            for ponta in (0, 1):
                if estavel.endswith(u"LINEAR/{0}".format(ponta)):
                    endereco[u"ponta"] = ponta
                    endereco[u"ponto_mm"] = _ponto(curva.GetEndPoint(ponta))
        except Exception:
            pass
        return endereco

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


def _direcao_da_cota(dimensao):
    u"""Direção da linha da cota linear. Entre duas PONTAS do esboço ela não se
    deduz das referências: a cota do anel da Ultrapex mede na vertical entre
    pontas afastadas 8 mm na horizontal."""
    try:
        curva = dimensao.Curve
        if isinstance(curva, Line):
            return _vetor(curva.Direction)
    except Exception:
        pass
    return None


def _segmentos_iguais(dimensao):
    u"""Cota de igualdade (EQ): é ela que centra o diâmetro da Solaris entre os
    dois planos; sem ela, só um lado anda e o diâmetro cresce em dobro."""
    try:
        return dimensao.NumberOfSegments > 1 and bool(dimensao.AreSegmentsEqual)
    except Exception:
        return False


def ler_cotas(doc, indice_por_id, curvas_de_esboco=None):
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
            endereco = _endereco_da_referencia(doc, referencia, indice_por_id, curvas_de_esboco)
            if endereco is None:
                incompleta = True
                break
            enderecos.append(endereco)

        categoria = dimensao.Category
        eh_restricao = (
            categoria is not None and _id_valor(categoria.Id) == id_restricoes
        )

        forma_da_cota = str(dimensao.DimensionShape)
        # Raio e diâmetro têm UMA referência (a curva); as lineares, duas ou mais.
        radial = forma_da_cota in (u"Radial", u"Diameter")
        minimo = 1 if radial else 2
        # Endereço de esboço só vale para raio/diâmetro. As cotas lineares
        # internas do esboço (lados do retângulo, cordas dos arcos), que o
        # Revit cria sozinho, continuam lacuna como antes do schema 0.2.0:
        # o construtor não as recria e só gerariam ruído no relatório.
        no_esboco = any(e.get(u"tipo") == u"esboco" for e in enderecos)
        com_plano = any(e.get(u"tipo") == u"plano" for e in enderecos)
        try:
            travada = bool(dimensao.IsLocked)
        except Exception:
            travada = False
        try:
            rotulada = dimensao.FamilyLabel is not None
        except Exception:
            rotulada = False
        # Curva de esboço presa a plano é o que faz o PERFIL flexionar (S11):
        # alinhamento esboço+plano, cota com plano rotulada ou travada, e cota
        # travada entre curvas do esboço. Cota solta do esboço (anotação, ou
        # as que o Revit cria sozinho) continua lacuna.
        com_face = any(e.get(u"tipo") == u"face" for e in enderecos)
        # Cota de valor 0, sem rótulo nem trava, entre curva do esboço e plano
        # (bocais da Solaris): na origem o perfil segue o plano. Vira
        # alinhamento, que a sonda S11 provou flexionar (V1 e V5).
        com_nivel = any(e.get(u"tipo") == u"nivel" for e in enderecos)
        if no_esboco and (com_plano or com_nivel) and not eh_restricao and not rotulada and not travada and \
                forma_da_cota == u"Linear" and len(enderecos) == 2:
            try:
                zero = dimensao.Value is not None and abs(dimensao.Value) < 1e-9
            except Exception:
                zero = False
            arco_sem_ponta = False
            for referencia_bruta, endereco_lido in zip(list(dimensao.References), enderecos):
                if endereco_lido.get(u"tipo") == u"esboco" and endereco_lido.get(u"ponta") is None:
                    elemento_ref = doc.GetElement(referencia_bruta.ElementId)
                    curva_ref = getattr(elemento_ref, "GeometryCurve", None)
                    if curva_ref is not None and not isinstance(curva_ref, Line):
                        arco_sem_ponta = True
            if zero and arco_sem_ponta:
                # A referência é o CENTRO do arco; o Revit não alinha arco com
                # plano ("cannot be matched"). Fica como lacuna honesta.
                lacunas.append({u"elemento_id": _id_valor(dimensao.Id), u"eh_restricao": False,
                                u"motivo": u"cota de valor 0 até o centro de um arco"})
                continue
            if zero:
                alinhamentos.append({u"referencias": enderecos, u"de_cota_zero": True})
                continue
        if no_esboco and not (com_plano or com_nivel or com_face) and forma_da_cota == u"Linear":
            try:
                zero_interna = dimensao.Value is not None and abs(dimensao.Value) < 1e-9
            except Exception:
                zero_interna = False
            pontos = [e.get(u"ponto_mm") for e in enderecos if e.get(u"ponto_mm")]
            # Valor 0 entre pontas DISTINTAS (anel da Ultrapex: 8 mm na
            # horizontal, 0 na vertical). Recriada, ela prende o raio do anel
            # (na direção deduzida) ou deforma tudo (na direção da origem):
            # fica como lacuna. Pontas coincidentes (letras do logo) seguem.
            distintas = len(pontos) == 2 and sum((a - b) ** 2 for a, b in zip(pontos[0], pontos[1])) > 1e-6
            if zero_interna and distintas:
                lacunas.append({u"elemento_id": _id_valor(dimensao.Id), u"eh_restricao": False,
                                u"motivo": u"cota de valor 0 entre pontas distintas do esboço"})
                continue
        # Angular: só entre duas curvas/planos (sem trava de ponta), rotulada ou
        # travada; o construtor recria pelo cruzamento das duas referências.
        linear = forma_da_cota == u"Linear"
        angular = forma_da_cota == u"Angular" and len(enderecos) == 2 and \
            not any(e.get(u"ponta") is not None for e in enderecos) and (rotulada or travada)
        # Cota do esboço COMANDA o perfil mesmo sem rótulo e sem trava: quando a
        # referência se move, a curva anda para manter o valor (bocais da
        # Solaris). Por isso toda cota linear do esboço é lida; o construtor
        # apaga as que o Revit gera sozinho e recria exatamente estas.
        # Cota SÓ entre curvas do esboço, sem rótulo nem trava, só mantém o
        # desenho e não liga o perfil a nada que se mova: fica de fora (as 118
        # das letras NURBS do logo da Solaris deformavam o logo inteiro).
        interna_livre = linear and not (com_plano or com_nivel or com_face or rotulada or travada)
        if interna_livre:
            # Entre RETAS ela mantém o perfil (bocais: 45 e 50 mm entre linhas;
            # sem elas -1,3% de volume num tipo). Só a que toca curva não reta
            # (NURBS, arco das letras) fica de fora.
            try:
                interna_livre = any(not isinstance(getattr(doc.GetElement(r.ElementId), "GeometryCurve", None), Line)
                                    for r in dimensao.References)
            except Exception:
                pass
        esboco_aceito = radial or angular or eh_restricao and (com_plano or com_face or com_nivel) or \
            linear and not interna_livre
        if incompleta or len(enderecos) < minimo or (no_esboco and not esboco_aceito):
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

        # Algumas cotas recusam até a LEITURA do rótulo ("This dimension can
        # not be labeled", visto em família gerada pelo gerador, 17/10). Para
        # o leitor isso é só "sem rótulo"; não pode derrubar a família inteira.
        try:
            rotulo = dimensao.FamilyLabel
        except Exception:
            rotulo = None
        cotas.append({
            u"referencias": enderecos,
            u"rotulo": rotulo.Definition.Name if rotulo is not None else None,
            u"forma": forma_da_cota,
            u"travada": travada,
            u"iguais": _segmentos_iguais(dimensao),
            u"direcao": _direcao_da_cota(dimensao),
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


def _face_do_conector(doc, conector, indice_por_id):
    u"""Forma e normal da face plana onde o conector está (pela geometria).

    A API não devolve a referência hospedeira do ConnectorElement; a face é a
    plana, de normal igual à direção do conector, que contém a origem dele.
    """
    origem, direcao = conector.Origin, conector.Direction
    opcoes = Options()
    opcoes.ComputeReferences = True
    for identificador, indice in indice_por_id.items():
        elemento = doc.GetElement(ElementId(identificador))
        if elemento is None:
            continue
        for objeto in elemento.get_Geometry(opcoes):
            if not isinstance(objeto, Solid):
                continue
            for face in objeto.Faces:
                if not isinstance(face, PlanarFace) or not face.FaceNormal.IsAlmostEqualTo(direcao):
                    continue
                projecao = face.Project(origem)
                if projecao is not None and projecao.Distance < 1e-6:
                    return {u"forma": indice, u"normal": _vetor(face.FaceNormal)}
    # Conector numa face de família ANINHADA (bocais da Solaris).
    from Autodesk.Revit.DB import GeometryInstance
    for instancia in FilteredElementCollector(doc).OfClass(FamilyInstance).ToElements():
        indice = _INDICE_ANINHADA.get(_id_valor(instancia.Id))
        if indice is None:
            continue
        for objeto in instancia.get_Geometry(opcoes) or []:
            if not isinstance(objeto, GeometryInstance):
                continue
            for solido in objeto.GetInstanceGeometry():
                if not isinstance(solido, Solid):
                    continue
                for face in solido.Faces:
                    if not isinstance(face, PlanarFace) or not face.FaceNormal.IsAlmostEqualTo(direcao):
                        continue
                    projecao = face.Project(origem)
                    if projecao is not None and projecao.Distance < 1e-6:
                        return {u"aninhada": indice, u"normal": _vetor(face.FaceNormal), u"origem": _ponto(origem)}
    # Conector hospedado num PLANO de referência (tê da Ultrapex: nenhuma face
    # passa pela origem dos 3 conectores; cada um coincide com um plano).
    for plano in FilteredElementCollector(doc).OfClass(ReferencePlane).ToElements():
        if abs(abs(plano.Normal.DotProduct(direcao)) - 1.0) > 1e-6:
            continue
        if abs((origem - plano.BubbleEnd).DotProduct(plano.Normal)) < 1e-6:
            endereco = _ENDERECO_DO_PLANO.get(_id_valor(plano.Id))
            if endereco:
                return {u"plano": endereco, u"normal": _vetor(direcao), u"origem": _ponto(origem)}
    return None


def ler_conectores(doc, indice_por_id):
    u"""Conectores de tubo (schema 0.3.0). Outros domínios viram lacuna."""
    gerenciador = doc.FamilyManager
    elementos = sorted(FilteredElementCollector(doc).OfClass(ConnectorElement).ToElements(),
                       key=lambda e: _id_valor(e.Id))
    posicao = dict((_id_valor(e.Id), i) for i, e in enumerate(elementos))
    conectores, lacunas = [], []
    for conector in elementos:
        dominio = str(conector.Domain)
        if dominio != "DomainPiping":
            lacunas.append({u"elemento_id": _id_valor(conector.Id),
                            u"motivo": u"conector fora da cobertura: {0}".format(dominio)})
            continue
        face = _face_do_conector(doc, conector, indice_por_id)
        if face is None:
            lacunas.append({u"elemento_id": _id_valor(conector.Id),
                            u"motivo": u"face hospedeira do conector não encontrada entre as formas lidas"})
            continue
        diametro = conector.get_Parameter(BuiltInParameter.CONNECTOR_DIAMETER)
        associado = gerenciador.GetAssociatedFamilyParameter(diametro) if diametro is not None else None
        # Família de roteamento (Ultrapex): o RAIO do conector dirige o RN, e o
        # tamanho da peça vem do tubo conectado.
        raio = conector.get_Parameter(BuiltInParameter.CONNECTOR_RADIUS)
        associado_raio = gerenciador.GetAssociatedFamilyParameter(raio) if raio is not None else None
        ligado = None
        try:
            outro = conector.GetLinkedConnectorElement()
            if outro is not None:
                ligado = posicao.get(_id_valor(outro.Id))
        except Exception:
            ligado = None
        conectores.append({
            u"dominio": u"tubo",
            u"sistema": rfaspec.para_unicode(str(conector.SystemClassification)),
            u"face": face,
            u"diametro_mm": rfaspec.interno_para_mm(2 * conector.Radius),
            u"diametro_rotulo": associado.Definition.Name if associado is not None else None,
            u"raio_rotulo": associado_raio.Definition.Name if associado_raio is not None else None,
            u"ligado_a": ligado,
        })
    return conectores, lacunas


def ler_tabelas_de_consulta(doc):
    u"""Tabelas de consulta (size_lookup) embutidas, com o CSV BYTE A BYTE.

    O conteúdo vai como texto de semântica latin-1 (unichr(ord(byte))), sem
    codec: o CSV exportado pelo Revit pode vir em qualquer codificação, e o
    construtor regrava os mesmos bytes. Sem as tabelas, toda fórmula
    size_lookup cai no destino (35 na Solaris, 3 a 5 por conexão Ultrapex).
    """
    import tempfile
    from Autodesk.Revit.DB import FamilySizeTableManager
    gerenciador = FamilySizeTableManager.GetFamilySizeTableManager(doc, doc.OwnerFamily.Id)
    if gerenciador is None:
        return [], []
    tabelas, lacunas = [], []
    pasta = tempfile.mkdtemp(prefix=u"rfadg_tabelas_")
    for nome in gerenciador.GetAllSizeTableNames():
        caminho = os.path.join(pasta, u"tabela.csv")
        try:
            if not gerenciador.ExportSizeTable(nome, caminho):
                raise ValueError(u"ExportSizeTable devolveu falso")
            with open(caminho, "rb") as arquivo:
                bruto = arquivo.read()
            tabelas.append({u"nome": rfaspec.para_unicode(nome),
                            u"conteudo": u"".join([unichr(ord(c)) for c in bruto])})  # noqa: F821
        except Exception as erro:
            lacunas.append({u"motivo": u"tabela de consulta '{0}' não exportada: {1}".format(
                rfaspec.para_unicode(nome), rfaspec.para_unicode(unicode(erro))[:120])})  # noqa: F821
    return tabelas, lacunas


def _tipo_de_peca(doc):
    parametro = doc.OwnerFamily.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
    if parametro is None:
        return None
    try:
        return rfaspec.para_unicode(str(Enum.ToObject(PartType, parametro.AsInteger())))
    except Exception:
        return None


# --------------------------------------------------------------------------
# Famílias aninhadas (plano em docs/PLANO-aninhadas-e-travas-de-esboco.md)
# --------------------------------------------------------------------------

_PROFUNDIDADE_MAXIMA = 3
# id da FamilyInstance -> índice em `aninhadas` (para cotas, alinhamentos e
# conectores que referenciam a instância).
_INDICE_ANINHADA = {}


def _nome_do_elemento(elemento):
    # Family/FamilySymbol/ImageType.Name não são acessíveis no IronPython.
    from Autodesk.Revit.DB import Element
    return rfaspec.para_unicode(Element.Name.__get__(elemento))


def _estado_global():
    return (_DOC[0], dict(_MATERIAIS), dict(_IMAGENS), dict(_ENDERECO_DO_PLANO), dict(_INDICE_ANINHADA))


def _restaurar_estado(estado):
    _DOC[0] = estado[0]
    for alvo, valor in zip((_MATERIAIS, _IMAGENS, _ENDERECO_DO_PLANO, _INDICE_ANINHADA), estado[1:]):
        alvo.clear()
        alvo.update(valor)


def _hospedeiro_da_aninhada(doc, instancia, indice_por_id):
    u"""Plano de referência ou face de forma onde a instância está hospedada."""
    try:
        referencia = instancia.HostFace
    except Exception:
        referencia = None
    hospedeiro = instancia.Host
    if hospedeiro is None:
        return None
    if isinstance(hospedeiro, ReferencePlane):
        endereco = _ENDERECO_DO_PLANO.get(_id_valor(hospedeiro.Id))
        return {u"tipo": u"plano", u"nome": endereco} if endereco else {u"tipo": u"ilegivel"}
    # Face de forma (plana ou curva: o BOCAL2 da Solaris fica na face do corpo
    # revolucionado). O construtor acha a face que contém o ponto da instância.
    indice = indice_por_id.get(_id_valor(hospedeiro.Id))
    if indice is not None:
        return {u"tipo": u"face_da_forma", u"forma": indice, u"ponto": _ponto(instancia.GetTransform().Origin)}
    return {u"tipo": u"ilegivel", u"classe": type(hospedeiro).__name__}


def _associacoes_da_instancia(gerenciador, instancia):
    associacoes = []
    for parametro in instancia.Parameters:
        try:
            associado = gerenciador.GetAssociatedFamilyParameter(parametro)
        except Exception:
            associado = None
        if associado is None:
            continue
        try:
            embutido = str(parametro.Definition.BuiltInParameter)
        except Exception:
            embutido = None
        associacoes.append({
            u"parametro": rfaspec.para_unicode(parametro.Definition.Name),
            u"embutido": embutido if embutido and embutido != u"INVALID" else None,
            u"da_familia": rfaspec.para_unicode(associado.Definition.Name),
        })
    return associacoes


def _valores_da_instancia(gerenciador, instancia):
    u"""Valores de instância próprios da aninhada (não associados à hospedeira).

    Parâmetro de instância da família aninhada vale POR instância: os bocais
    da Solaris têm o comprimento definido em cada instância. Só os de usuário
    (o embutido de posição já vem pela transformação).
    """
    valores = []
    for parametro in instancia.Parameters:
        try:
            if parametro.IsReadOnly or not parametro.HasValue:
                continue
            definicao = parametro.Definition
            try:
                if str(definicao.BuiltInParameter) != u"INVALID":
                    continue
            except Exception:
                pass
            if gerenciador.GetAssociatedFamilyParameter(parametro) is not None:
                continue
            armazenamento = parametro.StorageType
            item = {u"parametro": rfaspec.para_unicode(definicao.Name)}
            if armazenamento == StorageType.Double:
                comprimento = rfaspec.eh_comprimento(_forge_id(definicao.GetDataType()))
                item[u"valor"] = para_mm(parametro.AsDouble()) if comprimento else parametro.AsDouble()
                item[u"comprimento"] = comprimento
            elif armazenamento == StorageType.Integer:
                item[u"valor"] = parametro.AsInteger()
            elif armazenamento == StorageType.String:
                item[u"valor"] = rfaspec.para_unicode(parametro.AsString())
            elif armazenamento == StorageType.ElementId:
                material = _material(parametro.AsElementId())
                if material is None:
                    continue
                item[u"valor"] = material
            else:
                continue
            valores.append(item)
        except Exception:
            continue
    return valores


def ler_aninhadas(doc, indice_por_id, profundidade):
    u"""Instâncias aninhadas e, para cada família distinta, a FamilySpec dela.

    A família aninhada é aberta com EditFamily e lida pelo próprio leitor
    (recursão); o estado global do leitor é guardado e restaurado em volta.
    `GetSubComponentIds()` só devolve as compartilhadas: o coletor de
    FamilyInstance pega todas (armadilha do CLAUDE.md §10).
    """
    _INDICE_ANINHADA.clear()
    gerenciador = doc.FamilyManager
    instancias = sorted(FilteredElementCollector(doc).OfClass(FamilyInstance).ToElements(),
                        key=lambda e: _id_valor(e.Id))
    familias, por_nome, aninhadas, lacunas = [], {}, [], []
    for instancia in instancias:
        simbolo = instancia.Symbol
        familia = simbolo.Family
        nome_familia = _nome_do_elemento(familia)
        if nome_familia not in por_nome:
            if profundidade >= _PROFUNDIDADE_MAXIMA:
                lacunas.append({u"elemento_id": _id_valor(instancia.Id),
                                u"motivo": u"aninhada além de {0} níveis".format(_PROFUNDIDADE_MAXIMA)})
                continue
            estado = _estado_global()
            sub = None
            try:
                sub = doc.EditFamily(familia)
                especificacao = extrair(sub, profundidade + 1)
            except Exception as erro:
                especificacao = None
                lacunas.append({u"elemento_id": _id_valor(instancia.Id),
                                u"motivo": u"família aninhada '{0}' ilegível: {1}".format(
                                    nome_familia, rfaspec.para_unicode(unicode(erro))[:120])})  # noqa: F821
            finally:
                _restaurar_estado(estado)
                if sub is not None:
                    sub.Close(False)
            if especificacao is None:
                continue
            por_nome[nome_familia] = len(familias)
            familias.append({u"nome": nome_familia, u"especificacao": especificacao})
        transformacao = instancia.GetTransform()
        visivel = instancia.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM)
        _INDICE_ANINHADA[_id_valor(instancia.Id)] = len(aninhadas)
        aninhadas.append({
            u"familia": por_nome[nome_familia],
            u"tipo": rfaspec.para_unicode(simbolo.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()),
            u"ponto": _ponto(transformacao.Origin),
            u"eixo_x": _vetor(transformacao.BasisX),
            u"eixo_y": _vetor(transformacao.BasisY),
            u"eixo_z": _vetor(transformacao.BasisZ),
            u"espelhada": bool(instancia.Mirrored),
            u"hospedeiro": _hospedeiro_da_aninhada(doc, instancia, indice_por_id),
            u"associacoes": _associacoes_da_instancia(gerenciador, instancia),
            u"valores": _valores_da_instancia(gerenciador, instancia),
            u"visivel": bool(visivel.AsInteger()) if visivel is not None else None,
        })
    return familias, aninhadas, lacunas


def _medir_com_aninhadas(doc):
    u"""Extensão e volume por tipo INCLUINDO a geometria das aninhadas.

    A assinatura da régua (rfaspec.medir_por_tipo) só mede as formas da
    própria família; esta é a medida que diz se as aninhadas vieram certas.
    """
    from Autodesk.Revit.DB import Transaction, GeometryInstance, ViewDetailLevel
    gerenciador = doc.FamilyManager
    saida = {}
    opcoes = Options()
    # Conexões mostram as peças só no Fino; a mesma opção nos dois lados.
    opcoes.DetailLevel = ViewDetailLevel.Fine
    for tipo in list(gerenciador.Types):
        if not tipo.Name:
            continue
        transacao = Transaction(doc, u"medir com aninhadas")
        transacao.Start()
        try:
            gerenciador.CurrentType = tipo
            doc.Regenerate()
            volume, minimos, maximos = 0.0, None, None
            # As formas pela mesma coleta da régua (que já trata o corte de
            # vazio pelo GeomCombination) + a geometria das instâncias.
            objetos = list(rfaspec._coletar_solidos(doc)[0])
            for elemento in FilteredElementCollector(doc).OfClass(FamilyInstance).ToElements():
                geometria = elemento.get_Geometry(opcoes)
                if geometria is None:
                    continue
                for objeto in geometria:
                    if isinstance(objeto, GeometryInstance):
                        objetos.extend(list(objeto.GetInstanceGeometry()))
            for objeto in objetos:
                if not isinstance(objeto, Solid) or objeto.Volume <= 0:
                    continue
                volume += objeto.Volume
                caixa = objeto.GetBoundingBox()
                for x in (caixa.Min.X, caixa.Max.X):
                    for y in (caixa.Min.Y, caixa.Max.Y):
                        for z in (caixa.Min.Z, caixa.Max.Z):
                            p = caixa.Transform.OfPoint(XYZ(x, y, z))
                            if minimos is None:
                                minimos, maximos = [p.X, p.Y, p.Z], [p.X, p.Y, p.Z]
                            for eixo, valor in enumerate((p.X, p.Y, p.Z)):
                                minimos[eixo] = min(minimos[eixo], valor)
                                maximos[eixo] = max(maximos[eixo], valor)
            if minimos is not None:
                saida[rfaspec.para_unicode(tipo.Name)] = {
                    u"extensao_mm": [para_mm(maximos[i] - minimos[i]) for i in range(3)],
                    u"volume_mm3": rfaspec.interno_para_mm3(volume)}
        finally:
            transacao.RollBack()
    return saida


def extrair(doc, profundidade=0):
    if not doc.IsFamilyDocument:
        raise ValueError(
            u"O documento aberto não é uma família. Recebido: {0}".format(doc.Title)
        )

    _DOC[0] = doc
    _MATERIAIS.clear()
    _IMAGENS.clear()
    parametros, tipos = ler_parametros(doc)
    planos = ler_planos_de_referencia(doc)  # antes das cotas: define os endereços
    formas, indice_por_id, lacunas_de_forma, curvas_de_esboco = ler_formas(doc)
    # Antes das cotas: define o índice das instâncias que elas referenciam.
    familias_aninhadas, aninhadas, lacunas_de_aninhada = ler_aninhadas(doc, indice_por_id, profundidade)
    cotas, alinhamentos, lacunas = ler_cotas(doc, indice_por_id, curvas_de_esboco)
    # 0.2.0 só quando há cota no esboço: o resto do formato não mudou.
    no_esboco = any(endereco.get(u"tipo") == u"esboco"
                    for cota in cotas for endereco in cota[u"referencias"])
    combinacoes, lacunas_de_corte = ler_combinacoes(doc, indice_por_id)
    conectores, lacunas_de_conector = ler_conectores(doc, indice_por_id)
    tabelas, lacunas_de_tabela = ler_tabelas_de_consulta(doc)
    lacunas = lacunas_de_forma + lacunas_de_aninhada + lacunas + lacunas_de_corte + lacunas_de_conector + \
        lacunas_de_tabela
    identidade = ler_identidade(doc)
    identidade[u"part_type"] = _tipo_de_peca(doc)
    if conectores:
        versao = u"0.3.0"
    elif no_esboco:
        versao = u"0.2.0"
    else:
        versao = rfaspec.SCHEMA_VERSION

    especificacao = {
        u"versao_schema": versao,
        u"origem": {
            u"arquivo": doc.Title,
            u"versao_revit": rfaspec.env("RFADG_ORIGEM_VERSAO", u"desconhecida"),
        },
        u"identidade": identidade,
        u"parametros": parametros,
        u"tipos": tipos,
        # Configuração em que TODA a geometria abaixo foi serializada.
        u"tipo_corrente": ler_tipo_corrente(doc),
        u"planos_de_referencia": planos,
        u"formas": formas,
        u"cotas": cotas,
        u"alinhamentos": alinhamentos,
        u"combinacoes": combinacoes,
        u"conectores": conectores,
        u"tabelas_de_consulta": tabelas,
        u"materiais": dict(_MATERIAIS),
        u"imagens": dict(_IMAGENS),
        u"familias_aninhadas": familias_aninhadas,
        u"aninhadas": aninhadas,
        # Assinatura geométrica da origem, tipo a tipo. É contra ISTO que o
        # validador compara no destino — assim ele não precisa saber nada
        # sobre a geometria da família, só se ela reproduz a mesma coisa.
        u"medicoes": rfaspec.medir_por_tipo(doc),
        u"medicoes_com_aninhadas": _medir_com_aninhadas(doc) if aninhadas else None,
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

# -*- coding: utf-8 -*-
u"""Núcleo compartilhado do conversor de versão de famílias Revit.

Importado pelos scripts que rodam dentro do Revit via `pyrevit run`.
Como o pyRevit copia o script para uma pasta temporária, o caminho do repo
chega pela variável de ambiente RFADG_ROOT (ver scripts/_bootstrap.py).

IronPython 2.7 — sem f-strings, sem type hints, strings com acento como u"...".
"""

import os
import re
import json

from Autodesk.Revit.DB import (
    UnitUtils, UnitTypeId,
    FilteredElementCollector, GenericForm, GeometryInstance, Options, Solid,
    Transaction, ViewDetailLevel,
)


# --------------------------------------------------------------------------
# Versão do schema. Incrementar sempre que FamilySpec mudar de forma
# incompatível — o validador recusa spec de versão desconhecida.
# --------------------------------------------------------------------------
SCHEMA_VERSION = u"0.1.0"


# --------------------------------------------------------------------------
# Unidades
#
# O Revit trabalha internamente em pés. O FamilySpec grava tudo em MILÍMETROS
# para ser legível e neutro. Toda conversão passa por aqui — nunca multiplicar
# por constante mágica no meio do código.
# --------------------------------------------------------------------------

def mm_para_interno(valor_mm):
    u"""Milímetros -> unidade interna do Revit (pés)."""
    return UnitUtils.ConvertToInternalUnits(valor_mm, UnitTypeId.Millimeters)


def interno_para_mm(valor_interno):
    u"""Unidade interna do Revit (pés) -> milímetros."""
    return UnitUtils.ConvertFromInternalUnits(valor_interno, UnitTypeId.Millimeters)


def interno_para_mm3(volume_interno):
    u"""Volume interno (pés³) -> milímetros cúbicos."""
    return UnitUtils.ConvertFromInternalUnits(volume_interno, UnitTypeId.CubicMillimeters)


# --------------------------------------------------------------------------
# Medição de geometria
#
# Leitor e validador PRECISAM medir do mesmo jeito, senão a comparação de
# fidelidade mede a diferença entre dois medidores em vez da diferença entre
# duas famílias. Por isso a medição mora aqui e não em cada script.
# --------------------------------------------------------------------------

def _coletar_solidos(doc):
    u"""Sólidos com volume das formas SÓLIDAS. Retorna (lista, diagnóstico).

    Formas de vazio são ignoradas de propósito: a geometria dos sólidos já vem
    com o corte aplicado, então somar o vazio contaria volume duas vezes.

    O diagnóstico volta junto porque `print()` de script rodando sob
    `pyrevit run` NÃO aparece na saída do CLI. Diagnóstico que não chega ao
    disco não existe — por isso ele viaja no próprio JSON de saída.
    """
    diagnostico = {
        u"elementos": 0, u"formas": 0, u"solidas": 0,
        u"solidos_com_volume": 0, u"por_forma": [], u"erros": [],
    }
    solidos = []

    for elemento in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements():
        diagnostico[u"elementos"] += 1
        if not isinstance(elemento, GenericForm):
            continue
        diagnostico[u"formas"] += 1
        try:
            if not elemento.IsSolid:
                continue
            diagnostico[u"solidas"] += 1

            encontrados, detalhe = _solidos_da_forma(doc, elemento)
            detalhe[u"classe"] = para_unicode(type(elemento).__name__)
            diagnostico[u"por_forma"].append(detalhe)

            for solido in encontrados:
                diagnostico[u"solidos_com_volume"] += 1
                solidos.append(solido)
        except Exception as erro:
            diagnostico[u"erros"].append(para_unicode(str(erro))[:200])

    return solidos, diagnostico


def _vista_3d(doc):
    u"""Vista 3D do documento de família, se houver."""
    from Autodesk.Revit.DB import View3D
    for vista in FilteredElementCollector(doc).OfClass(View3D).ToElements():
        if not vista.IsTemplate:
            return vista
    return None


def _variantes_de_opcoes(doc):
    u"""Combinações de Options a tentar, da mais autoritativa para a menos.

    A ORDEM importa e não é chute defensivo:

    - `vista_3d` vem primeiro porque geometria obtida com Options.View é
      geometria como o Revit a desenha, ou seja, COM os cortes de vazio
      aplicados. Geometria sem vista é a forma isolada, que ignora o corte.
    - `referencias` é a variante comprovadamente funcional em criar_fixture.py.
    - `fina` devolveu GeometryElement não-nulo porém VAZIO nesta medição — fica
      por último, só como rede.

    Com Options.View definido NÃO se pode definir DetailLevel (o Revit lança).
    """
    variantes = []

    vista = _vista_3d(doc)
    if vista is not None:
        com_vista = Options()
        com_vista.View = vista
        com_vista.ComputeReferences = True
        variantes.append((u"vista_3d", com_vista))

    padrao = Options()
    padrao.ComputeReferences = True
    padrao.IncludeNonVisibleObjects = False
    variantes.append((u"referencias", padrao))

    simples = Options()
    variantes.append((u"simples", simples))

    fina = Options()
    fina.IncludeNonVisibleObjects = False
    fina.DetailLevel = ViewDetailLevel.Fine
    variantes.append((u"fina", fina))

    return variantes


def _solidos_da_forma(doc, elemento):
    u"""Sólidos com volume de uma forma. Retorna (lista, detalhe do diagnóstico).

    Percorre também GeometryInstance: em alguns contextos a geometria vem
    embrulhada e o Solid só aparece depois de GetInstanceGeometry().

    TODAS as variantes são medidas, mesmo depois de uma dar certo, e o volume
    de cada uma vai para o diagnóstico. É de propósito: a diferença de volume
    entre a variante com vista e a sem vista é exatamente o que revela se um
    vazio está cortando ou está inerte.
    """
    detalhe = {u"tentativas": []}
    escolhidos = []

    for rotulo, opcoes in _variantes_de_opcoes(doc):
        try:
            geometria = elemento.get_Geometry(opcoes)
        except Exception as erro:
            detalhe[u"tentativas"].append({
                u"opcoes": rotulo, u"erro": para_unicode(str(erro))[:120]})
            continue

        if geometria is None:
            detalhe[u"tentativas"].append({u"opcoes": rotulo, u"geometria": u"nula"})
            continue

        objetos = 0
        encontrados = []
        volume = 0.0
        for objeto in geometria:
            objetos += 1
            for candidato in _achatar(objeto):
                if isinstance(candidato, Solid) and candidato.Volume > 0:
                    encontrados.append(candidato)
                    volume += candidato.Volume

        detalhe[u"tentativas"].append({
            u"opcoes": rotulo, u"objetos": objetos, u"solidos": len(encontrados),
            u"volume_mm3": interno_para_mm3(volume)})

        if encontrados and not escolhidos:
            detalhe[u"opcoes_que_funcionou"] = rotulo
            escolhidos = encontrados

    return escolhidos, detalhe


def _achatar(objeto):
    u"""Desembrulha GeometryInstance, devolvendo os objetos de dentro."""
    if isinstance(objeto, GeometryInstance):
        for interno in objeto.GetInstanceGeometry():
            yield interno
    else:
        yield objeto


def medir_geometria(doc):
    u"""Extensões do bounding box (mm) e volume total (mm³) do estado atual.

    Retorna None quando não há sólido — o chamador reporta como falha, nunca
    trata ausência de geometria como se fosse geometria de tamanho zero.
    """
    solidos, diagnostico = _coletar_solidos(doc)

    volume = 0.0
    minimos = None
    maximos = None

    for solido in solidos:
        volume += solido.Volume
        caixa = solido.GetBoundingBox()
        # A caixa vem no sistema local do sólido; transformar para o do
        # documento antes de unir, senão sólidos com transform diferente
        # produzem uma união sem sentido.
        transformacao = caixa.Transform
        for canto in _cantos(caixa):
            ponto = transformacao.OfPoint(canto)
            if minimos is None:
                minimos = [ponto.X, ponto.Y, ponto.Z]
                maximos = [ponto.X, ponto.Y, ponto.Z]
            else:
                for eixo, valor in enumerate((ponto.X, ponto.Y, ponto.Z)):
                    if valor < minimos[eixo]:
                        minimos[eixo] = valor
                    if valor > maximos[eixo]:
                        maximos[eixo] = valor

    if minimos is None:
        # Ausência de geometria não é geometria de tamanho zero. O diagnóstico
        # vai junto para o chamador saber ONDE a cadeia se rompeu.
        return {u"vazio": True, u"diagnostico": diagnostico}

    return {
        u"extensao_mm": [
            interno_para_mm(maximos[0] - minimos[0]),
            interno_para_mm(maximos[1] - minimos[1]),
            interno_para_mm(maximos[2] - minimos[2]),
        ],
        u"volume_mm3": interno_para_mm3(volume),
        u"diagnostico": diagnostico,
    }


def _cantos(caixa):
    u"""Os 8 vértices de um BoundingBoxXYZ, em coordenadas locais."""
    from Autodesk.Revit.DB import XYZ
    minimo, maximo = caixa.Min, caixa.Max
    for x in (minimo.X, maximo.X):
        for y in (minimo.Y, maximo.Y):
            for z in (minimo.Z, maximo.Z):
                yield XYZ(x, y, z)


def medir_por_tipo(doc):
    u"""Mede a geometria em cada tipo da família. Retorna nome -> medição.

    Trocar o tipo corrente exige transação: é a regeneração provocada por essa
    troca que faz a família flexionar. Nada é salvo — a transação é revertida
    para não sujar o documento de origem.
    """
    gerenciador = doc.FamilyManager
    tipo_original = gerenciador.CurrentType

    medicoes = {}
    for tipo in gerenciador.Types:
        if not tipo.Name:
            continue
        transacao = Transaction(doc, u"RFADG — medir " + tipo.Name)
        transacao.Start()
        try:
            gerenciador.CurrentType = tipo
            doc.Regenerate()
            medicoes[tipo.Name] = medir_geometria(doc)
        finally:
            transacao.RollBack()

    if tipo_original is not None:
        transacao = Transaction(doc, u"RFADG — restaurar tipo")
        transacao.Start()
        try:
            gerenciador.CurrentType = tipo_original
            doc.Regenerate()
        finally:
            transacao.RollBack()

    return medicoes


# --------------------------------------------------------------------------
# Entrada e saída
#
# Os scripts não recebem argumentos de linha de comando: o `pyrevit run` não
# repassa argv. A comunicação é por variável de ambiente, que o processo do
# Revit herda de quem chamou o CLI.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# ForgeTypeId
#
# Armadilha real, paga na primeira rodada do construtor: o sufixo de versão
# muda entre versões do Revit ('autodesk.spec.aec:length-2.0.0' no 2023,
# '...-2.0.1' no 2025). Identidade de tipo de dado NUNCA compara a string
# inteira — compara a espécie, sem o sufixo.
# --------------------------------------------------------------------------

_SUFIXO_VERSAO = re.compile(r"-\d+\.\d+\.\d+$")

ESPECIE_COMPRIMENTO = u"autodesk.spec.aec:length"

# Espécies cujo valor é um comprimento em unidade interna e precisa virar mm.
# Área e volume NÃO entram: têm unidade própria e são convertidas à parte.
_ESPECIES_COMPRIMENTO = set([ESPECIE_COMPRIMENTO])


def especie_forge(forge_id):
    u"""'autodesk.spec.aec:length-2.0.1' -> 'autodesk.spec.aec:length'.

    O sufixo de versão muda entre versões do Revit (2.0.0 no 2023, 2.0.1 no
    2025), então identidade de tipo de dado compara sempre a espécie.
    """
    if not forge_id:
        return None
    return _SUFIXO_VERSAO.sub(u"", forge_id)


def eh_comprimento(forge_id):
    return especie_forge(forge_id) in _ESPECIES_COMPRIMENTO


def env(nome, padrao=None, obrigatorio=False):
    u"""Lê variável de ambiente, com erro explícito quando é obrigatória."""
    valor = os.environ.get(nome, padrao)
    if obrigatorio and not valor:
        raise ValueError(
            u"Variável de ambiente obrigatória não definida: {0}".format(nome)
        )
    return valor


def para_unicode(valor):
    u"""Normaliza qualquer coisa string-like para unicode puro, SEM codec.

    Em IronPython 2.7 `str` e `unicode` são o MESMO tipo (System.String), então
    não existe "byte string vinda da API" a decodificar — o que existe é a
    possibilidade de chegar um tipo .NET string-like exótico. O mapeamento
    unichr(ord(...)) copia code point a code point e converte qualquer coisa
    iterável de caracteres numa unicode nativa, sem invocar codec nenhum
    (o registry de codecs do engine embarcado do `pyrevit run` é incompleto e
    qualquer .decode()/.encode() estoura com "'unknown' codec").

    A detecção é por duck typing porque objetos .NET string-like podem não
    passar num isinstance contra os tipos Python.
    """
    if valor is None or isinstance(valor, (bool, int, long, float)):  # noqa: F821
        return valor
    if isinstance(valor, (dict, list, tuple)):
        return valor
    if hasattr(valor, "upper") and hasattr(valor, "__len__"):
        return u"".join([unichr(ord(caractere)) for caractere in valor])  # noqa: F821
    return valor


def normalizar(dados):
    u"""Aplica para_unicode() recursivamente em chaves e valores."""
    if isinstance(dados, dict):
        return dict(
            (para_unicode(chave), normalizar(valor))
            for chave, valor in dados.items()
        )
    if isinstance(dados, (list, tuple)):
        return [normalizar(item) for item in dados]
    return para_unicode(dados)


# --------------------------------------------------------------------------
# Emissor JSON próprio — por que não usar json.dumps
#
# O json.dumps da stdlib é INUTILIZÁVEL neste engine para texto acentuado.
# Causa raiz (json/encoder.py, py_encode_basestring_ascii, linha 47):
#
#     HAS_UTF8 = re.compile(r'[\x80-\xff]')
#     if isinstance(s, str) and HAS_UTF8.search(s) is not None:
#         s = s.decode('utf-8')
#
# Em CPython esse decode só roda em byte strings (unicode falha no isinstance).
# Em IronPython 2.7 `str` E `unicode` são o mesmo tipo (System.String), então
# TODA string com caractere >= U+0080 cai no decode('utf-8') — um decode sobre
# uma string que já é unicode. u"Referência" tem ê (U+00EA) no índice 5: é
# exatamente o "byte 0xea in position 5" do erro. E como o registry de codecs
# do engine embarcado do `pyrevit run` é incompleto, o lookup degrada para o
# codec 'unknown' e estoura UnicodeDecodeError.
#
# ensure_ascii=False não escapa: py_encode_basestring tem o MESMO isinstance +
# decode. Nenhuma sanitização prévia resolve, porque o decode fatal acontece
# DENTRO do encoder, sobre a string já limpa. A única saída robusta é não
# passar pelo json.dumps: o FamilySpec só contém dict/list/unicode/int/float/
# bool/None, e o emissor abaixo cobre isso escapando \uXXXX na mão, sem
# invocar codec algum. A saída é ASCII puro, determinística (chaves ordenadas,
# indentação de 2) e compatível com json.loads de qualquer runtime.
# --------------------------------------------------------------------------

_ESCAPES_JSON = {
    u'"': u'\\"',
    u"\\": u"\\\\",
    u"\b": u"\\b",
    u"\f": u"\\f",
    u"\n": u"\\n",
    u"\r": u"\\r",
    u"\t": u"\\t",
}

_INFINITO = float("inf")


def _texto_json(texto):
    u"""String -> literal JSON 100% ASCII, sem passar por codec algum.

    Caracteres fora de 0x20..0x7E viram \\uXXXX. Fora do BMP, o JSON exige par
    de surrogates \\uD8xx\\uDCxx. Em IronPython (string .NET, UTF-16) o ord()
    já entrega cada metade do par; em runtimes que expõem o code point inteiro
    (> 0xFFFF) o par é calculado na mão — \\u aceita só 4 dígitos hex.
    """
    pedacos = [u'"']
    for caractere in texto:
        if caractere in _ESCAPES_JSON:
            pedacos.append(_ESCAPES_JSON[caractere])
        else:
            codigo = ord(caractere)
            if 0x20 <= codigo <= 0x7E:
                pedacos.append(caractere)
            elif codigo > 0xFFFF:
                base = codigo - 0x10000
                pedacos.append(u"\\u{0:04x}\\u{1:04x}".format(
                    0xD800 + (base >> 10), 0xDC00 + (base & 0x3FF)))
            else:
                pedacos.append(u"\\u{0:04x}".format(codigo))
    pedacos.append(u'"')
    return u"".join(pedacos)


def _valor_json(valor, nivel):
    u"""Serializa um valor do FamilySpec. Tipo desconhecido falha em voz alta."""
    if valor is None:
        return u"null"
    # bool antes de int: bool é subclasse de int em Python 2.
    if isinstance(valor, bool):
        return u"true" if valor else u"false"
    if isinstance(valor, (int, long)):  # noqa: F821
        # unicode() e não repr(): repr de long em Python 2 traz sufixo "L".
        return unicode(valor)  # noqa: F821
    if isinstance(valor, float):
        # JSON não tem NaN/Infinity; um não-finito aqui é dado corrompido e
        # deve parar o pipeline, não virar null silencioso.
        if valor != valor or valor == _INFINITO or valor == -_INFINITO:
            raise ValueError(
                u"Float não finito no FamilySpec: {0!r}".format(valor)
            )
        return unicode(repr(valor))  # noqa: F821
    if isinstance(valor, unicode):  # noqa: F821 — em IronPython cobre str também
        return _texto_json(valor)
    if isinstance(valor, dict):
        if not valor:
            return u"{}"
        recuo = u"  " * (nivel + 1)
        partes = []
        for chave in sorted(valor.keys()):
            chave_texto = chave if isinstance(chave, unicode) else para_unicode(chave)  # noqa: F821
            if not isinstance(chave_texto, unicode):  # noqa: F821
                chave_texto = unicode(chave_texto)  # noqa: F821 — int/bool/None como chave
            partes.append(
                recuo + _texto_json(chave_texto) + u": "
                + _valor_json(valor[chave], nivel + 1)
            )
        return u"{\n" + u",\n".join(partes) + u"\n" + (u"  " * nivel) + u"}"
    if isinstance(valor, (list, tuple)):
        if not valor:
            return u"[]"
        recuo = u"  " * (nivel + 1)
        partes = [recuo + _valor_json(item, nivel + 1) for item in valor]
        return u"[\n" + u",\n".join(partes) + u"\n" + (u"  " * nivel) + u"]"
    # Falha em voz alta: um tipo .NET que escapou de normalizar() não pode
    # virar lixo silencioso no spec.
    raise TypeError(
        u"Tipo não serializável no FamilySpec: {0}".format(type(valor).__name__)
    )


def json_para_texto(dados):
    u"""FamilySpec -> texto JSON ASCII puro, determinístico, sem codecs."""
    return _valor_json(dados, 0)


def gravar_json(caminho, dados):
    u"""Grava JSON, criando o diretório se necessário.

    Usa o emissor próprio (ver bloco acima) porque json.dumps estoura
    UnicodeDecodeError em qualquer string acentuada neste engine. A saída é
    ASCII puro com escapes \\uXXXX: atravessa qualquer leitor e a acentuação
    volta intacta do outro lado.
    """
    pasta = os.path.dirname(caminho)
    if pasta and not os.path.isdir(pasta):
        os.makedirs(pasta)
    texto = json_para_texto(normalizar(dados)) + u"\n"
    with open(caminho, "wb") as arq:
        # texto é ASCII puro por construção; a escrita binária não invoca
        # codec e o resultado é idêntico em IronPython e CPython.
        arq.write(texto)


def ler_json(caminho):
    u"""Lê JSON gravado por gravar_json (ASCII puro com escapes \\uXXXX).

    Sem .decode(): o registry de codecs do engine embarcado é incompleto e até
    decode de ASCII pode falhar no lookup. Como o arquivo é ASCII puro, o
    mapeamento byte -> code point na mão é suficiente e livre de codec.
    json.loads sobre unicode é seguro mesmo neste engine: o caminho de decode
    problemático existe só no ENCODER da stdlib.
    """
    with open(caminho, "rb") as arq:
        bruto = arq.read()
    texto = u"".join([unichr(ord(caractere)) for caractere in bruto])  # noqa: F821
    return json.loads(texto)


# --------------------------------------------------------------------------
# Log
#
# `pyrevit run` roda sem UI. print() vai para o output do journal e é o único
# canal de diagnóstico — usar sempre, nunca TaskDialog.
# --------------------------------------------------------------------------

def log(mensagem):
    u"""Emite linha de log com prefixo identificável no journal do Revit."""
    if not isinstance(mensagem, unicode):  # noqa: F821 (IronPython 2.7)
        mensagem = unicode(mensagem)       # noqa: F821
    print(u"[RFADG] " + mensagem)


# --------------------------------------------------------------------------
# Resolução de template .rft
#
# Risco conhecido: o layout muda entre versões. Revit 2023 põe
# `Metric_Generic_Model-ENU.rft` na raiz de Family Templates; 2024/2025 usam
# subpastas por idioma com `English/Metric Generic Model.rft`. Por isso a busca
# é recursiva e por padrão de nome, nunca por caminho fixo.
# --------------------------------------------------------------------------

# Ordem de preferência: quanto mais cedo na lista, mais desejado.
_PREFERENCIA_IDIOMA = [u"-enu", u"english", u"metric generic model.rft"]


def _pontuar_template(caminho):
    u"""Pontua um candidato a template. Menor é melhor."""
    minusculo = caminho.lower().replace(u"\\", u"/")
    nome = os.path.basename(minusculo)

    # Descarta variantes que não são o Generic Model simples.
    for indesejado in (u"adaptive", u"based", u"pattern", u"two level"):
        if indesejado in nome:
            return None

    pontos = 100
    for indice, marca in enumerate(_PREFERENCIA_IDIOMA):
        if marca in minusculo:
            pontos = min(pontos, indice)
    return pontos


def resolver_template_generic_model(app):
    u"""Encontra o template de Generic Model da versão do Revit em execução.

    `app` é o Autodesk.Revit.ApplicationServices.Application.
    Retorna o caminho absoluto do .rft ou levanta IOError com diagnóstico.
    """
    raiz = app.FamilyTemplatePath
    if not raiz or not os.path.isdir(raiz):
        raise IOError(
            u"FamilyTemplatePath inválido para esta instalação: {0}".format(raiz)
        )

    candidatos = []
    for pasta_atual, _subpastas, arquivos in os.walk(raiz):
        for arquivo in arquivos:
            if not arquivo.lower().endswith(u".rft"):
                continue
            nome_normalizado = arquivo.lower().replace(u"_", u" ")
            if u"generic model" not in nome_normalizado:
                continue
            caminho = os.path.join(pasta_atual, arquivo)
            pontos = _pontuar_template(caminho)
            if pontos is not None:
                candidatos.append((pontos, caminho))

    if not candidatos:
        raise IOError(
            u"Nenhum template Generic Model encontrado em {0}. "
            u"Instale o conteúdo de biblioteca do Revit.".format(raiz)
        )

    candidatos.sort()
    escolhido = candidatos[0][1]
    log(u"Template resolvido: {0}".format(escolhido))
    return escolhido


# --------------------------------------------------------------------------
# Identidade de referência — o problema central do projeto
#
# Objetos `Reference` do Revit não atravessam documentos. Para religar uma cota
# no documento de destino é preciso reencontrar as mesmas duas referências que a
# cota media na origem. A estratégia é dar nome determinístico a todo plano de
# referência e endereçar tudo por esse nome, nunca por ElementId.
# --------------------------------------------------------------------------

PREFIXO_PLANO = u"RFADG_"


def nome_canonico_plano(rotulo):
    u"""Nome determinístico e estável para um plano de referência."""
    return PREFIXO_PLANO + rotulo


def eh_plano_canonico(nome):
    return bool(nome) and nome.startswith(PREFIXO_PLANO)

# -*- coding: utf-8 -*-
u"""Validador da GERAÇÃO de famílias (docs/SPEC-geracao-familias.md §8).

Irmão do validador.py, que continua intocado (é a régua da Rota B). Diferenças:

  - a referência é a assinatura ANALÍTICA que o compilador gravou em
    `medicoes`, não uma medição de origem;
  - a extensão é medida pelos vértices da malha das faces: o bbox do sólido é
    folgado em superfície curva (G0: cilindro de 400 mm medido com 403,19);
  - cada tipo traz a própria tolerância de extensão (`tolerancia_extensao_mm`),
    porque a malha pode não ter vértice no extremo de um eixo curvo;
  - confere também a posição (`minimo_mm`), que pega âncora invertida;
  - toda transação tem preprocessador de falhas: diálogo travaria o `pyrevit run`.

    pyrevit run scripts/validador_geracao.py <portadora.rfa> --revit=2024
"""

import os
import re
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

from Autodesk.Revit.DB import (  # noqa: E402
    BuiltInParameter, FailureProcessingResult, FailureSeverity,
    FilteredElementCollector, GenericForm, IFailuresPreprocessor,
    StorageType, Transaction,
)

log = rfaspec.log

TOLERANCIA_VOLUME_RELATIVA = 0.0001


class _Preprocessador(IFailuresPreprocessor):
    def __init__(self, registro):
        self.registro = registro

    def PreprocessFailures(self, acessor):
        houve_erro = False
        for mensagem in acessor.GetFailureMessages():
            texto = rfaspec.para_unicode(mensagem.GetDescriptionText())
            if mensagem.GetSeverity() == FailureSeverity.Warning:
                self.registro.append(u"AVISO: " + texto)
                acessor.DeleteWarning(mensagem)
            else:
                self.registro.append(u"ERRO: " + texto)
                houve_erro = True
        if houve_erro:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


def _solidos_visiveis(doc):
    u"""Sólidos das formas VISÍVEIS no tipo corrente.

    As cópias de um array do gerador ficam ocultas por fórmula ("N > k-1"),
    mas a geometria delas continua existindo no documento da família. Medir
    tudo, como o validador do conversor faz, somaria prateleiras que o usuário
    não vê. O gerador ainda não emite vazio, então não há GeomCombination aqui.
    """
    solidos = []
    for elemento in FilteredElementCollector(doc).OfClass(GenericForm).ToElements():
        if not elemento.IsSolid:
            continue
        visivel = elemento.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM)
        if visivel is not None and visivel.AsInteger() == 0:
            continue
        encontrados, _ = rfaspec._solidos_da_forma(elemento)
        solidos.extend(encontrados)
    return solidos


def _subcategorias_das_formas(doc):
    formas = sorted(FilteredElementCollector(doc).OfClass(GenericForm).ToElements(),
                    key=lambda elemento: rfaspec.id_inteiro(elemento.Id))
    saida = []
    for forma in formas:
        subcategoria = forma.Subcategory
        saida.append(rfaspec.para_unicode(subcategoria.Name) if subcategoria is not None else None)
    return saida


def _conectores_medidos(doc):
    import Autodesk.Revit.DB as DB
    saida = []
    for conector in FilteredElementCollector(doc).OfClass(DB.ConnectorElement).ToElements():
        origem, direcao = conector.Origin, conector.Direction
        saida.append({
            u"origem_mm": [rfaspec.interno_para_mm(v) for v in (origem.X, origem.Y, origem.Z)],
            u"normal": [round(direcao.X, 4), round(direcao.Y, 4), round(direcao.Z, 4)],
            u"diametro_mm": rfaspec.interno_para_mm(2 * conector.Radius),
        })
    return saida


def _conferir_conectores(esperados, medidos):
    u"""Cada conector esperado tem um medido na mesma posição, direção e diâmetro."""
    if len(esperados) != len(medidos):
        return u"{0} conectores esperados, {1} medidos".format(len(esperados), len(medidos))
    for esperado in esperados:
        achou = False
        for medido in medidos:
            if all(abs(a - b) < 1e-3 for a, b in zip(esperado[u"normal"], medido[u"normal"])) and \
                    all(abs(a - b) < 0.1 for a, b in zip(esperado[u"origem_mm"], medido[u"origem_mm"])):
                if abs(esperado[u"diametro_mm"] - medido[u"diametro_mm"]) > 0.1:
                    return u"conector em {0}: diâmetro {1:.1f} (esperado {2:.1f})".format(
                        [round(v, 1) for v in esperado[u"origem_mm"]], medido[u"diametro_mm"],
                        esperado[u"diametro_mm"])
                achou = True
                break
        if not achou:
            return u"conector esperado em {0} (normal {1}) não encontrado".format(
                [round(v, 1) for v in esperado[u"origem_mm"]], esperado[u"normal"])
    return None


def _medir_por_malha(doc):
    solidos = _solidos_visiveis(doc)
    if not solidos:
        return {u"vazio": True}
    volume = 0.0
    minimo = None
    maximo = None
    for solido in solidos:
        volume += solido.Volume
        for face in solido.Faces:
            for ponto in face.Triangulate(1.0).Vertices:
                valores = (ponto.X, ponto.Y, ponto.Z)
                if minimo is None:
                    minimo = list(valores)
                    maximo = list(valores)
                else:
                    for eixo in range(3):
                        minimo[eixo] = min(minimo[eixo], valores[eixo])
                        maximo[eixo] = max(maximo[eixo], valores[eixo])
    return {
        u"extensao_mm": [rfaspec.interno_para_mm(maximo[e] - minimo[e]) for e in range(3)],
        u"minimo_mm": [rfaspec.interno_para_mm(minimo[e]) for e in range(3)],
        u"volume_mm3": rfaspec.interno_para_mm3(volume),
    }


def _medir_tipos(doc, registro):
    gerenciador = doc.FamilyManager
    tipos = [(rfaspec.para_unicode(t.Name), t) for t in gerenciador.Types if t.Name]
    medidas = {}
    valores = {}
    transacao = Transaction(doc, u"validar geração")
    opcoes = transacao.GetFailureHandlingOptions()
    opcoes.SetFailuresPreprocessor(_Preprocessador(registro))
    opcoes.SetClearAfterRollback(True)
    transacao.SetFailureHandlingOptions(opcoes)
    transacao.Start()
    try:
        for nome, tipo in tipos:
            try:
                gerenciador.CurrentType = tipo
                doc.Regenerate()
                medidas[nome] = _medir_por_malha(doc)
                medidas[nome][u"conectores"] = _conectores_medidos(doc)
            except Exception as erro:
                medidas[nome] = {u"erro": rfaspec.para_unicode(unicode(erro))[:200]}  # noqa: F821
            valores[nome] = _valores_do_tipo(gerenciador, tipo)
            imagem = gerenciador.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_IMAGE)
            valor_imagem = tipo.AsElementId(imagem) if imagem is not None else None
            valores[nome][u"__imagem_do_tipo"] = (
                valor_imagem is not None and rfaspec.id_inteiro(valor_imagem) > 0)
    finally:
        transacao.RollBack()
    return medidas, valores


def _valores_do_tipo(gerenciador, tipo):
    saida = {}
    for parametro in gerenciador.Parameters:
        if not tipo.HasValue(parametro):
            continue
        nome = rfaspec.para_unicode(parametro.Definition.Name)
        if parametro.StorageType == StorageType.Double:
            bruto = tipo.AsDouble(parametro)
            saida[nome] = rfaspec.interno_para_mm(bruto) if bruto is not None else None
        elif parametro.StorageType == StorageType.Integer:
            saida[nome] = tipo.AsInteger(parametro)
    return saida


def _comparar(esperado, medido):
    if medido.get(u"vazio") or medido.get(u"erro"):
        return u"SEM_MEDICAO", medido.get(u"erro")
    tolerancia = esperado.get(u"tolerancia_extensao_mm", 0.1)
    desvios = [abs(medido[u"extensao_mm"][e] - esperado[u"extensao_mm"][e]) for e in range(3)]
    if max(desvios) > tolerancia:
        return u"EXTENSAO_DIVERGE", [round(d, 3) for d in desvios]
    desvios_min = [abs(medido[u"minimo_mm"][e] - esperado[u"minimo_mm"][e]) for e in range(3)]
    if max(desvios_min) > tolerancia:
        return u"POSICAO_DIVERGE", [round(d, 3) for d in desvios_min]
    volume = esperado[u"volume_mm3"]
    desvio = abs(medido[u"volume_mm3"] - volume)
    if desvio > max(abs(volume) * TOLERANCIA_VOLUME_RELATIVA, 1.0):
        return u"VOLUME_DIVERGE", round(100.0 * desvio / volume, 5)
    if esperado.get(u"conectores"):
        problema = _conferir_conectores(esperado[u"conectores"], medido.get(u"conectores") or [])
        if problema:
            return u"CONECTOR_DIVERGE", problema
    return u"REPRODUZ", None


_RE_MM = re.compile(r"(\d)\s*mm\b")


def _sem_espacos(texto):
    u"""Forma canônica da fórmula: o Revit reescreve número solto em fórmula de
    comprimento com a unidade ("0 - x" vira "0 mm - x", medido no 2024)."""
    return u"".join(_RE_MM.sub(r"\1", texto or u"").split())


def principal():
    entrada = rfaspec.env("RFADG_ENTRADA", obrigatorio=True)
    especificacao = rfaspec.ler_json(rfaspec.env("RFADG_SPEC", obrigatorio=True))
    caminho_relatorio = rfaspec.env("RFADG_RELATORIO_FLEX", obrigatorio=True)
    registro = []

    doc = __revit__.Application.OpenDocumentFile(entrada)  # noqa: F821
    try:
        subcategorias = _subcategorias_das_formas(doc)
        formulas = {}
        for parametro in doc.FamilyManager.Parameters:
            formulas[rfaspec.para_unicode(parametro.Definition.Name)] = parametro.Formula
        medidas, valores = _medir_tipos(doc, registro)
    finally:
        doc.Close(False)

    tipos = []
    for nome in sorted(especificacao[u"medicoes"].keys()):
        esperado = especificacao[u"medicoes"][nome]
        if nome not in medidas:
            tipos.append({u"tipo": nome, u"veredito": u"TIPO_AUSENTE"})
            continue
        veredito, detalhe = _comparar(esperado, medidas[nome])
        tipos.append({u"tipo": nome, u"veredito": veredito, u"detalhe": detalhe,
                      u"esperado": esperado, u"medido": medidas[nome]})

    divergencias = []
    for item in especificacao[u"parametros"]:
        nome = item[u"nome"]
        if nome not in formulas:
            divergencias.append({u"parametro": nome, u"problema": u"AUSENTE"})
        elif _sem_espacos(item.get(u"formula")) != _sem_espacos(formulas[nome]):
            divergencias.append({u"parametro": nome, u"problema": u"FORMULA",
                                 u"detalhe": u"esperada={0!r} obtida={1!r}".format(
                                     item.get(u"formula"), formulas[nome])})
    for tipo in especificacao[u"tipos"]:
        obtidos = valores.get(tipo[u"nome"], {})
        for nome, esperado in tipo[u"valores"].items():
            obtido = obtidos.get(nome)
            if obtido is None or abs(float(obtido) - float(esperado)) > 0.1:
                divergencias.append({u"parametro": nome, u"problema": u"VALOR",
                                     u"tipo": tipo[u"nome"],
                                     u"detalhe": u"esperado={0!r} obtido={1!r}".format(esperado, obtido)})

    if (especificacao.get(u"imagem_do_tipo") or {}).get(u"arquivo"):
        for nome, obtidos in sorted(valores.items()):
            if not obtidos.get(u"__imagem_do_tipo"):
                divergencias.append({u"parametro": u"Type Image", u"problema": u"IMAGEM_DO_TIPO",
                                     u"tipo": nome, u"detalhe": u"tipo sem imagem"})

    # Subcategoria por forma, na ordem de criação (a mesma da lista do spec).
    for indice, item in enumerate(especificacao.get(u"formas", [])):
        esperada = item.get(u"subcategoria")
        obtida = subcategorias[indice] if indice < len(subcategorias) else u"(forma ausente)"
        if esperada and esperada != obtida:
            divergencias.append({u"parametro": u"forma #{0}".format(indice), u"problema": u"SUBCATEGORIA",
                                 u"detalhe": u"esperada={0!r} obtida={1!r}".format(esperada, obtida)})

    aprovada = bool(tipos) and all(t[u"veredito"] == u"REPRODUZ" for t in tipos) and not divergencias
    rfaspec.gravar_json(caminho_relatorio, {
        u"aprovada": aprovada,
        u"revit": rfaspec.para_unicode(__revit__.Application.VersionNumber),  # noqa: F821
        u"tipos": tipos,
        u"divergencias_de_parametro": divergencias,
        u"registro": registro,
    })
    for t in tipos:
        log(u"{0}: {1}".format(t[u"tipo"], t[u"veredito"]))
    log(u"VALIDAÇÃO DA GERAÇÃO: {0}".format(u"APROVADA" if aprovada else u"REPROVADA"))


principal()

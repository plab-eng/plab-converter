# -*- coding: utf-8 -*-
u"""FASE 1 — validador: a família reconstruída reproduz a origem?

Roda no Revit de DESTINO. Abre o .rfa reconstruído (RFADG_ENTRADA) e compara,
tipo a tipo, contra a assinatura que o leitor gravou da ORIGEM no FamilySpec:

  - geometria: extensões do bounding box e volume total
  - parâmetros: existência, tipo de dado, instância/tipo, fórmula
  - valores: o que cada tipo atribui a cada parâmetro

O validador não sabe nada sobre a geometria da família — ele só verifica que o
destino reproduz o que a origem mediu. Isso o torna genérico: serve para
qualquer família, não só para a fixture.

A comparação de volume é o que denuncia um vazio que virou inerte: o bounding
box fica idêntico e só o volume acusa.

    pyrevit run scripts/validador.py <portadora.rfa> --revit=2023
"""

import os
import sys

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida. Rode via scripts/run_fase0.ps1.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

log = rfaspec.log

# Tolerâncias. Regeneração envolve aritmética de ponto flutuante em pés, então
# igualdade exata não é critério honesto. 0,1 mm pega qualquer falha real de
# constraint; 0,01% de volume pega vazio inerte sem acusar ruído numérico.
TOLERANCIA_MM = 0.1
TOLERANCIA_VOLUME_RELATIVA = 0.0001


def _abrir_familia(caminho):
    if not os.path.isfile(caminho):
        raise IOError(u"Família não encontrada: {0}".format(caminho))
    return __revit__.Application.OpenDocumentFile(caminho)  # noqa: F821


# --------------------------------------------------------------------------
# Geometria
# --------------------------------------------------------------------------

def _vazia(medicao):
    return medicao is None or medicao.get(u"vazio")


def _comparar_geometria(esperado, medido):
    u"""Compara duas medições. Retorna (veredito, detalhe)."""
    if _vazia(esperado) and _vazia(medido):
        return u"SEM_GEOMETRIA_NOS_DOIS", None
    if _vazia(esperado):
        return u"GEOMETRIA_INESPERADA", u"origem não tinha sólido, destino tem"
    if _vazia(medido):
        return u"SEM_SOLIDO", u"destino não produziu sólido com volume"

    desvios = []
    for eixo in range(3):
        desvios.append(abs(medido[u"extensao_mm"][eixo] - esperado[u"extensao_mm"][eixo]))

    volume_esperado = esperado[u"volume_mm3"]
    desvio_volume = abs(medido[u"volume_mm3"] - volume_esperado)
    limite_volume = max(abs(volume_esperado) * TOLERANCIA_VOLUME_RELATIVA, 1.0)

    if max(desvios) > TOLERANCIA_MM:
        return u"GEOMETRIA_DIVERGE", u"bounding box fora da tolerância"
    if desvio_volume > limite_volume:
        return u"VOLUME_DIVERGE", (
            u"bounding box bate mas volume não — sinal clássico de vazio "
            u"presente porém inerte"
        )
    return u"REPRODUZ", None


def validar_geometria(doc, especificacao):
    esperadas = especificacao.get(u"medicoes") or {}
    if not esperadas:
        return [{
            u"tipo": u"(todos)", u"veredito": u"SEM_REFERENCIA",
            u"detalhe": u"FamilySpec não traz medições da origem",
        }]

    medidas = rfaspec.medir_por_tipo(doc)

    resultados = []
    for nome in sorted(esperadas.keys()):
        if nome not in medidas:
            resultados.append({
                u"tipo": nome, u"veredito": u"TIPO_AUSENTE",
                u"detalhe": u"tipo não existe na família reconstruída",
            })
            continue

        esperado, medido = esperadas[nome], medidas[nome]
        veredito, detalhe = _comparar_geometria(esperado, medido)

        item = {u"tipo": nome, u"veredito": veredito}
        if detalhe:
            item[u"detalhe"] = detalhe
        item[u"esperado"] = esperado
        item[u"medido"] = medido
        resultados.append(item)

    return resultados


# --------------------------------------------------------------------------
# Parâmetros e valores
# --------------------------------------------------------------------------

def _valor_do_tipo(tipo_familia, parametro):
    u"""Mesma leitura do leitor, para a comparação ser maçã com maçã."""
    from Autodesk.Revit.DB import StorageType

    if not tipo_familia.HasValue(parametro):
        return None

    armazenamento = parametro.StorageType
    if armazenamento == StorageType.Double:
        valor = tipo_familia.AsDouble(parametro)
        if valor is None:
            return None
        if rfaspec.eh_comprimento(_forge_id(parametro.Definition.GetDataType())):
            return rfaspec.interno_para_mm(valor)
        return valor
    if armazenamento == StorageType.Integer:
        return tipo_familia.AsInteger(parametro)
    if armazenamento == StorageType.String:
        return tipo_familia.AsString(parametro)
    return None


def _forge_id(forge_type_id):
    if forge_type_id is None:
        return None
    try:
        return forge_type_id.TypeId or None
    except AttributeError:
        return None


def _iguais(esperado, obtido):
    u"""Compara valores de parâmetro, com tolerância para ponto flutuante.

    O teste de None vem antes de tudo e cobre os dois lados: `float(None)` no
    IronPython não levanta TypeError como no CPython — levanta
    NullReferenceException, que não é capturada por `except (TypeError,
    ValueError)` e derruba o validador inteiro.
    """
    if esperado is None or obtido is None:
        return esperado is None and obtido is None
    if isinstance(esperado, float) or isinstance(obtido, float):
        try:
            return abs(float(esperado) - float(obtido)) <= TOLERANCIA_MM
        except Exception:
            return False
    return esperado == obtido


def validar_parametros(doc, especificacao):
    u"""Confere existência, natureza e valores por tipo. Retorna divergências."""
    gerenciador = doc.FamilyManager

    no_destino = {}
    for parametro in gerenciador.Parameters:
        no_destino[parametro.Definition.Name] = parametro

    divergencias = []

    for item in especificacao[u"parametros"]:
        nome = item[u"nome"]
        parametro = no_destino.get(nome)
        if parametro is None:
            divergencias.append({
                u"parametro": nome, u"problema": u"AUSENTE",
                u"detalhe": u"não existe na família reconstruída",
            })
            continue

        if bool(parametro.IsInstance) != bool(item.get(u"de_instancia")):
            divergencias.append({
                u"parametro": nome, u"problema": u"NATUREZA",
                u"detalhe": u"instância/tipo diferente da origem",
            })

        esperada = item.get(u"formula")
        obtida = parametro.Formula
        if (esperada or None) != (obtida or None):
            divergencias.append({
                u"parametro": nome, u"problema": u"FORMULA",
                u"detalhe": u"origem={0!r} destino={1!r}".format(esperada, obtida),
            })

    tipos_no_destino = {}
    for tipo in gerenciador.Types:
        if tipo.Name:
            tipos_no_destino[tipo.Name] = tipo

    for tipo_spec in especificacao[u"tipos"]:
        tipo = tipos_no_destino.get(tipo_spec[u"nome"])
        if tipo is None:
            continue
        for nome, esperado in sorted(tipo_spec[u"valores"].items()):
            if esperado is None:
                # A origem não definiu valor para este parâmetro neste tipo.
                # Não há o que reproduzir, e o padrão que o template do destino
                # traz ("" ou 0) não é divergência — é o mesmo "sem valor".
                continue
            parametro = no_destino.get(nome)
            if parametro is None:
                continue
            obtido = _valor_do_tipo(tipo, parametro)
            if not _iguais(esperado, obtido):
                divergencias.append({
                    u"parametro": nome, u"problema": u"VALOR",
                    u"tipo": tipo_spec[u"nome"],
                    u"detalhe": u"origem={0!r} destino={1!r}".format(esperado, obtido),
                })

    return divergencias


# --------------------------------------------------------------------------

def principal():
    entrada = rfaspec.env("RFADG_ENTRADA", obrigatorio=True)
    caminho_spec = rfaspec.env("RFADG_SPEC", obrigatorio=True)
    caminho_relatorio = rfaspec.env("RFADG_RELATORIO_FLEX", obrigatorio=True)

    especificacao = rfaspec.ler_json(caminho_spec)

    doc = _abrir_familia(entrada)
    try:
        geometria = validar_geometria(doc, especificacao)
        parametros = validar_parametros(doc, especificacao)
    finally:
        doc.Close(False)

    geometria_ok = bool(geometria) and all(
        item[u"veredito"] == u"REPRODUZ" for item in geometria
    )
    aprovada = geometria_ok and not parametros

    rfaspec.gravar_json(caminho_relatorio, {
        u"aprovada": aprovada,
        u"tolerancia_mm": TOLERANCIA_MM,
        u"tolerancia_volume_relativa": TOLERANCIA_VOLUME_RELATIVA,
        u"geometria": geometria,
        u"divergencias_de_parametro": parametros,
    })

    for item in geometria:
        log(u"{0}: {1}".format(item[u"tipo"], item[u"veredito"]))
    if parametros:
        log(u"Divergências de parâmetro: {0}".format(len(parametros)))
        for item in parametros[:10]:
            log(u"  {0} [{1}] {2}".format(
                item[u"parametro"], item[u"problema"], item.get(u"detalhe", u"")))

    log(u"VALIDAÇÃO: {0}".format(u"APROVADA" if aprovada else u"REPROVADA"))


principal()

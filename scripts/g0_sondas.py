# -*- coding: utf-8 -*-
u"""G0 — sondas da geração de famílias (docs/SPEC-geracao-familias.md §10).

Cada sonda cria a SUA família do zero a partir do template Generic Model,
tenta um mecanismo da API, mede a geometria tipo a tipo e grava o veredito.
Nada do pipeline (leitor, construtor, validador) é tocado.

Sondas:
  S1  caixa centrada sem cota EQ (meia largura por fórmula)
  S2  cilindro paramétrico — A1 cota radial na aresta, A2 na curva do esboço,
      B revolução alinhada a plano
  S3  array — A LinearArray com contagem rotulada, B cópias com visibilidade
  S4  volume analítico x medido (dentro de S1 e S2)
  S5  a versão do Revit (template, AddParameter com GroupTypeId)
  S6  subcategoria pela API
  S7  imagem do tipo (Type Image) pela API

Toda transação tem um IFailuresPreprocessor que apaga avisos e devolve
ProceedWithRollBack diante de erro: em `pyrevit run` um diálogo de erro
travaria a sessão.

    .\\scripts\\run_g0.ps1 -Revit 2022
"""

import math
import os
import sys
import traceback

_RAIZ = os.environ.get("RFADG_ROOT")
if not _RAIZ:
    raise ValueError(u"RFADG_ROOT não definida. Rode via scripts/run_g0.ps1.")
sys.path.insert(0, os.path.join(_RAIZ, "pylib"))

import rfaspec  # noqa: E402

import Autodesk.Revit.DB as DB  # noqa: E402
from Autodesk.Revit.DB import (  # noqa: E402
    Arc, BuiltInParameter, CurveArray, CurveArrArray, FailureProcessingResult,
    FailureSeverity, FilteredElementCollector, IFailuresPreprocessor, Line,
    Options, PlanarFace, Plane, ReferenceArray, ReferencePlane, SaveAsOptions,
    SketchPlane, Solid, Transaction, TransactionStatus, View, ViewType, XYZ,
)

log = rfaspec.log
mm = rfaspec.mm_para_interno

TOLERANCIA_MM = 0.1
TOLERANCIA_VOLUME_RELATIVA = 0.0001


# --------------------------------------------------------------------------
# Infraestrutura
# --------------------------------------------------------------------------

class _Preprocessador(IFailuresPreprocessor):
    u"""Avisos: apaga e registra. Erros: registra e desfaz a transação."""

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


def _texto(erro):
    u"""Mensagem de exceção como unicode (para_unicode devolve o objeto intacto)."""
    return rfaspec.para_unicode(unicode(erro))  # noqa: F821


_ABERTAS = []


def _transacao(doc, nome, registro):
    transacao = Transaction(doc, nome)
    _ABERTAS.append(transacao)
    opcoes = transacao.GetFailureHandlingOptions()
    opcoes.SetFailuresPreprocessor(_Preprocessador(registro))
    opcoes.SetClearAfterRollback(True)
    transacao.SetFailureHandlingOptions(opcoes)
    return transacao


def _vista_de_planta(doc):
    for vista in FilteredElementCollector(doc).OfClass(View).ToElements():
        if not vista.IsTemplate and vista.ViewType == ViewType.FloorPlan:
            return vista
    raise ValueError(u"template sem vista de planta")


def _plano_centro_esq_dir(doc):
    u"""Plano do template com normal X passando pela origem."""
    for plano in FilteredElementCollector(doc).OfClass(ReferencePlane).ToElements():
        normal = plano.Normal
        if abs(abs(normal.X) - 1.0) < 1e-9 and abs(plano.BubbleEnd.X) < 1e-9:
            return plano
    raise ValueError(u"plano Center (Left/Right) não encontrado")


def _especie(nome):
    u"""ForgeTypeId da espécie, resolvido por nome (CLAUDE.md §7, 12b)."""
    spec = getattr(DB, "SpecTypeId", None)
    if spec is None:
        return None
    if nome == u"length":
        return getattr(spec, "Length", None)
    if nome == u"integer":
        return getattr(getattr(spec, "Int", None), "Integer", None)
    if nome == u"yesno":
        return getattr(getattr(spec, "Boolean", None), "YesNo", None)
    return None


_CAMINHO_ADDPARAMETER = []


def _parametro(doc, nome, especie, instancia=False):
    u"""AddParameter pelo caminho moderno (2022+) ou legado (2021)."""
    gerenciador = doc.FamilyManager
    grupos = getattr(DB, "GroupTypeId", None)
    tipo_de_dado = _especie(especie)
    if grupos is not None and tipo_de_dado is not None:
        if not _CAMINHO_ADDPARAMETER:
            _CAMINHO_ADDPARAMETER.append(u"GroupTypeId + SpecTypeId")
        return gerenciador.AddParameter(nome, grupos.Geometry, tipo_de_dado, instancia)

    if not _CAMINHO_ADDPARAMETER:
        _CAMINHO_ADDPARAMETER.append(u"BuiltInParameterGroup + ParameterType (legado)")
    legado = {u"length": u"Length", u"integer": u"Integer", u"yesno": u"YesNo"}
    tipo_legado = getattr(DB.ParameterType, legado[especie])
    return gerenciador.AddParameter(
        nome, DB.BuiltInParameterGroup.PG_GEOMETRY, tipo_legado, instancia)


def _retangulo(x0, x1, y0, y1, z=0.0):
    pontos = [XYZ(mm(x0), mm(y0), mm(z)), XYZ(mm(x1), mm(y0), mm(z)),
              XYZ(mm(x1), mm(y1), mm(z)), XYZ(mm(x0), mm(y1), mm(z))]
    laco = CurveArray()
    for indice in range(4):
        laco.Append(Line.CreateBound(pontos[indice], pontos[(indice + 1) % 4]))
    perfil = CurveArrArray()
    perfil.Append(laco)
    return perfil


def _circulo(raio_mm):
    u"""Círculo em dois arcos (o esboço aceita; um arco de 360° é arriscado)."""
    plano = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero)
    laco = CurveArray()
    laco.Append(Arc.Create(plano, mm(raio_mm), 0.0, math.pi))
    laco.Append(Arc.Create(plano, mm(raio_mm), math.pi, 2.0 * math.pi))
    perfil = CurveArrArray()
    perfil.Append(laco)
    return perfil


def _plano_de_esboco_z0(doc):
    return SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero))


def _plano_vertical_x(doc, vista, x_mm, nome):
    plano = doc.FamilyCreate.NewReferencePlane(
        XYZ(mm(x_mm), mm(-1000), 0.0), XYZ(mm(x_mm), mm(1000), 0.0), XYZ.BasisZ, vista)
    plano.Name = nome
    return plano


def _linha_de_cota_x(xa_mm, xb_mm, y_mm=-800.0):
    return Line.CreateBound(XYZ(mm(xa_mm), mm(y_mm), 0.0), XYZ(mm(xb_mm), mm(y_mm), 0.0))


def _referencias(*itens):
    arranjo = ReferenceArray()
    for item in itens:
        arranjo.Append(item)
    return arranjo


def _geometria(elemento):
    opcoes = Options()
    opcoes.ComputeReferences = True
    opcoes.IncludeNonVisibleObjects = False
    return elemento.get_Geometry(opcoes)


def _face_com_normal(elemento, normal):
    for objeto in _geometria(elemento):
        if isinstance(objeto, Solid):
            for face in objeto.Faces:
                if isinstance(face, PlanarFace) and face.FaceNormal.IsAlmostEqualTo(normal):
                    return face
    return None


def _arestas_circulares(elemento):
    arestas = []
    for objeto in _geometria(elemento):
        if isinstance(objeto, Solid):
            for aresta in objeto.Edges:
                if isinstance(aresta.AsCurve(), Arc):
                    arestas.append(aresta)
    return arestas


def _medir(doc):
    u"""Extensões e mínimo (pela malha), bbox do sólido e volume, com a mesma
    coleta de sólidos do validador."""
    solidos, _ = rfaspec._coletar_solidos(doc)
    if not solidos:
        return {u"vazio": True}
    volume = 0.0
    minimos = None
    maximos = None
    for solido in solidos:
        volume += solido.Volume
        caixa = solido.GetBoundingBox()
        for canto in rfaspec._cantos(caixa):
            ponto = caixa.Transform.OfPoint(canto)
            valores = (ponto.X, ponto.Y, ponto.Z)
            if minimos is None:
                minimos = list(valores)
                maximos = list(valores)
            else:
                for eixo in range(3):
                    minimos[eixo] = min(minimos[eixo], valores[eixo])
                    maximos[eixo] = max(maximos[eixo], valores[eixo])
    # O bbox do sólido é folgado em superfície curva (cilindro: +3 mm, medido
    # no 2022). A extensão "justa" sai dos vértices da malha das faces.
    malha_min = None
    malha_max = None
    for solido in solidos:
        for face in solido.Faces:
            for ponto in face.Triangulate(1.0).Vertices:
                valores = (ponto.X, ponto.Y, ponto.Z)
                if malha_min is None:
                    malha_min = list(valores)
                    malha_max = list(valores)
                else:
                    for eixo in range(3):
                        malha_min[eixo] = min(malha_min[eixo], valores[eixo])
                        malha_max[eixo] = max(malha_max[eixo], valores[eixo])
    return {
        u"extensao_mm": [rfaspec.interno_para_mm(malha_max[e] - malha_min[e]) for e in range(3)],
        u"minimo_mm": [rfaspec.interno_para_mm(malha_min[e]) for e in range(3)],
        u"extensao_bbox_solido_mm": [rfaspec.interno_para_mm(maximos[e] - minimos[e]) for e in range(3)],
        u"volume_mm3": rfaspec.interno_para_mm3(volume),
    }


def _medir_tipos(doc, registro):
    u"""Mede cada tipo numa transação única, revertida no fim (ver
    rfaspec.medir_por_tipo), agora com o preprocessador de falhas."""
    gerenciador = doc.FamilyManager
    tipos = []
    for tipo in gerenciador.Types:
        nome = rfaspec.para_unicode(tipo.Name)
        if nome:
            tipos.append((nome, tipo))
    medidas = {}
    transacao = _transacao(doc, u"G0 medir", registro)
    transacao.Start()
    try:
        for nome, tipo in tipos:
            try:
                gerenciador.CurrentType = tipo
                doc.Regenerate()
                medidas[nome] = _medir(doc)
            except Exception as erro:
                medidas[nome] = {u"erro": _texto(erro)[:200]}
    finally:
        transacao.RollBack()
    return medidas


def _confere(esperado, medido):
    u"""Mesma régua do validador (0,1 mm / 0,01%), mais o mínimo quando houver."""
    if medido.get(u"vazio") or medido.get(u"erro"):
        return False, u"sem medição"
    desvios = [abs(medido[u"extensao_mm"][e] - esperado[u"extensao_mm"][e]) for e in range(3)]
    if max(desvios) > TOLERANCIA_MM:
        return False, u"bbox diverge: {0}".format([round(d, 3) for d in desvios])
    if u"minimo_mm" in esperado:
        desvios_min = [abs(medido[u"minimo_mm"][e] - esperado[u"minimo_mm"][e]) for e in range(3)]
        if max(desvios_min) > TOLERANCIA_MM:
            return False, u"posição diverge (âncora): {0}".format([round(d, 3) for d in desvios_min])
    volume = esperado[u"volume_mm3"]
    desvio_volume = abs(medido[u"volume_mm3"] - volume)
    if desvio_volume > max(abs(volume) * TOLERANCIA_VOLUME_RELATIVA, 1.0):
        return False, u"volume diverge {0:.4f}%".format(100.0 * desvio_volume / volume)
    return True, u"desvio de volume {0:.6f}%".format(100.0 * desvio_volume / volume)


def _avaliar(resultado, esperados, medidos):
    u"""Compara tipo a tipo e fecha o veredito da sonda."""
    tipos = []
    tudo_ok = True
    for nome in sorted(esperados.keys()):
        medido = medidos.get(nome, {u"vazio": True})
        ok, detalhe = _confere(esperados[nome], medido)
        tudo_ok = tudo_ok and ok
        tipos.append({u"tipo": nome, u"ok": ok, u"detalhe": detalhe,
                      u"esperado": esperados[nome], u"medido": medido})
    resultado[u"tipos"] = tipos
    resultado[u"veredito"] = u"SIM" if tudo_ok else u"NAO"


def _salvar(doc, pasta, nome):
    caminho = os.path.join(pasta, nome + u".rfa")
    if os.path.isfile(caminho):
        os.remove(caminho)
    opcoes = SaveAsOptions()
    opcoes.OverwriteExistingFile = True
    doc.SaveAs(caminho, opcoes)
    return caminho


def _rodar(nome, funcao, app, template, pasta):
    u"""Isola cada sonda: documento próprio, exceção vira veredito ERRO."""
    log(u"--- {0} ---".format(nome))
    resultado = {u"sonda": nome, u"registro": [], u"veredito": u"ERRO"}
    doc = app.NewFamilyDocument(template)
    try:
        funcao(doc, resultado)
        try:
            resultado[u"arquivo"] = _salvar(doc, pasta, nome)
        except Exception as erro:
            resultado[u"registro"].append(u"SaveAs falhou: " + _texto(erro))
    except Exception as erro:
        resultado[u"erro"] = _texto(erro)[:300]
        resultado[u"traceback"] = rfaspec.para_unicode(traceback.format_exc())[-1500:]
    finally:
        # Sonda que quebrou no meio deixa transação aberta, e Close recusa.
        for transacao in _ABERTAS:
            try:
                if transacao.HasStarted() and not transacao.HasEnded():
                    transacao.RollBack()
                    resultado[u"registro"].append(u"transação aberta desfeita no fim da sonda")
            except Exception:
                pass
        del _ABERTAS[:]
        doc.Close(False)
    log(u"{0}: {1}".format(nome, resultado[u"veredito"]))
    return resultado


def _commit(transacao, resultado):
    status = transacao.Commit()
    if status != TransactionStatus.Committed:
        resultado[u"registro"].append(u"transação terminou em {0}".format(status))
        return False
    return True


# --------------------------------------------------------------------------
# S1 + S4: caixa centrada sem EQ
# --------------------------------------------------------------------------

S1_LARGURAS = {u"L300": 300.0, u"L600": 600.0, u"L1500": 1500.0}
S1_PROFUNDIDADE = 400.0
S1_ALTURA = 500.0


def sonda_caixa_centrada(doc, resultado):
    registro = resultado[u"registro"]
    transacao = _transacao(doc, u"S1", registro)
    transacao.Start()
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"L600")
    vista = _vista_de_planta(doc)

    largura = _parametro(doc, u"Largura", u"length")
    meia = _parametro(doc, u"Meia_Largura", u"length")
    gerenciador.Set(largura, mm(600.0))
    gerenciador.SetFormula(meia, u"Largura / 2")

    centro = _plano_centro_esq_dir(doc)
    esquerda = _plano_vertical_x(doc, vista, -300.0, u"RFADG_S1_Esq")
    direita = _plano_vertical_x(doc, vista, 300.0, u"RFADG_S1_Dir")
    doc.Regenerate()

    # Rotular ANTES de alinhar (CLAUDE.md §7, armadilha 8).
    for plano, x in ((esquerda, -300.0), (direita, 300.0)):
        cota = doc.FamilyCreate.NewDimension(
            vista, _linha_de_cota_x(0.0, x), _referencias(centro.GetReference(), plano.GetReference()))
        cota.FamilyLabel = meia
    doc.Regenerate()

    extrusao = doc.FamilyCreate.NewExtrusion(
        True, _retangulo(-300.0, 300.0, -S1_PROFUNDIDADE / 2, S1_PROFUNDIDADE / 2),
        _plano_de_esboco_z0(doc), mm(S1_ALTURA))
    doc.Regenerate()

    for plano, normal in ((esquerda, XYZ(-1, 0, 0)), (direita, XYZ(1, 0, 0))):
        face = _face_com_normal(extrusao, normal)
        doc.FamilyCreate.NewAlignment(vista, plano.GetReference(), face.Reference)
    doc.Regenerate()

    for nome in (u"L300", u"L1500"):
        gerenciador.NewType(nome)
        gerenciador.Set(largura, mm(S1_LARGURAS[nome]))
    if not _commit(transacao, resultado):
        return

    esperados = {}
    for nome, valor in S1_LARGURAS.items():
        esperados[nome] = {
            u"extensao_mm": [valor, S1_PROFUNDIDADE, S1_ALTURA],
            u"minimo_mm": [-valor / 2, -S1_PROFUNDIDADE / 2, 0.0],
            u"volume_mm3": valor * S1_PROFUNDIDADE * S1_ALTURA,
        }
    _avaliar(resultado, esperados, _medir_tipos(doc, registro))


# --------------------------------------------------------------------------
# S2 + S4: cilindro
# --------------------------------------------------------------------------

S2_RAIOS = {u"R100": 100.0, u"R200": 200.0, u"R350": 350.0}
S2_ALTURA = 500.0


def _cilindro_base(doc, registro):
    u"""Extrusão de círculo r=200, altura fixa, tipo R200 corrente."""
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"R200")
    raio = _parametro(doc, u"Raio", u"length")
    gerenciador.Set(raio, mm(200.0))
    extrusao = doc.FamilyCreate.NewExtrusion(
        True, _circulo(200.0), _plano_de_esboco_z0(doc), mm(S2_ALTURA))
    doc.Regenerate()
    return raio, extrusao


def _cota_radial(doc, vista, referencia, origem):
    u"""Tenta raio e diâmetro; devolve (cota, método) ou (None, erros)."""
    erros = []
    fabrica = doc.FamilyCreate
    for metodo in (u"NewRadialDimension", u"NewDiameterDimension"):
        funcao = getattr(fabrica, metodo, None)
        if funcao is None:
            erros.append(u"{0}: não existe nesta versão".format(metodo))
            continue
        try:
            return funcao(vista, referencia, origem), metodo
        except Exception as erro:
            erros.append(u"{0}: {1}".format(metodo, _texto(erro)[:160]))
    return None, erros


def _fechar_cilindro(doc, resultado, transacao, raio, rotulo_diametro):
    gerenciador = doc.FamilyManager
    for nome in (u"R100", u"R350"):
        gerenciador.NewType(nome)
        valor = S2_RAIOS[nome] * (2.0 if rotulo_diametro else 1.0)
        gerenciador.Set(raio, mm(valor))
    if not _commit(transacao, resultado):
        return
    esperados = {}
    for nome, r in S2_RAIOS.items():
        esperados[nome] = {
            u"extensao_mm": [2 * r, 2 * r, S2_ALTURA],
            u"minimo_mm": [-r, -r, 0.0],
            u"volume_mm3": math.pi * r * r * S2_ALTURA,
        }
    _avaliar(resultado, esperados, _medir_tipos(doc, resultado[u"registro"]))


def _sonda_cilindro_por_referencia(doc, resultado, obter_referencia):
    registro = resultado[u"registro"]
    transacao = _transacao(doc, u"S2", registro)
    transacao.Start()
    vista = _vista_de_planta(doc)
    raio, extrusao = _cilindro_base(doc, registro)

    referencia = obter_referencia(extrusao)
    if referencia is None:
        transacao.RollBack()
        resultado[u"erro"] = u"referência do arco não encontrada"
        return
    cota, metodo = _cota_radial(doc, vista, referencia, XYZ(mm(300), mm(300), 0.0))
    if cota is None:
        transacao.RollBack()
        resultado[u"erro"] = u"; ".join(metodo)
        return
    resultado[u"metodo"] = metodo
    diametro = metodo == u"NewDiameterDimension"
    if diametro:
        gerenciador = doc.FamilyManager
        gerenciador.Set(raio, mm(400.0))
    cota.FamilyLabel = raio
    doc.Regenerate()
    _fechar_cilindro(doc, resultado, transacao, raio, diametro)


def sonda_cilindro_aresta(doc, resultado):
    def referencia(extrusao):
        for aresta in _arestas_circulares(extrusao):
            if abs(aresta.AsCurve().Center.Z) < 1e-6:
                return aresta.Reference
        return None
    _sonda_cilindro_por_referencia(doc, resultado, referencia)


def sonda_cilindro_esboco(doc, resultado):
    def referencia(extrusao):
        for laco in extrusao.Sketch.Profile:
            for curva in laco:
                if isinstance(curva, Arc) and curva.Reference is not None:
                    return curva.Reference
        return None
    _sonda_cilindro_por_referencia(doc, resultado, referencia)


def sonda_cilindro_revolucao(doc, resultado):
    u"""Revolução de um retângulo com a face externa travada num plano."""
    registro = resultado[u"registro"]
    transacao = _transacao(doc, u"S2B", registro)
    transacao.Start()
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"R200")
    vista = _vista_de_planta(doc)
    raio = _parametro(doc, u"Raio", u"length")
    gerenciador.Set(raio, mm(200.0))

    centro = _plano_centro_esq_dir(doc)
    plano_raio = _plano_vertical_x(doc, vista, 200.0, u"RFADG_S2_Raio")
    doc.Regenerate()
    cota = doc.FamilyCreate.NewDimension(
        vista, _linha_de_cota_x(0.0, 200.0), _referencias(centro.GetReference(), plano_raio.GetReference()))
    cota.FamilyLabel = raio
    doc.Regenerate()

    pontos = [XYZ(0, 0, 0), XYZ(mm(200), 0, 0), XYZ(mm(200), 0, mm(S2_ALTURA)), XYZ(0, 0, mm(S2_ALTURA))]
    laco = CurveArray()
    for indice in range(4):
        laco.Append(Line.CreateBound(pontos[indice], pontos[(indice + 1) % 4]))
    perfil = CurveArrArray()
    perfil.Append(laco)
    esboco = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisY, XYZ.Zero))
    eixo = Line.CreateBound(XYZ(0, 0, 0), XYZ(0, 0, mm(S2_ALTURA)))
    revolucao = doc.FamilyCreate.NewRevolution(True, perfil, esboco, eixo, 0.0, 2.0 * math.pi)
    doc.Regenerate()

    cilindrica = None
    for objeto in _geometria(revolucao):
        if isinstance(objeto, Solid):
            for face in objeto.Faces:
                if isinstance(face, DB.CylindricalFace):
                    cilindrica = face
    if cilindrica is None:
        transacao.RollBack()
        resultado[u"erro"] = u"revolução sem face cilíndrica"
        return
    try:
        doc.FamilyCreate.NewAlignment(vista, plano_raio.GetReference(), cilindrica.Reference)
    except Exception as erro:
        transacao.RollBack()
        resultado[u"erro"] = u"NewAlignment plano x face cilíndrica: " + _texto(erro)[:200]
        return
    doc.Regenerate()
    _fechar_cilindro(doc, resultado, transacao, raio, False)


# --------------------------------------------------------------------------
# S3: array
# --------------------------------------------------------------------------

S3_LADO = 100.0
S3_PASSO = 300.0


def _cubo(doc, x0):
    return doc.FamilyCreate.NewExtrusion(
        True, _retangulo(x0, x0 + S3_LADO, 0.0, S3_LADO), _plano_de_esboco_z0(doc), mm(S3_LADO))


def sonda_array_linear(doc, resultado):
    registro = resultado[u"registro"]
    transacao = _transacao(doc, u"S3A", registro)
    transacao.Start()
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"N3")
    vista = _vista_de_planta(doc)
    contagem = _parametro(doc, u"N", u"integer")
    gerenciador.Set(contagem, 3)

    cubo = _cubo(doc, 0.0)
    doc.Regenerate()
    ancora = getattr(DB.ArrayAnchorMember, "Second", None)
    arranjo = DB.LinearArray.Create(doc, vista, cubo.Id, 3, XYZ(mm(S3_PASSO), 0, 0), ancora)
    doc.Regenerate()
    try:
        arranjo.Label = contagem
    except Exception as erro:
        transacao.RollBack()
        resultado[u"erro"] = u"BaseArray.Label: " + _texto(erro)[:200]
        return
    doc.Regenerate()

    valores = {u"N2": 2, u"N3": 3, u"N5": 5}
    for nome in (u"N2", u"N5"):
        gerenciador.NewType(nome)
        gerenciador.Set(contagem, valores[nome])
    if not _commit(transacao, resultado):
        return
    esperados = {}
    for nome, n in valores.items():
        esperados[nome] = {
            u"extensao_mm": [(n - 1) * S3_PASSO + S3_LADO, S3_LADO, S3_LADO],
            u"volume_mm3": n * S3_LADO ** 3,
        }
    _avaliar(resultado, esperados, _medir_tipos(doc, registro))


def sonda_array_visibilidade(doc, resultado):
    u"""4 cópias; a k-ésima fica visível quando N >= k (fórmula sim/não).

    A medição de sólidos não enxerga visibilidade (a geometria existe no
    documento da família); o que se confere aqui é a fórmula avaliada por tipo.
    """
    registro = resultado[u"registro"]
    transacao = _transacao(doc, u"S3B", registro)
    transacao.Start()
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"N2")
    contagem = _parametro(doc, u"N", u"integer")
    gerenciador.Set(contagem, 2)

    chaves = []
    for k in range(1, 5):
        cubo = _cubo(doc, (k - 1) * S3_PASSO)
        visivel = _parametro(doc, u"Visivel_{0}".format(k), u"yesno")
        doc.Regenerate()
        gerenciador.AssociateElementParameterToFamilyParameter(
            cubo.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM), visivel)
        # O Revit não aceita >= nem <= em fórmula (medido no 2022): N > k-1.
        gerenciador.SetFormula(visivel, u"N > {0}".format(k - 1))
        chaves.append((k, visivel))
    doc.Regenerate()

    valores = {u"N2": 2, u"N4": 4}
    gerenciador.NewType(u"N4")
    gerenciador.Set(contagem, 4)
    if not _commit(transacao, resultado):
        return

    tipos = []
    tudo_ok = True
    for tipo in gerenciador.Types:
        nome = rfaspec.para_unicode(tipo.Name)
        if nome not in valores:
            continue
        obtidos = [tipo.AsInteger(visivel) for _, visivel in chaves]
        esperados = [1 if valores[nome] >= k else 0 for k, _ in chaves]
        ok = obtidos == esperados
        tudo_ok = tudo_ok and ok
        tipos.append({u"tipo": nome, u"ok": ok, u"esperado": esperados, u"obtido": obtidos})
    resultado[u"tipos"] = tipos
    resultado[u"veredito"] = u"SIM" if tudo_ok and tipos else u"NAO"


# --------------------------------------------------------------------------
# S6 e S7
# --------------------------------------------------------------------------

def sonda_subcategoria(doc, resultado):
    registro = resultado[u"registro"]
    transacao = _transacao(doc, u"S6", registro)
    transacao.Start()
    doc.FamilyManager.NewType(u"Padrao")
    categoria = doc.OwnerFamily.FamilyCategory
    subcategoria = doc.Settings.Categories.NewSubcategory(categoria, u"Tampo")
    cubo = _cubo(doc, 0.0)
    cubo.Subcategory = subcategoria
    doc.Regenerate()
    if not _commit(transacao, resultado):
        return
    lida = cubo.Subcategory
    resultado[u"lida"] = rfaspec.para_unicode(lida.Name) if lida is not None else None
    resultado[u"veredito"] = u"SIM" if resultado[u"lida"] == u"Tampo" else u"NAO"


def _imagem_de_teste(pasta):
    import clr
    clr.AddReference("System.Drawing")
    from System.Drawing import Bitmap, Color
    from System.Drawing.Imaging import ImageFormat
    caminho = os.path.join(pasta, u"g0_imagem_teste.png")
    bitmap = Bitmap(64, 64)
    for x in range(64):
        for y in range(64):
            bitmap.SetPixel(x, y, Color.FromArgb(40, 120 + x, 200 - y))
    bitmap.Save(caminho, ImageFormat.Png)
    bitmap.Dispose()
    return caminho


def sonda_imagem_do_tipo(doc, resultado, pasta):
    registro = resultado[u"registro"]
    caminho = _imagem_de_teste(pasta)
    transacao = _transacao(doc, u"S7", registro)
    transacao.Start()
    gerenciador = doc.FamilyManager
    gerenciador.NewType(u"Padrao")

    opcoes_cls = getattr(DB, "ImageTypeOptions", None)
    if opcoes_cls is None:
        transacao.RollBack()
        resultado[u"erro"] = u"ImageTypeOptions não existe nesta versão"
        return
    origem = getattr(getattr(DB, "ImageTypeSource", None), "Import", None)
    try:
        opcoes = opcoes_cls(caminho, False, origem)
        resultado[u"metodo"] = u"ImageTypeOptions(caminho, False, Import)"
    except Exception:
        opcoes = opcoes_cls(caminho)
        resultado[u"metodo"] = u"ImageTypeOptions(caminho)"
    imagem = DB.ImageType.Create(doc, opcoes)
    parametro = gerenciador.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_IMAGE)
    if parametro is None:
        transacao.RollBack()
        resultado[u"erro"] = u"família sem o parâmetro Type Image"
        return
    gerenciador.Set(parametro, imagem.Id)
    if not _commit(transacao, resultado):
        return
    valor = gerenciador.CurrentType.AsElementId(parametro)
    resultado[u"veredito"] = u"SIM" if valor is not None and rfaspec.id_inteiro(valor) == rfaspec.id_inteiro(imagem.Id) else u"NAO"


# --------------------------------------------------------------------------

def principal():
    template = rfaspec.env("RFADG_TEMPLATE", obrigatorio=True)
    pasta = rfaspec.env("RFADG_G0_SAIDA", obrigatorio=True)
    if not os.path.isdir(pasta):
        os.makedirs(pasta)
    app = __revit__.Application  # noqa: F821

    sondas = [
        (u"S1_caixa_centrada", sonda_caixa_centrada),
        (u"S2A1_cilindro_aresta", sonda_cilindro_aresta),
        (u"S2A2_cilindro_esboco", sonda_cilindro_esboco),
        (u"S2B_cilindro_revolucao", sonda_cilindro_revolucao),
        (u"S3A_array_linear", sonda_array_linear),
        (u"S3B_array_visibilidade", sonda_array_visibilidade),
        (u"S6_subcategoria", sonda_subcategoria),
        (u"S7_imagem_do_tipo", lambda doc, res: sonda_imagem_do_tipo(doc, res, pasta)),
    ]
    resultados = [_rodar(nome, funcao, app, template, pasta) for nome, funcao in sondas]

    rfaspec.gravar_json(os.path.join(pasta, u"resultado.json"), {
        u"revit": {
            u"versao": rfaspec.para_unicode(app.VersionNumber),
            u"build": rfaspec.para_unicode(app.VersionBuild),
        },
        u"S5": {
            u"template": template,
            u"addparameter": _CAMINHO_ADDPARAMETER[0] if _CAMINHO_ADDPARAMETER else None,
        },
        u"sondas": resultados,
    })
    log(u"G0 concluída: {0}".format(
        u", ".join(u"{0}={1}".format(r[u"sonda"], r[u"veredito"]) for r in resultados)))


principal()

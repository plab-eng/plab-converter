"""Compilador: intenção -> FamilySpec + assinatura esperada (spec §6).

Puro e determinístico: mesma intenção, mesma FamilySpec. Emite exatamente o
que o construtor do conversor já sabe montar (planos verticais, cotas
rotuladas, extrusões, alinhamentos, associações, tipos e fórmulas), mais a
cota radial no esboço (schema 0.2.0), provada na sonda S2-A2 da G0.

Regras que vêm de armadilhas pagas (CLAUDE.md §5 e §7, docs/G0-resultado.md):
- a ordem dos planos é a âncora: o plano criado primeiro fica parado;
- a caixa centrada não usa cota EQ: duas cotas a partir do plano Center,
  rotuladas com um parâmetro de fórmula "meia largura" (S1);
- a geometria é emitida nos valores do tipo corrente;
- fórmula do Revit não aceita >= nem <= (o subconjunto daqui nem tem comparação).
"""

import math

from . import expressao as ex
from .intencao import CATEGORIAS

FORGE = {
    "length": "autodesk.spec.aec:length-2.0.0",
    "integer": "autodesk.spec:spec.int64-2.0.0",
    "yesno": "autodesk.spec:spec.bool-1.0.0",
    "number": "autodesk.spec.aec:number-2.0.0",
}
ARMAZENAMENTO = {"length": "Double", "number": "Double", "integer": "Integer", "yesno": "Integer"}
GRUPO = "autodesk.parameter.group:geometry-1.0.0"

CENTRO = {"x": "Center (Left/Right)", "y": "Center (Front/Back)"}
NORMAL = {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0]}
LADOS = {"x": ("Esq", "Dir"), "y": ("Frente", "Tras")}

# Cota rotulada com valor abaixo disto é recusada: o Revit não cria cota nula.
COTA_MINIMA_MM = 1.0
PREFIXO_TESTE = "_t_"


class CompilacaoRecusada(ValueError):
    def __init__(self, problemas):
        self.problemas = problemas
        super().__init__("compilação recusada:\n- " + "\n- ".join(problemas))


class _Contexto:
    def __init__(self, intencao, fixos):
        self.intencao = intencao
        self.fixos = dict(fixos or {})
        self.usuario = {p["nome"]: p for p in intencao["parametros"]}
        self.derivados = []          # [(nome, formula)] na ordem de criação
        self.planos = []
        self.cotas = []
        self.formas = []
        self.alinhamentos = []
        self.geometrias = []         # funções valores -> (min, max, volume, tolerância)
        self.positivos = []          # (descrição, expressão) que precisam ser > COTA_MINIMA_MM
        self.sinais = []             # (descrição, expressão, sinal esperado)
        self.lacunas = []
        self.usa_radial = False
        self.extensao_plano = 2000.0

    def expr(self, texto):
        texto = str(texto)
        return ex.substituir(texto, self.fixos) if self.fixos else texto

    def parametro(self, texto, componente, campo):
        """Nome do parâmetro que carrega `texto`, criando um derivado se preciso.

        Devolve None quando a expressão é constante: não há o que rotular.
        """
        texto = self.expr(texto)
        if ex.eh_constante(texto):
            return None
        if ex.eh_nome(texto) and texto in self.usuario:
            return texto.strip()
        nome = f"GER_{componente}_{campo}"
        self.derivados.append((nome, texto))
        return nome

    def plano(self, eixo, nome, coordenada):
        e = self.extensao_plano
        if eixo == "x":
            inicio, fim = [coordenada, -e, 0.0], [coordenada, e, 0.0]
        else:
            inicio, fim = [-e, coordenada, 0.0], [e, coordenada, 0.0]
        self.planos.append({"nome": nome, "canonico": True, "inicio": inicio,
                            "fim": fim, "normal": NORMAL[eixo]})
        return nome


def _ref_plano(nome):
    return {"tipo": "plano", "nome": nome}


def _cota(ctx, plano_a, plano_b, rotulo):
    ctx.cotas.append({"forma": "Linear", "referencias": [_ref_plano(plano_a), _ref_plano(plano_b)],
                      "rotulo": rotulo})


# --------------------------------------------------------------------------
# Padrões
# --------------------------------------------------------------------------

def _eixo_da_caixa(ctx, comp, eixo, tamanho, centro, v0):
    """Planos e cotas de um eixo horizontal. Devolve (plano_menor, plano_maior)."""
    menor_lado, maior_lado = LADOS[eixo]
    tamanho, centro = ctx.expr(tamanho), ctx.expr(centro)
    t0 = ex.avaliar(tamanho, v0)
    c0 = ex.avaliar(centro, v0)
    ctx.positivos.append((f"{comp}: tamanho em {eixo}", tamanho))

    if ex.eh_constante(centro) and abs(c0) < 1e-9:
        # Centrada: meia medida por fórmula rotulando as duas cotas (sonda S1).
        meia = ctx.parametro(f"({tamanho}) / 2", comp, f"meia_{eixo}")
        menor = ctx.plano(eixo, f"RFADG_{comp}_{menor_lado}", c0 - t0 / 2)
        maior = ctx.plano(eixo, f"RFADG_{comp}_{maior_lado}", c0 + t0 / 2)
        if meia:
            _cota(ctx, CENTRO[eixo], menor, meia)
            _cota(ctx, CENTRO[eixo], maior, meia)
        return menor, maior

    # Fora do centro: cadeia centro -> plano próximo -> plano distante, nessa
    # ordem de criação, para cada plano ser âncora do seguinte.
    sinal = 1.0 if c0 > 0 else -1.0
    proximo_expr = f"({centro}) - ({tamanho}) / 2" if sinal > 0 else f"0 - ({centro}) - ({tamanho}) / 2"
    ctx.sinais.append((f"{comp}: centro em {eixo}", centro, sinal))
    ctx.positivos.append((f"{comp}: afastamento do centro em {eixo}", proximo_expr))
    afastamento = ctx.parametro(proximo_expr, comp, f"afast_{eixo}")
    rotulo_tamanho = ctx.parametro(tamanho, comp, f"tam_{eixo}")
    a0 = ex.avaliar(proximo_expr, v0)
    lado_proximo, lado_distante = (menor_lado, maior_lado) if sinal > 0 else (maior_lado, menor_lado)
    proximo = ctx.plano(eixo, f"RFADG_{comp}_{lado_proximo}", sinal * a0)
    distante = ctx.plano(eixo, f"RFADG_{comp}_{lado_distante}", sinal * (a0 + t0))
    if afastamento:
        _cota(ctx, CENTRO[eixo], proximo, afastamento)
    if rotulo_tamanho:
        _cota(ctx, proximo, distante, rotulo_tamanho)
    return (proximo, distante) if sinal > 0 else (distante, proximo)


def _altura(ctx, comp, base, altura, v0):
    """Deslocamentos e associações da extrusão (base e topo)."""
    base, altura = ctx.expr(base), ctx.expr(altura)
    ctx.positivos.append((f"{comp}: altura", altura))
    b0, h0 = ex.avaliar(base, v0), ex.avaliar(altura, v0)
    associacoes = {}
    if not ex.eh_constante(base):
        associacoes["Extrusion Start"] = {"builtin": "EXTRUSION_START_PARAM",
                                          "parametro_de_familia": ctx.parametro(base, comp, "base")}
    topo_expr = altura if (ex.eh_constante(base) and abs(b0) < 1e-9) else f"({base}) + ({altura})"
    topo = ctx.parametro(topo_expr, comp, "topo")
    if topo:
        associacoes["Extrusion End"] = {"builtin": "EXTRUSION_END_PARAM", "parametro_de_familia": topo}
    return b0, b0 + h0, associacoes, base, altura


def _extrusao(ctx, perfil, inicio, fim, associacoes, comp):
    indice = len(ctx.formas)
    ctx.formas.append({
        "indice": indice, "tipo": "extrusao", "solido": True, "perfil": perfil,
        "plano_de_esboco": {"normal": [0.0, 0.0, 1.0], "origem": [0.0, 0.0, 0.0]},
        "deslocamento_inicial": inicio, "deslocamento_final": fim,
        "associacoes": associacoes, "subcategoria": comp.get("subcategoria"),
        "visivel": True, "componente": comp["id"],
    })
    for chave in ("subcategoria", "material"):
        if comp.get(chave):
            ctx.lacunas.append({"componente": comp["id"], "motivo":
                                f"{chave} {comp[chave]!r} ainda não é construída (G2)"})
    return indice


def _linha(a, b):
    return {"tipo": "linha", "inicio": a, "fim": b}


def padrao_caixa(ctx, comp, v0):
    args = comp["args"]
    largura, profundidade = args["largura"], args["profundidade"]
    cx, cy = args.get("centro_x", "0"), args.get("centro_y", "0")
    parametrico = ctx.intencao["modo"] == "parametrico"

    if parametrico:
        esq, dir_ = _eixo_da_caixa(ctx, comp["id"], "x", largura, cx, v0)
        frente, tras = _eixo_da_caixa(ctx, comp["id"], "y", profundidade, cy, v0)
    inicio, fim, associacoes, base, altura = _altura(ctx, comp["id"], args.get("base", "0"),
                                                     args["altura"], v0)
    if not parametrico:
        associacoes = {}

    def caixa(valores):
        c = [ex.avaliar(ctx.expr(cx), valores), ex.avaliar(ctx.expr(cy), valores)]
        t = [ex.avaliar(ctx.expr(largura), valores), ex.avaliar(ctx.expr(profundidade), valores)]
        b, h = ex.avaliar(base, valores), ex.avaliar(altura, valores)
        minimo = [c[0] - t[0] / 2, c[1] - t[1] / 2, b]
        maximo = [c[0] + t[0] / 2, c[1] + t[1] / 2, b + h]
        return minimo, maximo, t[0] * t[1] * h, 0.1

    x0, y0, x1, y1 = (*caixa(v0)[0][:2], *caixa(v0)[1][:2])
    perfil = [[_linha([x0, y0, 0.0], [x1, y0, 0.0]), _linha([x1, y0, 0.0], [x1, y1, 0.0]),
               _linha([x1, y1, 0.0], [x0, y1, 0.0]), _linha([x0, y1, 0.0], [x0, y0, 0.0])]]
    indice = _extrusao(ctx, perfil, inicio, fim, associacoes, comp)
    ctx.geometrias.append(caixa)

    if parametrico:
        meio_z = (inicio + fim) / 2
        for plano, normal, origem in (
                (esq, [-1.0, 0.0, 0.0], [x0, (y0 + y1) / 2, meio_z]),
                (dir_, [1.0, 0.0, 0.0], [x1, (y0 + y1) / 2, meio_z]),
                (frente, [0.0, -1.0, 0.0], [(x0 + x1) / 2, y0, meio_z]),
                (tras, [0.0, 1.0, 0.0], [(x0 + x1) / 2, y1, meio_z])):
            ctx.alinhamentos.append({"referencias": [
                _ref_plano(plano),
                {"tipo": "face", "forma": indice, "normal": normal, "origem": origem}]})


def padrao_cilindro(ctx, comp, v0):
    """Cilindro em z, centrado na origem; raio pela cota radial no esboço (S2-A2)."""
    args = comp["args"]
    diametro = ctx.expr(args["diametro"])
    ctx.positivos.append((f"{comp['id']}: diâmetro", diametro))
    inicio, fim, associacoes, base, altura = _altura(ctx, comp["id"], args.get("base", "0"),
                                                     args["altura"], v0)
    parametrico = ctx.intencao["modo"] == "parametrico"
    if not parametrico:
        associacoes = {}
    r0 = ex.avaliar(diametro, v0) / 2
    perfil = [[
        {"tipo": "arco", "inicio": [r0, 0.0, 0.0], "fim": [-r0, 0.0, 0.0], "meio": [0.0, r0, 0.0]},
        {"tipo": "arco", "inicio": [-r0, 0.0, 0.0], "fim": [r0, 0.0, 0.0], "meio": [0.0, -r0, 0.0]},
    ]]
    indice = _extrusao(ctx, perfil, inicio, fim, associacoes, comp)
    if parametrico:
        raio = ctx.parametro(f"({diametro}) / 2", comp["id"], "raio")
        if raio:
            ctx.usa_radial = True
            ctx.cotas.append({"forma": "Radial", "rotulo": raio, "referencias": [
                {"tipo": "esboco", "forma": indice, "laco": 0, "curva": 0}]})

    def cilindro(valores):
        r = ex.avaliar(diametro, valores) / 2
        b, h = ex.avaliar(base, valores), ex.avaliar(altura, valores)
        # A extensão é medida pela malha, que pode não ter vértice no extremo
        # de um eixo (G0: 0,32 mm a menos em r=200).
        return [-r, -r, b], [r, r, b + h], math.pi * r * r * h, max(0.1, 0.002 * 2 * r)
    ctx.geometrias.append(cilindro)


PADROES = {"caixa": padrao_caixa, "cilindro": padrao_cilindro}


# --------------------------------------------------------------------------
# Tipos e assinatura
# --------------------------------------------------------------------------

def _valores_base(intencao, fixos):
    valores = {p["nome"]: p["padrao"] for p in intencao["parametros"]}
    valores.update(fixos or {})
    return valores


def _tipos_reais(intencao, fixos):
    base = _valores_base(intencao, fixos)
    tipos = []
    for tipo in intencao.get("tipos") or [{"nome": "Padrao", "valores": {}}]:
        valores = dict(base)
        valores.update({k: v for k, v in tipo.get("valores", {}).items() if k not in (fixos or {})})
        tipos.append((tipo["nome"], valores))
    return tipos


def _tipos_de_teste(intencao, fixos):
    """Todos no mínimo, todos no máximo, e cada parâmetro sozinho nos extremos."""
    base = _valores_base(intencao, fixos)
    com_faixa = [p for p in intencao["parametros"]
                 if p.get("faixa") and p["nome"] not in (fixos or {})]
    tipos = []
    if not com_faixa:
        return tipos
    minimos, maximos = dict(base), dict(base)
    for p in com_faixa:
        minimos[p["nome"]], maximos[p["nome"]] = p["faixa"]
    tipos += [(f"{PREFIXO_TESTE}todos_min", minimos), (f"{PREFIXO_TESTE}todos_max", maximos)]
    for p in com_faixa:
        for extremo, valor in zip(("min", "max"), p["faixa"]):
            valores = dict(base)
            valores[p["nome"]] = valor
            tipos.append((f"{PREFIXO_TESTE}{p['nome']}_{extremo}", valores))
    return tipos


def _assinatura(ctx, valores):
    minimo, maximo, volume, tolerancia = None, None, 0.0, 0.1
    for geometria in ctx.geometrias:
        mn, mx, vol, tol = geometria(valores)
        minimo = mn if minimo is None else [min(a, b) for a, b in zip(minimo, mn)]
        maximo = mx if maximo is None else [max(a, b) for a, b in zip(maximo, mx)]
        volume += vol
        tolerancia = max(tolerancia, tol)
    return {"extensao_mm": [b - a for a, b in zip(minimo, maximo)], "minimo_mm": minimo,
            "volume_mm3": volume, "tolerancia_extensao_mm": tolerancia}


def _viabilidade(ctx, nome, valores):
    problemas = []
    for descricao, texto in ctx.positivos:
        valor = ex.avaliar(texto, valores)
        if valor < COTA_MINIMA_MM:
            problemas.append(f"tipo {nome}: {descricao} = {valor:.2f} mm (precisa ser >= {COTA_MINIMA_MM})")
    for descricao, texto, sinal in ctx.sinais:
        if ex.avaliar(texto, valores) * sinal <= 0:
            problemas.append(f"tipo {nome}: {descricao} troca de lado (o padrão não cruza o centro)")
    return problemas


def _valor_para_tipo(especie, valor):
    return int(round(valor)) if especie in ("integer", "yesno") else float(valor)


# --------------------------------------------------------------------------

def compilar(intencao, com_tipos_de_teste=True, fixos=None):
    """Intenção validada -> FamilySpec (dict). `fixos` = parâmetros desligados
    da geometria pelo laço de desfazer (spec §6.8), com o valor que assumem."""
    tipos = _tipos_reais(intencao, fixos)
    nome_corrente, v0 = tipos[0]
    ctx = _Contexto(intencao, fixos)

    for comp in intencao["componentes"]:
        PADROES[comp["padrao"]](ctx, comp, v0)

    if com_tipos_de_teste and intencao["modo"] == "parametrico":
        tipos = tipos + _tipos_de_teste(intencao, fixos)

    problemas = []
    for nome, valores in tipos:
        problemas += _viabilidade(ctx, nome, valores)
    if problemas:
        raise CompilacaoRecusada(problemas)

    parametros = []
    for p in intencao["parametros"]:
        parametros.append({
            "nome": p["nome"], "tipo_de_dado": FORGE[p["especie"]], "grupo": GRUPO,
            "de_instancia": bool(p.get("instancia")), "formula": None,
            "dirigido_por_formula": False, "compartilhado": False, "guid": None,
            "armazenamento": ARMAZENAMENTO[p["especie"]], "reporta": False,
        })
    for nome, formula in ctx.derivados:
        parametros.append({
            "nome": nome, "tipo_de_dado": FORGE["length"], "grupo": GRUPO,
            "de_instancia": False, "formula": formula, "dirigido_por_formula": True,
            "compartilhado": False, "guid": None, "armazenamento": "Double", "reporta": False,
        })

    especie = {p["nome"]: p["especie"] for p in intencao["parametros"]}
    tipos_spec, medicoes = [], {}
    for nome, valores in tipos:
        saida = {k: _valor_para_tipo(especie[k], v) for k, v in valores.items() if k in especie}
        for derivado, formula in ctx.derivados:
            saida[derivado] = ex.avaliar(formula, valores)
        tipos_spec.append({"nome": nome, "valores": saida})
        medicoes[nome] = _assinatura(ctx, valores)

    planos = [{"nome": CENTRO["x"], "canonico": False, "inicio": [0.0, -1.0, 0.0],
               "fim": [0.0, 1.0, 0.0], "normal": NORMAL["x"]},
              {"nome": CENTRO["y"], "canonico": False, "inicio": [-1.0, 0.0, 0.0],
               "fim": [1.0, 0.0, 0.0], "normal": NORMAL["y"]}] + ctx.planos

    return {
        "versao_schema": "0.2.0" if ctx.usa_radial else "0.1.0",
        "origem": {"arquivo": intencao["nome"], "versao_revit": None,
                   "gerador": "plab-converter/gerador intencao 0.1"},
        "identidade": {"categoria_id": CATEGORIAS[intencao["categoria"]],
                       "categoria_nome": intencao["categoria"]},
        "parametros": parametros,
        "tipo_corrente": nome_corrente,
        "tipos": tipos_spec,
        "planos_de_referencia": planos,
        "cotas": ctx.cotas,
        "formas": ctx.formas,
        "alinhamentos": ctx.alinhamentos,
        "combinacoes": [],
        "medicoes": medicoes,
        "lacunas": ctx.lacunas,
        "gerador": {
            "modo": intencao["modo"],
            "tipos_de_teste": [n for n, _ in tipos if n.startswith(PREFIXO_TESTE)],
            "fixos": dict(fixos or {}),
            "derivados": [n for n, _ in ctx.derivados],
        },
    }

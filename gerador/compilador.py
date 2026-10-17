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
        self.derivados = []          # dicts nome/formula/especie/valor, na ordem de criação
        self.planos = []
        self.cotas = []
        self.formas = []
        self.alinhamentos = []
        self.geometrias = []         # funções valores -> (min, max, volume, tolerância)
        self.positivos = []          # (descrição, expressão) que precisam ser > COTA_MINIMA_MM
        self.sinais = []             # (descrição, expressão, sinal esperado)
        self.lacunas = []
        self.usa_radial = False
        self.faces_de_conector = {}  # componente -> (índice da forma, valores -> {face: centro})
        self.extensao_plano = 2000.0

    def expr(self, texto):
        texto = str(texto)
        return ex.substituir(texto, self.fixos) if self.fixos else texto

    def _derivado(self, nome, formula, especie, valor):
        self.derivados.append({"nome": nome, "formula": formula, "especie": especie, "valor": valor})
        return nome

    def parametro(self, texto, componente, campo, forcar=False):
        """Nome do parâmetro que carrega `texto`, criando um derivado se preciso.

        Devolve None quando a expressão é constante e `forcar` é falso: não há
        o que rotular. Com `forcar`, a constante vira parâmetro de fórmula: é o
        jeito de TRAVAR uma cota de tamanho fixo (um plano sem cota rotulada
        fica solto e a face alinhada a ele não acompanha o resto).
        """
        texto = self.expr(texto)
        if ex.eh_constante(texto) and not forcar:
            return None
        if ex.eh_nome(texto) and texto in self.usuario:
            return texto.strip()
        nome = f"GER_{componente}_{campo}"
        return self._derivado(nome, texto, "length", lambda valores, t=texto: ex.avaliar(t, valores))

    def visibilidade(self, n, k, nome):
        """Sim/não "cópia k aparece": fórmula `n > k-1` (o Revit não aceita >=)."""
        return self._derivado(nome, f"{n} > {k - 1}", "yesno",
                              lambda valores: 1 if ex.avaliar(n, valores) > k - 1 else 0)

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
        meia = ctx.parametro(f"({tamanho}) / 2", comp, f"meia_{eixo}", forcar=True)
        menor = ctx.plano(eixo, f"RFADG_{comp}_{menor_lado}", c0 - t0 / 2)
        maior = ctx.plano(eixo, f"RFADG_{comp}_{maior_lado}", c0 + t0 / 2)
        if meia:
            _cota(ctx, CENTRO[eixo], menor, meia)
            _cota(ctx, CENTRO[eixo], maior, meia)
        return menor, maior

    if abs(c0) < t0 / 2:
        # Cruza o centro sem estar centrada: cada lado tem a sua cota a partir
        # do plano Center (t/2 - c e t/2 + c). A viabilidade garante que os
        # dois lados continuam positivos em todos os tipos, isto é, que a peça
        # não deixa de cruzar o centro.
        lado_menor = f"({tamanho}) / 2 - ({centro})"
        lado_maior = f"({tamanho}) / 2 + ({centro})"
        ctx.positivos.append((f"{comp}: lado {menor_lado} a partir do centro", lado_menor))
        ctx.positivos.append((f"{comp}: lado {maior_lado} a partir do centro", lado_maior))
        rotulo_menor = ctx.parametro(lado_menor, comp, f"lado_{menor_lado}", forcar=True)
        rotulo_maior = ctx.parametro(lado_maior, comp, f"lado_{maior_lado}", forcar=True)
        menor = ctx.plano(eixo, f"RFADG_{comp}_{menor_lado}", c0 - t0 / 2)
        maior = ctx.plano(eixo, f"RFADG_{comp}_{maior_lado}", c0 + t0 / 2)
        _cota(ctx, CENTRO[eixo], menor, rotulo_menor)
        _cota(ctx, CENTRO[eixo], maior, rotulo_maior)
        return menor, maior

    # Fora do centro: cadeia centro -> plano próximo -> plano distante, nessa
    # ordem de criação, para cada plano ser âncora do seguinte.
    sinal = 1.0 if c0 > 0 else -1.0
    proximo_expr = f"({centro}) - ({tamanho}) / 2" if sinal > 0 else f"0 - ({centro}) - ({tamanho}) / 2"
    ctx.sinais.append((f"{comp}: centro em {eixo}", centro, sinal))
    ctx.positivos.append((f"{comp}: afastamento do centro em {eixo}", proximo_expr))
    afastamento = ctx.parametro(proximo_expr, comp, f"afast_{eixo}", forcar=True)
    rotulo_tamanho = ctx.parametro(tamanho, comp, f"tam_{eixo}", forcar=True)
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
    if comp.get("material"):
        ctx.lacunas.append({"componente": comp["id"], "motivo":
                            f"material {comp['material']!r} ainda não é construído "
                            "(materiais por nome, roadmap do conversor)"})
    return indice


def _linha(a, b):
    return {"tipo": "linha", "inicio": a, "fim": b}


def _ligar_visibilidade(ctx, comp, associacoes, visivel):
    """Associa o Visible da forma ao sim/não da cópia. Devolve o teste por tipo."""
    if not visivel:
        return lambda valores: True
    n, k = visivel
    if ctx.intencao["modo"] == "parametrico":
        nome = ctx.visibilidade(n, k, f"GER_{comp['id']}_vis")
        associacoes["Visible"] = {"builtin": "IS_VISIBLE_PARAM", "parametro_de_familia": nome}
    return lambda valores: ex.avaliar(n, valores) > k - 1


def padrao_caixa(ctx, comp, v0, visivel=None):
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
    aparece = _ligar_visibilidade(ctx, comp, associacoes, visivel)

    def caixa(valores):
        c = [ex.avaliar(ctx.expr(cx), valores), ex.avaliar(ctx.expr(cy), valores)]
        t = [ex.avaliar(ctx.expr(largura), valores), ex.avaliar(ctx.expr(profundidade), valores)]
        b, h = ex.avaliar(base, valores), ex.avaliar(altura, valores)
        minimo = [c[0] - t[0] / 2, c[1] - t[1] / 2, b]
        maximo = [c[0] + t[0] / 2, c[1] + t[1] / 2, b + h]
        return minimo, maximo, t[0] * t[1] * h, 0.1, {"caixa": [minimo, maximo]}

    x0, y0, x1, y1 = (*caixa(v0)[0][:2], *caixa(v0)[1][:2])
    perfil = [[_linha([x0, y0, 0.0], [x1, y0, 0.0]), _linha([x1, y0, 0.0], [x1, y1, 0.0]),
               _linha([x1, y1, 0.0], [x0, y1, 0.0]), _linha([x0, y1, 0.0], [x0, y0, 0.0])]]
    indice = _extrusao(ctx, perfil, inicio, fim, associacoes, comp)
    ctx.geometrias.append(lambda valores: caixa(valores) if aparece(valores) else None)

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


def padrao_cilindro(ctx, comp, v0, visivel=None):
    """Cilindro em z, centrado na origem; raio pela cota radial no esboço (S2-A2)."""
    args = comp["args"]
    diametro = ctx.expr(args["diametro"])
    ctx.positivos.append((f"{comp['id']}: diâmetro", diametro))
    inicio, fim, associacoes, base, altura = _altura(ctx, comp["id"], args.get("base", "0"),
                                                     args["altura"], v0)
    parametrico = ctx.intencao["modo"] == "parametrico"
    if not parametrico:
        associacoes = {}
    aparece = _ligar_visibilidade(ctx, comp, associacoes, visivel)
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

    ctx.faces_de_conector[comp["id"]] = (indice, lambda valores: {
        "base": [0.0, 0.0, ex.avaliar(base, valores)],
        "topo": [0.0, 0.0, ex.avaliar(base, valores) + ex.avaliar(altura, valores)]})

    def cilindro(valores):
        r = ex.avaliar(diametro, valores) / 2
        b, h = ex.avaliar(base, valores), ex.avaliar(altura, valores)
        # A extensão é medida pela malha, que pode não ter vértice no extremo
        # de um eixo (G0: 0,32 mm a menos em r=200).
        return ([-r, -r, b], [r, r, b + h], math.pi * r * r * h, max(0.1, 0.002 * 2 * r),
                {"cilindro": [0.0, 0.0, r, b, b + h]})
    ctx.geometrias.append(lambda valores: cilindro(valores) if aparece(valores) else None)


# --------------------------------------------------------------------------
# Padrões estáticos (G4): geometria fixa, sem cotas nem travas
# --------------------------------------------------------------------------

def _forma_estatica(ctx, comp, tipo, perfil, plano, extra):
    indice = len(ctx.formas)
    forma = {"indice": indice, "tipo": tipo, "solido": True, "perfil": perfil,
             "plano_de_esboco": plano, "associacoes": {}, "subcategoria": comp.get("subcategoria"),
             "visivel": True, "componente": comp["id"]}
    forma.update(extra)
    ctx.formas.append(forma)
    if comp.get("material"):
        ctx.lacunas.append({"componente": comp["id"], "motivo":
                            f"material {comp['material']!r} ainda não é construído "
                            "(materiais por nome, roadmap do conversor)"})
    return indice


def _area_e_momento(pontos):
    """Área (com sinal) e momento de 1ª ordem em relação ao 1º eixo do polígono."""
    area = momento = 0.0
    for (a0, b0), (a1, b1) in zip(pontos, pontos[1:] + pontos[:1]):
        cruz = a0 * b1 - a1 * b0
        area += cruz / 2
        momento += (a0 + a1) * cruz / 6
    return area, momento


def padrao_perfil_extrudado(ctx, comp, v0, visivel=None):
    """Polígono num plano vertical, extrudado (cadeira de balanço, peças inclinadas).

    plano "yz": pontos (y, z), extrusão em +x a partir de x = inicio;
    plano "xz": pontos (x, z), extrusão em +y a partir de y = inicio.
    """
    args = comp["args"]
    pontos = [[float(a), float(b)] for a, b in args["pontos"]]
    inicio, espessura = float(args["inicio"]), float(args["espessura"])
    area, _ = _area_e_momento(pontos)
    if abs(area) < 1.0:
        raise CompilacaoRecusada([f"{comp['id']}: perfil sem área"])
    if espessura <= 0:
        raise CompilacaoRecusada([f"{comp['id']}: espessura precisa ser positiva"])
    if args["plano"] == "yz":
        mundo = [[inicio, a, b] for a, b in pontos]
        plano = {"normal": [1.0, 0.0, 0.0], "origem": [inicio, 0.0, 0.0]}
    else:
        mundo = [[a, inicio, b] for a, b in pontos]
        plano = {"normal": [0.0, 1.0, 0.0], "origem": [0.0, inicio, 0.0]}
    perfil = [[_linha(p, q) for p, q in zip(mundo, mundo[1:] + mundo[:1])]]
    _forma_estatica(ctx, comp, "extrusao", perfil, plano,
                    {"deslocamento_inicial": 0.0, "deslocamento_final": espessura})
    eixo_extrusao = 0 if args["plano"] == "yz" else 1
    minimo = [min(p[e] for p in mundo) for e in range(3)]
    maximo = [max(p[e] for p in mundo) for e in range(3)]
    maximo[eixo_extrusao] = inicio + espessura
    volume = abs(area) * espessura
    primitiva = {"prisma": {"pontos": mundo, "direcao": [1.0 if e == eixo_extrusao else 0.0 for e in range(3)],
                            "espessura": espessura}}
    ctx.geometrias.append(lambda valores: (minimo, maximo, volume, 0.1, primitiva))


def padrao_revolucao(ctx, comp, v0, visivel=None):
    """Perfil (raio, posição no eixo) girado 360° (globo, cúpula, peça torneada).

    eixo "z": vertical por (cx, cy), posição = altura acima de cz;
    eixo "y": horizontal por (cx, cz), posição = deslocamento em y a partir de cy.
    """
    args = comp["args"]
    pontos = [[float(r), float(h)] for r, h in args["perfil"]]
    cx, cy, cz = [float(v) for v in args["centro"]]
    if any(r < 0 for r, _ in pontos):
        raise CompilacaoRecusada([f"{comp['id']}: raio negativo (o perfil não pode cruzar o eixo)"])
    area, momento = _area_e_momento(pontos)
    if abs(area) < 1.0:
        raise CompilacaoRecusada([f"{comp['id']}: perfil sem área"])
    hs = [h for _, h in pontos]
    if args["eixo"] == "z":
        mundo = [[cx + r, cy, cz + h] for r, h in pontos]
        plano = {"normal": [0.0, 1.0, 0.0], "origem": [cx, cy, cz]}
        eixo = {"inicio": [cx, cy, cz + min(hs)], "fim": [cx, cy, cz + max(hs)]}
    else:
        mundo = [[cx + r, cy + h, cz] for r, h in pontos]
        plano = {"normal": [0.0, 0.0, 1.0], "origem": [cx, cy, cz]}
        eixo = {"inicio": [cx, cy + min(hs), cz], "fim": [cx, cy + max(hs), cz]}
    perfil = [[_linha(p, q) for p, q in zip(mundo, mundo[1:] + mundo[:1])]]
    _forma_estatica(ctx, comp, "revolucao", perfil, plano,
                    {"eixo": eixo, "angulo_inicial": 0.0, "angulo_final": 2 * math.pi})
    rmax = max(r for r, _ in pontos)
    if args["eixo"] == "z":
        minimo, maximo = [cx - rmax, cy - rmax, cz + min(hs)], [cx + rmax, cy + rmax, cz + max(hs)]
    else:
        minimo, maximo = [cx - rmax, cy + min(hs), cz - rmax], [cx + rmax, cy + max(hs), cz + rmax]
    volume = 2 * math.pi * abs(momento)  # Pappus: 2π ∫∫ r dA
    primitiva = {"revolucao": {"perfil": pontos, "centro": [cx, cy, cz], "eixo": args["eixo"]}}
    # Superfície curva medida pela malha: tolerância proporcional ao raio.
    ctx.geometrias.append(lambda valores: (minimo, maximo, volume, max(0.5, 0.004 * 2 * rmax), primitiva))


PADROES = {"caixa": padrao_caixa, "cilindro": padrao_cilindro,
           "perfil_extrudado": padrao_perfil_extrudado, "revolucao": padrao_revolucao}


def _expandir(ctx, comp):
    """Componente -> [(componente simples, visibilidade)]. Array vira cópias.

    Cada cópia é uma forma comum, com planos, cotas e alinhamentos próprios,
    então ela flexiona como qualquer caixa. A contagem paramétrica liga e
    desliga cópias pela visibilidade (sonda S3-B), até `n_max`.
    """
    padrao = comp["padrao"]
    if padrao in PADROES:
        return [(comp, None)]
    args = comp["args"]
    item = args["item"]

    def copia(sufixo, indices):
        return {"id": f"{comp['id']}_{sufixo}", "padrao": item["padrao"],
                "args": {chave: ex.substituir(str(valor), indices) for chave, valor in item["args"].items()},
                "subcategoria": comp.get("subcategoria"), "material": comp.get("material")}

    if padrao == "array_retangular":
        return [(copia(f"{i}_{j}", {"i": i, "j": j}), None)
                for i in range(1, args["linhas"] + 1) for j in range(1, args["colunas"] + 1)]

    n = ctx.expr(str(args["n"]))
    if ex.eh_constante(n):
        return [(copia(str(k), {"k": k}), None) for k in range(1, int(round(ex.avaliar(n, {}))) + 1)]
    return [(copia(str(k), {"k": k}), (n, k)) for k in range(1, args["n_max"] + 1)]


# --------------------------------------------------------------------------
# Tipos e assinatura
# --------------------------------------------------------------------------

NORMAIS_DE_FACE = {"topo": [0.0, 0.0, 1.0], "base": [0.0, 0.0, -1.0]}


def _conectores(ctx, intencao):
    """Conectores da FamilySpec e o teste: onde cada um deve estar, por tipo."""
    saida, esperados = [], []
    for indice, item in enumerate(intencao.get("conectores") or []):
        if item["componente"] not in ctx.faces_de_conector:
            raise CompilacaoRecusada([f"conectores[{indice}]: componente {item['componente']!r} não tem "
                                      "face de conector (por enquanto só cilindro)"])
        forma, centros = ctx.faces_de_conector[item["componente"]]
        diametro = ctx.expr(str(item["diametro"]))
        conector = {"dominio": "tubo", "sistema": item.get("sistema") or "Fitting",
                    "face": {"forma": forma, "normal": NORMAIS_DE_FACE[item["face"]]},
                    "ligado_a": item.get("ligado_a"), "diametro_rotulo": None, "diametro_mm": None}
        if ex.eh_constante(diametro):
            conector["diametro_mm"] = ex.avaliar(diametro, {})
        else:
            conector["diametro_rotulo"] = ctx.parametro(diametro, f"conector{indice}", "diametro")
        saida.append(conector)
        esperados.append((item["face"], centros, diametro))
    return saida, esperados


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
        resultado = geometria(valores)
        if resultado is None:
            continue  # cópia oculta neste tipo
        mn, mx, vol, tol, _ = resultado
        minimo = mn if minimo is None else [min(a, b) for a, b in zip(minimo, mn)]
        maximo = mx if maximo is None else [max(a, b) for a, b in zip(maximo, mx)]
        volume += vol
        tolerancia = max(tolerancia, tol)
    return {"extensao_mm": [b - a for a, b in zip(minimo, maximo)], "minimo_mm": minimo,
            "volume_mm3": volume, "tolerancia_extensao_mm": tolerancia}


def _primitivas(ctx, valores):
    """Sólidos visíveis no tipo, como caixas e cilindros (para a prévia)."""
    return [resultado[4] for resultado in (g(valores) for g in ctx.geometrias) if resultado is not None]


def _viabilidade(ctx, nome, valores):
    """Lista de (tipo, causa). A causa não leva o valor, para agrupar entre tipos."""
    problemas = []
    for descricao, texto in ctx.positivos:
        if ex.avaliar(texto, valores) < COTA_MINIMA_MM:
            problemas.append((nome, f"{descricao} fica abaixo de {COTA_MINIMA_MM} mm"))
    for descricao, texto, sinal in ctx.sinais:
        if ex.avaliar(texto, valores) * sinal <= 0:
            problemas.append((nome, f"{descricao} troca de lado (passaria pelo centro)"))
    return problemas


def _valor_para_tipo(especie, valor):
    return int(round(valor)) if especie in ("integer", "yesno") else float(valor)


# --------------------------------------------------------------------------

def compilar(intencao, com_tipos_de_teste=True, fixos=None, imagem=None):
    """Intenção validada -> FamilySpec (dict). `fixos` = parâmetros desligados
    da geometria pelo laço de desfazer (spec §6.8), com o valor que assumem.
    `imagem` = caminho absoluto da imagem que vira o Type Image de todos os
    tipos (a imagem é obrigatória na entrada; quem resolve o caminho é o
    orquestrador, que conhece a pasta da intenção)."""
    tipos = _tipos_reais(intencao, fixos)
    nome_corrente, v0 = tipos[0]
    ctx = _Contexto(intencao, fixos)

    for comp in intencao["componentes"]:
        for simples, visivel in _expandir(ctx, comp):
            PADROES[simples["padrao"]](ctx, simples, v0, visivel)

    conectores, conectores_por_tipo = _conectores(ctx, intencao)

    if com_tipos_de_teste and intencao["modo"] == "parametrico":
        tipos = tipos + _tipos_de_teste(intencao, fixos)

    por_causa = {}
    for nome, valores in tipos:
        for tipo_nome, causa in _viabilidade(ctx, nome, valores):
            por_causa.setdefault(causa, []).append(tipo_nome)
    if por_causa:
        # Uma linha por causa, com os tipos em que ela aparece: a mesma causa
        # repetida em 16 tipos e 5 cópias esconde as outras.
        raise CompilacaoRecusada([
            f"{causa} — em {len(nomes)} tipo(s): {', '.join(nomes[:4])}{' ...' if len(nomes) > 4 else ''}"
            for causa, nomes in por_causa.items()])

    parametros = []
    for p in intencao["parametros"]:
        parametros.append({
            "nome": p["nome"], "tipo_de_dado": FORGE[p["especie"]], "grupo": GRUPO,
            "de_instancia": bool(p.get("instancia")), "formula": None,
            "dirigido_por_formula": False, "compartilhado": False, "guid": None,
            "armazenamento": ARMAZENAMENTO[p["especie"]], "reporta": False,
        })
    for derivado in ctx.derivados:
        parametros.append({
            "nome": derivado["nome"], "tipo_de_dado": FORGE[derivado["especie"]], "grupo": GRUPO,
            "de_instancia": False, "formula": derivado["formula"], "dirigido_por_formula": True,
            "compartilhado": False, "guid": None,
            "armazenamento": ARMAZENAMENTO[derivado["especie"]], "reporta": False,
        })

    especie = {p["nome"]: p["especie"] for p in intencao["parametros"]}
    tipos_spec, medicoes = [], {}
    for nome, valores in tipos:
        saida = {k: _valor_para_tipo(especie[k], v) for k, v in valores.items() if k in especie}
        for derivado in ctx.derivados:
            saida[derivado["nome"]] = derivado["valor"](valores)
        tipos_spec.append({"nome": nome, "valores": saida})
        medicoes[nome] = _assinatura(ctx, valores)
        if conectores_por_tipo:
            medicoes[nome]["conectores"] = [
                {"origem_mm": centros(valores)[face], "normal": NORMAIS_DE_FACE[face],
                 "diametro_mm": ex.avaliar(diametro, valores)}
                for face, centros, diametro in conectores_por_tipo]

    planos = [{"nome": CENTRO["x"], "canonico": False, "inicio": [0.0, -1.0, 0.0],
               "fim": [0.0, 1.0, 0.0], "normal": NORMAL["x"]},
              {"nome": CENTRO["y"], "canonico": False, "inicio": [-1.0, 0.0, 0.0],
               "fim": [1.0, 0.0, 0.0], "normal": NORMAL["y"]}] + ctx.planos

    return {
        "versao_schema": "0.3.0" if conectores else ("0.2.0" if ctx.usa_radial else "0.1.0"),
        "origem": {"arquivo": intencao["nome"], "versao_revit": None,
                   "gerador": "plab-converter/gerador intencao 0.1"},
        "identidade": {"categoria_id": CATEGORIAS[intencao["categoria"]],
                       "categoria_nome": intencao["categoria"],
                       "part_type": intencao.get("tipo_de_peca")},
        "conectores": conectores,
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
        "imagem_do_tipo": {"arquivo": imagem} if imagem else None,
        "gerador": {
            "modo": intencao["modo"],
            "tipos_de_teste": [n for n, _ in tipos if n.startswith(PREFIXO_TESTE)],
            "fixos": dict(fixos or {}),
            "derivados": [d["nome"] for d in ctx.derivados],
            "primitivas": _primitivas(ctx, v0),
        },
    }

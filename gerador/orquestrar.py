"""Orquestrador da geração (spec §3.1 e §6.6–6.8).

compila (com tipos de teste) -> constrói no Revit -> valida -> se um tipo de
teste reprovar, fixa o parâmetro culpado e recompila (no máximo 2 voltas) ->
compila de novo SEM os tipos de teste -> constrói e valida a família final.

O `pyrevit run` devolve exit 0 mesmo quando o script quebra (CLAUDE.md §7, 4b):
toda saída é apagada antes de cada etapa e precisa reaparecer depois.
"""

import glob
import json
import os
import subprocess

from . import compilador, intencao as intencao_mod

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_VOLTAS = 2


class EtapaFalhou(RuntimeError):
    pass


def resolver_template(ano):
    raiz = rf"C:\ProgramData\Autodesk\RVT {ano}\Family Templates"
    candidatos = []
    for caminho in glob.glob(os.path.join(raiz, "**", "*.rft"), recursive=True):
        nome = os.path.basename(caminho).lower().replace("_", " ")
        if "generic model" not in nome:
            continue
        if any(ruim in nome for ruim in ("adaptive", "based", "pattern", "two level")):
            continue
        completo = caminho.lower()
        prioridade = 0 if "-enu" in completo else 1 if "\\english\\" in completo else 2
        candidatos.append((prioridade, nome, caminho))
    if not candidatos:
        raise EtapaFalhou(f"nenhum template Generic Model em {raiz}")
    return sorted(candidatos)[0][2]


def _gravar_spec(caminho, spec):
    # ASCII puro: o rfaspec.ler_json do lado IronPython mapeia byte -> code point.
    with open(caminho, "w", encoding="ascii") as arquivo:
        json.dump(spec, arquivo, ensure_ascii=True, indent=1, sort_keys=True)


def _pyrevit(script, ano, ambiente, log):
    portadora = os.path.join(RAIZ, "out", "portadora.rfa")
    env = dict(os.environ)
    env.update({"RFADG_ROOT": RAIZ, **ambiente})
    processo = subprocess.run(
        ["pyrevit", "run", os.path.join(RAIZ, "scripts", script), portadora, f"--revit={ano}"],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    with open(log, "w", encoding="utf-8") as arquivo:
        arquivo.write(processo.stdout + processo.stderr)
    return processo.stdout + processo.stderr


def _apagar(*caminhos):
    for caminho in caminhos:
        if os.path.isfile(caminho):
            os.remove(caminho)


def construir_e_validar(spec, pasta, rotulo, ano):
    caminho_spec = os.path.join(pasta, f"{rotulo}.spec.json")
    rfa = os.path.join(pasta, f"{rotulo}.rfa")
    rel_construtor = os.path.join(pasta, f"{rotulo}.construtor.json")
    rel_validador = os.path.join(pasta, f"{rotulo}.validacao.json")
    _apagar(rfa, rel_construtor, rel_validador)
    _gravar_spec(caminho_spec, spec)

    saida = _pyrevit("construtor.py", ano, {
        "RFADG_SPEC": caminho_spec, "RFADG_SAIDA": rfa,
        "RFADG_TEMPLATE": resolver_template(ano), "RFADG_RELATORIO": rel_construtor,
    }, os.path.join(pasta, f"{rotulo}.construtor.log"))
    if not os.path.isfile(rfa):
        raise EtapaFalhou(f"construtor não gerou {rfa}:\n{saida[-2500:]}")

    saida = _pyrevit("validador_geracao.py", ano, {
        "RFADG_ENTRADA": rfa, "RFADG_SPEC": caminho_spec, "RFADG_RELATORIO_FLEX": rel_validador,
    }, os.path.join(pasta, f"{rotulo}.validacao.log"))
    if not os.path.isfile(rel_validador):
        raise EtapaFalhou(f"validador não gerou {rel_validador}:\n{saida[-2500:]}")

    with open(rel_construtor, encoding="utf-8") as arquivo:
        construtor = json.load(arquivo)
    with open(rel_validador, encoding="utf-8") as arquivo:
        validacao = json.load(arquivo)
    return rfa, construtor, validacao


def _culpados(validacao, intencao):
    """Parâmetros cujos tipos de teste reprovaram. None = não dá para isolar."""
    reprovados = [t["tipo"] for t in validacao["tipos"] if t["veredito"] != "REPRODUZ"]
    if not reprovados:
        return set()
    nomes = {p["nome"] for p in intencao["parametros"]}
    culpados = set()
    for tipo in reprovados:
        if not tipo.startswith(compilador.PREFIXO_TESTE):
            return None  # tipo real reprovou: defeito de construção, não de faixa
        miolo = tipo[len(compilador.PREFIXO_TESTE):].rsplit("_", 1)[0]
        if miolo in nomes:
            culpados.add(miolo)
    # Só os "todos_*" reprovaram: interação entre parâmetros, sem culpado único.
    return culpados or None


def gerar(caminho_intencao, ano=2024, pasta=None):
    dados = intencao_mod.carregar(caminho_intencao)
    pasta = pasta or os.path.join(RAIZ, "out", "gerador", dados["nome"], str(ano))
    os.makedirs(pasta, exist_ok=True)
    padroes = {p["nome"]: p["padrao"] for p in dados["parametros"]}
    fixos = {}
    historico = []

    for volta in range(MAX_VOLTAS + 1):
        spec = compilador.compilar(dados, com_tipos_de_teste=True, fixos=fixos)
        _, construtor, validacao = construir_e_validar(spec, pasta, f"teste_v{volta}", ano)
        historico.append({"volta": volta, "fixos": dict(fixos), "aprovada": validacao["aprovada"],
                          "nao_reproduzido": construtor.get("nao_reproduzido", [])})
        if validacao["aprovada"]:
            break
        culpados = _culpados(validacao, dados)
        if not culpados or volta == MAX_VOLTAS:
            return _relatorio(pasta, dados, None, historico, validacao, aprovada=False)
        for nome in sorted(culpados):
            fixos[nome] = padroes[nome]

    final = compilador.compilar(dados, com_tipos_de_teste=False, fixos=fixos)
    rfa, construtor, validacao = construir_e_validar(final, pasta, dados["nome"], ano)
    historico.append({"volta": "final", "fixos": dict(fixos), "aprovada": validacao["aprovada"],
                      "nao_reproduzido": construtor.get("nao_reproduzido", [])})
    return _relatorio(pasta, dados, rfa, historico, validacao, aprovada=validacao["aprovada"],
                      lacunas=final["lacunas"], fixos=fixos)


def _relatorio(pasta, dados, rfa, historico, validacao, aprovada, lacunas=(), fixos=None):
    relatorio = {
        "familia": dados["nome"], "aprovada": aprovada, "rfa": rfa,
        "parametros_fixados": [{"parametro": n, "valor": v, "motivo": "PARAMETRO_FIXADO: tipo de teste reprovou"}
                               for n, v in sorted((fixos or {}).items())],
        "lacunas": list(lacunas), "historico": historico,
        "ultima_validacao": {"tipos": [{k: t.get(k) for k in ("tipo", "veredito", "detalhe")}
                                       for t in validacao["tipos"]],
                             "divergencias_de_parametro": validacao["divergencias_de_parametro"]},
    }
    with open(os.path.join(pasta, "relatorio.json"), "w", encoding="utf-8") as arquivo:
        json.dump(relatorio, arquivo, ensure_ascii=False, indent=2)
    return relatorio

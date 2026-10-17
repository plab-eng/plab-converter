"""Conexões montadas direto da tabela por bitola da ficha (G5).

Cada produto tem um tradutor `linha da tabela -> intenção`. Quando a geometria
não tem caminho paramétrico provado (ramal inclinado: a cota de raio só foi
provada em esboço horizontal), sai uma família ESTÁTICA por DN, e isso fica
nas `lacunas_aceitas` da intenção.
"""

import math

from . import intencao as intencao_mod


def _dn(linha):
    return float(linha["bitola"][2:])


def juncao_45(linha, imagem, ficha):
    """Junção simples 45° (Tigre FTC000021 p.18; legenda pelo desenho enviado pelo José).

    A altura total, B/E = DN de baixo e de cima, C = da borda do corpo até a
    ponta do ramal (horizontal), D e F = profundidades das bolsas de cima e de baixo.
    """
    dn = _dn(linha)
    a, c, d = linha["A"], linha["C"], linha["D"]
    r = dn / 2
    seno = coss = math.sqrt(0.5)
    # Ponta do ramal: a borda mais à direita do disco fica a C da borda esquerda do corpo.
    comprimento_ramal = (c - r - r * coss) / seno
    z_ponta = a - d                      # adotado: ponta do ramal no início da bolsa de cima
    z_nasce = z_ponta - comprimento_ramal * coss
    if comprimento_ramal <= r or z_nasce <= 0:
        raise ValueError(f"{linha['bitola']}: medidas não fecham a geometria (ramal {comprimento_ramal:.1f})")
    dados = {
        "versao_intencao": "0.1", "modo": "estatico", "categoria": "Pipe Fittings", "tipo_de_peca": "Wye",
        "nome": f"PLAB_HID_Juncao_45_Esgoto_SN_{linha['bitola']}",
        "entradas": {"imagem": imagem, "ficha": ficha, "preenchido_por": "ficha"},
        "parametros": [],
        "componentes": [
            {"id": "corpo", "padrao": "cilindro", "subcategoria": "Conexao",
             "args": {"diametro": f"{dn:g}", "altura": f"{a:g}"}},
            {"id": "ramal", "padrao": "revolucao", "subcategoria": "Conexao",
             "args": {"eixo": "xz", "angulo": 45, "centro": [0.0, 0.0, round(z_nasce, 3)],
                      "perfil": [[0.0, 0.0], [r, 0.0], [r, round(comprimento_ramal, 3)],
                                 [0.0, round(comprimento_ramal, 3)]]}}],
        "conectores": [
            {"componente": "corpo", "face": "base", "diametro": f"{dn:g}", "sistema": "Fitting", "ligado_a": 1},
            {"componente": "corpo", "face": "topo", "diametro": f"{dn:g}", "sistema": "Fitting", "ligado_a": 0},
            {"componente": "ramal", "face": "fim", "diametro": f"{dn:g}", "sistema": "Fitting"}],
        "tipos": [{"nome": linha["bitola"], "valores": {}}],
        "perguntas": [{"id": "tabela", "pergunta": "medidas da ficha", "opcoes": None, "padrao": None,
                       "por_que": f"p.{linha['pagina']}: {linha['texto']}", "resposta": linha["texto"],
                       "origem": "ficha"}],
        "lacunas_aceitas": [
            "estática: uma família por DN (cota de raio em esboço inclinado não provada)",
            "diâmetro externo do corpo e do ramal adotado = DN (a ficha não traz)",
            "ponta do ramal adotada no início da bolsa de cima (z = A - D); a ficha não dá a altura do ramal",
            "corpo maciço, sem furo e sem o degrau das bolsas (D e F não viram geometria)"],
    }
    return intencao_mod.validar(dados)


GERADORES = {"Junção Simples": juncao_45}


def intencoes_do_produto(extracao, produto, imagem, ficha):
    alvo = next((p for p in extracao.get("produtos", []) if p["nome"] == produto), None)
    if alvo is None:
        raise ValueError(f"produto {produto!r} não está na extração")
    if produto not in GERADORES:
        raise ValueError(f"sem gerador para {produto!r}; disponíveis: {sorted(GERADORES)}")
    saida, problemas = [], []
    for linha in alvo["tabelas"][0]["linhas"]:
        if "problema" in linha:
            problemas.append(f"{linha['bitola']}: {linha['problema']}")
            continue
        try:
            saida.append(GERADORES[produto](linha, imagem, ficha))
        except ValueError as erro:
            problemas.append(str(erro))
    return saida, problemas

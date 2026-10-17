import copy
import json
import math
import os

import pytest

from gerador import compilador, intencao

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exemplo(nome):
    return intencao.carregar(os.path.join(RAIZ, "exemplos", f"{nome}.json"))


def test_deterministico():
    a = json.dumps(compilador.compilar(_exemplo("mesa_4_pes")), sort_keys=True)
    b = json.dumps(compilador.compilar(_exemplo("mesa_4_pes")), sort_keys=True)
    assert a == b


def test_caixa_centrada_usa_meia_medida_sem_eq():
    spec = compilador.compilar(_exemplo("mesa_4_pes"))
    derivados = {p["nome"]: p["formula"] for p in spec["parametros"] if p["formula"]}
    assert derivados["GER_tampo_meia_x"] == "(Largura) / 2"
    cotas_meia = [c for c in spec["cotas"] if c["rotulo"] == "GER_tampo_meia_x"]
    assert [c["referencias"][0]["nome"] for c in cotas_meia] == ["Center (Left/Right)"] * 2


def test_cadeia_fora_do_centro_ancora_no_plano_proximo():
    spec = compilador.compilar(_exemplo("mesa_4_pes"))
    nomes = [p["nome"] for p in spec["planos_de_referencia"]]
    # o pé (1,1) fica no canto -x: o plano próximo do centro (Dir) nasce antes do distante (Esq).
    assert nomes.index("RFADG_pe_1_1_Dir") < nomes.index("RFADG_pe_1_1_Esq")
    cota = next(c for c in spec["cotas"] if c["rotulo"] == "Lado_Pe"
                and c["referencias"][0]["nome"] == "RFADG_pe_1_1_Dir")
    assert cota["referencias"][1]["nome"] == "RFADG_pe_1_1_Esq"


def test_assinatura_da_mesa():
    spec = compilador.compilar(_exemplo("mesa_4_pes"))
    m = spec["medicoes"]["1600x900"]
    assert m["extensao_mm"] == [1600.0, 900.0, 750.0]
    volume = 1600 * 900 * 30 + 4 * 50 * 50 * 720
    assert m["volume_mm3"] == pytest.approx(volume)


def test_tipos_de_teste():
    spec = compilador.compilar(_exemplo("mesa_4_pes"))
    teste = spec["gerador"]["tipos_de_teste"]
    assert len(teste) == 2 + 2 * 6
    sem = compilador.compilar(_exemplo("mesa_4_pes"), com_tipos_de_teste=False)
    assert sem["gerador"]["tipos_de_teste"] == []
    assert [t["nome"] for t in sem["tipos"]] == ["1200x800", "1600x900"]


def test_valores_dos_derivados_no_tipo():
    spec = compilador.compilar(_exemplo("mesa_4_pes"), com_tipos_de_teste=False)
    valores = spec["tipos"][0]["valores"]
    assert valores["GER_tampo_meia_x"] == 600.0
    assert valores["GER_pe_1_1_afast_x"] == pytest.approx(1200 / 2 - 40 - 50)


def test_cilindro_emite_cota_radial_e_schema_020():
    spec = compilador.compilar(_exemplo("mesa_redonda"))
    assert spec["versao_schema"] == "0.2.0"
    radiais = [c for c in spec["cotas"] if c["forma"] == "Radial"]
    assert [c["rotulo"] for c in radiais] == ["GER_tampo_raio", "GER_coluna_raio", "GER_base_raio"]
    m = spec["medicoes"]["D1200"]
    assert m["extensao_mm"][0] == 1200.0
    volume = (math.pi * 600 ** 2 * 30 + math.pi * 50 ** 2 * 700 + math.pi * 250 ** 2 * 20)
    assert m["volume_mm3"] == pytest.approx(volume)


def test_caixa_pura_continua_no_schema_010():
    assert compilador.compilar(_exemplo("mesa_4_pes"))["versao_schema"] == "0.1.0"


def test_viabilidade_recusa_pe_que_cruza_o_centro():
    dados = _exemplo("mesa_4_pes")
    for p in dados["parametros"]:
        if p["nome"] == "Recuo_Pe":
            p["faixa"] = [0, 700]
    with pytest.raises(compilador.CompilacaoRecusada, match="Recuo_Pe_max"):
        compilador.compilar(dados)


def test_fixar_parametro_tira_da_geometria():
    spec = compilador.compilar(_exemplo("mesa_4_pes"), fixos={"Recuo_Pe": 40})
    assert not any(n.startswith("_t_Recuo_Pe") for n in spec["gerador"]["tipos_de_teste"])
    formulas = [p["formula"] for p in spec["parametros"] if p["formula"]]
    assert not any("Recuo_Pe" in f for f in formulas)


def test_intencao_recusa_chave_desconhecida_e_sem_imagem():
    dados = json.load(open(os.path.join(RAIZ, "exemplos", "mesa_4_pes.json"), encoding="utf-8"))
    dados["componentes"][0]["cor"] = "azul"
    dados["entradas"]["imagem"] = None
    with pytest.raises(intencao.IntencaoRecusada) as erro:
        intencao.validar(copy.deepcopy(dados))
    texto = str(erro.value)
    assert "'cor'" in texto and "imagem" in texto


def test_intencao_recusa_pergunta_aberta():
    dados = json.load(open(os.path.join(RAIZ, "exemplos", "mesa_4_pes.json"), encoding="utf-8"))
    dados["perguntas"] = [{"id": "recuo", "pergunta": "?", "opcoes": ["a"], "padrao": "a", "por_que": "x"}]
    with pytest.raises(intencao.IntencaoRecusada, match="sem resposta"):
        intencao.validar(dados)


def test_array_retangular_vira_quatro_pes_visiveis():
    spec = compilador.compilar(_exemplo("mesa_4_pes"), com_tipos_de_teste=False)
    pes = [f for f in spec["formas"] if f["componente"].startswith("pe_")]
    assert [f["componente"] for f in pes] == ["pe_1_1", "pe_1_2", "pe_2_1", "pe_2_2"]
    assert all("Visible" not in f["associacoes"] for f in pes)
    assert all(f["subcategoria"] == "Pes" for f in pes)


def test_array_linear_liga_copias_pela_visibilidade():
    spec = compilador.compilar(_exemplo("estante"), com_tipos_de_teste=False)
    formulas = {p["nome"]: p for p in spec["parametros"] if p["formula"]}
    vis = formulas["GER_prateleira_4_vis"]
    assert vis["formula"] == "N_Prateleiras > 3"
    assert vis["tipo_de_dado"].startswith("autodesk.spec:spec.bool")
    tipos = {t["nome"]: t["valores"] for t in spec["tipos"]}
    assert tipos["900x1800 3P"]["GER_prateleira_3_vis"] == 1
    assert tipos["900x1800 3P"]["GER_prateleira_4_vis"] == 0
    forma = next(f for f in spec["formas"] if f["componente"] == "prateleira_4")
    assert forma["associacoes"]["Visible"]["parametro_de_familia"] == "GER_prateleira_4_vis"


def test_copia_oculta_fica_fora_da_assinatura():
    spec = compilador.compilar(_exemplo("estante"), com_tipos_de_teste=False)
    e, l, p, a, n = 18, 900, 350, 1800, 3
    corpo = 2 * e * p * a + 2 * (l - 2 * e) * p * e
    prateleiras = n * (l - 2 * e) * (p - 20) * e
    assert spec["medicoes"]["900x1800 3P"]["volume_mm3"] == pytest.approx(corpo + prateleiras)


def test_peca_que_cruza_o_centro_tem_cota_de_cada_lado():
    spec = compilador.compilar(_exemplo("estante"), com_tipos_de_teste=False)
    formulas = {p["nome"]: p["formula"] for p in spec["parametros"] if p["formula"]}
    assert formulas["GER_prateleira_1_lado_Frente"] == "(Profundidade - 20) / 2 - (10)"
    assert formulas["GER_prateleira_1_lado_Tras"] == "(Profundidade - 20) / 2 + (10)"


def test_tamanho_constante_vira_parametro_de_formula():
    # Sem rótulo, o plano distante ficaria solto e a face não acompanharia.
    spec = compilador.compilar(_exemplo("cadeira"), com_tipos_de_teste=False)
    formulas = {p["nome"]: p["formula"] for p in spec["parametros"] if p["formula"]}
    assert formulas["GER_encosto_tam_y"] == "30"


def test_laco_de_desfazer_fixa_o_culpado(monkeypatch, tmp_path):
    from gerador import orquestrar
    chamadas = []

    def falso(spec, pasta, rotulo, ano):
        chamadas.append((rotulo, dict(spec["gerador"]["fixos"])))
        reprovado = rotulo == "teste_v0"
        tipos = [{"tipo": t, "veredito": "VOLUME_DIVERGE" if reprovado and t == "_t_Recuo_Pe_max" else "REPRODUZ",
                  "detalhe": None} for t in spec["medicoes"]]
        return str(tmp_path / f"{rotulo}.rfa"), {"nao_reproduzido": []}, {
            "aprovada": not reprovado, "tipos": tipos, "divergencias_de_parametro": []}

    monkeypatch.setattr(orquestrar, "construir_e_validar", falso)
    relatorio = orquestrar.gerar(os.path.join(RAIZ, "exemplos", "mesa_4_pes.json"), pasta=str(tmp_path))
    assert [c[0] for c in chamadas] == ["teste_v0", "teste_v1", "PLAB_MOB_Mesa_Retangular"]
    assert chamadas[1][1] == {"Recuo_Pe": 40}
    assert relatorio["aprovada"] is True
    assert relatorio["parametros_fixados"][0]["parametro"] == "Recuo_Pe"


def test_laco_para_quando_tipo_real_reprova(monkeypatch, tmp_path):
    from gerador import orquestrar

    def falso(spec, pasta, rotulo, ano):
        tipos = [{"tipo": t, "veredito": "EXTENSAO_DIVERGE" if t == "1200x800" else "REPRODUZ", "detalhe": None}
                 for t in spec["medicoes"]]
        return "x.rfa", {"nao_reproduzido": []}, {"aprovada": False, "tipos": tipos, "divergencias_de_parametro": []}

    monkeypatch.setattr(orquestrar, "construir_e_validar", falso)
    relatorio = orquestrar.gerar(os.path.join(RAIZ, "exemplos", "mesa_4_pes.json"), pasta=str(tmp_path))
    assert relatorio["aprovada"] is False and relatorio["rfa"] is None
    assert len(relatorio["historico"]) == 1

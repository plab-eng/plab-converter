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
    # pé 1 fica no canto -x: o plano próximo do centro (Dir) nasce antes do distante (Esq).
    assert nomes.index("RFADG_pe1_Dir") < nomes.index("RFADG_pe1_Esq")
    cota = next(c for c in spec["cotas"] if c["rotulo"] == "Lado_Pe"
                and c["referencias"][0]["nome"] == "RFADG_pe1_Dir")
    assert cota["referencias"][1]["nome"] == "RFADG_pe1_Esq"


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
    assert valores["GER_pe1_afast_x"] == pytest.approx(1200 / 2 - 40 - 50)


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

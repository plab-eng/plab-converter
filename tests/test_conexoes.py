"""G5: luva simples da Tigre FTC000021 (trecho real da p.21) com conectores."""

from gerador import compilador, fichas, modelos

LUVA = ["Luva Simples\nPeso unit\nCódigo Descrição do produto UR EAN unitário EAN embalagem\n(gramas)\n"
        "11723 LUVA SIMP ESG SN DN40 CB 25 16,0 7891960130356 7891960708005\n"
        "BITOLA A B C D E\nDN40 37 45 18 18 DN40\nDN50 62,5 65 20,5 39 DN50\nDN100 83,5 116,3 30,5 50 DN100\n"
        "* medidas aproximadas em milímetros (mm)."]


def _luva():
    traducao = fichas.para_luva_simples(fichas.extrair(LUVA))
    return modelos.montar("luva_simples", "PLAB_HID_Luva_Simples_Esgoto_SN", "foto.png", ficha="tigre.pdf",
                          evidencias=traducao["evidencias"], tipos_da_ficha=traducao["tipos"]), traducao


def test_tabela_vira_um_tipo_por_dn():
    dados, traducao = _luva()
    assert [t["nome"] for t in dados["tipos"]] == ["DN40", "DN50", "DN100"]
    assert dados["tipos"][1]["valores"] == {"DN": 50.0, "Comprimento": 62.5, "Diametro_Bolsa": 65.0,
                                            "Bolsa_Inferior": 20.5, "Bolsa_Superior": 39.0}
    assert "DN50 62,5" in traducao["evidencias"]["DN50"]


def test_conectores_ligados_e_assinatura_por_tipo():
    dados, _ = _luva()
    spec = compilador.compilar(dados, com_tipos_de_teste=False)
    assert spec["versao_schema"] == "0.3.0"
    assert spec["identidade"]["part_type"] == "Union" and spec["identidade"]["categoria_id"] == -2008049
    assert [(c["diametro_rotulo"], c["ligado_a"]) for c in spec["conectores"]] == [("DN", 1), ("DN", 0)]
    esperados = spec["medicoes"]["DN100"]["conectores"]
    assert esperados == [{"origem_mm": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, -1.0], "diametro_mm": 100.0},
                         {"origem_mm": [0.0, 0.0, 83.5], "normal": [0.0, 0.0, 1.0], "diametro_mm": 100.0}]


def test_juncao_45_estatica_fecha_a_tabela():
    import math
    from gerador import conexoes
    from tests.test_fichas import TIGRE
    intencoes, problemas = conexoes.intencoes_do_produto(fichas.extrair(TIGRE), "Junção Simples", "f.png", "t.pdf")
    assert problemas == [] and [d["tipos"][0]["nome"] for d in intencoes] == ["DN40", "DN100"]
    spec = compilador.compilar(intencoes[1], com_tipos_de_teste=False)
    assert spec["identidade"]["part_type"] == "Wye"
    m = spec["medicoes"]["DN100"]
    assert [round(v, 1) for v in m["extensao_mm"]] == [219.1, 100.0, 255.0]   # C, DN, A
    ramal = m["conectores"][2]
    assert ramal["normal"] == [math.sqrt(0.5), 0.0, math.sqrt(0.5)] and ramal["diametro_mm"] == 100.0
    assert [c["ligado_a"] for c in spec["conectores"]] == [1, 0, None]

import json

from gerador import regua


def _validacao(tmp_path, extensao):
    caminho = tmp_path / "v.json"
    caminho.write_text(json.dumps({"tipos": [{"tipo": "Padrao", "medido": {"extensao_mm": extensao}}]}),
                       encoding="utf-8")
    return str(caminho)


def test_aprova_dentro_de_4_por_cento(tmp_path):
    r = regua.comparar(_validacao(tmp_path, [600, 303, 1600]), {"largura": 600, "profundidade": 300, "altura": 1600})
    assert r["aprovado"] and r["eixos"]["profundidade"]["acerto"] == 0.99


def test_reprova_acima_de_4_por_cento(tmp_path):
    r = regua.comparar(_validacao(tmp_path, [600, 315, 1600]), {"largura": 600, "profundidade": 300, "altura": 1600})
    assert not r["aprovado"] and not r["eixos"]["profundidade"]["passa"]

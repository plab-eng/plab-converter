import pytest
from PIL import Image

from gerador import compilador, modelos, previa


def test_lista_os_modelos():
    nomes = [m["modelo"] for m in modelos.listar()]
    assert nomes == ["armario", "bancada", "cadeira", "estante", "estante_portas_inferiores",
                     "mesa_4_pes", "mesa_redonda"]


def test_perguntas_no_formato_das_receitas():
    perguntas = modelos.perguntas("estante", imagem="foto.jpg")
    prateleiras = next(p for p in perguntas if p["id"] == "prateleiras")
    assert set(prateleiras) == {"id", "pergunta", "padrao", "por_que", "opcoes", "imagem"}
    assert prateleiras["opcoes"] == [1, 2, 3, 4, 5]


def test_montar_com_respostas_e_padrao_registrado():
    dados = modelos.montar("estante", "PLAB_MOB_Estante_Sala", "foto.jpg", {"largura": 1200, "prateleiras": 4})
    valores = {p["nome"]: p for p in dados["parametros"]}
    assert valores["Largura"]["padrao"] == 1200 and valores["Largura"]["origem"] == "usuario"
    assert valores["Altura"]["padrao"] == 1800 and valores["Altura"]["origem"] == "regra"
    registro = {p["id"]: p for p in dados["perguntas"]}
    assert registro["altura"]["aceitou_padrao"] is True
    assert registro["prateleiras"]["resposta"] == 4
    spec = compilador.compilar(dados, com_tipos_de_teste=False)
    assert spec["medicoes"]["Padrao"]["extensao_mm"][0] == 1200.0


def test_montar_recusa_resposta_fora_da_faixa_e_pergunta_inexistente():
    with pytest.raises(modelos.RespostaInvalida, match="fora da faixa"):
        modelos.montar("estante", "X", "foto.jpg", {"largura": 5000})
    with pytest.raises(modelos.RespostaInvalida, match="cor"):
        modelos.montar("estante", "X", "foto.jpg", {"cor": 1})


def test_previa_gera_png(tmp_path):
    dados = modelos.montar("cadeira", "PLAB_MOB_Cadeira", "foto.jpg")
    spec = compilador.compilar(dados, com_tipos_de_teste=False)
    assert len(spec["gerador"]["primitivas"]) == 6
    destino = previa.desenhar(spec["gerador"]["primitivas"], str(tmp_path / "p.png"), lado=256)
    assert Image.open(destino).size == (256, 256)


def test_previa_omite_copia_oculta():
    dados = modelos.montar("estante", "X", "foto.jpg", {"prateleiras": 2})
    spec = compilador.compilar(dados, com_tipos_de_teste=False)
    # 4 peças do corpo + 2 prateleiras visíveis (de 5 possíveis)
    assert len(spec["gerador"]["primitivas"]) == 6

import pytest

from gerador.expressao import ExpressaoInvalida, avaliar, eh_constante, nomes


def test_avalia_aritmetica_com_parametros():
    assert avaliar("Largura / 2 - Recuo", {"Largura": 1200, "Recuo": 40}) == 560.0


def test_lista_nomes_sem_repetir():
    assert nomes("A + B * A - (C / 2)") == ["A", "B", "C"]


def test_constante():
    assert eh_constante("2 * 15")
    assert not eh_constante("Altura - 30")


@pytest.mark.parametrize("texto", [
    "abs(Largura)", "Largura >= 2", "Largura.x", "Largura ** 2", "", "True", "'a'",
])
def test_recusa_fora_do_subconjunto(texto):
    with pytest.raises(ExpressaoInvalida):
        nomes(texto)


def test_parametro_desconhecido():
    with pytest.raises(ExpressaoInvalida, match="Profundidade"):
        avaliar("Largura + Profundidade", {"Largura": 1})


def test_divisao_por_zero():
    with pytest.raises(ExpressaoInvalida, match="zero"):
        avaliar("Largura / N", {"Largura": 1, "N": 0})

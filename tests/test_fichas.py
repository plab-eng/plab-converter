"""Fichas: trechos do texto real dos três PDFs recebidos em 17/10/2026."""

from gerador import compilador, fichas, modelos

TIGRE = [
    "Página 17 de 28\nJunção Simples\nPeso unit\nCódigo Descrição do produto UR EAN unitário EAN embalagem\n(gramas)\n"
    "11702 JUNCAO SIMP ESG SN DN40 CB 25 47,5 7891960130349 7891960707756\n"
    "11397 JUNCAO SIMP ESG SN DN150 1 1.188,0 7897795001441 -",
    "Página 18 de 28\nBITOLA A B C D E F\nDN40 97,5 DN40 86,1 18 DN40 20,3\nDN100 255 DN100 219,1 50 DN100 58,3\n"
    "* medidas aproximadas em milímetros (mm).\nJunção de Redução\nPeso unit",
]

ARMARIO = [
    "ARMÁRIO ESTANTE PARA LIVROS 2 PORTAS - 60x210x42CM\n"
    "Descrição Básica: Armário de madeira – M.D.F., com duas portas inferiores, revestido\n"
    "prateleiras, medindo 60x210x42cm ( LxAxP). Ver desenho e foto.\n"
    "1. TAMPO SUPERIOR\nb) espessura mínima de 25mm;\n3. LATERAIS DO BALCÃO\nb) espessura mínima de 18mm;",
    "6. PRATELEIRAS DA ESTANTE\na) uma coluna contendo três prateleiras;",
]

ESTANTE = ["", "1 144-56 MONTANTEDIREITO1790X65X18(QUADRO)\n5 193-10 LATERAL1790X380X17 163-0 28\n"
               "7 217-16 PRATELEIRA745X375X17\n8 255-4 PORTA614X322X18\n10 226-6 RODAPELATERAL398X70X18\n"
               "11 226-5 RODAPE816X70X18\n12 213-5 MOLDURASUPERIOR816X35X17"]


def test_detecta_os_tres_formatos():
    assert fichas.detectar(TIGRE) == "tabela_por_bitola"
    assert fichas.detectar(ARMARIO) == "especificacao_texto"
    assert fichas.detectar(ESTANTE) == "lista_de_pecas"


def test_tabela_atravessa_a_pagina_e_fica_com_o_produto_certo():
    x = fichas.extrair(TIGRE)
    juncao = x["produtos"][0]
    assert juncao["nome"] == "Junção Simples"
    assert [c["codigo"] for c in juncao["codigos"]] == ["11702", "11397"]
    linha = juncao["tabelas"][0]["linhas"][0]
    assert (linha["bitola"], linha["A"], linha["B"], linha["C"], linha["F"]) == ("DN40", 97.5, "DN40", 86.1, 20.3)
    assert linha["pagina"] == 2


def test_especificacao_texto_vira_respostas_com_evidencia():
    traducao = fichas.para_estante_portas_inferiores(fichas.extrair(ARMARIO))
    assert traducao["respostas"] == {"largura": 600.0, "altura": 2100.0, "profundidade": 420.0,
                                     "prateleiras": 3, "espessura": 18.0}
    assert "LxAxP" in traducao["evidencias"]["largura"]
    assert [p["id"] for p in traducao["perguntas"]] == ["altura_portas"]


def test_lista_de_pecas_deixa_o_ambiguo_como_pergunta():
    traducao = fichas.para_estante_portas_inferiores(fichas.extrair(ESTANTE))
    assert traducao["respostas"] == {"largura": 816.0, "profundidade": 398.0, "espessura": 17.0}
    perguntas = {p["id"]: p for p in traducao["perguntas"]}
    assert set(perguntas) == {"altura", "altura_portas", "prateleiras"}
    assert perguntas["altura"]["opcoes"] == [1790.0, 1825.0]


def test_ficha_monta_intencao_com_origem_e_evidencia():
    traducao = fichas.para_estante_portas_inferiores(fichas.extrair(ARMARIO))
    dados = modelos.montar("estante_portas_inferiores", "PLAB_MOB_Armario_Livros", "foto.png",
                           respostas={"altura_portas": 850}, ficha="armario.pdf",
                           respostas_da_ficha=traducao["respostas"], evidencias=traducao["evidencias"])
    parametros = {p["nome"]: p for p in dados["parametros"]}
    assert parametros["Largura"]["origem"] == "ficha" and parametros["Altura_Portas"]["origem"] == "usuario"
    registro = {p["id"]: p for p in dados["perguntas"]}
    assert "evidencia" in registro["largura"] and registro["altura_portas"]["origem"] == "usuario"
    assert dados["entradas"]["ficha"] == "armario.pdf"
    spec = compilador.compilar(dados, com_tipos_de_teste=False)
    assert spec["medicoes"]["Padrao"]["extensao_mm"][2] == 2100.0


def test_documento_sem_regra_nao_inventa():
    assert fichas.extrair(["texto qualquer sem medidas"])["formato"] is None

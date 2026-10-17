"""Expressões da intenção: nomes de parâmetro, números, + - * / e parênteses.

É o subconjunto que vale nos dois lados: o compilador avalia em Python para
calcular posições e a assinatura esperada, e a mesma string vai como fórmula
para o Revit. Qualquer outra coisa (chamada, comparação, atributo) é recusada
com o trecho culpado — nada é ignorado em silêncio.
"""

import ast
import re

_RE_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_OPERADORES = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}


class ExpressaoInvalida(ValueError):
    pass


def _arvore(texto):
    if not isinstance(texto, str) or not texto.strip():
        raise ExpressaoInvalida(f"expressão vazia ou não-texto: {texto!r}")
    try:
        arvore = ast.parse(texto.strip(), mode="eval")
    except SyntaxError as erro:
        raise ExpressaoInvalida(f"sintaxe inválida em {texto!r}: {erro.msg}") from None
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load,
                           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)):
            continue
        if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)) \
                and not isinstance(no.value, bool):
            continue
        raise ExpressaoInvalida(
            f"{texto!r}: só nomes, números, + - * / e parênteses ({type(no).__name__})")
    return arvore


def nomes(texto):
    """Nomes de parâmetro usados na expressão, na ordem em que aparecem."""
    # ast.walk percorre em largura; a ordem do texto vem da coluna.
    encontrados = [no for no in ast.walk(_arvore(texto)) if isinstance(no, ast.Name)]
    vistos = []
    for no in sorted(encontrados, key=lambda n: n.col_offset):
        if no.id not in vistos:
            vistos.append(no.id)
    return vistos


def avaliar(texto, valores):
    """Valor numérico da expressão com `valores` (nome -> número)."""
    def calc(no):
        if isinstance(no, ast.Expression):
            return calc(no.body)
        if isinstance(no, ast.Constant):
            return float(no.value)
        if isinstance(no, ast.Name):
            if no.id not in valores:
                raise ExpressaoInvalida(f"parâmetro desconhecido {no.id!r} em {texto!r}")
            return float(valores[no.id])
        if isinstance(no, ast.UnaryOp):
            valor = calc(no.operand)
            return -valor if isinstance(no.op, ast.USub) else valor
        if isinstance(no, ast.BinOp):
            direita = calc(no.right)
            if isinstance(no.op, ast.Div) and direita == 0:
                raise ExpressaoInvalida(f"divisão por zero em {texto!r}")
            return _OPERADORES[type(no.op)](calc(no.left), direita)
        raise ExpressaoInvalida(f"nó inesperado em {texto!r}")
    return calc(_arvore(texto))


def substituir(texto, valores):
    """Troca os nomes de `valores` pelo número (usado para fixar parâmetro)."""
    class _Troca(ast.NodeTransformer):
        def visit_Name(self, no):
            if no.id in valores:
                return ast.copy_location(ast.Constant(float(valores[no.id])), no)
            return no
    arvore = _Troca().visit(_arvore(texto))
    return ast.unparse(ast.fix_missing_locations(arvore))


def eh_nome(texto):
    return isinstance(texto, str) and bool(_RE_NOME.match(texto.strip()))


def eh_constante(texto):
    """True quando a expressão não usa parâmetro nenhum (ex.: "0", "2 * 15")."""
    return not nomes(texto)


def validar_nome(nome):
    if not eh_nome(nome):
        raise ExpressaoInvalida(f"nome de parâmetro inválido: {nome!r} (use letras, dígitos e _)")
    return nome

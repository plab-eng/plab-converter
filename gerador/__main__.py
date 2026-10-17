"""python -m gerador compilar <intencao.json> [--sem-teste] [--saida spec.json]
python -m gerador gerar <intencao.json> [--revit 2024]
python -m gerador previa <intencao.json> --saida previa.png
python -m gerador modelos
python -m gerador perguntas <modelo> [--saida perguntas.json]
python -m gerador montar <modelo> --nome <familia> --imagem <arquivo> [--respostas r.json]
                         [--preenchido-por usuario|regra|ia|ficha] --saida intencao.json
"""

import argparse
import json
import sys

from . import compilador, intencao, modelos, orquestrar, previa


def _escrever(texto, saida):
    if saida:
        with open(saida, "w", encoding="utf-8") as arquivo:
            arquivo.write(texto)
    else:
        print(texto)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gerador")
    sub = parser.add_subparsers(dest="comando", required=True)
    p_comp = sub.add_parser("compilar", help="intenção -> FamilySpec (sem Revit)")
    p_comp.add_argument("intencao")
    p_comp.add_argument("--sem-teste", action="store_true")
    p_comp.add_argument("--saida")
    p_gerar = sub.add_parser("gerar", help="intenção -> .rfa validado (usa o Revit)")
    p_gerar.add_argument("intencao")
    p_gerar.add_argument("--revit", type=int, default=2024)
    p_previa = sub.add_parser("previa", help="intenção -> PNG isométrico (sem Revit)")
    p_previa.add_argument("intencao")
    p_previa.add_argument("--saida", required=True)
    sub.add_parser("modelos", help="lista os modelos prontos")
    p_perg = sub.add_parser("perguntas", help="perguntas de um modelo, no formato das receitas")
    p_perg.add_argument("modelo")
    p_perg.add_argument("--saida")
    p_montar = sub.add_parser("montar", help="modelo + respostas -> intenção")
    p_montar.add_argument("modelo")
    p_montar.add_argument("--nome", required=True)
    p_montar.add_argument("--imagem", required=True)
    p_montar.add_argument("--respostas")
    p_montar.add_argument("--preenchido-por", default="usuario", choices=intencao.PREENCHIDO_POR)
    p_montar.add_argument("--saida", required=True)
    args = parser.parse_args(argv)

    try:
        if args.comando == "compilar":
            spec = compilador.compilar(intencao.carregar(args.intencao),
                                       com_tipos_de_teste=not args.sem_teste)
            texto = json.dumps(spec, ensure_ascii=True, indent=1, sort_keys=True)
            if args.saida:
                with open(args.saida, "w", encoding="ascii") as arquivo:
                    arquivo.write(texto)
            else:
                print(texto)
            return 0
        if args.comando == "previa":
            dados = intencao.carregar(args.intencao)
            spec = compilador.compilar(dados, com_tipos_de_teste=False)
            previa.desenhar(spec["gerador"]["primitivas"], args.saida,
                            legenda=f"previa gerada - {dados['nome']} ({spec['tipo_corrente']})")
            print(args.saida)
            return 0
        if args.comando == "modelos":
            for item in modelos.listar():
                print(f"{item['modelo']:<14} {item['descricao']}")
            return 0
        if args.comando == "perguntas":
            _escrever(json.dumps(modelos.perguntas(args.modelo), ensure_ascii=False, indent=2), args.saida)
            return 0
        if args.comando == "montar":
            respostas = {}
            if args.respostas:
                with open(args.respostas, encoding="utf-8") as arquivo:
                    respostas = json.load(arquivo)
            dados = modelos.montar(args.modelo, args.nome, args.imagem, respostas, args.preenchido_por)
            _escrever(json.dumps(dados, ensure_ascii=False, indent=2), args.saida)
            return 0
        relatorio = orquestrar.gerar(args.intencao, ano=args.revit)
        print(json.dumps({k: relatorio[k] for k in ("familia", "aprovada", "rfa", "parametros_fixados")},
                         ensure_ascii=False, indent=2))
        return 0 if relatorio["aprovada"] else 1
    except (intencao.IntencaoRecusada, compilador.CompilacaoRecusada, modelos.RespostaInvalida) as erro:
        print(erro, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""python -m gerador compilar <intencao.json> [--sem-teste] [--saida spec.json]
python -m gerador gerar <intencao.json> [--revit 2024]
"""

import argparse
import json
import sys

from . import compilador, intencao, orquestrar


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
        relatorio = orquestrar.gerar(args.intencao, ano=args.revit)
        print(json.dumps({k: relatorio[k] for k in ("familia", "aprovada", "rfa", "parametros_fixados")},
                         ensure_ascii=False, indent=2))
        return 0 if relatorio["aprovada"] else 1
    except (intencao.IntencaoRecusada, compilador.CompilacaoRecusada) as erro:
        print(erro, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Diff de dicionarios entre duas versoes VIZINHAS (Rota B, etapa 3). Python 3.

Uso:
    python -I tools/rvtbin/schema_diff.py schema_2024.json schema_2025.json --json diff_2025_2024.json

Os tags sao ordinais de definicao e mudam de versao para versao, entao tudo e
comparado pelo NOME da classe, com as refs de classe resolvidas para nome.
Saida pensada para o tradutor de um salto N -> N-1:
- classes_so_em_N    : nao existem em N-1 -> entram no mapa de classes (remover/trocar/abortar)
- classes_so_em_N-1  : sumiram em N (raro; registrar)
- alteradas          : mesma classe com versao, base ou campos diferentes
"""
import argparse
import json
import sys


def carregar(caminho):
    classes = json.load(open(caminho, encoding="utf-8"))
    por_tag = {c["tag"]: c["nome"] for c in classes}
    por_nome = {}
    for c in classes:
        por_nome.setdefault(c["nome"], c)        # nome repetido: fica a 1a definicao
    return classes, por_tag, por_nome


def tipo_txt(t, por_tag):
    s = t["especie"]
    if t.get("mod") not in (None, "0x00"):
        s += "/" + t["mod"]
    if "contagem" in t:
        s += "[%d]" % t["contagem"]
    if "interno" in t:
        s += "<" + tipo_txt(t["interno"], por_tag) + ">"
    if t.get("ref"):
        s += ":" + por_tag.get(t["ref"], "?%d" % t["ref"])
    if "ponteiro" in t:
        s += "*"
    return s


def diff(a_path, b_path):
    """a = versao mais NOVA (N), b = versao de DESTINO (N-1)."""
    ca, ta, na = carregar(a_path)
    cb, tb, nb = carregar(b_path)
    so_a = sorted(set(na) - set(nb))
    so_b = sorted(set(nb) - set(na))
    alteradas = []
    for nome in sorted(set(na) & set(nb)):
        x, y = na[nome], nb[nome]
        fx = [(f["nome"], tipo_txt(f["tipo"], ta)) for f in x["campos"]]
        fy = [(f["nome"], tipo_txt(f["tipo"], tb)) for f in y["campos"]]
        base_x = ta.get(x["base"]) if x["base"] else None
        base_y = tb.get(y["base"]) if y["base"] else None
        if fx == fy and x["versao"] == y["versao"] and base_x == base_y:
            continue
        nomes_x = [f[0] for f in fx]
        nomes_y = [f[0] for f in fy]
        dx, dy = dict(fx), dict(fy)
        alteradas.append({
            "classe": nome,
            "versao": [x["versao"], y["versao"]],
            "base": [base_x, base_y] if base_x != base_y else None,
            "campos_so_em_N": [n for n in nomes_x if n not in dy],
            "campos_so_em_N-1": [n for n in nomes_y if n not in dx],
            "tipo_mudou": [[n, dx[n], dy[n]] for n in nomes_x if n in dy and dx[n] != dy[n]],
            "ordem_mudou": [n for n in nomes_x if n in dy] != [n for n in nomes_y if n in dx],
        })
    return {"N": a_path, "N-1": b_path, "classes_N": len(na), "classes_N-1": len(nb),
            "classes_so_em_N": so_a, "classes_so_em_N-1": so_b, "alteradas": alteradas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("novo")
    ap.add_argument("destino")
    ap.add_argument("--json")
    a = ap.parse_args()
    d = diff(a.novo, a.destino)
    alt = d["alteradas"]
    print("classes: %d -> %d | so na nova: %d | so na destino: %d | alteradas: %d" % (
        d["classes_N"], d["classes_N-1"], len(d["classes_so_em_N"]),
        len(d["classes_so_em_N-1"]), len(alt)))
    print("  alteradas: versao mudou %d | campo novo %d | campo sumiu %d | tipo mudou %d | ordem mudou %d" % (
        sum(1 for x in alt if x["versao"][0] != x["versao"][1]),
        sum(1 for x in alt if x["campos_so_em_N"]),
        sum(1 for x in alt if x["campos_so_em_N-1"]),
        sum(1 for x in alt if x["tipo_mudou"]),
        sum(1 for x in alt if x["ordem_mudou"])))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

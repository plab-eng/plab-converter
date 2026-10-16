# -*- coding: utf-8 -*-
"""Decodificador de dados de elemento guiado pelo dicionario (Rota B, etapa 4).

EXPERIMENTAL: cada regra de codificacao abaixo tem a origem anotada
(medido aqui | hipotese). Hipotese nao confirmada levanta ErroDados com o
offset, para a proxima rodada de investigacao.

Uso (trace de um registro):
    python -I tools/rvtbin/dados.py SCHEMA.json PARTICAO.bin OFFSET CLASSE
"""
import json
import struct
import sys

PRIM = {  # especie -> formato struct (medido: u32/u64 no Identifier 2023/2024)
    "bool": "<B", "u16": "<H", "u32": "<I", "i32": "<i", "i32_legado": "<i",
    "f32": "<f", "f64": "<d", "u64": "<Q", "i64?": "<q",
}


class ErroDados(Exception):
    pass


class Decodificador(object):
    def __init__(self, schema_json, dados, trace=False):
        classes = json.load(open(schema_json, encoding="utf-8"))
        self.por_tag = {c["tag"]: c for c in classes}
        self.por_nome = {c["nome"]: c for c in classes}
        self.d = dados
        self.p = 0
        self.trace = trace

    def _ler(self, fmt):
        n = struct.calcsize(fmt)
        if self.p + n > len(self.d):
            raise ErroDados("fim dos dados em 0x%x" % self.p)
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += n
        return v

    def _log(self, nivel, texto):
        if self.trace:
            print("%06x %s%s" % (self.p, "  " * nivel, texto))

    def classe(self, c, nivel=0):
        """Campos da base primeiro (hipotese), depois os proprios, na ordem do dicionario."""
        out = {}
        if c.get("base"):
            out["__base__"] = self.classe(self.por_tag[c["base"]], nivel)
        for f in c["campos"]:
            ini = self.p
            v = self.tipo(f["tipo"], nivel + 1, f["nome"])
            out[f["nome"]] = v
            if self.trace and not isinstance(v, dict):
                self._log(nivel, "%s = %r   [%s]" % (f["nome"], v, self.d[ini:self.p].hex(" ")[:60]))
        return out

    def tipo(self, t, nivel, nome):
        esp = t["especie"]
        mod = int(t["mod"], 16)
        if mod == 0x50:
            # medido (ElementParents.m_deletion, 2023 e 2024): u32 contagem + itens
            n = self._ler("<I")
            if n > 1000000:
                raise ErroDados("container com %d itens: campo %s em 0x%x" % (n, nome, self.p - 4))
            item = dict(t, mod="0x00")
            return [self.tipo(item, nivel, "%s[%d]" % (nome, i)) for i in range(n)]
        if mod & 0xf0 in (0x10, 0x50) or (mod and esp != "classe") or (esp == "classe" and mod not in (0x00, 0x01, 0x02, 0x03)):
            raise ErroDados("modificador %s (especie %s) ainda nao mapeado: campo %s em 0x%x"
                            % (t["mod"], esp, nome, self.p))
        if esp in PRIM:
            return self._ler(PRIM[esp])
        if esp == "classe" and "ponteiro" in t:
            # medido (ElementHeader.m_pBBox/m_parents): u16 tag da classe REAL, ffff = nulo
            tag = self._ler("<H")
            if tag == 0xffff:
                return None
            if tag not in self.por_tag:
                raise ErroDados("ponteiro para tag 0x%x inexistente: campo %s em 0x%x" % (tag, nome, self.p - 2))
            c = self.por_tag[tag]
            self._log(nivel - 1, "%s -> %s (tag 0x%x) {" % (nome, c["nome"], tag))
            return {"__classe__": c["nome"], "valor": self.classe(c, nivel)}
        if esp == "classe":
            c = self.por_tag[t["ref"]]
            self._log(nivel - 1, "%s : %s {" % (nome, c["nome"]))
            return self.classe(c, nivel)
        raise ErroDados("especie %s ainda nao mapeada: campo %s em 0x%x" % (esp, nome, self.p))


def registro(dec, offset, largura_id):
    """Registro da cadeia da particao (medido 2023 u32 / 2024+ u64):
    id ; u32 tamanho ; u16 tag ; corpo ; u32 tamanho (repetido).
    `tamanho` conta do tag ate o fim do corpo. Devolve (id, classe, ini_corpo, fim_corpo)."""
    fmt = "<I" if largura_id == 4 else "<Q"
    eid = struct.unpack_from(fmt, dec.d, offset)[0]
    tam, tag = struct.unpack_from("<IH", dec.d, offset + largura_id)
    ini = offset + largura_id + 6
    fim = offset + largura_id + 4 + tam
    if struct.unpack_from("<I", dec.d, fim)[0] != tam:
        raise ErroDados("trailer nao repete o tamanho no registro em 0x%x" % offset)
    return eid, dec.por_tag[tag], ini, fim


def varrer(schema, particao, largura):
    """Percorre a cadeia de registros da particao e mede a cobertura do decodificador."""
    import collections
    dec = Decodificador(schema, open(particao, "rb").read())
    off, ok, total = 0, 0, 0
    por_classe = collections.Counter()
    falhas = collections.Counter()
    exemplo = {}
    while off + largura + 6 <= len(dec.d):
        try:
            eid, c, ini, fim = registro(dec, off, largura)
        except (ErroDados, KeyError, struct.error):
            break                       # fim da cadeia (o resto nao e registro)
        total += 1
        por_classe[c["nome"]] += 1
        dec.p = ini
        try:
            dec.classe(c)
            if dec.p == fim:
                ok += 1
            else:
                k = "%s: termina em %+d bytes" % (c["nome"], dec.p - fim)
                falhas[k] += 1
                exemplo.setdefault(k, off)
        except (ErroDados, KeyError, struct.error) as e:
            msg = str(e)
            k = c["nome"] + ": " + msg.split(" em 0x")[0].split(": campo")[0] + \
                (" (" + msg.split("campo ")[1].split(" ")[0] + ")" if "campo " in msg else "")
            falhas[k] += 1
            exemplo.setdefault(k, off)
        off = fim + 4
    print("registros na cadeia: %d | decodificados ate o trailer: %d (%.0f%%) | bytes da cadeia: %d de %d" % (
        total, ok, 100.0 * ok / max(total, 1), off, len(dec.d)))
    print("classes mais comuns: %s" % por_classe.most_common(8))
    for k, n in falhas.most_common(15):
        print("  %4d x %s   [ex. registro em 0x%x]" % (n, k, exemplo[k]))


def main():
    if sys.argv[1] == "--varrer":
        return varrer(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    schema, particao, offset, largura = sys.argv[1], sys.argv[2], int(sys.argv[3], 0), int(sys.argv[4])
    dec = Decodificador(schema, open(particao, "rb").read(), trace=True)
    eid, c, ini, fim = registro(dec, offset, largura)
    print("registro id=%d classe=%s corpo 0x%x..0x%x" % (eid, c["nome"], ini, fim))
    dec.p = ini
    try:
        dec.classe(c)
        print("%s: decodificado ate 0x%x, corpo termina em 0x%x" % (
            "OK" if dec.p == fim else "DIVERGE", dec.p, fim))
    except ErroDados as e:
        print("PAROU: %s" % e)
        print("bytes seguintes: %s" % dec.d[dec.p:dec.p + 48].hex(" "))


if __name__ == "__main__":
    main()

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
    "f32": "<f", "f64": "<d", "u64": "<Q",
    # medido (ClassDefinitionRef.m_ref, 3 familias x 2023): TAG de classe u16 —
    # o tag da classe real do elemento (Viewer3d, FamilySymbol, CurveElem...)
    "i64?": "<H",
}
PONTEIRO_NULO = 0
PONTEIRO_NOVO = 0xffffffff


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

    def classe(self, c, nivel=0, adiar=True):
        """Campos da base primeiro, depois os proprios, na ordem do dicionario.
        Medido (ElementHeader, 2023): os CORPOS dos objetos apontados vem DEPOIS
        de todos os campos da classe que os contem, na ordem dos ponteiros."""
        out = {}
        pendentes = []
        anterior = getattr(self, "_pendentes", None)
        self._pendentes = pendentes
        if c.get("base"):
            out["__base__"] = self.classe(self.por_tag[c["base"]], nivel, adiar=False)
        for f in c["campos"]:
            ini = self.p
            v = self.tipo(f["tipo"], nivel + 1, f["nome"])
            out[f["nome"]] = v
            if self.trace and not isinstance(v, dict):
                self._log(nivel, "%s = %r   [%s]" % (f["nome"], v, self.d[ini:self.p].hex(" ")[:60]))
        self._pendentes = anterior
        if not adiar and anterior is not None:
            anterior.extend(pendentes)       # a base escreve junto com a derivada
            return out
        for destino, alvo in pendentes:
            self._log(nivel, "corpo adiado de %s -> %s {" % (destino["campo"], alvo["nome"]))
            destino["valor"] = self.classe(alvo, nivel + 1)
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
        if esp == "guid" and mod == 0:
            # hipotese: 16 bytes crus (MaterialElem.m_guid, Family.m_guid)
            if self.p + 16 > len(self.d):
                raise ErroDados("fim dos dados em 0x%x" % self.p)
            g = self.d[self.p:self.p + 16].hex()
            self.p += 16
            return g
        if esp == "embrulho" and mod == 0:
            # hipotese: embrulho simples = so o tipo interno (LinearDimString.m_refPnts[i])
            return self.tipo(t["interno"], nivel, nome)
        if esp == "string":
            # medido (DimensionStyle.m_equalityText = "EQ", 2023): u32 n caracteres + UTF-16LE
            n = self._ler("<I")
            if n > 100000:
                raise ErroDados("string com %d caracteres: campo %s em 0x%x" % (n, nome, self.p - 4))
            s = self.d[self.p:self.p + 2 * n].decode("utf-16le", "replace")
            self.p += 2 * n
            return s
        if esp == "classe" and mod & 0xf0 == 0x50 and mod & 0x0f in (1, 2, 3):
            # hipotese (corpo de elemento, Element.m_constrInfo 2023): container de PONTEIROS =
            # u32 n + n ponteiros (cada um u32 indice + u16 tag, corpo adiado)
            n = self._ler("<I")
            if n > 1000000:
                raise ErroDados("container de ponteiros com %d itens: campo %s em 0x%x" % (n, nome, self.p - 4))
            item = dict(t, mod="0x%02x" % (mod & 0x0f), ponteiro=mod & 0x0f)
            return [self.tipo(item, nivel, "%s[%d]" % (nome, i)) for i in range(n)]
        if mod == 0x10 and "contagem" in t:
            # medido (Outline.m_minmax = 2 x 3 f64, 2023): array FIXO, contagem vem do dicionario,
            # sem prefixo no dado
            if esp == "embrulho":
                return [self.tipo(t["interno"], nivel, "%s[%d]" % (nome, i)) for i in range(t["contagem"])]
            item = dict(t, mod="0x00")
            item.pop("contagem")
            return [self.tipo(item, nivel, "%s[%d]" % (nome, i)) for i in range(t["contagem"])]
        if mod & 0xf0 in (0x10, 0x50) or (mod and esp != "classe") or (esp == "classe" and mod not in (0x00, 0x01, 0x02, 0x03)):
            raise ErroDados("modificador %s (especie %s) ainda nao mapeado: campo %s em 0x%x"
                            % (t["mod"], esp, nome, self.p))
        if esp in PRIM:
            return self._ler(PRIM[esp])
        if esp == "classe" and "ponteiro" in t:
            # medido (ElementHeader.m_pBBox/m_parents, 3 familias 2023):
            # u32 indice (0 = nulo, sem tag; ffffffff = objeto novo) + u16 tag da classe REAL;
            # o corpo vem adiado (ver classe()).
            idx = self._ler("<I")
            if idx == PONTEIRO_NULO:
                return None
            if idx != PONTEIRO_NOVO:
                # medido (ControlledDocAccess.m_pDoc = 1, corpo de elemento 2023): referencia a
                # objeto ja existente pelo indice; sem tag e sem corpo
                return {"__ref__": idx}
            tag = self._ler("<H")
            if tag not in self.por_tag:
                raise ErroDados("ponteiro para tag 0x%x inexistente: campo %s em 0x%x" % (tag, nome, self.p - 2))
            c = self.por_tag[tag]
            self._log(nivel - 1, "%s -> %s (tag 0x%x), corpo adiado" % (nome, c["nome"], tag))
            destino = {"__classe__": c["nome"], "campo": nome, "valor": None}
            self._pendentes.append((destino, c))
            return destino
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


def fim_da_cadeia_de_headers(dec, largura):
    off = 0
    while True:
        try:
            _, _, _, fim = registro(dec, off, largura)
        except (ErroDados, KeyError, struct.error):
            return off
        off = fim + 4


def corpo(dec, offset, largura):
    """Moldura do corpo de elemento (medido 2023, elementos 0 e 1 da fixture):
    id ; u32 desconhecido ; u32 tam ; u16 tag ; corpo ; u32 tam (tam conta do tag ao fim)."""
    fmt = "<I" if largura == 4 else "<Q"
    eid = struct.unpack_from(fmt, dec.d, offset)[0]
    x, tam, tag = struct.unpack_from("<IIH", dec.d, offset + largura)
    ini = offset + largura + 10
    fim = offset + largura + 8 + tam
    if tam < 2 or fim + 4 > len(dec.d) or struct.unpack_from("<I", dec.d, fim)[0] != tam:
        raise ErroDados("moldura de corpo invalida em 0x%x" % offset)
    return eid, x, dec.por_tag[tag], ini, fim


def varrer_corpos(schema, particao, largura):
    import collections
    dec = Decodificador(schema, open(particao, "rb").read())
    off = fim_da_cadeia_de_headers(dec, largura)
    # procura o primeiro corpo valido logo depois do terminador da cadeia de headers
    for desloc in range(0, 64, 2):
        try:
            corpo(dec, off + desloc, largura)
            off += desloc
            break
        except (ErroDados, KeyError, struct.error):
            continue
    ini_regiao = off
    ok = total = 0
    falhas = collections.Counter()
    exemplo = {}
    por_classe = collections.Counter()
    while True:
        try:
            eid, x, c, ini, fim = corpo(dec, off, largura)
        except (ErroDados, KeyError, struct.error):
            break
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
            k = c["nome"] + ": " + msg.split(" em 0x")[0]
            falhas[k] += 1
            exemplo.setdefault(k, off)
        off = fim + 4
    print("corpos: %d | decodificados ate o trailer: %d (%.0f%%) | regiao 0x%x..0x%x de 0x%x" % (
        total, ok, 100.0 * ok / max(total, 1), ini_regiao, off, len(dec.d)))
    print("classes mais comuns: %s" % por_classe.most_common(8))
    for k, n in falhas.most_common(15):
        print("  %4d x %s   [ex. 0x%x]" % (n, k[:150], exemplo[k]))


def main():
    if sys.argv[1] == "--varrer":
        return varrer(sys.argv[2], sys.argv[3], int(sys.argv[4]))
    if sys.argv[1] == "--corpos":
        return varrer_corpos(sys.argv[2], sys.argv[3], int(sys.argv[4]))
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

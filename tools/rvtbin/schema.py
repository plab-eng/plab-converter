# -*- coding: utf-8 -*-
"""Parser do dicionario de classes `Formats/Latest` (Rota B, etapa 3). Python 3.

Uso:
    python -I tools/rvtbin/schema.py ARQUIVO.rfa|.rvt [--json SAIDA.json]

Gramatica (conferida aqui consumindo o stream INTEIRO de 2021 a 2025; base de
partida: leitor `schema_classes` do rvt-rs, github.com/DrunkOnJava/rvt-rs,
Apache-2.0):

    stream  := { u16 0 ; classe }            ate sobrar so zero
    classe  := u16 n ; nome[n] ; base ; u32 versao ; u32 ncampos ;
               campo * ncampos ; u32 nguids ; guid16 * nguids
    base    := u16 b   (0 = sem base; bit 15 = classe definida inline:
                        u16 0 ; classe, cujo tag tem de ser b & 0x7fff)
    campo   := u32 n ; nome[n] ; tipo
    tipo    := u32 palavra  (byte baixo = especie, 2o byte = modificador)
               [modificador 0x10 -> u32 contagem]
               [especie 0x0d -> 5 bytes 01 00 00 00 20 ; tipo ; ref se o tipo interno tem ref]
               [especie 0x0e com nibble baixo do modificador = 0 -> ref ;
                ref := u16 r (bit 15 = inline: u16 0 ; classe)]
               [especie 0x0e com nibble baixo 1..3 = ponteiro, sem ref]

O tag de cada classe e o ordinal de definicao, comecando em 12.
"""
import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ole_inspect import inspecionar  # noqa: E402

PRIMEIRO_TAG = 12
ESPECIES = {
    0x01: "bool", 0x02: "u16", 0x03: "i32_legado", 0x04: "u32", 0x05: "i32",
    0x06: "f32", 0x07: "f64", 0x08: "string", 0x09: "guid", 0x0a: "i64?", 0x0b: "u64",
    0x0d: "embrulho", 0x0e: "classe",
}


class ErroSchema(Exception):
    pass


class Leitor(object):
    def __init__(self, dados):
        self.d = dados
        self.p = 0
        self.proximo_tag = PRIMEIRO_TAG
        self.classes = {}          # tag -> dict
        self.ordem = []

    def _ler(self, fmt):
        n = struct.calcsize(fmt)
        if self.p + n > len(self.d):
            raise ErroSchema("fim do stream em 0x%x" % self.p)
        v = struct.unpack_from(fmt, self.d, self.p)
        self.p += n
        return v[0] if len(v) == 1 else v

    def _texto(self, n):
        if n > 300 or self.p + n > len(self.d):
            raise ErroSchema("nome de %d bytes em 0x%x" % (n, self.p))
        b = self.d[self.p:self.p + n]
        self.p += n
        if any(c < 0x20 or c > 0x7e for c in b):
            raise ErroSchema("nome nao-ASCII em 0x%x: %r" % (self.p - n, b[:40]))
        return b.decode("ascii")

    def classe(self, tag_esperado=None, profundidade=0):
        if profundidade > 64:
            raise ErroSchema("aninhamento > 64 em 0x%x" % self.p)
        ini = self.p
        nome = self._texto(self._ler("<H"))
        tag = self.proximo_tag
        self.proximo_tag += 1
        if tag_esperado is not None and tag != tag_esperado:
            raise ErroSchema("classe inline %s com tag %d, esperado %d" % (nome, tag, tag_esperado))
        c = {"tag": tag, "nome": nome, "offset": ini}
        self.classes[tag] = c
        self.ordem.append(tag)
        b = self._ler("<H")
        if b & 0x8000:
            if self._ler("<H") != 0:
                raise ErroSchema("pad da base inline != 0 em 0x%x" % self.p)
            self.classe(b & 0x7fff, profundidade + 1)
        c["base"] = (b & 0x7fff) or None
        c["versao"] = self._ler("<I")
        n = self._ler("<I")
        if n > 2000:
            raise ErroSchema("%s com %d campos" % (nome, n))
        c["campos"] = [self.campo(profundidade) for _ in range(n)]
        ng = self._ler("<I")
        if ng > 60000:
            raise ErroSchema("%s com %d guids" % (nome, ng))
        c["guids"] = [self.d[self.p + 16 * i:self.p + 16 * (i + 1)].hex() for i in range(ng)]
        self.p += 16 * ng
        return c

    def campo(self, profundidade):
        nome = self._texto(self._ler("<I"))
        return {"nome": nome, "tipo": self.tipo(profundidade)}

    def tipo(self, profundidade):
        palavra = self._ler("<I")
        especie = palavra & 0xff
        mod = (palavra >> 8) & 0xff
        if especie not in ESPECIES:
            raise ErroSchema("especie 0x%02x desconhecida (palavra 0x%08x) em 0x%x"
                             % (especie, palavra, self.p - 4))
        t = {"palavra": "0x%08x" % palavra, "especie": ESPECIES[especie], "mod": "0x%02x" % mod}
        if mod & 0xf0 == 0x10:
            t["contagem"] = self._ler("<I")
        if especie == 0x0d:
            filler = self.d[self.p:self.p + 5]
            if filler != b"\x01\x00\x00\x00\x20":
                raise ErroSchema("embrulho 0x0d sem o filler esperado em 0x%x: %s" % (self.p, filler.hex()))
            self.p += 5
            t["interno"] = self.tipo(profundidade)
            if "ref" in t["interno"]:
                t["ref"] = self.ref(profundidade)     # externo repete a ref do interno
        elif especie == 0x0e and mod & 0x0f:
            t["ponteiro"] = mod & 0x0f        # 1..3: ponteiro, sem ref de classe
        elif especie == 0x0e:
            t["ref"] = self.ref(profundidade)
        return t

    def ref(self, profundidade):
        r = self._ler("<H")
        if r & 0x8000:
            if self._ler("<H") != 0:
                raise ErroSchema("pad da ref inline != 0 em 0x%x" % self.p)
            self.classe(r & 0x7fff, profundidade + 1)
        return (r & 0x7fff) or None

    def tudo(self):
        while self.p < len(self.d):
            if not any(self.d[self.p:]):
                break
            if self._ler("<H") != 0:
                raise ErroSchema("separador != 0 em 0x%x" % (self.p - 2))
            self.classe()
        return self


def ler_schema(caminho):
    s = {x["stream"]: x for x in inspecionar(caminho)}["Formats/Latest"]
    if not s["crc_ok"]:
        raise ErroSchema("Formats/Latest com CRC invalido: descompressao errada")
    lt = Leitor(s["_conteudo"])
    try:
        lt.tudo()
    except ErroSchema as e:
        ctx = lt.d[max(0, lt.p - 48):lt.p + 48]
        raise ErroSchema("%s | %d classes lidas | contexto: %s" % (e, len(lt.ordem), ctx.hex(" ")))
    return lt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--json")
    a = ap.parse_args()
    lt = ler_schema(a.arquivo)
    ncampos = sum(len(c["campos"]) for c in lt.classes.values())
    print("classes=%d campos=%d bytes=%d consumidos=%d" % (
        len(lt.classes), ncampos, len(lt.d), lt.p))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump([lt.classes[t] for t in lt.ordem], f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

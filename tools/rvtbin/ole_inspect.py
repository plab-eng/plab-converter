# -*- coding: utf-8 -*-
"""Inspetor OLE de .rvt/.rfa (Rota B, etapa 1). Python 3, fora do Revit.

Uso:
    python -I tools/rvtbin/ole_inspect.py ARQUIVO [--dump PASTA]

Lista cada stream com tamanho comprimido e descomprimido e, com --dump,
grava o conteudo descomprimido em PASTA/<stream>.bin (barra vira '__').

Formato das compressoes (medido em 16/10/2026, .rfa 2025 e .rvt 2023/2025):
- os membros sao gzip (1f 8b 08) com o CRC do trailer INVALIDO de proposito:
  zlib com wbits=31 recusa ("incorrect data check"). Por isso descomprimimos
  o deflate CRU (wbits=-15) a partir do fim do cabecalho gzip;
- Formats/Latest: um membro gzip no byte 0;
- Global/*: 8 bytes de prefixo + um membro gzip;
- Partitions/N: cabecalho proprio + VARIOS membros gzip em sequencia.
Streams sem gzip (BasicFileInfo, PartAtom, TransmissionData) sao texto/binario
cru e saem como estao.
"""
import argparse
import json
import os
import sys
import zlib

import olefile

GZ_MAGIC = b"\x1f\x8b\x08"


def _fim_cabecalho_gzip(dados, i):
    """Devolve o indice onde comeca o deflate de um membro gzip em `i`."""
    flags = dados[i + 3]
    j = i + 10
    if flags & 0x04:                      # FEXTRA
        xlen = dados[j] | (dados[j + 1] << 8)
        j += 2 + xlen
    if flags & 0x08:                      # FNAME
        j = dados.index(b"\x00", j) + 1
    if flags & 0x10:                      # FCOMMENT
        j = dados.index(b"\x00", j) + 1
    if flags & 0x02:                      # FHCRC
        j += 2
    return j


def membros_gzip(dados):
    """Lista de membros: (offset, bytes_comprimidos, conteudo)."""
    membros = []
    i = dados.find(GZ_MAGIC)
    while i != -1:
        try:
            ini = _fim_cabecalho_gzip(dados, i)
            d = zlib.decompressobj(-15)
            conteudo = d.decompress(dados[ini:])
            if not d.eof:
                raise zlib.error("deflate truncado")
            usado = len(dados) - ini - len(d.unused_data)
            fim = ini + usado + 8         # trailer CRC32 + ISIZE
            membros.append((i, fim - i, conteudo))
            i = dados.find(GZ_MAGIC, fim)
        except (zlib.error, IndexError, ValueError):
            # falso positivo de magic dentro de dado cru: segue procurando
            i = dados.find(GZ_MAGIC, i + 1)
    return membros


def inspecionar(caminho):
    ole = olefile.OleFileIO(caminho)
    streams = []
    for partes in ole.listdir():
        nome = "/".join(partes)
        cru = ole.openstream(nome).read()
        membros = membros_gzip(cru)
        conteudo = b"".join(m[2] for m in membros) if membros else cru
        streams.append({
            "stream": nome,
            "bytes": len(cru),
            "membros_gzip": len(membros),
            "prefixo_hex": cru[:min(membros[0][0], 64) if membros else 16].hex(),
            "bytes_descomprimidos": len(conteudo),
            "_conteudo": conteudo,
        })
    ole.close()
    return streams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--dump", help="pasta para gravar os streams descomprimidos")
    a = ap.parse_args()

    streams = inspecionar(a.arquivo)
    if a.dump:
        os.makedirs(a.dump, exist_ok=True)
    for s in streams:
        print("%-32s %10d -> %10d  gz=%d" % (
            s["stream"], s["bytes"], s["bytes_descomprimidos"], s["membros_gzip"]))
        if a.dump:
            nome = s["stream"].replace("/", "__") + ".bin"
            with open(os.path.join(a.dump, nome), "wb") as f:
                f.write(s["_conteudo"])
    if a.dump:
        resumo = [dict((k, v) for k, v in s.items() if k != "_conteudo") for s in streams]
        with open(os.path.join(a.dump, "_resumo.json"), "w", encoding="utf-8") as f:
            json.dump({"arquivo": a.arquivo, "streams": resumo}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

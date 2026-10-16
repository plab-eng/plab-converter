# -*- coding: utf-8 -*-
"""Inspetor OLE de .rvt/.rfa (Rota B, etapa 1). Python 3, fora do Revit.

Uso:
    python -I tools/rvtbin/ole_inspect.py ARQUIVO [--dump PASTA]

Lista cada stream com tamanho comprimido e descomprimido e, com --dump,
grava o conteudo descomprimido em PASTA/<stream>.bin (barra vira '__').

Formato (medido em 16/10/2026, .rfa 2023/2024/2025 e .rvt 2023/2025):
- PAGINACAO: os streams comprimidos sao gravados em paginas de 65.249 bytes,
  64.896 de dado + 353 de checksum/ECC no fim de cada pagina cheia (a ultima
  pagina, curta, fica inteira). Tem que remover esses 353 bytes ANTES de
  descomprimir. Sem isso o deflate segue "decodificando" lixo sem erro depois
  da primeira pagina e o CRC do gzip falha. Com a remocao o CRC confere.
  Constantes e lista de streams paginados vindos do rvt-rs
  (github.com/DrunkOnJava/rvt-rs, Apache-2.0), conferidos aqui pelo CRC.
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
PAGINA_GRAVADA = 65249
PAGINA_DADO = 64896
STREAMS_PAGINADOS = (
    "Formats/Latest", "Global/ContentDocuments", "Global/DocumentIncrementTable",
    "Global/ElemTable", "Global/History", "Global/Latest", "Global/PartitionTable",
)


def eh_paginado(nome):
    partes = nome.split("/")
    return nome in STREAMS_PAGINADOS or (len(partes) == 2 and partes[0] == "Partitions")


def tirar_paginas(dados):
    """Remove os 353 bytes de checksum do fim de cada pagina cheia."""
    cheias = len(dados) // PAGINA_GRAVADA
    if cheias == 0:
        return dados
    pedacos = [dados[i * PAGINA_GRAVADA:i * PAGINA_GRAVADA + PAGINA_DADO] for i in range(cheias)]
    pedacos.append(dados[cheias * PAGINA_GRAVADA:])
    return b"".join(pedacos)


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
    """Lista de membros: (offset, bytes_comprimidos, conteudo, crc_ok)."""
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
            trailer = dados[ini + usado:fim]
            crc_ok = (len(trailer) == 8 and
                      int.from_bytes(trailer[:4], "little") == zlib.crc32(conteudo) and
                      int.from_bytes(trailer[4:], "little") == len(conteudo) & 0xFFFFFFFF)
            membros.append((i, fim - i, conteudo, crc_ok))
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
        limpo = tirar_paginas(cru) if eh_paginado(nome) else cru
        membros = membros_gzip(limpo)
        conteudo = b"".join(m[2] for m in membros) if membros else cru
        streams.append({
            "stream": nome,
            "bytes": len(cru),
            "membros_gzip": len(membros),
            "crc_ok": all(m[3] for m in membros) if membros else None,
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
        print("%-32s %10d -> %10d  gz=%d  crc=%s" % (
            s["stream"], s["bytes"], s["bytes_descomprimidos"], s["membros_gzip"],
            {True: "ok", False: "FALHA", None: "-"}[s["crc_ok"]]))
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

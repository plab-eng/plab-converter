"""Prévia isométrica (PNG) das primitivas que o compilador grava.

Não precisa do Revit: desenha caixas e cilindros do tipo corrente, com faces
sombreadas pela normal e ordenadas de trás para a frente. Serve para o usuário
conferir antes de gastar tempo de Revit e, nos exemplos, faz o papel da imagem
obrigatória (sempre identificada como prévia gerada, nunca como foto).
"""

import math

import numpy as np
from PIL import Image, ImageDraw

_LADOS_CILINDRO = 32
_LUZ = (-0.45, -0.6, 0.66)
_COR = (186, 160, 120)


def _faces_caixa(minimo, maximo):
    (x0, y0, z0), (x1, y1, z1) = minimo, maximo
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    indices = [((0, 3, 2, 1), (0, 0, -1)), ((4, 5, 6, 7), (0, 0, 1)), ((0, 1, 5, 4), (0, -1, 0)),
               ((2, 3, 7, 6), (0, 1, 0)), ((1, 2, 6, 5), (1, 0, 0)), ((3, 0, 4, 7), (-1, 0, 0))]
    return [([v[i] for i in ids], normal) for ids, normal in indices]


def _faces_cilindro(cx, cy, r, z0, z1):
    pontos = [(cx + r * math.cos(2 * math.pi * k / _LADOS_CILINDRO),
               cy + r * math.sin(2 * math.pi * k / _LADOS_CILINDRO)) for k in range(_LADOS_CILINDRO)]
    faces = [([(x, y, z1) for x, y in pontos], (0, 0, 1)), ([(x, y, z0) for x, y in reversed(pontos)], (0, 0, -1))]
    for k in range(_LADOS_CILINDRO):
        (xa, ya), (xb, yb) = pontos[k], pontos[(k + 1) % _LADOS_CILINDRO]
        meio = 2 * math.pi * (k + 0.5) / _LADOS_CILINDRO
        faces.append(([(xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)], (math.cos(meio), math.sin(meio), 0)))
    return faces


def _projetar(ponto):
    """Isométrica vista da frente-esquerda (câmera em -x, -y, +z)."""
    x, y, z = ponto
    return ((x - y) * math.cos(math.pi / 6), -(z + (x + y) * math.sin(math.pi / 6)))


def desenhar(primitivas, caminho, lado=512, legenda=None):
    faces = []
    for primitiva in primitivas:
        if "caixa" in primitiva:
            faces += _faces_caixa(*primitiva["caixa"])
        elif "cilindro" in primitiva:
            faces += _faces_cilindro(*primitiva["cilindro"])
    # Visível: normal apontando para a câmera (-1, -1, 1).
    visiveis = [(pts, n) for pts, n in faces if -n[0] - n[1] + n[2] > 1e-9]
    if not visiveis:
        raise ValueError("nada a desenhar")

    projetados = [[_projetar(p) for p in pts] for pts, _ in visiveis]
    xs = [p[0] for poli in projetados for p in poli]
    ys = [p[1] for poli in projetados for p in poli]
    margem = 0.08 * lado
    escala = (lado - 2 * margem) / max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    ox = margem + ((lado - 2 * margem) - (max(xs) - min(xs)) * escala) / 2 - min(xs) * escala
    oy = margem + ((lado - 2 * margem) - (max(ys) - min(ys)) * escala) / 2 - min(ys) * escala

    # Z-buffer: a ordem de pintura pela profundidade média escondia a porta da
    # frente atrás da lateral. Cada face é plana, então a profundidade
    # (x + y - z, maior = mais longe) é linear na tela: resolve-se a, b, c com
    # três vértices e compara-se pixel a pixel.
    profundidade = np.full((lado, lado), np.inf)
    face_id = np.full((lado, lado), -1, dtype=np.int32)
    v, u = np.mgrid[0:lado, 0:lado]
    for i, (pontos, _) in enumerate(visiveis):
        tela = [(ox + x * escala, oy + y * escala) for x, y in projetados[i]]
        mascara = Image.new("1", (lado, lado), 0)
        ImageDraw.Draw(mascara).polygon(tela, fill=1, outline=1)
        dentro = np.array(mascara, dtype=bool)
        if not dentro.any():
            continue
        amostras = [(tela[k][0], tela[k][1], pontos[k][0] + pontos[k][1] - pontos[k][2]) for k in range(len(tela))]
        coef = _plano_de_profundidade(amostras)
        if coef is None:
            continue
        z = coef[0] * u + coef[1] * v + coef[2]
        ganha = dentro & (z < profundidade - 1e-6)
        profundidade[ganha] = z[ganha]
        face_id[ganha] = i

    pixels = np.full((lado, lado, 3), (250, 250, 248), dtype=np.uint8)
    for i, (_, normal) in enumerate(visiveis):
        luz = max(0.25, sum(a * b for a, b in zip(normal, _LUZ)) / math.sqrt(sum(c * c for c in normal)))
        pixels[face_id == i] = tuple(int(c * (0.55 + 0.45 * luz)) for c in _COR)
    # Aresta onde a face visível muda (inclusive contra o fundo).
    borda = np.zeros((lado, lado), dtype=bool)
    borda[:, 1:] |= face_id[:, 1:] != face_id[:, :-1]
    borda[1:, :] |= face_id[1:, :] != face_id[:-1, :]
    pixels[borda] = (70, 60, 50)

    imagem = Image.fromarray(pixels, "RGB")
    if legenda:
        ImageDraw.Draw(imagem).text((8, lado - 18), legenda, fill=(90, 90, 90))
    imagem.save(caminho)
    return caminho


def _plano_de_profundidade(amostras):
    """z = a*u + b*v + c pelos mínimos quadrados dos vértices projetados."""
    matriz = np.array([[u, v, 1.0] for u, v, _ in amostras])
    alvo = np.array([z for _, _, z in amostras])
    if np.linalg.matrix_rank(matriz) < 3:
        return None  # face vista de lado (degenerada na tela)
    coef, *_ = np.linalg.lstsq(matriz, alvo, rcond=None)
    return coef

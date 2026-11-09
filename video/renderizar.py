"""Renderiza as cenas do vídeo (1920x1080) e monta o MP4 com a narração.

Requer Pillow e ffmpeg. Uso (Python do sistema, que tem Pillow):
    python3 video/renderizar.py
Entradas: video/roteiro.py, video/build/demo.json, video/build/gui_*.jpg, video/build/audio/*.mp3, evidencias/
Saída: video/SolarOps_Chat_SD2.mp4 e video/SolarOps_Chat_SD2.srt
"""

import json
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "video"))
from roteiro import BEATS  # noqa: E402

BUILD = os.path.join(ROOT, "video", "build")
FRAMES = os.path.join(BUILD, "frames")
SEGS = os.path.join(BUILD, "segs")
OUT_MP4 = os.path.join(ROOT, "video", "SolarOps_Chat_SD2.mp4")
OUT_SRT = os.path.join(ROOT, "video", "SolarOps_Chat_SD2.srt")
W, H = 1920, 1080
LEAD, TAIL = 0.45, 0.75  # silêncio antes e depois de cada fala

# ---------------------------------------------------------------- estilo
BG = (13, 16, 22)
PANEL = (24, 28, 36)
TERM_BG = (18, 20, 26)
LINE = (48, 54, 66)
TEXT = (230, 237, 243)
MUTED = (139, 148, 158)
AMBER = (245, 184, 61)
TEAL = (79, 209, 197)
RED = (255, 107, 107)
GREEN = (126, 231, 135)
PURPLE = (199, 146, 234)

SF = "/System/Library/Fonts/SFNS.ttf"
MONO = "/System/Library/Fonts/SFNSMono.ttf"


def font(size, weight="Regular", mono=False):
    f = ImageFont.truetype(MONO if mono else SF, size)
    try:
        f.set_variation_by_name(weight)
    except (OSError, ValueError):
        pass
    return f


def text_w(f, s):
    return f.getlength(s)


def wrap(f, s, width):
    words, lines, cur = s.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if text_w(f, cand) <= width or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def wrap_mono(f, s, width):
    cw = text_w(f, "M")
    n = max(10, int(width // cw))
    indent = len(s) - len(s.lstrip(" "))
    out, first = [], True
    body = s
    while body:
        lim = n if first else n - 2
        if len(body) <= lim:
            out.append(body if first else "  " + body)
            break
        cut = body.rfind(" ", 0, lim)
        cut = lim if cut <= indent else cut
        out.append(body[:cut] if first else "  " + body[:cut])
        body = body[cut:].lstrip(" ")
        first = False
    return out or [""]


def rounded(draw, box, r, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)


def shadow(img, box, r=18, blur=24, alpha=150):
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((x0 + 6, y0 + 14, x1 + 6, y1 + 14), r, fill=(0, 0, 0, alpha))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def base(title, index):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    # brilho âmbar discreto no canto (identidade "solar")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W - 520, -420, W + 380, 380), fill=AMBER + (34,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img)
    if title:
        d.text((64, 44), "SOLAROPS CHAT  ·  SISTEMAS DISTRIBUÍDOS II", font=font(20, "Semibold"), fill=AMBER)
        d.text((62, 74), title, font=font(46, "Bold"), fill=TEXT)
        d.line((64, 138, W - 64, 138), fill=LINE, width=2)
    d.text((64, H - 44), "Luís Felipe Silva Barbosa  ·  Unimontes  ·  2026/2", font=font(18), fill=MUTED)
    d.text((W - 64, H - 44), f"{index:02d}/{len(BEATS):02d}", font=font(18, "Medium"), fill=MUTED, anchor="ra")
    return img


# ---------------------------------------------------------------- terminal
def line_color(s, prev):
    t = s.lstrip()
    if s.startswith("    ") and prev is not None:
        return prev
    if t.startswith("$ "):
        return GREEN
    if t.startswith("> "):
        return AMBER
    if "[privado] bot" in t:
        return TEAL
    if t.startswith("[erro]") or t.startswith("[processo"):
        return RED
    if t.startswith("[privado]"):
        return PURPLE
    if t.startswith("*") or t.startswith("Digite") or t.startswith("Participantes") or t.startswith("  - "):
        return MUTED
    return TEXT


def terminal(img, box, title, lines, fsize=17, highlight_from=None, tag=None):
    """lines: list of (text, highlighted:bool). Mostra as últimas linhas que cabem."""
    x0, y0, x1, y1 = box
    shadow(img, box, r=14, blur=18, alpha=120)
    d = ImageDraw.Draw(img)
    rounded(d, box, 14, fill=TERM_BG, outline=LINE, width=2)
    d.rounded_rectangle((x0, y0, x1, y0 + 36), 14, fill=(34, 38, 48))
    d.rectangle((x0, y0 + 20, x1, y0 + 36), fill=(34, 38, 48))
    for i, c in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        d.ellipse((x0 + 16 + i * 22, y0 + 12, x0 + 28 + i * 22, y0 + 24), fill=c)
    d.text((x0 + 90, y0 + 8), title, font=font(17, "Semibold"), fill=TEXT)
    if tag:
        tf = font(15, "Bold")
        tw = text_w(tf, tag) + 20
        col = AMBER if "TLS" in tag else MUTED
        rounded(d, (x1 - tw - 14, y0 + 7, x1 - 14, y0 + 29), 8, outline=col, width=2)
        d.text((x1 - tw - 4, y0 + 9), tag, font=tf, fill=col)
    f = font(fsize, mono=True)
    lh = int(fsize * 1.38)
    inner_w = x1 - x0 - 34
    rendered, prev = [], None
    for text, hi in lines:
        col = line_color(text, prev)
        prev = col
        for part in wrap_mono(f, text, inner_w):
            rendered.append((part, col, hi))
    max_lines = (y1 - y0 - 52) // lh
    rendered = rendered[-max_lines:]
    y = y0 + 46
    for part, col, hi in rendered:
        if hi:
            d.rectangle((x0 + 6, y - 2, x0 + 10, y + lh - 4), fill=AMBER)
            d.rectangle((x0 + 12, y - 2, x1 - 8, y + lh - 4), fill=(48, 41, 26))
        d.text((x0 + 20, y), part, font=f, fill=col)
        y += lh


def overlay_alpha(img):
    return img


# ---------------------------------------------------------------- imagens da GUI
def paste_image(img, path, box, boxes=None, src_size=None):
    """Cola a imagem dentro de `box` mantendo a proporção; desenha destaques (coordenadas da imagem)."""
    im = Image.open(path).convert("RGBA")
    x0, y0, x1, y1 = box
    scale = min((x1 - x0) / im.width, (y1 - y0) / im.height)
    nw, nh = int(im.width * scale), int(im.height * scale)
    im = im.resize((nw, nh), Image.LANCZOS)
    px, py = x0 + ((x1 - x0) - nw) // 2, y0
    shadow(img, (px, py, px + nw, py + nh), r=12, blur=26, alpha=170)
    mask = Image.new("L", (nw, nh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, nw, nh), 12, fill=255)
    img.paste(im, (px, py), mask)
    d = ImageDraw.Draw(img)
    for bx in boxes or []:
        bx0, by0, bx1, by1 = [int(v * scale) for v in bx]
        rounded(d, (px + bx0 - 4, py + by0 - 4, px + bx1 + 4, py + by1 + 4), 8, outline=AMBER, width=4)
    return (px, py, px + nw, py + nh)


# ---------------------------------------------------------------- cenas
DEMO = None
TERM_INFO = {
    "ana": ("ana · COS", "texto claro :5050"),
    "rui": ("rui · técnico", "TLS :5051"),
    "eva": ("eva · engenheira", "texto claro :5050"),
}


def demo_lines(term, until, since):
    out = []
    for t, text in DEMO.get(term, []):
        if t > until:
            break
        if text.startswith("$ python"):
            continue
        out.append((text, since is not None and t >= since))
    return out


def scene_demo(img, v):
    gui = paste_image(img, os.path.join(BUILD, v["image"]), (48, 170, 1150, 1000), v.get("boxes"))
    d = ImageDraw.Draw(img)
    d.text((gui[0], gui[3] + 14), "Servidor: interface gráfica (tkinter), capturada durante a execução real",
           font=font(17), fill=MUTED)
    terms = v["terms"]
    top, bottom, gap = 170, 1010, 18
    hgt = (bottom - top - gap * (len(terms) - 1)) // len(terms)
    for i, term in enumerate(terms):
        y = top + i * (hgt + gap)
        name, tag = TERM_INFO[term]
        terminal(img, (1180, y, W - 48, y + hgt), name, demo_lines(term, v["until"], v.get("since")),
                 fsize=16 if len(terms) == 3 else 17, tag=tag)


def scene_title(img):
    d = ImageDraw.Draw(img)
    # painel solar estilizado
    ox, oy = 1240, 300
    for r in range(4):
        for c in range(5):
            x, y = ox + c * 104 - r * 34, oy + r * 72
            d.polygon([(x, y), (x + 96, y), (x + 96 - 30, y + 64), (x - 30, y + 64)],
                      fill=(30, 44, 70), outline=(70, 110, 160))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((1500, 60, 1780, 340), fill=AMBER + (210,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)))
    d = ImageDraw.Draw(img)
    d.ellipse((1560, 120, 1720, 280), fill=(255, 205, 90))
    d.text((120, 300), "SolarOps Chat", font=font(118, "Bold"), fill=TEXT)
    d.text((124, 440), "Chat cliente-servidor com sockets, threads,", font=font(40), fill=TEXT)
    d.text((124, 494), "TLS e bot com LLM para O&M de usinas solares", font=font(40), fill=TEXT)
    d.rectangle((124, 590, 284, 596), fill=AMBER)
    d.text((124, 630), "Trabalho Prático  ·  Sistemas Distribuídos II  ·  Unimontes", font=font(28, "Medium"), fill=AMBER)
    d.text((124, 680), "Luís Felipe Silva Barbosa", font=font(30, "Semibold"), fill=TEXT)
    d.text((124, 726), "Prof. Marcel Veloso Campos  ·  2026/2", font=font(26), fill=MUTED)


def scene_bullets(img, items):
    d = ImageDraw.Draw(img)
    f = font(46, "Medium")
    y = 230
    for it in items:
        lines = wrap(f, it, 1640)
        d.ellipse((92, y + 19, 112, y + 39), fill=AMBER)
        for ln in lines:
            d.text((140, y), ln, font=f, fill=TEXT)
            y += 62
        y += 50


def box_label(d, box, title, sub, col=TEXT, border=LINE, fill=PANEL, tsize=30, ssize=20, scol=MUTED):
    rounded(d, box, 18, fill=fill, outline=border, width=3)
    x0, y0, x1, y1 = box
    d.text(((x0 + x1) / 2, y0 + 24), title, font=font(tsize, "Bold"), fill=col, anchor="ma")
    yy = y0 + 24 + tsize + 16
    for s in sub:
        d.text(((x0 + x1) / 2, yy), s, font=font(ssize), fill=scol, anchor="ma")
        yy += int(ssize * 1.4)


def arrow(d, p0, p1, col, width=4, dashed=False, label=None, lab_off=(0, -30)):
    import math
    x0, y0 = p0
    x1, y1 = p1
    if dashed:
        n = int(math.hypot(x1 - x0, y1 - y0) // 18)
        for i in range(0, n, 2):
            a, b = i / n, min(1, (i + 1) / n)
            d.line((x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, x0 + (x1 - x0) * b, y0 + (y1 - y0) * b), fill=col, width=width)
    else:
        d.line((x0, y0, x1, y1), fill=col, width=width)
    ang = math.atan2(y1 - y0, x1 - x0)
    for s in (1, -1):
        d.line((x1, y1, x1 - 18 * math.cos(ang - s * 0.45), y1 - 18 * math.sin(ang - s * 0.45)), fill=col, width=width)
    if label:
        mx, my = (x0 + x1) / 2 + lab_off[0], (y0 + y1) / 2 + lab_off[1]
        lf = font(19, "Semibold")
        tw = text_w(lf, label)
        d.rounded_rectangle((mx - tw / 2 - 10, my - 15, mx + tw / 2 + 10, my + 15), 8, fill=BG, outline=col, width=2)
        d.text((mx, my), label, font=lf, fill=col, anchor="mm")


def scene_arquitetura(img):
    d = ImageDraw.Draw(img)
    clients = [("ana · COS", "client.py", False, 230), ("rui · técnico", "client.py", True, 470),
               ("eva · engenheira", "client.py", False, 710)]
    for name, file, tls, y in clients:
        box_label(d, (90, y, 470, y + 170), name, [file, "thread receptora + input"],
                  border=AMBER if tls else LINE, tsize=28)
        arrow(d, (475, y + 85), (792, 555 + (y - 470) * 0.3), AMBER if tls else MUTED, dashed=not tls,
              label=("TLS :5051" if tls else "texto claro :5050"), lab_off=(0, 0))
    box_label(d, (800, 380, 1230, 730), "server.py", [
        "accept: 1 thread por porta", "1 thread por cliente", "reaper (prazo do bot)", "lock único sem I/O",
        "send_lock por participante", "", "GUI tkinter + fila"], border=TEAL, tsize=34)
    box_label(d, (1330, 420, 1610, 640), "bot.py", ["processo separado", "pool de 4 workers", "histórico por usuário"],
              border=AMBER, tsize=30)
    arrow(d, (1325, 530), (1236, 530), AMBER, label="TLS", lab_off=(0, -34))
    box_label(d, (1660, 450, 1860, 610), "OpenAI", ["gpt-5.4-nano", "HTTPS"], border=LINE, tsize=28)
    arrow(d, (1612, 530), (1655, 530), MUTED)
    d.text((90, 940), "Somente sockets TCP entre os componentes  ·  Python 3.14, biblioteca padrão (socket, threading, ssl)",
           font=font(24, "Medium"), fill=MUTED)


def scene_percurso(img):
    d = ImageDraw.Draw(img)
    steps = [
        ("1  Cliente", ["gera req_id (uuid4)", "envia BOT_REQ", "pelo socket TLS"]),
        ("2  Servidor", ["valida e sobrescreve from", "pending[req_id] com", "prazo de 30 s"]),
        ("3  Bot", ["worker do pool", "chama a LLM", "(timeout 20 s)"]),
        ("4  Bot", ["BOT_RESP ou ERROR", "com o mesmo req_id", "to = solicitante"]),
        ("5  Servidor", ["confere pendente", "e destinatário;", "entrega só a ele"]),
    ]
    x, y, w, h, gap = 80, 400, 318, 210, 32
    for i, (title, lines) in enumerate(steps):
        bx = x + i * (w + gap)
        box_label(d, (bx, y, bx + w, y + h), title, lines, border=AMBER if i in (0, 4) else LINE, tsize=34,
                  ssize=25, scol=TEXT)
        if i < len(steps) - 1:
            arrow(d, (bx + w + 4, y + h / 2), (bx + w + gap - 4, y + h / 2), AMBER, width=4)
    d.text((W / 2, 720), "Enquanto isso, as threads dos outros clientes continuam roteando MSG e DM.",
           font=font(30, "Medium"), fill=TEAL, anchor="ma")


def scene_protocol(img):
    d = ImageDraw.Draw(img)
    rows = [("type", "HELLO · WELCOME · MSG · DM · BOT_REQ · BOT_RESP · ERROR · JOIN · LEAVE · LIST"),
            ("from", "remetente (o servidor sobrescreve)"), ("to", "* · nome · bot"),
            ("content", "texto da mensagem"), ("req_id", "uuid4 que correlaciona pedido e resposta"),
            ("ts", "ISO 8601 UTC"), ("role", "cos · tecnico · engenheiro · bot")]
    y = 200
    for k, v in rows:
        rounded(d, (64, y, 900, y + 78), 12, fill=PANEL, outline=LINE, width=2)
        d.text((92, y + 22), k, font=font(28, "Bold", mono=True), fill=AMBER)
        wl = wrap(font(22), v, 600)
        for j, ln in enumerate(wl):
            d.text((270, y + (78 - len(wl) * 28) / 2 + j * 28), ln, font=font(22), fill=TEXT)
        y += 94
    raw = open(os.path.join(ROOT, "evidencias", "exemplo_protocolo.txt"), encoding="utf-8").read().strip()
    obj = json.loads(raw)
    pretty = ["{"] + [f'  "{k}": {json.dumps(v, ensure_ascii=False)},' for k, v in obj.items()] + ["}\\n   ← fim da mensagem"]
    terminal(img, (960, 200, W - 64, 580), "protocol.py · uma mensagem JSON por linha",
             [(p, False) for p in pretty], fsize=22)
    d = ImageDraw.Draw(img)
    notes = ["LineReader acumula bytes até \\n", "Mensagens partidas ou coladas: OK", "Limite de 64 KB por linha"]
    yy = 640
    for n in notes:
        d.ellipse((980, yy + 12, 994, yy + 26), fill=TEAL)
        d.text((1010, yy), n, font=font(28, "Medium"), fill=TEXT)
        yy += 50


PY_KW = r"\b(def|while|try|except|return|with|for|in|if|not|continue|and|is|None|True|False|self)\b"


def code_panel(img, box, file, a, b):
    src = open(os.path.join(ROOT, file), encoding="utf-8").read().splitlines()[a - 1:b]
    x0, y0, x1, y1 = box
    shadow(img, box, r=14, blur=18, alpha=120)
    d = ImageDraw.Draw(img)
    rounded(d, box, 14, fill=TERM_BG, outline=LINE, width=2)
    d.text((x0 + 20, y0 + 12), f"{file}  ·  linhas {a} a {b}", font=font(18, "Semibold"), fill=AMBER)
    f = font(18, mono=True)
    cw = text_w(f, "M")
    maxc = int((x1 - x0 - 90) // cw)
    y = y0 + 48
    for n, ln in enumerate(src, start=a):
        ln = ln if len(ln) <= maxc else ln[: maxc - 1] + "…"
        d.text((x0 + 18, y), f"{n:>3}", font=f, fill=(90, 98, 112))
        x = x0 + 70
        if ln.strip().startswith("#"):
            d.text((x, y), ln, font=f, fill=(110, 120, 135))
        else:
            pos = 0
            for m in re.finditer(PY_KW + r'|"[^"]*"|#.*$', ln):
                d.text((x + pos * cw, y), ln[pos:m.start()], font=f, fill=TEXT)
                tok = m.group(0)
                col = (110, 120, 135) if tok.startswith("#") else GREEN if tok.startswith('"') else PURPLE
                d.text((x + m.start() * cw, y), tok, font=f, fill=col)
                pos = m.end()
            d.text((x + pos * cw, y), ln[pos:], font=f, fill=TEXT)
        y += 27


def scene_code(img, v):
    y = 176
    for file, a, b in v["panels"]:
        h = 48 + 27 * (b - a + 1) + 14
        code_panel(img, (64, y, 1240, y + h), file, a, b)
        y += h + 22
    d = ImageDraw.Draw(img)
    notes = [("Accept", "1 thread por porta (5050 e 5051)"), ("Cliente", "1 thread por conexão; TLS e HELLO nela"),
             ("Lock único", "participantes + pendentes, sem I/O"), ("send_lock", "um por participante"),
             ("Reaper", "aplica o prazo do bot a cada 0,5 s")]
    y = 200
    for k, v2 in notes:
        rounded(d, (1290, y, W - 64, y + 132), 16, fill=PANEL, outline=LINE, width=2)
        d.text((1316, y + 22), k, font=font(30, "Bold"), fill=AMBER)
        for j, ln in enumerate(wrap(font(23), v2, 520)):
            d.text((1316, y + 66 + j * 28), ln, font=font(23), fill=TEXT)
        y += 156


def scene_tls(img):
    d = ImageDraw.Draw(img)
    box_label(d, (90, 210, 640, 400), "SolarOps CA", ["CA própria da usina", "RSA 2048 · keyCertSign"], border=AMBER)
    arrow(d, (365, 405), (365, 480), AMBER, label="assina", lab_off=(60, 0))
    box_label(d, (90, 485, 640, 705), "server.crt", ["CN = localhost", "SAN: localhost, 127.0.0.1",
                                                     "extendedKeyUsage serverAuth"], border=TEAL)
    checks = ["create_default_context(cafile=certs/ca.crt)", "CERT_REQUIRED + check_hostname",
              "Verificação X.509 estrita do Python 3.14", "Outra CA → conexão recusada"]
    y = 750
    for c in checks:
        d.ellipse((96, y + 12, 110, y + 26), fill=TEAL)
        d.text((126, y), c, font=font(25, "Medium"), fill=TEXT)
        y += 46
    rows = [("Enlace", "Porta", "Proteção"), ("rui (TLS) ↔ servidor", "5051", "TLS 1.3"), ("bot ↔ servidor", "5051", "TLS 1.3"),
            ("bot ↔ OpenAI", "443", "HTTPS"), ("ana, eva ↔ servidor", "5050", "texto claro*")]
    x, y = 760, 230
    widths = [520, 180, 340]
    for i, r in enumerate(rows):
        xx = x
        fill = (34, 38, 48) if i == 0 else PANEL
        for j, cell in enumerate(r):
            rounded(d, (xx, y, xx + widths[j] - 10, y + 70), 10, fill=fill, outline=LINE, width=2)
            col = AMBER if i == 0 else (RED if "claro" in cell else TEXT)
            d.text((xx + 22, y + 20), cell, font=font(26, "Bold" if i == 0 else "Medium"), fill=col)
            xx += widths[j]
        y += 82
    d.text((760, y + 20), "* mantido apenas como referência para a comparação no Wireshark", font=font(22), fill=MUTED)
    d.text((760, y + 90), "Decifragem: no servidor, na thread do cliente;", font=font(28, "Medium"), fill=TEXT)
    d.text((760, y + 132), "no cliente e no bot, na thread receptora.", font=font(28, "Medium"), fill=TEXT)


def scene_image(img, path):
    paste_image(img, os.path.join(ROOT, path), (64, 176, 1100, 1010))
    d = ImageDraw.Draw(img)
    notes = ["Captura na interface de loopback (lo0)", "Filtro: tcp.port == 5050", "Follow TCP Stream",
             "JSON legível: tipo, remetente, conteúdo", "Qualquer um na rede consegue ler"]
    y = 260
    for n in notes:
        d.ellipse((1180, y + 12, 1196, y + 28), fill=RED if "Qualquer" in n else AMBER)
        for j, ln in enumerate(wrap(font(32, "Medium"), n, 640)):
            d.text((1216, y + j * 42), ln, font=font(32, "Medium"), fill=TEXT)
        y += 100


def scene_terminal(img, v):
    lines = []
    for fpath in v["files"]:
        for ln in open(os.path.join(ROOT, fpath), encoding="utf-8").read().splitlines():
            ln = re.sub(r"\s{2,}", "  ", ln.strip())
            hi = ("Server Hello" in ln) or ("5051 contendo" in ln) or ("0x0304" in ln)
            lines.append((ln, hi))
        lines.append(("", False))
    terminal(img, (64, 176, W - 64, 1010), v["label"], lines[:-1], fsize=22)


def scene_final(img):
    summary = open(os.path.join(ROOT, "evidencias", "pytest.txt")).read().strip().splitlines()[-1]
    rows = [("$ make test", False), ("tests/test_protocol.py   14", False), ("tests/test_server.py     50", False),
            ("tests/test_client.py     70", False), ("tests/test_bot.py        37", False),
            ("tests/test_tls.py         8", False), ("tests/test_e2e.py         9", False),
            ("tests/test_stress.py      1", False), (summary, True)]
    terminal(img, (64, 176, 980, 525), "pytest · suíte completa", rows, fsize=21)
    d = ImageDraw.Draw(img)
    stats = [("189", "testes automatizados"), ("9", "cenários ponta a ponta"), ("10", "clientes no teste de carga")]
    x = 64
    for n, label in stats:
        rounded(d, (x, 600, x + 290, 780), 18, fill=PANEL, outline=LINE, width=2)
        d.text((x + 145, 620), n, font=font(72, "Bold"), fill=AMBER, anchor="ma")
        d.text((x + 145, 720), label, font=font(21), fill=TEXT, anchor="ma")
        x += 313
    d.text((1060, 200), "Limitações", font=font(40, "Bold"), fill=TEXT)
    lim = ["Proteção por enlace, não ponta a ponta", "Sem autenticação de usuário (TLS só do servidor)",
           "Histórico do bot em memória", "Base de conhecimento ilustrativa (SOLX-100)"]
    y = 280
    for it in lim:
        d.ellipse((1064, y + 14, 1080, y + 30), fill=AMBER)
        for j, ln in enumerate(wrap(font(30), it, 700)):
            d.text((1100, y + j * 40), ln, font=font(30), fill=TEXT)
        y += 90
    d.text((1060, 760), "Obrigado!", font=font(64, "Bold"), fill=AMBER)


def render(beat, index):
    v = beat["visual"]
    img = base(beat["title"], index)
    kind = v["type"]
    if kind == "title":
        scene_title(img)
    elif kind == "bullets":
        scene_bullets(img, v["items"])
    elif kind == "diagram":
        (scene_arquitetura if v["name"] == "arquitetura" else scene_percurso)(img)
    elif kind == "protocol":
        scene_protocol(img)
    elif kind == "code":
        scene_code(img, v)
    elif kind == "gui":
        paste_image(img, os.path.join(BUILD, v["image"]), (210, 176, 1710, 1000), v.get("boxes"))
    elif kind == "demo":
        scene_demo(img, v)
    elif kind == "tls":
        scene_tls(img)
    elif kind == "image":
        scene_image(img, v["path"])
    elif kind == "terminal":
        scene_terminal(img, v)
    elif kind == "final":
        scene_final(img)
    path = os.path.join(FRAMES, f"{beat['id']}.png")
    img.convert("RGB").save(path, optimize=True)
    return path


# ---------------------------------------------------------------- áudio, vídeo e legendas
def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def subtitle_chunks(text, limit=90):
    """Frases (.!?) e, se longas, quebradas em vírgulas/dois-pontos para caber em ~2 linhas."""
    out = []
    for sent in (x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()):
        parts, cur = re.split(r"(?<=[,:;])\s+", sent), ""
        for part in parts:
            if cur and len(cur) + 1 + len(part) > limit:
                out.append(cur)
                cur = part
            else:
                cur = (cur + " " + part).strip()
        if cur:
            out.append(cur)
    return out


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    global DEMO
    DEMO = json.load(open(os.path.join(BUILD, "demo.json"), encoding="utf-8"))
    os.makedirs(FRAMES, exist_ok=True)
    os.makedirs(SEGS, exist_ok=True)
    segs, srt, t0 = [], [], 0.0
    for i, beat in enumerate(BEATS, start=1):
        frame = render(beat, i)
        audio = os.path.join(BUILD, "audio", f"{beat['id']}.mp3")
        speech = duration(audio)
        total = LEAD + speech + TAIL
        seg = os.path.join(SEGS, f"{beat['id']}.mp4")
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", frame, "-i", audio,
             "-filter_complex",
             f"[0:v]format=yuv420p,fade=t=in:st=0:d=0.35,fade=t=out:st={total - 0.35:.3f}:d=0.35[v];"
             f"[1:a]adelay={int(LEAD * 1000)}|{int(LEAD * 1000)},apad,atrim=0:{total:.3f},"
             f"aformat=sample_rates=48000:channel_layouts=stereo[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium",
             "-crf", "18", "-tune", "stillimage", "-r", "30", "-c:a", "aac", "-b:a", "160k", seg])
        segs.append(seg)
        # legendas: frases distribuídas proporcionalmente ao tamanho
        sentences = subtitle_chunks(beat["text"])
        chars = sum(len(s) for s in sentences)
        cur = t0 + LEAD
        for s in sentences:
            dur = speech * len(s) / chars
            srt.append((cur, cur + dur, s))
            cur += dur
        t0 += total
        print(f"{beat['id']:22s} {total:6.1f}s", flush=True)

    lst = os.path.join(SEGS, "lista.txt")
    with open(lst, "w") as fh:
        fh.writelines(f"file '{s}'\n" for s in segs)
    joined = os.path.join(BUILD, "juntado.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    with open(OUT_SRT, "w", encoding="utf-8") as fh:
        for n, (a, b, s) in enumerate(srt, start=1):
            fh.write(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{s}\n\n")
    # barra de progresso âmbar + legenda como faixa opcional (mov_text) + loudness normalizado
    run(["ffmpeg", "-y", "-i", joined, "-i", OUT_SRT,
         "-f", "lavfi", "-i", f"color=c=0xF5B83D:s={W}x6:r=30:d={t0:.3f}",
         "-filter_complex", f"[0:v][2:v]overlay=x='-W+W*t/{t0:.3f}':y=H-6:shortest=1[v];[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]",
         "-map", "[v]", "-map", "[a]", "-map", "1:s", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-c:s", "mov_text", "-metadata:s:s:0", "language=por",
         "-movflags", "+faststart", OUT_MP4])
    print(f"OK {OUT_MP4} ({t0 / 60:.1f} min)")


if __name__ == "__main__":
    main()

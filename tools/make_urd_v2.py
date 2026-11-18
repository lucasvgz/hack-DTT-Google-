"""
Construit la paire de démo réaliste à partir de l'URD 2025 de BNP Paribas (document public) :
  - samples/urd_v1.pdf : 10 pages du chapitre 4 « États financiers consolidés » (pages imprimées 200 à 209)
  - samples/urd_v2.pdf : même extrait, modifié À LA MAIN directement dans le flux de contenu du PDF
                         (mêmes polices, même mise en page) : chiffres, orthographe, ponctuation,
                         formulation, espace double et saut de ligne déplacé.

Usage : python3 tools/make_urd_v2.py <URD_2025_BNP.pdf>       (nécessite pymupdf)
Source : https://invest.bnpparibas/document/document-d-enregistrement-universel-et-rapport-financier-annuel-2025-pdf
"""
import os
import re
import sys
import pymupdf as fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRST, LAST = 201, 210  # index 0 des pages physiques 202 à 211 = pages imprimées 200 à 209

# (page de l'extrait 0-based, texte d'origine dans UNE instruction TJ, remplacement, n° d'occurrence, motif)
EDITS = [
    # Chiffres
    (0, "350)", "305)", 0, "Chiffres · 4.1 Coût du risque 2025 : (3 350) → (3 305)"),
    (0, "10,29", "10,92", 0, "Chiffres · 4.1 Résultat par action : 10,29 → 10,92 (le résultat dilué reste à 10,29)"),
    (1, "858", "885", 0, "Chiffres · 4.2 Résultat net : 12 858 → 12 885 (incohérent avec le 4.1)"),
    (2, "330", "303", 0, "Chiffres · 4.3 Bilan, caisse et banques centrales : 211 330 → 211 303"),
    (3, "065", "056", 0, "Chiffres · 4.4 Flux de trésorerie, résultat avant impôt : 17 065 → 17 056"),
    (8, "20%", "25%", 0, "Chiffres · 1.b.3 seuil d'influence notable : 20 % → 25 %"),
    # Suppression
    (8, "détient, directement", "détient,", 0, "Suppression · 1.b.3 « directement » retiré"),
    # Orthographe
    (8, "influence notable", "influance notable", 0, "Orthographe · 1.b.3 « influence » → « influance »"),
    (9, "acquisition.", "acquisiiton.", 0, "Orthographe · 1.b.4 « acquisition » → « acquisiiton »"),
    # Ponctuation
    (8, "associées, sont", "associées sont", 0, "Ponctuation · 1.b.3 virgule supprimée"),
    (0, "2026.", "2026", 0, "Ponctuation · 4.1 point final supprimé"),
    # Formulation
    (8, "est présumée", "est supposée", 0, "Formulation · 1.b.3 « présumée » → « supposée » (portée différente)"),
    # Espaces & sauts de ligne
    (1, "d’actifs ", "d’actifs et", 1, "Saut de ligne · titre 4.2 : « et » remonte sur la 1re ligne"),
    (1, "et passifs comptabilisées directement", "passifs comptabilisées directement", 1, "Saut de ligne · titre 4.2 (suite)"),
]


def parse_tounicode(data):
    """CMap ToUnicode -> {gid: caractère}."""
    m = {}
    txt = data.decode("latin-1")
    for block in re.findall(r"beginbfchar(.*?)endbfchar", txt, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            m[int(src, 16)] = bytes.fromhex(dst).decode("utf-16-be", "replace")
    for block in re.findall(r"beginbfrange(.*?)endbfrange", txt, re.S):
        for a, b, rest in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)", block):
            a, b = int(a, 16), int(b, 16)
            if rest.startswith("["):
                for k, h in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", rest)):
                    m[a + k] = bytes.fromhex(h).decode("utf-16-be", "replace")
            else:
                base = int(rest[1:-1], 16)
                for k in range(b - a + 1):
                    m[a + k] = chr(base + k)
    return m


def font_maps(doc, page):
    maps = {}
    for xref, ext, typ, basefont, ref, enc in page.get_fonts():
        tu = doc.xref_get_key(xref, "ToUnicode")
        if tu[0] != "xref":
            continue
        g2u = parse_tounicode(doc.xref_stream(int(tu[1].split()[0])))
        width = 4 if "Identity" in (enc or "") or "Identity" in basefont else 2
        u2g = {}
        for g, u in sorted(g2u.items()):
            u2g.setdefault(u, g)
        maps[ref] = (g2u, u2g, width)
    return maps


TOKEN = re.compile(rb"/([A-Za-z0-9_.+-]+)\s+[-\d.]+\s+Tf|\[((?:[^\]\\]|\\.)*)\]\s*TJ|<([0-9A-Fa-f\s]*)>\s*Tj")
PART = re.compile(rb"<([0-9A-Fa-f\s]*)>|(-?[\d.]+)")


def apply_edit(content, maps, old, new, nth):
    seen = 0
    font = None
    for m in TOKEN.finditer(content):
        if m.group(1):
            font = m.group(1).decode()
            continue
        if font not in maps:
            continue
        g2u, u2g, w = maps[font]
        arr = m.group(2) if m.group(2) is not None else b"<" + m.group(3) + b">"
        parts = []  # ("hex", [gids]) | ("num", bytes)
        text, where = "", []
        for pm in PART.finditer(arr):
            if pm.group(2) is not None:
                parts.append(["num", pm.group(2)])
                continue
            h = re.sub(rb"\s", b"", pm.group(1)).decode()
            gids = [int(h[i:i + w], 16) for i in range(0, len(h), w)]
            for gi, g in enumerate(gids):
                for ch in g2u.get(g, "?"):  # une ligature (fi, fl) = 1 glyphe mais 2 caractères
                    text += ch
                    where.append((len(parts), gi))
            parts.append(["hex", [[g] for g in gids]])
        idx = text.replace("\xa0", " ").find(old)
        if idx < 0:
            continue
        if seen < nth:
            seen += 1
            continue
        missing = [c for c in new if c not in u2g]
        if missing:
            raise ValueError(f"glyphes absents de la police {font} : {missing}")
        # On ne touche qu'aux caractères qui diffèrent : les crénages (nombres du TJ) restent en place
        i = 0
        while i < min(len(old), len(new)) and old[i] == new[i]:
            i += 1
        j = 0
        while j < min(len(old), len(new)) - i and old[-1 - j] == new[-1 - j]:
            j += 1
        mid_old = where[idx + i: idx + len(old) - j]
        mid_new = new[i: len(new) - j]
        if len(mid_old) == len(mid_new):
            for (pi, gi), ch in zip(mid_old, mid_new):
                parts[pi][1][gi] = [u2g[ch]]
        else:
            for pi, gi in mid_old:
                parts[pi][1][gi] = []
            if mid_old:
                pi, gi = mid_old[0]
                parts[pi][1][gi] = [u2g[c] for c in mid_new]
            else:  # insertion pure : après le caractère précédent
                pi, gi = where[idx + i - 1]
                parts[pi][1][gi] = parts[pi][1][gi] + [u2g[c] for c in mid_new]
        out = []
        for kind, val in parts:
            if kind == "num":
                out.append(val)
            else:
                out.append(b"<" + "".join(f"{g:0{w}X}" for grp in val for g in grp).encode() + b">")
        new_op = b"[" + b" ".join(out) + b"]TJ"
        return content[:m.start()] + new_op + content[m.end():]
    raise ValueError(f"introuvable : {old!r} (occurrence {nth})")


def main(src_path):
    src = fitz.open(src_path)
    v1 = fitz.open()
    v1.insert_pdf(src, from_page=FIRST, to_page=LAST)
    meta = {"title": "BNP Paribas - Document d'enregistrement universel 2025 - Extrait chapitre 4 (p. 200-209)",
            "author": "BNP Paribas (document public) - extrait pour démonstration Tickmark"}
    v1.set_metadata(meta)
    out1 = os.path.join(ROOT, "samples", "urd_v1.pdf")
    v1.save(out1, garbage=4, deflate=True)

    v2 = fitz.open(out1)
    for pno in sorted({e[0] for e in EDITS}):
        page = v2[pno]
        page.clean_contents()  # un seul flux de contenu par page
        xref = page.get_contents()[0]
        content = v2.xref_stream(xref)
        maps = font_maps(v2, page)
        for p, old, new, nth, why in EDITS:
            if p == pno:
                content = apply_edit(content, maps, old, new, nth)
                print(f"  p.{pno + 1:>2} · {why}")
        v2.update_stream(xref, content)
    v2.set_metadata({**meta, "title": meta["title"] + " - V2 (modifiée pour la démo)"})
    v2.save(os.path.join(ROOT, "samples", "urd_v2.pdf"), garbage=4, deflate=True)
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "URD_2025_BNP.pdf")

"""
Génère le jeu de démonstration (données FICTIVES) :
  - samples/URD_2025_v1_precedente.pdf
  - samples/URD_2025_v2_nouvelle.pdf
  - js/demo-docs.js (mêmes textes, utilisés par le bouton « Documents de démonstration »)

Usage : python3 tools/generate_samples.py   (depuis la racine du repo, nécessite reportlab)
"""
import json
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

V1 = """DOCUMENT D'ENREGISTREMENT UNIVERSEL 2025
{CLIENT} - Extrait du rapport de gestion (données fictives de démonstration)

1. Message de la Direction générale

L'exercice 2025 a été marqué par une croissance solide de l'ensemble de nos activités,
dans un environnement macroéconomique toujours incertain. Le Groupe a poursuivi
sa stratégie de transformation et a finalisé l'aquisition de la société Nordica Data,
renforçant ainsi ses positions sur le marché européen.

2. Chiffres clés consolidés (en millions d'euros)

Chiffre d'affaires consolidé ........................ 48 831
Résultat opérationnel courant ....................... 11 236
Résultat net part du Groupe ......................... 7 412
Endettement financier net ........................... 3 905
Dividende proposé par action (en euros) ............. 4,60

Le chiffre d'affaires progresse de 6,2 % à périmètre et change constants.
La marge opérationnelle courante s'établit à 23,0 %, en hausse de 80 points de base.

3. Faits marquants de l'exercice

Le 14 mars 2025, le Conseil d'administration a approuvé le plan stratégique 2025-2028.
Le Groupe a émis une obligation verte de 750 millions d'euros à échéance 2032.
Les effectifs s'élèvent à 61 240 collaborateurs au 31 décembre 2025.
\f4. Note 12 - Provisions pour risques et charges

Les provisions pour risques et charges s'élèvent à 1 284 millions d'euros
au 31 décembre 2025, contre 1 197 millions d'euros au 31 décembre 2024.
Elles comprennent principalement des provisions pour litiges, pour restructuration
et pour engagements de retraite. Les provisions sont évaluées selon la norme IAS 37.

5. Événements postérieurs à la clôture

Aucun événement significatif susceptible d'avoir une incidence sur les comptes
consolidés n'est intervenu entre la date de clôture et la date d'arrêté des comptes.

6. Perspectives

Pour l'exercice 2026, le Groupe vise une croissance organique comprise entre 4 % et 6 %
ainsi qu'une amélioration de la marge opérationnelle courante.
Le Conseil proposera à l'Assemblée générale du 22 avril 2026 la distribution
d'un dividende de 4,60 euros par action."""

V2 = """DOCUMENT D'ENREGISTREMENT UNIVERSEL 2025
{CLIENT} - Extrait du rapport de gestion (données fictives de démonstration)

1. Message de la Direction générale

L'exercice 2025 a été marqué par une croissance solide de l'ensemble de nos activités,
dans un environnement macroéconomique encore incertain. Le Groupe a poursuivi
sa stratégie de transformation et a finalisé l'acquisition de la société Nordica Data,
renforçant ses positions sur le marché européen.

2. Chiffres clés consolidés (en millions d'euros)

Chiffre d'affaires consolidé ........................ 48 831
Résultat opérationnel courant ....................... 11 236
Résultat net part du Groupe ......................... 7 421
Endettement financier net ........................... 3 950
Dividende proposé par action (en euros) ............. 4,60

Le chiffre d'affaires progresse de 6,4 % à périmètre et change constants.
La marge opérationnelle courante s'établit à 23,0 %, en hausse de 80 points de base

3. Faits marquants de l'exercice

Le 14 mars 2025 le Conseil d'administration a approuvé le plan stratégique 2025–2028.
Le Groupe a émis une obligation verte  de 750 millions d'euros à échéance 2032.
Les effectifs s'élèvent à 61 420 collaborateurs au 31 décembre 2025.
\f4. Note 12 - Provisions pour risques et charges

Les provisions pour risques et charges s'élèvent à 1 284 millions d'euros
au 31 décembre 2025, contre 1 197 millions d'euros au 31 décembre 2024.
Elles comprenent principalement des provisions pour litiges, pour restructuration et pour
engagements de retraite. Les provisions sont évaluées conformément à la norme IAS 37.


5. Événements postérieurs à la clôture

Aucun événement significatif susceptible d'avoir une incidence sur les comptes
consolidés n'est intervenu entre la date de clôture et la date d'arrêté des comptes.
Le 12 février 2026, le Groupe a annoncé la cession de sa filiale Baltic Logistics.

6. Perspectives

Pour l'exercice 2026, le Groupe vise une croissance organique comprise entre 4 % et 5 %
ainsi qu'une amélioration de la marge opérationnelle courante.
Le Conseil proposera à l'Assemblée Générale du 22 avril 2026 la distribution
d'un dividende de 4,50 euros par action."""


def write_pdf(text, path, label):
    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(f"URD 2025 - extrait fictif - {label}")
    w, h = A4
    for page in text.split("\f"):
        y = h - 70
        c.setFont("Helvetica", 7)
        c.drawString(60, h - 40, "DONNEES FICTIVES - jeu de test Tickmark")
        for i, line in enumerate(page.split("\n")):
            bold = line[:2].strip().rstrip(".").isdigit() or line.startswith("DOCUMENT")
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
            if line:
                c.drawString(60, y, line)
            y -= 15
        c.showPage()
    c.save()


if __name__ == "__main__":
    client = "Groupe Exemple"
    write_pdf(V1.replace("{CLIENT}", client), os.path.join(ROOT, "samples", "URD_2025_v1_precedente.pdf"), "version precedente")
    write_pdf(V2.replace("{CLIENT}", client), os.path.join(ROOT, "samples", "URD_2025_v2_nouvelle.pdf"), "nouvelle version")
    with open(os.path.join(ROOT, "js", "demo-docs.js"), "w", encoding="utf-8") as f:
        f.write("// Généré par tools/generate_samples.py — données FICTIVES de démonstration.\n")
        f.write(f"export const DEMO_BEFORE = {json.dumps(V1, ensure_ascii=False)};\n")
        f.write(f"export const DEMO_AFTER = {json.dumps(V2, ensure_ascii=False)};\n")
    print("ok")

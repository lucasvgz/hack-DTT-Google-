"""Generates realistic sample enterprise URD PDFs (V0, V1, URD N-1) embedding all 15 error & diff types."""

from __future__ import annotations

from pathlib import Path
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _table_style(header_bg=colors.HexColor("#1f3a5f")) -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), header_bg),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ]
    )


def _build_bar_chart(title: str, values: list[float], labels: list[str]) -> Drawing:
    d = Drawing(420, 180)
    bc = VerticalBarChart()
    bc.x = 50
    bc.y = 30
    bc.height = 115
    bc.width = 320
    bc.data = [values]
    bc.categoryAxis.categoryNames = labels
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max(values) * 1.25
    bc.bars[0].fillColor = colors.HexColor("#2b6cb0")
    d.add(bc)
    for i, val in enumerate(values):
        x = bc.x + (i + 0.5) * (bc.width / len(values)) - 12
        y = bc.y + (val / bc.valueAxis.valueMax) * bc.height + 5
        d.add(String(x, y, f"{int(val)} M€", fontSize=8, fillColor=colors.black))
    return d


def generate_samples(out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    body_red_bold = ParagraphStyle(
        "BodyRedBold",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#9b2c2c"),
    )

    # 1. URD N-1 (2024 published)
    p_n1 = out / "URD_2024_Publie.pdf"
    doc_n1 = SimpleDocTemplate(str(p_n1), pagesize=A4)
    story_n1 = [
        Paragraph("Document d'Enregistrement Universel 2024", h1),
        Paragraph("Version Finale Publiée — 15 mars 2025", body),
        Spacer(1, 14),
        Paragraph("1. Compte de résultat consolidé (en M€)", h2),
        Table(
            [
                ["Agrégat (en M€)", "2024", "2023", "Var %"],
                ["Chiffre d'affaires", "1 200", "1 100", "+9,1 %"],
                ["EBITDA", "280", "250", "+12,0 %"],
                ["Résultat net", "110", "95", "+15,8 %"],
            ],
            style=_table_style(),
        ),
    ]
    doc_n1.build(story_n1)

    # 2. URD 2025 V0 (Draft)
    p_v0 = out / "URD_2025_V0_Brouillon.pdf"
    doc_v0 = SimpleDocTemplate(str(p_v0), pagesize=A4)
    story_v0 = [
        Paragraph("Document d'Enregistrement Universel 2025 — Version 0 (Brouillon)", h1),
        Paragraph("Projet préliminaire du 10 mars 2026 — Confidentiel [À compléter]", body),
        Spacer(1, 12),
        Paragraph("Table de concordance AMF", h2),
        Table(
            [
                ["Information réglementaire", "Page"],
                ["Rapport de gestion et performance", "2"],
                ["Facteurs de risques", "4"],
            ],
            style=_table_style(),
        ),
        PageBreak(),
        Paragraph("1. Rapport de gestion et performance financière", h1),
        Paragraph(
            "En 2025, le groupe affiche un chiffre d'affaires consolidé en hausse de +8,3 % à 1 300 M€.",
            body,
        ),
        Paragraph("Gouvernance : la politique de rémunération est stable par rapport à 2024.", body),
        Spacer(1, 10),
        Paragraph("Tableau 1 : Synthèse financière (en M€)", h2),
        Table(
            [
                ["Agrégat (en M€)", "2025", "2024", "Var %"],
                ["Chiffre d'affaires", "1 300", "1 200", "+8,3 %"],
                ["EBITDA", "310", "280", "+10,7 %"],
                ["Total performance opérationnelle", "1 610", "1 480", "+8,8 %"],
            ],
            style=_table_style(),
        ),
        Spacer(1, 10),
        Paragraph("Tableau 2 : Détail des coûts de structure (en M€)", h2),
        Table(
            [
                ["Poste (en M€)", "2025", "2024"],
                ["Frais généraux", "500,0", "490,0"],
                ["Marketing", "120,0", "115,0"],
                ["Total coûts", "620,0", "605,0"],
            ],
            style=_table_style(),
        ),
        PageBreak(),
        Paragraph("2. Annexes et Notes aux états financiers", h1),
        Paragraph("Note 1 : Périmètre et effectifs (5 200 ETP).", body),
        Spacer(1, 8),
        Paragraph("3. Déclaration de durabilité CSRD", h1),
        Paragraph("Les effectifs moyens du périmètre CSRD s'élèvent à 5 200 ETP.", body),
        PageBreak(),
        Paragraph("4. Facteurs de risques et litiges", h1),
        Paragraph(
            "Le groupe est exposé à un litige fiscal provisionné à hauteur de 18 M€ et à des risques de dépréciation.",
            body,
        ),
    ]
    doc_v0.build(story_v0)

    # 3. URD 2025 V1 (Amended version containing diffs & embedded errors across all 15 controls)
    p_v1 = out / "URD_2025_V1_Amende.pdf"
    doc_v1 = SimpleDocTemplate(str(p_v1), pagesize=A4)
    story_v1 = [
        Paragraph("Document d'Enregistrement Universel 2025 — Version 1 (Amendée)", h1),
        Paragraph("Version de dépôt AMF du 28 mars 2026", body),
        Spacer(1, 12),
        Paragraph("Table de concordance AMF", h2),
        Table(
            [
                ["Information réglementaire", "Page"],
                ["Rapport de gestion et performance", "2"],
                ["Facteurs de risques et litiges", "9"],  # Error 3: wrong page number (page 9 doesn't exist!)
            ],
            style=_table_style(),
        ),
        PageBreak(),
        Paragraph("1. Rapport de gestion et performance financière", h1),
        # Error 8: Text says +5,0 % while table shows -8,3 % / +8,3 %
        Paragraph(
            "En 2025, le groupe affiche un chiffre d'affaires consolidé en hausse de +5,0 % à 1 300 M€. Voir cf. Note 14.",
            body,
        ),
        # Form diff: same text as V0, changed font/size/color/bold!
        Paragraph("Gouvernance : la politique de rémunération est stable par rapport à 2024.", body_red_bold),
        Spacer(1, 8),
        # Error 1 (arithmétique) + Error 2 (variation sign inverted) + Error 4/12 (2024 N-1 changed to 1 180)
        Paragraph("Tableau 1 : Synthèse financière (en M€)", h2),
        Table(
            [
                ["Agrégat (en M€)", "2025", "2024", "Var %"],
                ["Chiffre d'affaires", "1 300", "1 180", "-8,3 %"],
                ["EBITDA", "310", "280", "+10,7 %"],
                ["Total performance opérationnelle", "1 640", "1 460", "+8,8 %"],  # 1300+310=1610 != 1640
            ],
            style=_table_style(),
        ),
        Spacer(1, 8),
        # Minor numeric diff for Materiality check 13 (500.0 -> 500.5)
        Paragraph("Tableau 2 : Détail des coûts de structure (en M€)", h2),
        Table(
            [
                ["Poste (en M€)", "2025", "2024"],
                ["Frais généraux", "500,5", "490,0"],
                ["Marketing", "120,0", "115,0"],
                ["Total coûts", "620,5", "605,0"],
            ],
            style=_table_style(),
        ),
        Spacer(1, 10),
        # Error 10: Chart vs table mismatch (chart shows 1450 M€ vs 1300 M€)
        Paragraph("Graphique 1 : Évolution du Chiffre d'affaires (Synthèse financière)", h2),
        _build_bar_chart("Synthèse financière", [1180, 1300, 1450], ["2024", "2025 T", "2025 Bar"]),
        PageBreak(),
        Paragraph("2. Annexes et Notes aux états financiers", h1),
        Paragraph("Note 1 : Périmètre IFRS 5 — Retraitement N-1 des activités abandonnées et effectifs (5 200 ETP).", body),
        # Error 6: ESEF negative sign tag issue
        Paragraph('Balise ESEF : <ix:nonFraction name="ifrs-full:ProfitLoss">-42,5</ix:nonFraction>', body),
        Spacer(1, 8),
        # Error 7 (EBITDA=295 != 310) + Error 5 (columns inverted 2024 | 2025) + Error 9 (title k€ vs M€)
        Paragraph("Tableau 3 : Réconciliation des agrégats en annexes (en k€)", h2),
        Table(
            [
                ["Agrégat (en M€)", "2024", "2025"],
                ["Chiffre d'affaires", "1 200", "1 300"],
                ["EBITDA", "270", "295"],
                ["Total", "1 470", "1 595"],
            ],
            style=_table_style(),
        ),
        Spacer(1, 8),
        Paragraph("3. Déclaration de durabilité CSRD", h1),
        # Error 11: CSRD headcount mismatch (4 850 vs 5 200 ETP) + Error 15: Greenwashing / IAP
        Paragraph(
            "Le groupe est désormais neutre en carbone avec un EBITDA ajusté record. "
            "Les effectifs moyens du périmètre CSRD s'élèvent à 4 850 ETP.",
            body,
        ),
        Paragraph("Section en cours : [À compléter]", body),
        PageBreak(),
        Paragraph("4. Facteurs de risques et litiges", h1),
        # Error 14: Risk factor modified (litige reduced from 18 M€ to 4 M€)
        Paragraph(
            "Le groupe est exposé à un litige fiscal mineur provisionné à hauteur de 4 M€.",
            body,
        ),
    ]
    doc_v1.build(story_v1)

    return {"v0": p_v0, "v1": p_v1, "urd_n_minus_1": p_n1}


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent / "sample_data"
    paths = generate_samples(base)
    for k, v in paths.items():
        print(f"Generated {k}: {v}")

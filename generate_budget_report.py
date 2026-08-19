#!/usr/bin/env python3
"""
Generate a one-page-per-department Budget vs Actual PDF report.

Input CSV columns required:
    Month (Year), Department(BM), budgeted_cost, actuals_cost

Example:
    python generate_budget_report.py \
        --csv Budget_vs_Actual_Cost.csv \
        --output Budget_vs_Actual_Report.pdf \
        --last-month 2026-07 \
        --vat-rate 0.20
"""

import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether
)


REQUIRED_COLUMNS = {
    "Month (Year)",
    "Department(BM)",
    "budgeted_cost",
    "actuals_cost",
    "Vendor"
}


def money(value):
    """Format a number as a readable cost value."""
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"£{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"£{value / 1_000:.1f}K"
    return f"£{value:,.0f}"

def full_money(value):
    return f"£{float(value):,.2f}"

def pct(value):
    return f"{float(value):.1f}%"

def clean_data(df, cloud_name):
    # Work on a copy so the original dataframe is not modified
    df = df.copy()

    # Normalize text columns
    df["Vendor"] = df["Vendor"].astype(str).str.strip().str.lower()
    df["Department(BM)"] = df["Department(BM)"].astype(str).str.strip().str.lower()

    # Split into Azure and GCP
    df = df[df["Vendor"] == cloud_name].copy()

    overall = df.groupby("month", as_index=False).agg(
        budgeted_cost=("budgeted_cost", "sum"),
        actuals_cost=("actuals_cost", "sum")
    )

    overall["Department(BM)"] = cloud_name
    overall["Vendor"] = cloud_name

    df = pd.concat([overall, df],ignore_index=True)
    df = df[df["Department(BM)"] != "not set"].copy()
    
    totals = (
            df
            .groupby("Department(BM)", as_index=False)
            .agg(
                total_budget=("budgeted_cost", "sum"),
                total_actual=("actuals_cost", "sum")
            )
        )
    
    valid_departments = totals[
            (totals["total_budget"] != 0) |
            (totals["total_actual"] != 0)
        ]["Department(BM)"]

    df = df[
            df["Department(BM)"].isin(valid_departments)
        ].copy()


    return df

def make_chart(department_df, department, last_month, output_dir):
    """Create monthly Budget vs Actual Incl. VAT column chart."""
    d = department_df.sort_values("month").copy()
    d = d[d["month"] <= last_month]

    # Aggregate defensively in case the input contains duplicate rows.
    monthly = (
        d.groupby("month", as_index=False)
        .agg(
            budget=("budgeted_cost", "sum"),
            actual=("actuals_cost", "sum"),
        )
    )

    monthly["actual_incl_vat"] = monthly["actual"] * 1.20

    # Display all months from Jan through the selected last month.
    labels = monthly["month"].dt.strftime("%b").tolist()
    x = range(len(monthly))

    width = 0.4
    gap = 0.08

    # Increased height
    fig, ax = plt.subplots(figsize=(12, 5.2), dpi=150)

    budget_bars = ax.bar(
        [i - (width + gap) / 2 for i in x],
        monthly["budget"],
        width=width,
        color="#1f77b4",
        label="Budget Cost",
    )

    actual_bars = ax.bar(
        [i + (width + gap) / 2 for i in x],
        monthly["actual_incl_vat"],
        width=width,
        color="#ff7f0e",
        label="Actual Cost incl. VAT",
    )

    # Add values above bars
    ax.bar_label(
        budget_bars,
        fmt=lambda x: f"£{x:,.0f}",
        padding=3,
        fontsize=8
    )

    ax.bar_label(
        actual_bars,
        fmt=lambda x: f"£{x:,.0f}",
        padding=3,
        fontsize=8
    )

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)

    ax.set_xlabel("Month")
    ax.set_ylabel("Cost")

    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v:,.0f}")
    )

    ax.grid(
        axis="y",
        linestyle="--",
        alpha=0.25
    )

    ax.set_axisbelow(True)

    # Add 15% space above the tallest bar
    max_cost = max(
        monthly["budget"].max(),
        monthly["actual_incl_vat"].max()
    )

    ax.set_ylim(0, max_cost * 1.15)

    # Legend
    ax.legend(
        loc="upper right",
        bbox_to_anchor=(1, 1.08),
        frameon=False,
        ncols=2
    )

    ax.set_title(
        "Monthly Budget vs Actual Cost (incl. VAT)",
        loc="left",
        fontsize=12,
        fontweight="bold"
    )

    ax.margins(x=0.02)

    # Leave room for title and legend
    fig.tight_layout(rect=[0, 0, 1, 0.92])

    safe_name = "".join(
        c if c.isalnum() or c in ("-", "_") else "_"
        for c in department
    )

    chart_path = output_dir / f"{safe_name}.png"

    fig.savefig(
        chart_path,
        bbox_inches="tight"
    )

    plt.close(fig)

    return chart_path

def build_report(csv_path, output_pdf, last_month, vat_rate):
    df = pd.read_csv(csv_path)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    df["month"] = pd.to_datetime(df["Month (Year)"], format="%Y-%m", errors="raise")
    df["budgeted_cost"] = pd.to_numeric(df["budgeted_cost"], errors="raise")
    df["actuals_cost"] = pd.to_numeric(df["actuals_cost"], errors="raise")
    df["Department(BM)"] = df["Department(BM)"].astype(str).str.strip()
    df["Vendor"] = df["Vendor"].astype(str).str.strip()


    last_month_dt = pd.Period(last_month, freq="M").to_timestamp()
    year = last_month_dt.year

    # Use only the selected year.
    # df = df[df["month"].dt.year == year].copy()
    # if df.empty:
    #     raise ValueError(f"No data found for year {year}")

    # Validate that the selected last month exists.
    if last_month_dt not in set(df["month"].unique()):
        raise ValueError(f"Selected last month {last_month} is not present in the CSV.")

    # Temporary chart directory.
    chart_dir = Path(output_pdf).parent / "_budget_report_charts"
    chart_dir.mkdir(parents=True, exist_ok=True)


    for cloud_name in ['azure', 'gcp']:
        # ======================================================================
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#172033"),
            spaceAfter=3 * mm,
        )
        subtitle_style = ParagraphStyle(
            "Subtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=colors.HexColor("#657085"),
            leading=11,
        )
        widget_label = ParagraphStyle(
            "WidgetLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.HexColor("#657085"),
            leading=10,
        )
        widget_value = ParagraphStyle(
            "WidgetValue",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=colors.HexColor("#172033"),
            leading=18,
        )
        widget_detail = ParagraphStyle(
            "WidgetDetail",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            textColor=colors.HexColor("#657085"),
            leading=9,
        )

        doc = SimpleDocTemplate(
            f"{cloud_name}_{output_pdf}",
            pagesize=A4,
            rightMargin=12 * mm,
            leftMargin=12 * mm,
            topMargin=10 * mm,
            bottomMargin=10 * mm,
            title="Budget vs Actual Cost Report",
            author="Python",
        )

        page_width = A4[0] - 24 * mm
        widget_width = (page_width - 3 * 4 * mm) / 4

        story = []
        # ======================================================================

        new_df = clean_data(df, cloud_name)
        departments = sorted(new_df["Department(BM)"].unique())

        for page_index, department in enumerate(departments):
            dept = new_df[new_df["Department(BM)"] == department].copy()

            # Budget for the whole year.
            annual_budget = dept["budgeted_cost"].sum()

            # Budget through the selected last month.
            ytd = dept[dept["month"] <= last_month_dt]
            budget_to_last_month = ytd["budgeted_cost"].sum()

            # Actual for the selected last month, including VAT.
            ytd = dept[dept["month"] <= last_month_dt]

            budget_to_last_month = ytd["budgeted_cost"].sum()

            actual_to_last_month_ex_vat = ytd["actuals_cost"].sum()
            actual_to_last_month_incl_vat = actual_to_last_month_ex_vat * (1 + vat_rate)

            # Variance is based on the selected last month's budget.
            last_month_budget = ytd["budgeted_cost"].sum()
            variance = actual_to_last_month_incl_vat - last_month_budget
            variance_pct = (
                (variance / last_month_budget) * 100
                if last_month_budget != 0 else None
            )

            story.append(Paragraph(
                f"Budget vs Actual Cost — {department}",
                title_style
            ))
            story.append(Paragraph(
                f"Year: {year} &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Reporting through: {last_month_dt.strftime('%B %Y')} "
                f"&nbsp;&nbsp;|&nbsp;&nbsp; VAT: {vat_rate:.0%}",
                subtitle_style
            ))
            story.append(Spacer(1, 5 * mm))

            variance_text = (
                f"{full_money(variance)} ({pct(variance_pct)})"
                if variance_pct is not None
                else f"{full_money(variance)} (N/A)"
            )

            widget_contents = [
                [
                    Paragraph("BUDGET FOR THE YEAR", widget_label),
                    Spacer(1, 5 * mm),
                    Paragraph(full_money(annual_budget), widget_value),
                    Spacer(1, 5 * mm),
                    Paragraph("Sum of monthly budget", widget_detail),
                ],
                [
                    Paragraph(f"BUDGET TO {last_month_dt.strftime('%B').upper()}", widget_label),
                    Spacer(1, 5 * mm),
                    Paragraph(full_money(budget_to_last_month), widget_value),
                    Spacer(1, 5 * mm),
                    Paragraph("Jan through reporting month", widget_detail),
                ],
                [
                    Paragraph("ACTUAL TO LAST MONTH INCL. VAT", widget_label),
                    Spacer(1, 5 * mm),
                    Paragraph(full_money(actual_to_last_month_incl_vat), widget_value),
                    Spacer(1, 5 * mm),
                    Paragraph(
                        f"Ex-VAT: {full_money(actual_to_last_month_ex_vat)}",
                        widget_detail
                    ),
                ],
                [
                    Paragraph("VARIANCE VS LAST-MONTH BUDGET", widget_label),
                    Spacer(1, 5 * mm),
                    Paragraph(variance_text, widget_value),
                    Spacer(1, 5 * mm),
                    Paragraph(
                        "(Actual incl. VAT − Budget) / Budget × 100",
                        widget_detail
                    ),
                ],
            ]

            widget_table = Table(
                [widget_contents],
                colWidths=[widget_width] * 4,
            )
            
            # widget_table.setStyle(TableStyle([
            #     ("VALIGN", (0, 0), (-1, -1), "TOP"),
            # ]))
            widget_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            widget_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F7FA")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D9DEE7")),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#D9DEE7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]))
            story.append(widget_table)
            story.append(Spacer(1, 7 * mm))

            chart_path = make_chart(dept, department, last_month_dt, chart_dir)
            chart = Image(str(chart_path), width=page_width, height=86 * mm)
            story.append(chart)

            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph(
                "Variance % formula: (Actual cost including VAT − Budget cost) / "
                "Budget cost × 100. Monthly actual cost is calculated as "
                f"actuals_cost × (1 + {vat_rate:.0%}).",
                subtitle_style
            ))

            if page_index < len(departments) - 1:
                story.append(PageBreak())

        doc.build(story)
        print(f"Report generated for {cloud_name}: {cloud_name}_{output_pdf}")
        print(f"Departments/pages: {len(departments)}")
        print(f"Reporting through: {last_month}")

    # Remove generated chart images after the PDF has been built.
    for path in chart_dir.glob("*.png"):
        path.unlink(missing_ok=True)
    try:
        chart_dir.rmdir()
    except OSError:
        pass

    print("Budget report for Azure and GCP have been created successfully!")

def main():
    parser = argparse.ArgumentParser(description="Generate department budget vs actual PDF report.")
    parser.add_argument("--csv", required=True, help="Input CSV file")
    parser.add_argument("--output", default="Budget_vs_Actual_Report.pdf", help="Output PDF")
    parser.add_argument(
        "--last-month",
        default="2026-07",
        help="Last month to include in the report, YYYY-MM. Default: 2026-07",
    )
    parser.add_argument(
        "--vat-rate",
        type=float,
        default=0.20,
        help="VAT rate as decimal. Default: 0.20 (20%%)",
    )
    args = parser.parse_args()

    build_report(
        Path(args.csv),
        Path(args.output),
        args.last_month,
        args.vat_rate,
    )


if __name__ == "__main__":
    main()

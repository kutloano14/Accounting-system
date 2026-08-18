from __future__ import annotations

import base64
import re
from io import BytesIO
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _title_block(story: list, title: str, company: dict, period_label: str | None = None):
    styles = getSampleStyleSheet()
    company_name = company.get("company_name") or "My Company"
    right_lines = [
        x
        for x in [
            company.get("address", ""),
            company.get("email", ""),
            company.get("phone", ""),
            f"Tax: {company.get('tax_number', '')}" if company.get("tax_number") else "",
        ]
        if x
    ]
    right_text = "<br/>".join(right_lines)

    header_tbl = Table(
        [[Paragraph(f"<b>{company_name}</b>", styles["Title"]), Paragraph(right_text, styles["Normal"]) if right_text else ""]],
        colWidths=[110 * mm, None],
    )
    header_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header_tbl)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"<b>{title}</b>", styles["Heading2"]))
    if period_label:
        story.append(Paragraph(f"Period: {period_label}", styles["Normal"]))
    story.append(Spacer(1, 3 * mm))


def _table(data: list[list], col_widths=None, extra_styles: list[tuple] | None = None):
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1D3557")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9D5EA")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FBFF")]),
    ]
    if extra_styles:
        style_commands.extend(extra_styles)
    tbl.setStyle(TableStyle(style_commands))
    return tbl


def _fmt_money(value) -> str:
    return f"{float(value or 0):,.2f}"


def _logo_cell(company_profile: dict, width_mm: float = 18, default_initials: str = "CO", style=None):
    data_url = str(company_profile.get("logo_data_url") or "").strip()
    if not data_url.startswith("data:image/"):
        if style is None:
            style = getSampleStyleSheet()["Normal"]
        return Paragraph(f"<font size=16><b>{default_initials}</b></font>", style)

    try:
        header, payload = data_url.split(",", 1)
        if "base64" not in header.lower() or not payload:
            raise ValueError("Unsupported image format")
        image_bytes = base64.b64decode(payload, validate=True)
        img = ImageReader(BytesIO(image_bytes))
        return Image(img, width=width_mm * mm, height=max(12, width_mm) * mm)
    except Exception:
        if style is None:
            style = getSampleStyleSheet()["Normal"]
        return Paragraph(f"<font size=16><b>{default_initials}</b></font>", style)


def _map_rows_by_code(rows: list[dict]) -> dict[str, dict]:
    mapped: dict[str, dict] = {}
    for row in rows or []:
        code = str(row.get("code") or "").strip()
        if code:
            mapped[code] = row
    return mapped


def _build_balance_sheet_table(data: dict, compare_data: dict | None, period_label: str | None, compare_label: str | None) -> Table:
    if compare_data is not None:
        rows = [["Section", "Code", "Description", period_label or "Current", compare_label or "Comparative"]]
        amount_col_start = 3
    else:
        rows = [["Section", "Code", "Description", "Amount"]]
        amount_col_start = 3

    section_rows: list[int] = []
    subtotal_rows: list[int] = []
    total_rows: list[int] = []

    def add_section(title: str):
        rows.append([title, "", "", "", ""] if compare_data is not None else [title, "", "", ""])
        section_rows.append(len(rows) - 1)

    def add_line(section: str, item: dict, compare_item: dict | None = None):
        if compare_data is not None:
            rows.append([
                section,
                item.get("code"),
                item.get("name"),
                _fmt_money(item.get("amount", 0)),
                _fmt_money((compare_item or {}).get("amount", 0)),
            ])
        else:
            rows.append([section, item.get("code"), item.get("name"), _fmt_money(item.get("amount", 0))])

    def add_subtotal(label: str, current_value, compare_value=None):
        if compare_data is not None:
            rows.append(["", "", label, _fmt_money(current_value), _fmt_money(compare_value)])
        else:
            rows.append(["", "", label, _fmt_money(current_value)])
        subtotal_rows.append(len(rows) - 1)

    def add_total(label: str, current_value, compare_value=None):
        if compare_data is not None:
            rows.append(["", "", label, _fmt_money(current_value), _fmt_money(compare_value)])
        else:
            rows.append(["", "", label, _fmt_money(current_value)])
        total_rows.append(len(rows) - 1)

    ca_compare = _map_rows_by_code(compare_data.get("current_assets", [])) if compare_data else {}
    nca_compare = _map_rows_by_code(compare_data.get("non_current_assets", [])) if compare_data else {}
    cl_compare = _map_rows_by_code(compare_data.get("current_liabilities", [])) if compare_data else {}
    ncl_compare = _map_rows_by_code(compare_data.get("non_current_liabilities", [])) if compare_data else {}
    eq_compare = _map_rows_by_code(compare_data.get("equity", [])) if compare_data else {}

    add_section("Assets")
    add_section("Current Assets")
    for r in data.get("current_assets", []):
        add_line("", r, ca_compare.get(str(r.get("code") or "").strip()))
    add_subtotal("Total Current Assets", data.get("total_current_assets", 0), (compare_data or {}).get("total_current_assets", 0))

    add_section("Non-Current Assets")
    for r in data.get("non_current_assets", []):
        add_line("", r, nca_compare.get(str(r.get("code") or "").strip()))
    add_subtotal("Total Non-Current Assets", data.get("total_non_current_assets", 0), (compare_data or {}).get("total_non_current_assets", 0))
    add_total("Total Assets", data.get("total_assets", 0), (compare_data or {}).get("total_assets", 0))

    add_section("Liabilities")
    add_section("Current Liabilities")
    for r in data.get("current_liabilities", []):
        add_line("", r, cl_compare.get(str(r.get("code") or "").strip()))
    add_subtotal("Total Current Liabilities", data.get("total_current_liabilities", 0), (compare_data or {}).get("total_current_liabilities", 0))

    add_section("Non-Current Liabilities")
    for r in data.get("non_current_liabilities", []):
        add_line("", r, ncl_compare.get(str(r.get("code") or "").strip()))
    add_subtotal("Total Non-Current Liabilities", data.get("total_non_current_liabilities", 0), (compare_data or {}).get("total_non_current_liabilities", 0))
    add_total("Total Liabilities", data.get("total_liabilities", 0), (compare_data or {}).get("total_liabilities", 0))

    add_section("Equity")
    for r in data.get("equity", []):
        add_line("", r, eq_compare.get(str(r.get("code") or "").strip()))
    add_subtotal("Retained Earnings", data.get("retained_earnings", 0), (compare_data or {}).get("retained_earnings", 0))
    add_total("Total Equity", data.get("total_equity", 0), (compare_data or {}).get("total_equity", 0))

    if compare_data is not None:
        rows.append(["", "", "Assets = Liabilities + Equity", "Yes" if data.get("balanced") else "No", "Yes" if compare_data.get("balanced") else "No"])
    else:
        rows.append(["", "", "Assets = Liabilities + Equity", "Yes" if data.get("balanced") else "No"])
    total_rows.append(len(rows) - 1)

    extra_styles: list[tuple] = [
        ("ALIGN", (amount_col_start, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (2, 1), (2, -1), 10),
    ]
    for idx in section_rows:
        extra_styles.extend(
            [
                ("FONTNAME", (0, idx), (-1, idx), "Helvetica-Bold"),
                ("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#EEF4FF")),
            ]
        )
    for idx in subtotal_rows:
        extra_styles.extend(
            [
                ("FONTNAME", (0, idx), (-1, idx), "Helvetica-Bold"),
                ("LINEABOVE", (2, idx), (-1, idx), 0.5, colors.HexColor("#94AACC")),
            ]
        )
    for idx in total_rows:
        extra_styles.extend(
            [
                ("FONTNAME", (0, idx), (-1, idx), "Helvetica-Bold"),
                ("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#E3EEFF")),
                ("LINEABOVE", (2, idx), (-1, idx), 0.8, colors.HexColor("#5E7FAF")),
            ]
        )

    return _table(rows, extra_styles=extra_styles)


def build_report_pdf(
    report_name: str,
    data,
    company_profile: dict,
    period_label: str | None = None,
    compare_data=None,
    compare_label: str | None = None,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)

    story = []

    if report_name == "trial-balance":
        _title_block(story, "Trial Balance", company_profile, period_label)
        if compare_data is not None:
            rows = [["Code", "Account", period_label or "Current", compare_label or "Comparative"]]
            compare_map = {
                f"{str(r.get('account_code') or '').strip()}::{str(r.get('account_name') or '').strip().lower()}": r
                for r in (compare_data or [])
            }
            for r in data:
                key = f"{str(r.get('account_code') or '').strip()}::{str(r.get('account_name') or '').strip().lower()}"
                c = compare_map.get(key, {})
                rows.append([
                    r.get("account_code"),
                    r.get("account_name"),
                    _fmt_money(r.get("net", 0)),
                    _fmt_money(c.get("net", 0)),
                ])
        else:
            rows = [["Code", "Account", "Debit", "Credit", "Net"]]
            for r in data:
                rows.append([
                    r.get("account_code"),
                    r.get("account_name"),
                    _fmt_money(r.get("debit", 0)),
                    _fmt_money(r.get("credit", 0)),
                    _fmt_money(r.get("net", 0)),
                ])
        story.append(_table(rows))

    elif report_name == "profit-loss":
        _title_block(story, "Profit and Loss Statement", company_profile, period_label)
        if compare_data is not None:
            rows = [["Section", "Code", "Name", period_label or "Current", compare_label or "Comparative"]]
            income_compare = _map_rows_by_code(compare_data.get("income", []))
            expense_compare = _map_rows_by_code(compare_data.get("expenses", []))

            for r in data.get("income", []):
                c = income_compare.get(str(r.get("code") or "").strip(), {})
                rows.append(["Income", r.get("code"), r.get("name"), _fmt_money(r.get("amount", 0)), _fmt_money(c.get("amount", 0))])

            for r in data.get("expenses", []):
                c = expense_compare.get(str(r.get("code") or "").strip(), {})
                rows.append(["Expense", r.get("code"), r.get("name"), _fmt_money(r.get("amount", 0)), _fmt_money(c.get("amount", 0))])

            rows.append(["Summary", "", "Total Income", _fmt_money(data.get("total_income", 0)), _fmt_money(compare_data.get("total_income", 0))])
            rows.append(["Summary", "", "Total Expense", _fmt_money(data.get("total_expense", 0)), _fmt_money(compare_data.get("total_expense", 0))])
            rows.append(["Summary", "", "Net Profit", _fmt_money(data.get("net_profit", 0)), _fmt_money(compare_data.get("net_profit", 0))])
        else:
            rows = [["Section", "Code", "Name", "Amount"]]
            for r in data.get("income", []):
                rows.append(["Income", r.get("code"), r.get("name"), _fmt_money(r.get("amount", 0))])
            for r in data.get("expenses", []):
                rows.append(["Expense", r.get("code"), r.get("name"), _fmt_money(r.get("amount", 0))])
            rows.append(["Summary", "", "Total Income", _fmt_money(data.get("total_income", 0))])
            rows.append(["Summary", "", "Total Expense", _fmt_money(data.get("total_expense", 0))])
            rows.append(["Summary", "", "Net Profit", _fmt_money(data.get("net_profit", 0))])
        story.append(_table(rows))

    elif report_name == "balance-sheet":
        _title_block(story, "Balance Sheet", company_profile, period_label)
        story.append(_build_balance_sheet_table(data, compare_data, period_label, compare_label))

    elif report_name == "cash-flow":
        _title_block(story, "Cash Flow Statement", company_profile, period_label)
        if compare_data is not None:
            rows = [["Summary Line", period_label or "Current", compare_label or "Comparative"]]
            rows.append(["Net Cash from Operating Activities", _fmt_money(data.get("net_cash_from_operating", 0)), _fmt_money(compare_data.get("net_cash_from_operating", 0))])
            rows.append(["Net Cash from Investing Activities", _fmt_money(data.get("net_cash_from_investing", 0)), _fmt_money(compare_data.get("net_cash_from_investing", 0))])
            rows.append(["Net Cash from Financing Activities", _fmt_money(data.get("net_cash_from_financing", 0)), _fmt_money(compare_data.get("net_cash_from_financing", 0))])
            rows.append(["Net Increase in Cash", _fmt_money(data.get("net_increase_in_cash", 0)), _fmt_money(compare_data.get("net_increase_in_cash", 0))])
            rows.append(["Opening Cash Balance", _fmt_money(data.get("opening_cash_balance", 0)), _fmt_money(compare_data.get("opening_cash_balance", 0))])
            rows.append(["Closing Cash Balance", _fmt_money(data.get("closing_cash_balance", 0)), _fmt_money(compare_data.get("closing_cash_balance", 0))])
        else:
            rows = [["Section", "Date", "Description", "Account", "Amount"]]
            for r in data.get("operating_activities", []):
                rows.append(["Operating", str(r.get("date", "")), r.get("description"), r.get("account") or "", _fmt_money(r.get("amount", 0))])
            for r in data.get("investing_activities", []):
                rows.append(["Investing", str(r.get("date", "")), r.get("description"), r.get("account") or "", _fmt_money(r.get("amount", 0))])
            for r in data.get("financing_activities", []):
                rows.append(["Financing", str(r.get("date", "")), r.get("description"), r.get("account") or "", _fmt_money(r.get("amount", 0))])
            rows.append(["Summary", "", "Net Increase in Cash", "", _fmt_money(data.get("net_increase_in_cash", 0))])
            rows.append(["Summary", "", "Opening Cash", "", _fmt_money(data.get("opening_cash_balance", 0))])
            rows.append(["Summary", "", "Closing Cash", "", _fmt_money(data.get("closing_cash_balance", 0))])
        story.append(_table(rows))

    elif report_name == "cash-flow-projection":
        _title_block(story, "Cash Flow Projection", company_profile, period_label)
        assumptions = data.get("assumptions", {}) if isinstance(data, dict) else {}
        if assumptions:
            story.append(
                Paragraph(
                    (
                        f"Forecast Months: {assumptions.get('months', '')} | "
                        f"Inflow Growth %: {assumptions.get('inflow_growth_pct', 0)} | "
                        f"Outflow Growth %: {assumptions.get('outflow_growth_pct', 0)}"
                    ),
                    getSampleStyleSheet()["Normal"],
                )
            )
            story.append(Spacer(1, 2 * mm))

        rows = [["Month", "Income", "Other In", "Payroll", "OpEx", "Tax", "Interest", "Capex", "Financing", "Net", "Closing"]]
        for r in data.get("projection", []):
            rows.append(
                [
                    r.get("month", ""),
                    _fmt_money(r.get("projected_income_inflows", 0)),
                    _fmt_money(r.get("projected_other_inflows", 0)),
                    _fmt_money(r.get("projected_payroll_expenses", 0)),
                    _fmt_money(r.get("projected_operating_expenses", 0)),
                    _fmt_money(r.get("projected_tax_expenses", 0)),
                    _fmt_money(r.get("projected_interest_expenses", 0)),
                    _fmt_money(r.get("projected_capex_outflows", 0)),
                    _fmt_money(r.get("projected_financing_outflows", 0)),
                    _fmt_money(r.get("projected_net_cash", 0)),
                    _fmt_money(r.get("closing_balance", 0)),
                ]
            )
        story.append(_table(rows))

        totals_rows = [["Line", "Average / Month"]]
        totals_rows.append(["Income Inflows", _fmt_money(assumptions.get("avg_income_inflows", 0))])
        totals_rows.append(["Other Inflows", _fmt_money(assumptions.get("avg_other_inflows", 0))])
        totals_rows.append(["Payroll Expenses", _fmt_money(assumptions.get("avg_payroll_expenses", 0))])
        totals_rows.append(["Operating Expenses", _fmt_money(assumptions.get("avg_operating_expenses", 0))])
        totals_rows.append(["Tax Expenses", _fmt_money(assumptions.get("avg_tax_expenses", 0))])
        totals_rows.append(["Interest Expenses", _fmt_money(assumptions.get("avg_interest_expenses", 0))])
        totals_rows.append(["Capex Outflows", _fmt_money(assumptions.get("avg_capex_outflows", 0))])
        totals_rows.append(["Financing Outflows", _fmt_money(assumptions.get("avg_financing_outflows", 0))])
        story.append(Spacer(1, 2 * mm))
        story.append(_table(totals_rows))

    else:
        _title_block(story, "General Ledger", company_profile, period_label)
        rows = [["Entry", "Date", "Memo", "Code", "Account", "Debit", "Credit"]]
        for e in data:
            for line in e.get("lines", []):
                rows.append(
                    [
                        e.get("id"),
                        str(e.get("entry_date", "")),
                        e.get("memo", ""),
                        line.get("account_code"),
                        line.get("account_name"),
                        f"{line.get('debit', 0):,.2f}",
                        f"{line.get('credit', 0):,.2f}",
                    ]
                )
        story.append(_table(rows))

    doc.build(story)
    return buf.getvalue()


def build_payroll_run_pdf(run_data: dict, company_profile: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story = []

    _title_block(story, f"Payroll Summary - {run_data.get('period_label', '')}", company_profile, str(run_data.get("pay_date", "")))

    summary_rows = [
        ["Metric", "Value"],
        ["Status", str(run_data.get("status", ""))],
        ["Total Gross", _fmt_money(run_data.get("total_gross", 0))],
        ["PAYE", _fmt_money(run_data.get("total_tax", 0))],
        ["NSSA", _fmt_money(run_data.get("total_nssa", 0))],
        ["Pension", _fmt_money(run_data.get("total_pension", 0))],
        ["Other Deductions", _fmt_money(run_data.get("total_other_deductions", 0))],
        ["SDL", _fmt_money(run_data.get("total_sdl", 0))],
        ["Total Net", _fmt_money(run_data.get("total_net", 0))],
    ]
    story.append(_table(summary_rows, col_widths=[80 * mm, 80 * mm]))
    story.append(Spacer(1, 3 * mm))

    line_rows = [["Code", "Employee", "Gross", "PAYE", "NSSA", "Pension", "Other", "SDL", "Net"]]
    for ln in run_data.get("lines", []):
        line_rows.append(
            [
                ln.get("employee_code", ""),
                ln.get("employee_name", ""),
                _fmt_money(ln.get("gross_pay", 0)),
                _fmt_money(ln.get("tax_amount", 0)),
                _fmt_money(ln.get("nssa_amount", 0)),
                _fmt_money(ln.get("pension_amount", 0)),
                _fmt_money(ln.get("other_deduction", 0)),
                _fmt_money(ln.get("sdl_amount", 0)),
                _fmt_money(ln.get("net_pay", 0)),
            ]
        )
    story.append(_table(line_rows))

    doc.build(story)
    return buf.getvalue()

def build_irp5_context(run_data: dict, employee_line: dict, company_profile: dict, employee_details: dict | None = None) -> dict:
    employee = employee_details or {}
    gross = float(employee_line.get("gross_pay") or 0.0)
    tax = float(employee_line.get("tax_amount") or 0.0)
    employer = {
        "company_name": company_profile.get("company_name") or "My Company",
        "address": company_profile.get("address") or "",
        "email": company_profile.get("email") or "",
        "phone": company_profile.get("phone") or "",
        "tax_number": company_profile.get("tax_number") or "",
        "paye_ref_no": company_profile.get("paye_ref_no") or "",
        "sdl_ref_no": company_profile.get("sdl_ref_no") or "",
        "uif_ref_no": company_profile.get("uif_ref_no") or "",
        "logo_data_url": company_profile.get("logo_data_url") or "",
    }
    employee_payload = {
        "full_name": employee.get("full_name") or employee_line.get("employee_name") or "",
        "initials": employee.get("initials") or "",
        "surname": employee.get("surname") or "",
        "address": employee.get("address") or "",
        "nationality": employee.get("nationality") or "",
        "bank_account": employee.get("bank_account") or "",
        "bank_name": employee.get("bank_name") or "",
        "bank_branch": employee.get("bank_branch") or "",
        "bank_account_type": employee.get("bank_account_type") or "",
        "id_number": employee.get("id_number") or "",
        "tax_number": employee.get("tax_number") or "",
        "email": employee.get("email") or "",
    }
    period_label = str(run_data.get("period_label") or "")
    financial_year = str(run_data.get("financial_year_label") or "")
    if not financial_year and "FY " in period_label:
        financial_year = period_label.split("FY ", 1)[-1].strip()
    year_of_assessment = ""
    if financial_year and "/" in financial_year:
        try:
            _, end_year = [part.strip() for part in financial_year.split("/", 1)]
            year_of_assessment = end_year
        except ValueError:
            year_of_assessment = ""
    elif financial_year:
        year_of_assessment = financial_year
    if not year_of_assessment and period_label:
        match = re.search(r"(20\d{2})", period_label)
        if match:
            year_of_assessment = match.group(1)
    period_of_reconciliation = ""
    if financial_year and "/" in financial_year:
        try:
            start_year, end_year = [part.strip() for part in financial_year.split("/", 1)]
            if start_year.isdigit() and end_year.isdigit():
                period_of_reconciliation = f"{end_year}02"
        except ValueError:
            period_of_reconciliation = ""
    elif year_of_assessment and period_label:
        period_of_reconciliation = f"{year_of_assessment}02"
    certificate = {
        "certificate_type": "IRP5",
        "period_label": period_label,
        "financial_year_label": financial_year,
        "year_of_assessment": year_of_assessment,
        "period_of_reconciliation": period_of_reconciliation,
        "reconciliation_period": period_of_reconciliation,
    }
    coded_amounts = {
        "tax_withheld": [{"code": "4102", "description": "PAYE", "amount": round(tax, 2)}],
        "income_received": [{"code": "3601", "description": "Income", "amount": round(gross, 2)}],
        "deductions_contributions": [
            {"code": "4497", "description": "Employee provident fund", "amount": 0.0},
            {"code": "4210", "description": "Employee UIF", "amount": 0.0},
            {"code": "4497", "description": "Deduction contribution", "amount": 0.0},
        ],
    }
    return {
        "employer": employer,
        "employee": employee_payload,
        "certificate": certificate,
        "coded_amounts": coded_amounts,
    }

def build_payroll_payslip_pdf(run_data: dict, employee_line: dict, company_profile: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    story = []

    period_label = f"{run_data.get('period_label', '')} | Pay Date: {run_data.get('pay_date', '')}"
    _title_block(story, f"Payslip - {employee_line.get('employee_name', '')}", company_profile, period_label)

    emp_rows = [
        ["Employee Code", employee_line.get("employee_code", "")],
        ["Employee Name", employee_line.get("employee_name", "")],
        ["Run Status", run_data.get("status", "")],
    ]
    story.append(_table([["Field", "Value"], *emp_rows], col_widths=[60 * mm, 100 * mm]))
    story.append(Spacer(1, 3 * mm))

    pay_rows = [
        ["Component", "Amount"],
        ["Gross Pay", _fmt_money(employee_line.get("gross_pay", 0))],
        ["PAYE", _fmt_money(employee_line.get("tax_amount", 0))],
        ["NSSA", _fmt_money(employee_line.get("nssa_amount", 0))],
        ["Pension", _fmt_money(employee_line.get("pension_amount", 0))],
        ["Other Deductions", _fmt_money(employee_line.get("other_deduction", 0))],
        ["SDL", _fmt_money(employee_line.get("sdl_amount", 0))],
        ["Total Deductions", _fmt_money(employee_line.get("total_deductions", 0))],
        ["Net Pay", _fmt_money(employee_line.get("net_pay", 0))],
    ]
    pay_tbl = _table(pay_rows, col_widths=[90 * mm, 70 * mm], extra_styles=[("FONTNAME", (0, len(pay_rows) - 1), (-1, len(pay_rows) - 1), "Helvetica-Bold")])
    story.append(pay_tbl)

    doc.build(story)
    return buf.getvalue()


def build_tax_certificate_pdf(run_data: dict, employee_line: dict, company_profile: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    story = []

    styles = getSampleStyleSheet()
    components = employee_line.get("components") or []
    comp_lower = [(str(c.get("name") or "").lower(), c) for c in components]

    def _component_total(name_part: str, scope: str | None = None) -> float:
        total = 0.0
        for name, item in comp_lower:
            if name_part in name and (scope is None or str(item.get("scope") or "").lower() == scope):
                total += float(item.get("amount") or 0.0)
        return round(total, 2)

    employee = employee_line.get("employee") or {}
    irp5_meta = employee_line.get("irp5_meta") or {}
    period_label = str(run_data.get("period_label") or "")
    pay_date = str(run_data.get("pay_date") or "")
    financial_year_label = str(irp5_meta.get("financial_year_label") or run_data.get("financial_year_label") or "")
    if not financial_year_label and "FY " in period_label:
        financial_year_label = period_label.split("FY ", 1)[-1].strip()
    transaction_year = ""
    year_match = None
    if period_label:
        import re as _re
        year_match = _re.search(r"(20\d{2})", period_label)
    if pay_date and len(pay_date) >= 4:
        transaction_year = pay_date[:4]
    elif year_match:
        transaction_year = year_match.group(1)

    assessment_year = transaction_year or ""
    reconciliation_period = period_label or ""
    employment_from = str(irp5_meta.get("period_employed_from") or "")
    employment_to = str(irp5_meta.get("period_employed_to") or "")
    periods_in_year = float(irp5_meta.get("periods_in_year") or 12.0)
    months_worked = float(irp5_meta.get("months_worked") or 0.0)
    if financial_year_label and "/" in financial_year_label:
        try:
            fy_start, fy_end = [int(part.strip()) for part in financial_year_label.split("/", 1)]
            assessment_year = str(fy_end)
            reconciliation_period = f"{fy_end}02"
            if not employment_from:
                employment_from = f"{fy_start}/03/01"
            if not employment_to:
                employment_to = f"{fy_end}/02/28"
        except ValueError:
            pass

    cert_number = f"{company_profile.get('paye_ref_no') or company_profile.get('tax_number', '0000000000')}{assessment_year or transaction_year or '0000'}{employee_line.get('employee_code', '')}".replace(" ", "")
    certificate_type = "IRP5"

    tax_amount = float(employee_line.get("tax_amount") or 0.0)
    gross_income = float(employee_line.get("gross_pay") or 0.0)
    provident_employee = float(employee_line.get("pension_amount") or _component_total("provident", "employee"))
    provident_employer = _component_total("company provident", "employer")
    uif_employee = _component_total("uif", "employee")
    uif_employer = _component_total("company uif", "employer")
    uif_total = round(uif_employee + uif_employer, 2)
    sdl_total = float(employee_line.get("sdl_amount") or 0.0)
    total_statutory = round(tax_amount + uif_total + sdl_total, 2)
    total_deductions = round(provident_employee + provident_employer, 2)

    def _derive_date_of_birth(id_number: str | None) -> str:
        digits = "".join(ch for ch in str(id_number or "") if ch.isdigit())
        if len(digits) < 6:
            return ""
        yy = int(digits[0:2])
        mm = digits[2:4]
        dd = digits[4:6]
        century = 1900 if yy > 30 else 2000
        return f"{century + yy:04d}/{mm}/{dd}"

    def _compact_info_rows(rows: list[list], required_labels: set[str]) -> list[list]:
        compact: list[list] = []
        for label, value in rows:
            if str(value or "").strip() or label in required_labels:
                compact.append([label, value])
        return compact

    compact_styles = [
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]

    company_name = company_profile.get("company_name") or "Default Company"
    header_logo = _logo_cell(company_profile, width_mm=18, default_initials="CO")
    if isinstance(header_logo, Image):
        header_tbl = Table([[header_logo, Paragraph(f"<b>{company_name}</b>", styles["Heading3"]) ]], colWidths=[18 * mm, None])
        header_tbl.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(header_tbl)
    else:
        story.append(Paragraph(f"<b>{company_name}</b>", styles["Heading3"]))
    story.append(Paragraph("<b>Employee Income Tax Certificate IRP5/IT3(a)</b>", styles["Heading4"]))
    story.append(
        Paragraph(
            (
                f"Transaction year {transaction_year or ''}  "
                f"Period of reconciliation {reconciliation_period or ''}  "
                f"Year of assessment {assessment_year or transaction_year or ''}<br/>"
                f"Certificate number {cert_number}  "
                f"Type of certificate {certificate_type}"
            ),
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 1 * mm))

    story.append(Paragraph("<b>Employee Information</b>", styles["Heading5"]))
    def _required_value(value: str | None, placeholder: str = "UPDATE PROFILE") -> str:
        clean = str(value or "").strip()
        return clean or placeholder

    employee_rows = [
        ["Surname/Trading name", employee.get("surname") or employee_line.get("employee_name", "")],
        ["Employee code", employee_line.get("employee_code", "")],
        ["First two names", employee.get("full_name") or employee_line.get("employee_name", "")],
        ["Initials", employee.get("initials", "")],
        ["Date of birth", employee.get("date_of_birth") or _derive_date_of_birth(employee.get("id_number"))],
        ["ID number", _required_value(employee.get("id_number"))],
        ["Tax reference no.", _required_value(employee.get("tax_number"))],
        ["Contact email", _required_value(employee.get("email"))],
        ["Residential address", employee.get("address", "")],
        ["Bank account", employee.get("bank_account", "")],
        ["Bank name", employee.get("bank_name", "")],
        ["Branch", employee.get("bank_branch", "")],
        ["Account type", employee.get("bank_account_type", "")],
    ]
    employee_rows = _compact_info_rows(
        employee_rows,
        required_labels={"Surname/Trading name", "Employee code", "First two names", "ID number", "Tax reference no.", "Contact email"},
    )
    story.append(_table(employee_rows, col_widths=[62 * mm, 118 * mm], extra_styles=compact_styles))
    story.append(Spacer(1, 0.8 * mm))

    story.append(Paragraph("<b>Employer Information</b>", styles["Heading5"]))
    employer_rows = [
        ["Trading or other name", company_profile.get("company_name", "")],
        ["PAYE ref. no.", _required_value(company_profile.get("paye_ref_no") or company_profile.get("tax_number"), placeholder="UPDATE COMPANY PROFILE")],
        ["SDL ref. no.", _required_value(company_profile.get("sdl_ref_no"), placeholder="UPDATE COMPANY PROFILE")],
        ["UIF ref. no.", _required_value(company_profile.get("uif_ref_no"), placeholder="UPDATE COMPANY PROFILE")],
    ]
    employer_rows = _compact_info_rows(
        employer_rows,
        required_labels={"Trading or other name", "PAYE ref. no.", "SDL ref. no.", "UIF ref. no."},
    )
    story.append(_table(employer_rows, col_widths=[62 * mm, 118 * mm], extra_styles=compact_styles))
    story.append(Spacer(1, 0.8 * mm))

    story.append(Paragraph("<b>Tax Certificate Information</b>", styles["Heading5"]))
    story.append(Paragraph("<b>Pay Periods Directive Numbers</b>", styles["Heading6"]))
    pay_period_rows = [
        ["Periods in year of assessment", f"{periods_in_year:.4f}"],
        ["Number of periods worked", f"{months_worked:.4f}" if months_worked > 0 else f"{periods_in_year:.4f}"],
        ["Period employed from", employment_from],
        ["Period employed to", employment_to or (pay_date.replace("-", "/") if pay_date else "")],
    ]
    story.append(_table(pay_period_rows, col_widths=[95 * mm, 85 * mm], extra_styles=compact_styles))
    story.append(Spacer(1, 0.8 * mm))

    story.append(Paragraph("<b>Tax Withheld</b>", styles["Heading6"]))
    code_tax_rows = [
        ["Description", "Amount", "Code"],
        ["PAYE", _fmt_money(tax_amount), "4102"],
        ["PAYE on Lump Sum Benefit", "", "4115"],
        ["Additional Medical Tax Credits", "", "4120"],
        ["Employee and Employer UIF", _fmt_money(uif_total), "4141"],
        ["Employer SDL contribution", _fmt_money(sdl_total), "4142"],
        ["Total Tax, UIF and SDL", _fmt_money(total_statutory), "4149"],
        ["Medical Tax Credit", "", "4116"],
        ["Reason for non deduction of employees tax", "", "4150"],
    ]
    story.append(_table(code_tax_rows, col_widths=[118 * mm, 40 * mm, 22 * mm], extra_styles=compact_styles))
    story.append(Spacer(1, 0.8 * mm))

    story.append(Paragraph("<b>Income Received</b>", styles["Heading6"]))
    code_income_rows = [
        ["Description", "Amount", "Code"],
        ["Income", _fmt_money(gross_income), "3601"],
        ["Annual Payment", _fmt_money(0.0), "3605"],
        ["Provident Fund contributions", _fmt_money(provident_employee), "3825"],
        ["Gross employment income (taxable)", _fmt_money(gross_income), "3699"],
    ]
    story.append(_table(code_income_rows, col_widths=[118 * mm, 40 * mm, 22 * mm], extra_styles=compact_styles))
    story.append(Spacer(1, 0.8 * mm))

    story.append(Paragraph("<b>Deductions/Contributions</b>", styles["Heading6"]))
    code_deduct_rows = [
        ["Description", "Amount", "Code"],
        ["Current and Arrear Provident Fund Contributions", _fmt_money(provident_employee), "4003"],
        ["Employer's provident fund contributions paid for the benefit of employee", _fmt_money(provident_employer), "4473"],
        ["Total Deductions/Contributions", _fmt_money(total_deductions), "4497"],
    ]
    story.append(_table(code_deduct_rows, col_widths=[118 * mm, 40 * mm, 22 * mm], extra_styles=compact_styles))
    story.append(Spacer(1, 0.6 * mm))

    doc.build(story)
    return buf.getvalue()


def build_employment_certificate_pdf(employee: dict, company_profile: dict, issue_date: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    story = []
    _title_block(story, "Employment Certificate", company_profile, f"Issue Date: {issue_date}")

    text = (
        f"This is to certify that {employee.get('full_name', '')} (Employee Code: {employee.get('employee_code', '')}) "
        f"is employed by {company_profile.get('company_name', 'the company')} and is currently marked as "
        f"{'active' if employee.get('active') else 'inactive'}."
    )
    story.append(Paragraph(text, getSampleStyleSheet()["Normal"]))
    story.append(Spacer(1, 5 * mm))
    story.append(_table([
        ["Employee Code", employee.get("employee_code", "")],
        ["Employee Name", employee.get("full_name", "")],
        ["Default Gross Salary", _fmt_money(employee.get("default_gross_salary", 0))],
        ["Default Tax Rate", f"{float(employee.get('tax_rate', 0)):.2f}%"],
        ["Status", "Active" if employee.get("active") else "Inactive"],
    ], col_widths=[80 * mm, 80 * mm]))

    doc.build(story)
    return buf.getvalue()


def build_invoice_pdf(invoice_data: dict, company_profile: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    styles = getSampleStyleSheet()
    story = []

    invoice_number = str(invoice_data.get("invoice_number") or "")
    currency = str(invoice_data.get("currency") or company_profile.get("currency") or "USD")
    issue_date = str(invoice_data.get("issue_date") or "")
    due_date = str(invoice_data.get("due_date") or "")
    status = str(invoice_data.get("status") or "").upper()

    company_name = company_profile.get("company_name") or "My Company"
    company_lines = [
        x
        for x in [
            company_profile.get("address", ""),
            company_profile.get("email", ""),
            company_profile.get("phone", ""),
            f"Tax: {company_profile.get('tax_number', '')}" if company_profile.get("tax_number") else "",
        ]
        if x
    ]
    company_text = "<br/>".join(company_lines)
    logo_initials = "".join(part[0].upper() for part in company_name.split() if part[:1])[:2] or "CO"
    logo_block = _logo_cell(company_profile, width_mm=18, default_initials=logo_initials)
    if isinstance(logo_block, Image):
        logo_block = Table([[logo_block]], colWidths=[18 * mm])
        logo_block.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
    else:
        logo_block = Table(
            [[logo_block]],
            colWidths=[18 * mm],
        )
        logo_block.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF2FF")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1D3557")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9D5EA")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )

    title_tbl = Table(
        [
            [
                logo_block,
                Paragraph(f"<font size=18><b>{company_name}</b></font>", styles["Normal"]),
                Paragraph("<font size=18><b>INVOICE</b></font>", styles["Normal"]),
            ],
            [
                "",
                Paragraph(company_text or " ", styles["Normal"]),
                Paragraph(
                    (
                        f"<b>Invoice #:</b> {invoice_number}<br/>"
                        f"<b>Issue Date:</b> {issue_date}<br/>"
                        f"<b>Due Date:</b> {due_date}<br/>"
                        f"<b>Status:</b> {status}"
                    ),
                    styles["Normal"],
                ),
            ],
        ],
        colWidths=[18 * mm, 92 * mm, None],
    )
    title_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(title_tbl)
    story.append(Spacer(1, 4 * mm))

    customer_name = str(invoice_data.get("customer_name") or "")
    customer_email = str(invoice_data.get("customer_email") or "")
    bill_to = [customer_name]
    if customer_email:
        bill_to.append(customer_email)
    bill_to_text = "<br/>".join([x for x in bill_to if x]) or "Customer"

    details_tbl = Table(
        [
            [Paragraph("<b>Bill To</b>", styles["Normal"]), Paragraph("<b>Payment Summary</b>", styles["Normal"])],
            [
                Paragraph(bill_to_text, styles["Normal"]),
                Paragraph(
                    (
                        f"<b>Subtotal:</b> {currency} {_fmt_money(invoice_data.get('subtotal', 0))}<br/>"
                        f"<b>Tax:</b> {currency} {_fmt_money(invoice_data.get('tax_total', 0))}<br/>"
                        f"<b>Total:</b> {currency} {_fmt_money(invoice_data.get('total', 0))}<br/>"
                        f"<b>Outstanding:</b> {currency} {_fmt_money(invoice_data.get('outstanding_balance', 0))}"
                    ),
                    styles["Normal"],
                ),
            ],
        ],
        colWidths=[110 * mm, None],
    )
    details_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4FF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D2DEEE")),
            ]
        )
    )
    story.append(details_tbl)
    story.append(Spacer(1, 5 * mm))

    line_rows = [["#", "Description", "Qty", "Unit Price", "Tax %", "Line Total"]]
    for idx, line in enumerate(invoice_data.get("lines", []) or [], start=1):
        line_rows.append(
            [
                idx,
                line.get("description", ""),
                _fmt_money(line.get("quantity", 0)),
                f"{currency} {_fmt_money(line.get('unit_price', 0))}",
                f"{_fmt_money(line.get('tax_rate', 0))}%",
                f"{currency} {_fmt_money(line.get('line_total', 0))}",
            ]
        )

    lines_tbl = _table(
        line_rows,
        col_widths=[12 * mm, 78 * mm, 20 * mm, 28 * mm, 18 * mm, 30 * mm],
        extra_styles=[
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ],
    )
    story.append(lines_tbl)
    story.append(Spacer(1, 4 * mm))

    notes = str(invoice_data.get("notes") or "").strip()
    if notes:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("<b>Notes</b>", styles["Normal"]))
        story.append(Paragraph(notes, styles["Normal"]))

    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "Thank you for your business.",
            styles["Normal"],
        )
    )

    doc.build(story)
    return buf.getvalue()

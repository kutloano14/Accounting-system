from __future__ import annotations

import json
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


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


def _fmt_date(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y/%m/%d")
    return str(value)


def _fmt_number(value, decimals: int = 4) -> str:
    return f"{float(value or 0):,.{decimals}f}"


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
    employee_code = (employee_line.get("employee_code") or "").replace(" ", "")
    pay_date = run_data.get("pay_date")
    tax_year = str(run_data.get("transaction_year") or (pay_date.year if hasattr(pay_date, "year") else ""))
    reconciliation_period = str(run_data.get("reconciliation_period") or f"{tax_year}02" if tax_year else "")
    certificate_number = str(
        run_data.get("certificate_number")
        or f"{(company_profile.get('tax_number') or '').replace(' ', '')}{reconciliation_period}{employee_code}"
    )

    paye_amount = float(employee_line.get("tax_amount", 0) or 0)
    uif_amount = float(employee_line.get("nssa_amount", 0) or 0)
    sdl_amount = float(employee_line.get("sdl_amount", 0) or 0)
    annual_payment = float(employee_line.get("annual_payment", 0) or 0)
    provident_contributions = float(employee_line.get("pension_amount", 0) or 0)

    gross_income = float(employee_line.get("gross_pay", 0) or 0)
    gross_taxable = gross_income + annual_payment + provident_contributions

    deductions_total = float(employee_line.get("employee_deductions_total", 0) or 0)
    employer_pf_contributions = float(employee_line.get("employer_contributions_total", 0) or 0)

    return {
        "period_label": run_data.get("period_label", ""),
        "certificate": {
            "title": "Employee Income Tax Certificate IRP5/IT3(a)",
            "transaction_year": tax_year,
            "reconciliation_period": reconciliation_period,
            "year_of_assessment": str(run_data.get("year_of_assessment") or tax_year),
            "certificate_number": certificate_number,
            "certificate_type": str(run_data.get("certificate_type") or "IRP5"),
        },
        "employer": {
            "company_name": company_profile.get("company_name") or "My Company",
            "address": company_profile.get("address") or "",
            "email": company_profile.get("email") or "",
            "phone": company_profile.get("phone") or "",
            "tax_number": company_profile.get("tax_number") or "",
        },
        "employee": {
            "full_name": employee.get("full_name") or employee_line.get("employee_name") or "",
            "initials": employee.get("initials") or "",
            "surname": employee.get("surname") or "",
            "address": employee.get("address") or "",
            "nationality": employee.get("nationality") or "",
            "id_number": employee.get("id_number") or employee_line.get("id_number") or "",
            "tax_number": employee.get("tax_number") or employee_line.get("tax_number") or "",
            "bank_account": employee.get("bank_account") or employee_line.get("bank_account") or "",
            "bank_name": employee.get("bank_name") or "",
            "bank_branch": employee.get("bank_branch") or "",
            "bank_account_type": employee.get("bank_account_type") or "",
            "email": employee.get("email") or "",
            "phone": employee.get("phone") or "",
            "date_of_birth": employee.get("date_of_birth") or "",
            "passport_number": employee.get("passport_number") or "",
            "passport_country": employee.get("passport_country") or "",
            "employee_code": employee_line.get("employee_code") or "",
            "gross_pay": employee_line.get("gross_pay", 0),
            "tax_amount": employee_line.get("tax_amount", 0),
            "nssa_amount": employee_line.get("nssa_amount", 0),
            "pension_amount": employee_line.get("pension_amount", 0),
            "other_deduction": employee_line.get("other_deduction", 0),
            "sdl_amount": employee_line.get("sdl_amount", 0),
            "employee_deductions_total": employee_line.get("employee_deductions_total", 0),
            "employer_contributions_total": employee_line.get("employer_contributions_total", 0),
            "net_pay": employee_line.get("net_pay", 0),
        },
        "employment": {
            "periods_in_year": float(run_data.get("periods_in_year") or 12),
            "periods_worked": float(run_data.get("periods_worked") or 12),
            "period_employed_from": _fmt_date(employee.get("hire_date") or run_data.get("period_employed_from") or ""),
            "period_employed_to": _fmt_date(run_data.get("period_employed_to") or run_data.get("pay_date") or ""),
        },
        "coded_amounts": {
            "tax_withheld": [
                {"description": "PAYE", "amount": paye_amount, "code": "4102"},
                {"description": "PAYE on Lump Sum Benefit", "amount": float(employee_line.get("paye_lump_sum", 0) or 0), "code": "4115"},
                {
                    "description": "Additional Medical Tax Credits",
                    "amount": float(employee_line.get("additional_medical_tax_credits", 0) or 0),
                    "code": "4120",
                },
                {"description": "Employee and Employer UIF", "amount": uif_amount, "code": "4141"},
                {"description": "Employer SDL contribution", "amount": sdl_amount, "code": "4142"},
                {
                    "description": "Total Tax, UIF and SDL",
                    "amount": paye_amount + uif_amount + sdl_amount,
                    "code": "4149",
                },
                {"description": "Medical Tax Credit", "amount": float(employee_line.get("medical_tax_credit", 0) or 0), "code": "4116"},
                {
                    "description": "Reason for non deduction of employees tax",
                    "amount": "",
                    "code": "4150",
                    "text_value": str(employee_line.get("non_deduction_reason") or ""),
                },
            ],
            "income_received": [
                {"description": "Income", "amount": gross_income, "code": "3601"},
                {"description": "Annual Payment", "amount": annual_payment, "code": "3605"},
                {"description": "Provident Fund contributions", "amount": provident_contributions, "code": "3825"},
                {"description": "Gross employment income (taxable)", "amount": gross_taxable, "code": "3699"},
            ],
            "deductions_contributions": [
                {
                    "description": "Current and Arrear Provident Fund Contributions",
                    "amount": deductions_total,
                    "code": "4003",
                },
                {
                    "description": "Employer's provident fund contributions paid for the benefit of employee",
                    "amount": employer_pf_contributions,
                    "code": "4473",
                },
                {
                    "description": "Total Deductions/Contributions",
                    "amount": deductions_total + employer_pf_contributions,
                    "code": "4497",
                },
            ],
        },
    }


def build_irp5_pdf(run_data: dict, employee_line: dict, company_profile: dict, employee_details: dict | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    story = []
    context = build_irp5_context(run_data, employee_line, company_profile, employee_details)
    certificate = context["certificate"]
    employer = context["employer"]
    employee = context["employee"]
    employment = context["employment"]
    coded_amounts = context["coded_amounts"]

    _title_block(story, certificate["title"], company_profile, None)
    story.append(_table([
        ["Transaction year", "Period of reconciliation", "Year of assessment"],
        [certificate.get("transaction_year", ""), certificate.get("reconciliation_period", ""), certificate.get("year_of_assessment", "")],
    ], col_widths=[56 * mm, 56 * mm, 56 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(_table([
        ["Certificate number", "Type of certificate"],
        [certificate.get("certificate_number", ""), certificate.get("certificate_type", "IRP5")],
    ], col_widths=[112 * mm, 56 * mm]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("<b>Employee Information</b>", getSampleStyleSheet()["Heading4"]))
    story.append(_table([
        ["Surname/Trading name", "Employee code", "Initials", "Date of birth"],
        [
            employee.get("surname", ""),
            employee.get("employee_code", ""),
            employee.get("initials", ""),
            employee.get("date_of_birth", ""),
        ],
        ["First names", "ID number", "Passport number", "Tax reference no."],
        [
            employee.get("full_name", ""),
            employee.get("id_number", ""),
            employee.get("passport_number", ""),
            employee.get("tax_number", ""),
        ],
        ["Home/Business/Cell", "Email", "Nationality", "Passport country"],
        [
            employee.get("phone", ""),
            employee.get("email", ""),
            employee.get("nationality", ""),
            employee.get("passport_country", ""),
        ],
    ], col_widths=[44 * mm, 44 * mm, 44 * mm, 44 * mm]))

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("<b>Employee Address and Remuneration Bank Account Details</b>", getSampleStyleSheet()["Heading4"]))
    story.append(_table([
        ["Residential/Postal Address", "Account holder name", "Bank name", "Branch name"],
        [
            employee.get("address", ""),
            employee.get("full_name", ""),
            employee.get("bank_name", ""),
            employee.get("bank_branch", ""),
        ],
        ["Branch number", "Account number", "Account holder relationship", "Account type"],
        ["", employee.get("bank_account", ""), "Own", employee.get("bank_account_type", "")],
    ], col_widths=[44 * mm, 44 * mm, 44 * mm, 44 * mm]))

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("<b>Employer Information</b>", getSampleStyleSheet()["Heading4"]))
    story.append(_table([
        ["Field", "Value"],
        ["Trading or other name", employer.get("company_name", "")],
        ["PAYE ref. no.", employer.get("tax_number", "")],
        ["SDL ref. no.", company_profile.get("sdl_number", "")],
        ["UIF ref. no.", company_profile.get("uif_number", "")],
        ["Address", employer.get("address", "")],
        ["Email", employer.get("email", "")],
        ["Phone", employer.get("phone", "")],
    ], col_widths=[70 * mm, 100 * mm]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("<b>Tax Certificate Information</b>", getSampleStyleSheet()["Heading4"]))
    story.append(_table([
        ["Field", "Value"],
        ["Periods in year of assessment", _fmt_number(employment.get("periods_in_year", 12), 4)],
        ["Number of periods worked", _fmt_number(employment.get("periods_worked", 12), 4)],
        ["Period employed from", employment.get("period_employed_from", "")],
        ["Period employed to", employment.get("period_employed_to", "")],
    ], col_widths=[70 * mm, 100 * mm]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("<b>Tax Withheld</b>", getSampleStyleSheet()["Heading4"]))
    tax_rows = [["Description", "Amount", "Code"]]
    for row in coded_amounts.get("tax_withheld", []):
        text_value = row.get("text_value")
        amount = row.get("amount", "")
        amount_value = text_value if text_value is not None and text_value != "" else (_fmt_money(amount) if amount != "" else "")
        tax_rows.append([row.get("description", ""), amount_value, row.get("code", "")])
    story.append(_table(tax_rows, col_widths=[96 * mm, 45 * mm, 29 * mm], extra_styles=[("ALIGN", (1, 1), (1, -1), "RIGHT")]))

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("<b>Income Received</b>", getSampleStyleSheet()["Heading4"]))
    income_rows = [["Description", "Amount", "Code"]]
    for row in coded_amounts.get("income_received", []):
        income_rows.append([row.get("description", ""), _fmt_money(row.get("amount", 0)), row.get("code", "")])
    story.append(_table(income_rows, col_widths=[96 * mm, 45 * mm, 29 * mm], extra_styles=[("ALIGN", (1, 1), (1, -1), "RIGHT")]))

    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("<b>Deductions/Contributions</b>", getSampleStyleSheet()["Heading4"]))
    contribution_rows = [["Description", "Amount", "Code"]]
    for row in coded_amounts.get("deductions_contributions", []):
        contribution_rows.append([row.get("description", ""), _fmt_money(row.get("amount", 0)), row.get("code", "")])
    story.append(_table(contribution_rows, col_widths=[96 * mm, 45 * mm, 29 * mm], extra_styles=[("ALIGN", (1, 1), (1, -1), "RIGHT")]))

    doc.build(story)
    return buf.getvalue()


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
    ]
    deductions_json = employee_line.get("deductions_json") or []
    if isinstance(deductions_json, str):
        try:
            deductions_json = json.loads(deductions_json)
        except Exception:
            deductions_json = []
    for item in deductions_json:
        if item.get("scope") in {"employee", "both"}:
            pay_rows.append([f"{item.get('name', 'Rule')} (deduction)", _fmt_money(item.get('amount', 0))])
    pay_rows.extend([
        ["Employee Deductions Total", _fmt_money(employee_line.get("employee_deductions_total", 0))],
        ["Employer Contributions Total", _fmt_money(employee_line.get("employer_contributions_total", 0))],
        ["Net Pay", _fmt_money(employee_line.get("net_pay", 0))],
    ])
    pay_tbl = _table(pay_rows, col_widths=[90 * mm, 70 * mm], extra_styles=[("FONTNAME", (0, len(pay_rows) - 1), (-1, len(pay_rows) - 1), "Helvetica-Bold")])
    story.append(pay_tbl)

    doc.build(story)
    return buf.getvalue()


def build_tax_certificate_pdf(run_data: dict, employee_line: dict, company_profile: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    story = []

    period_label = f"Tax Period: {run_data.get('period_label', '')}"
    _title_block(story, f"Employee Tax Certificate - {employee_line.get('employee_name', '')}", company_profile, period_label)

    rows = [
        ["Field", "Value"],
        ["Employee Code", employee_line.get("employee_code", "")],
        ["Employee Name", employee_line.get("employee_name", "")],
        ["Gross Earnings", _fmt_money(employee_line.get("gross_pay", 0))],
        ["PAYE", _fmt_money(employee_line.get("tax_amount", 0))],
        ["NSSA", _fmt_money(employee_line.get("nssa_amount", 0))],
        ["Pension", _fmt_money(employee_line.get("pension_amount", 0))],
        ["Other Deductions", _fmt_money(employee_line.get("other_deduction", 0))],
        ["SDL", _fmt_money(employee_line.get("sdl_amount", 0))],
        ["Net Pay", _fmt_money(employee_line.get("net_pay", 0))],
    ]
    story.append(_table(rows, col_widths=[80 * mm, 80 * mm]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("This certificate confirms payroll tax deductions for the stated period.", getSampleStyleSheet()["Normal"]))

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

    title_tbl = Table(
        [
            [
                Paragraph(f"<font size=18><b>{company_name}</b></font>", styles["Normal"]),
                Paragraph("<font size=18><b>INVOICE</b></font>", styles["Normal"]),
            ],
            [
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
        colWidths=[110 * mm, None],
    )
    title_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
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

    totals_tbl = Table(
        [
            ["Subtotal", f"{currency} {_fmt_money(invoice_data.get('subtotal', 0))}"],
            ["Tax", f"{currency} {_fmt_money(invoice_data.get('tax_total', 0))}"],
            ["Total", f"{currency} {_fmt_money(invoice_data.get('total', 0))}"],
            ["Outstanding", f"{currency} {_fmt_money(invoice_data.get('outstanding_balance', 0))}"],
        ],
        colWidths=[45 * mm, 45 * mm],
        hAlign="RIGHT",
    )
    totals_tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D2DEEE")),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#EAF2FF")),
                ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#E3EEFF")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (0, 2), (-1, 3), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]
        )
    )
    story.append(totals_tbl)

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

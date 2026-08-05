from __future__ import annotations

from typing import Any


def round_money(value: float) -> float:
    return round(float(value or 0.0), 2)


def build_payroll_components(
    gross: float,
    tax_amount: float,
    nssa_amount: float,
    pension_amount: float,
    sdl_amount: float,
    other_deduction: float,
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    employee_deductions_total = round_money(tax_amount + nssa_amount + pension_amount + sdl_amount + other_deduction)
    employer_contributions_total = 0.0
    components: list[dict[str, Any]] = []

    for rule in rules or []:
        if not rule.get("active", True):
            continue
        scope = str(rule.get("scope") or "employee").strip().lower()
        calc_type = str(rule.get("calculation_type") or "fixed_amount").strip().lower()
        value = float(rule.get("value") or 0.0)
        if scope not in {"employee", "employer", "both"}:
            scope = "employee"

        amount = 0.0
        if calc_type == "percentage_of_gross":
            amount = round_money(gross * value / 100.0)
        elif calc_type == "percentage_of_tax":
            amount = round_money(tax_amount * value / 100.0)
        elif calc_type == "percentage_of_net":
            net_before_rule = round_money(max(gross - employee_deductions_total, 0.0))
            amount = round_money(net_before_rule * value / 100.0)
        else:
            amount = round_money(value)

        if scope in {"employee", "both"}:
            employee_deductions_total = round_money(employee_deductions_total + amount)
        if scope in {"employer", "both"}:
            employer_contributions_total = round_money(employer_contributions_total + amount)

        components.append({
            "name": rule.get("name") or "Rule",
            "scope": scope,
            "calculation_type": calc_type,
            "value": value,
            "amount": round_money(amount),
        })

    employee_deductions_total = round_money(employee_deductions_total)
    employer_contributions_total = round_money(employer_contributions_total)
    net_pay = round_money(max(gross - employee_deductions_total, 0.0))

    return {
        "components": components,
        "employee_deductions_total": employee_deductions_total,
        "employer_contributions_total": employer_contributions_total,
        "net_pay": net_pay,
    }

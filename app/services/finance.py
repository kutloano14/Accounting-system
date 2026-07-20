from datetime import date


def straight_line_monthly_depreciation(cost: float, salvage_value: float, useful_life_years: int) -> float:
    life_months = max(useful_life_years * 12, 1)
    depreciable = max(cost - salvage_value, 0.0)
    return round(depreciable / life_months, 2)


def months_between(start_date: date, end_date: date) -> int:
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    return max(months, 0)


def build_loan_schedule(principal: float, annual_interest_rate: float, term_months: int, months: int | None = None) -> list[dict]:
    n = max(term_months, 1)
    m = min(months or n, n)
    r = annual_interest_rate / 100.0 / 12.0

    if r == 0:
        payment = round(principal / n, 2)
    else:
        factor = (1 + r) ** n
        payment = round((principal * r * factor) / (factor - 1), 2)

    balance = round(principal, 2)
    schedule = []

    for month in range(1, m + 1):
        interest = round(balance * r, 2)
        principal_part = round(payment - interest, 2)

        if month == n or principal_part > balance:
            principal_part = balance
            payment_line = round(principal_part + interest, 2)
        else:
            payment_line = payment

        balance = round(balance - principal_part, 2)
        if balance < 0:
            balance = 0.0

        schedule.append(
            {
                "month": month,
                "payment": payment_line,
                "interest": interest,
                "principal": principal_part,
                "balance": balance,
            }
        )

    return schedule

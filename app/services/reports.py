from datetime import date
import calendar

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app import models
from app.services.finance import months_between, straight_line_monthly_depreciation


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _cash_balance_as_of(db: Session, company_id: int, as_of_date: date | None = None) -> float:
    opening_query = db.query(models.BankOpeningBalance)
    opening_query = opening_query.filter(models.BankOpeningBalance.company_id == company_id)
    if as_of_date:
        opening_query = opening_query.filter(models.BankOpeningBalance.balance_date <= as_of_date)
    opening = opening_query.order_by(models.BankOpeningBalance.balance_date.desc(), models.BankOpeningBalance.id.desc()).first()

    opening_amount = float(opening.amount) if opening else 0.0
    movement_query = db.query(func.coalesce(func.sum(models.BankTransaction.amount), 0.0))
    movement_query = movement_query.filter(models.BankTransaction.company_id == company_id)
    if as_of_date:
        movement_query = movement_query.filter(models.BankTransaction.txn_date <= as_of_date)
    movement = float(movement_query.scalar() or 0.0)
    return opening_amount + movement


def _projection_bucket(txn: models.BankTransaction) -> str:
    amount = float(txn.amount)
    desc = (txn.description or "").lower()
    acc_name = ((txn.assigned_account.name if txn.assigned_account else "") or "").lower()
    acc_cat = _normalize_category((txn.assigned_account.category if txn.assigned_account else "") or "")

    if amount >= 0:
        if acc_cat == "Income" or any(k in desc for k in ["sale", "invoice", "service", "revenue", "income"]) or any(
            k in acc_name for k in ["revenue", "sales", "income"]
        ):
            return "income_inflows"
        return "other_inflows"

    if any(k in desc for k in ["salary", "payroll", "wage", "staff"]) or any(k in acc_name for k in ["salary", "payroll", "wage"]):
        return "payroll_expenses"
    if any(k in desc for k in ["tax", "vat", "levy"]) or any(k in acc_name for k in ["tax", "vat"]):
        return "tax_expenses"
    if any(k in desc for k in ["interest"]) or any(k in acc_name for k in ["interest"]):
        return "interest_expenses"
    if any(k in desc for k in ["asset", "equipment", "vehicle", "property", "machine", "capex"]) or any(
        k in acc_name for k in ["fixed asset", "equipment", "vehicle", "property"]
    ):
        return "capex_outflows"
    if any(k in desc for k in ["loan", "principal", "dividend", "capital repayment"]) or any(
        k in acc_name for k in ["loan payable", "equity", "dividend"]
    ):
        return "financing_outflows"
    return "operating_expenses"


def _normalize_category(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"asset", "assets"}:
        return "Asset"
    if value in {"liability", "liabilities"}:
        return "Liability"
    if value in {"equity", "capital"}:
        return "Equity"
    if value in {"income", "revenue", "sales"}:
        return "Income"
    if value in {"expense", "expenses", "cost"}:
        return "Expense"
    return ""


def _account_code_number(code: str) -> int | None:
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _is_current_asset(code: str, name: str) -> bool:
    text = (name or "").lower()
    if any(k in text for k in ["fixed", "vehicle", "property", "equipment", "plant", "land"]):
        return False

    n = _account_code_number(code)
    if n is None:
        return True
    return 1000 <= n < 1500


def _is_current_liability(code: str, name: str) -> bool:
    text = (name or "").lower()
    if any(k in text for k in ["loan", "long", "mortgage", "bond"]):
        return False

    n = _account_code_number(code)
    if n is None:
        return True
    return 2000 <= n < 2200


def _account_totals(
    db: Session, company_id: int, from_date: date | None = None, to_date: date | None = None
) -> dict[int, dict[str, float]]:
    query = (
        db.query(
            models.JournalLine.account_id,
            func.coalesce(func.sum(models.JournalLine.debit), 0.0).label("debit"),
            func.coalesce(func.sum(models.JournalLine.credit), 0.0).label("credit"),
        )
        .join(models.JournalEntry, models.JournalEntry.id == models.JournalLine.entry_id)
        .filter(models.JournalEntry.company_id == company_id)
    )

    if from_date:
        query = query.filter(models.JournalEntry.entry_date >= from_date)
    if to_date:
        query = query.filter(models.JournalEntry.entry_date <= to_date)

    rows = query.group_by(models.JournalLine.account_id).all()
    return {
        int(account_id): {"debit": float(debit), "credit": float(credit)}
        for account_id, debit, credit in rows
    }


def trial_balance(db: Session, company_id: int, from_date: date | None = None, to_date: date | None = None) -> list[dict]:
    totals = _account_totals(db, company_id=company_id, from_date=from_date, to_date=to_date)
    accounts = db.query(models.Account).filter(models.Account.company_id == company_id).order_by(models.Account.code).all()

    data = []
    for account in accounts:
        sums = totals.get(int(account.id), {"debit": 0.0, "credit": 0.0})
        debit = sums["debit"]
        credit = sums["credit"]
        data.append(
            {
                "account_code": account.code,
                "account_name": account.name,
                "debit": round(float(debit), 2),
                "credit": round(float(credit), 2),
                "net": round(float(debit) - float(credit), 2),
            }
        )
    return data


def profit_and_loss(db: Session, company_id: int, from_date: date | None = None, to_date: date | None = None) -> dict:
    totals = _account_totals(db, company_id=company_id, from_date=from_date, to_date=to_date)
    accounts = db.query(models.Account).filter(models.Account.company_id == company_id).order_by(models.Account.code).all()

    income = []
    expenses = []
    total_income = 0.0
    total_expense = 0.0

    for account in accounts:
        normalized = _normalize_category(account.category)
        if normalized not in {"Income", "Expense"}:
            continue

        sums = totals.get(int(account.id), {"debit": 0.0, "credit": 0.0})
        debit = sums["debit"]
        credit = sums["credit"]

        if normalized == "Income":
            amount = credit - debit
            income.append({"code": account.code, "name": account.name, "amount": round(amount, 2)})
            total_income += amount
        else:
            amount = debit - credit
            expenses.append({"code": account.code, "name": account.name, "amount": round(amount, 2)})
            total_expense += amount

    net_profit = total_income - total_expense
    return {
        "income": income,
        "expenses": expenses,
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "net_profit": round(net_profit, 2),
    }


def balance_sheet(db: Session, company_id: int, from_date: date | None = None, to_date: date | None = None) -> dict:
    totals = _account_totals(db, company_id=company_id, from_date=from_date, to_date=to_date)
    accounts = db.query(models.Account).filter(models.Account.company_id == company_id).order_by(models.Account.code).all()

    current_assets = []
    non_current_assets = []
    current_liabilities = []
    non_current_liabilities = []
    equity = []
    total_current_assets = 0.0
    total_non_current_assets = 0.0
    total_current_liabilities = 0.0
    total_non_current_liabilities = 0.0
    total_equity = 0.0
    asset_net_by_account: dict[str, float] = {}

    for account in accounts:
        normalized = _normalize_category(account.category)
        if normalized not in {"Asset", "Liability", "Equity"}:
            continue

        code = account.code
        name = account.name
        sums = totals.get(int(account.id), {"debit": 0.0, "credit": 0.0})
        debit = sums["debit"]
        credit = sums["credit"]

        if normalized == "Asset":
            amount = debit - credit
            row = {"code": code, "name": name, "amount": round(amount, 2)}
            if _is_current_asset(code, name):
                current_assets.append(row)
                total_current_assets += amount
            else:
                non_current_assets.append(row)
                total_non_current_assets += amount
            asset_net_by_account[code] = amount
        elif normalized == "Liability":
            amount = credit - debit
            row = {"code": code, "name": name, "amount": round(amount, 2)}
            if _is_current_liability(code, name):
                current_liabilities.append(row)
                total_current_liabilities += amount
            else:
                non_current_liabilities.append(row)
                total_non_current_liabilities += amount
        else:
            amount = credit - debit
            equity.append({"code": code, "name": name, "amount": round(amount, 2)})
            total_equity += amount

    # If an asset is only in the fixed-asset register (no journal movement yet),
    # include its book value so Balance Sheet reflects registered assets.
    today = date.today()
    fixed_assets = (
        db.query(models.FixedAsset)
        .filter(models.FixedAsset.company_id == company_id)
        .filter(models.FixedAsset.status == "active")
        .all()
    )

    register_by_code: dict[str, dict] = {}
    for item in fixed_assets:
        monthly_dep = straight_line_monthly_depreciation(item.cost, item.salvage_value, item.useful_life_years)
        elapsed_months = min(months_between(item.purchase_date, today), item.useful_life_years * 12)
        accumulated = round(monthly_dep * elapsed_months, 2)
        book_value = round(max(item.cost - accumulated, item.salvage_value), 2)
        code = item.asset_account.code

        if code not in register_by_code:
            register_by_code[code] = {"name": item.asset_account.name, "amount": 0.0}
        register_by_code[code]["amount"] += book_value

    for code, reg in register_by_code.items():
        gl_amount = asset_net_by_account.get(code, 0.0)
        if abs(gl_amount) < 0.005 and abs(reg["amount"]) > 0.005:
            row = {"code": code, "name": reg["name"], "amount": round(reg["amount"], 2)}
            if _is_current_asset(code, reg["name"]):
                current_assets.append(row)
                total_current_assets += reg["amount"]
            else:
                non_current_assets.append(row)
                total_non_current_assets += reg["amount"]

    current_assets = sorted(current_assets, key=lambda x: x["code"])
    non_current_assets = sorted(non_current_assets, key=lambda x: x["code"])
    current_liabilities = sorted(current_liabilities, key=lambda x: x["code"])
    non_current_liabilities = sorted(non_current_liabilities, key=lambda x: x["code"])
    equity = sorted(equity, key=lambda x: x["code"])

    pnl = profit_and_loss(db, company_id=company_id, from_date=from_date, to_date=to_date)
    retained_earnings = pnl["net_profit"]
    total_assets = total_current_assets + total_non_current_assets
    total_liabilities = total_current_liabilities + total_non_current_liabilities
    total_equity_with_earnings = total_equity + retained_earnings

    assets_legacy = current_assets + non_current_assets
    liabilities_legacy = current_liabilities + non_current_liabilities

    return {
        "current_assets": current_assets,
        "non_current_assets": non_current_assets,
        "current_liabilities": current_liabilities,
        "non_current_liabilities": non_current_liabilities,
        "assets": assets_legacy,
        "liabilities": liabilities_legacy,
        "equity": equity,
        "retained_earnings": round(retained_earnings, 2),
        "total_current_assets": round(total_current_assets, 2),
        "total_non_current_assets": round(total_non_current_assets, 2),
        "total_assets": round(total_assets, 2),
        "total_current_liabilities": round(total_current_liabilities, 2),
        "total_non_current_liabilities": round(total_non_current_liabilities, 2),
        "total_liabilities": round(total_liabilities, 2),
        "total_equity": round(total_equity_with_earnings, 2),
        "balanced": round(total_assets, 2) == round(total_liabilities + total_equity_with_earnings, 2),
    }


def cash_flow_statement(db: Session, company_id: int, from_date: date | None = None, to_date: date | None = None) -> dict:
    opening_query = db.query(models.BankOpeningBalance)
    opening_query = opening_query.filter(models.BankOpeningBalance.company_id == company_id)
    if from_date:
        opening_query = opening_query.filter(models.BankOpeningBalance.balance_date <= from_date)

    opening = opening_query.order_by(models.BankOpeningBalance.balance_date.desc(), models.BankOpeningBalance.id.desc()).first()
    opening_balance = float(opening.amount) if opening else 0.0

    txns_query = db.query(models.BankTransaction).filter(models.BankTransaction.company_id == company_id)
    if from_date:
        txns_query = txns_query.filter(models.BankTransaction.txn_date >= from_date)
    if to_date:
        txns_query = txns_query.filter(models.BankTransaction.txn_date <= to_date)
    txns = txns_query.order_by(models.BankTransaction.txn_date.asc(), models.BankTransaction.id.asc()).all()

    operating: list[dict] = []
    investing: list[dict] = []
    financing: list[dict] = []

    op_total = 0.0
    inv_total = 0.0
    fin_total = 0.0

    for txn in txns:
        amt = float(txn.amount)
        text = (txn.description or "").lower()
        account_name = (txn.assigned_account.name if txn.assigned_account else "") or ""
        account_name_l = account_name.lower()

        section = "operating"
        if any(k in text for k in ["loan", "capital", "equity", "dividend"]):
            section = "financing"
        elif any(k in text for k in ["vehicle", "asset", "equipment", "property", "land"]):
            section = "investing"
        elif any(k in account_name_l for k in ["loan payable", "equity"]):
            section = "financing"
        elif any(k in account_name_l for k in ["fixed asset", "asset"]):
            section = "investing"

        row = {
            "date": txn.txn_date,
            "description": txn.description,
            "amount": round(amt, 2),
            "account": account_name or None,
        }

        if section == "operating":
            operating.append(row)
            op_total += amt
        elif section == "investing":
            investing.append(row)
            inv_total += amt
        else:
            financing.append(row)
            fin_total += amt

    net_increase = op_total + inv_total + fin_total
    closing_balance = opening_balance + net_increase

    return {
        "operating_activities": operating,
        "investing_activities": investing,
        "financing_activities": financing,
        "net_cash_from_operating": round(op_total, 2),
        "net_cash_from_investing": round(inv_total, 2),
        "net_cash_from_financing": round(fin_total, 2),
        "net_increase_in_cash": round(net_increase, 2),
        "opening_cash_balance": round(opening_balance, 2),
        "closing_cash_balance": round(closing_balance, 2),
    }


def general_ledger(db: Session, company_id: int, from_date: date | None = None, to_date: date | None = None) -> list[dict]:
    entries_query = (
        db.query(models.JournalEntry)
        .options(joinedload(models.JournalEntry.lines).joinedload(models.JournalLine.account))
        .filter(models.JournalEntry.company_id == company_id)
    )
    if from_date:
        entries_query = entries_query.filter(models.JournalEntry.entry_date >= from_date)
    if to_date:
        entries_query = entries_query.filter(models.JournalEntry.entry_date <= to_date)

    entries = entries_query.order_by(models.JournalEntry.entry_date.asc(), models.JournalEntry.id.asc()).all()

    data = []
    for entry in entries:
        lines = []
        for line in entry.lines:
            lines.append(
                {
                    "account_code": line.account.code,
                    "account_name": line.account.name,
                    "debit": round(float(line.debit), 2),
                    "credit": round(float(line.credit), 2),
                }
            )

        data.append(
            {
                "id": entry.id,
                "entry_date": entry.entry_date,
                "memo": entry.memo,
                "source": entry.source,
                "source_id": entry.source_id,
                "lines": lines,
            }
        )
    return data


def cash_flow_projection(
    db: Session,
    company_id: int,
    months: int = 12,
    from_date: date | None = None,
    to_date: date | None = None,
    inflow_growth_pct: float = 0.0,
    outflow_growth_pct: float = 0.0,
    opening_balance_override: float | None = None,
) -> dict:
    months = max(1, min(int(months), 60))

    base_end = to_date or date.today()
    history_start = _add_months(_month_start(base_end), -5)

    txns_query = db.query(models.BankTransaction).filter(models.BankTransaction.company_id == company_id)
    txns_query = txns_query.filter(models.BankTransaction.txn_date >= history_start)
    txns_query = txns_query.filter(models.BankTransaction.txn_date <= base_end)
    txns = txns_query.order_by(models.BankTransaction.txn_date.asc()).all()

    monthly_buckets: dict[str, dict[str, float]] = {}
    bucket_names = [
        "income_inflows",
        "other_inflows",
        "payroll_expenses",
        "operating_expenses",
        "tax_expenses",
        "interest_expenses",
        "capex_outflows",
        "financing_outflows",
    ]

    for txn in txns:
        key = f"{txn.txn_date.year:04d}-{txn.txn_date.month:02d}"
        monthly_buckets.setdefault(key, {name: 0.0 for name in bucket_names})
        bucket = _projection_bucket(txn)
        amt = abs(float(txn.amount))
        monthly_buckets[key][bucket] = monthly_buckets[key].get(bucket, 0.0) + amt

    month_count = max(1, len(monthly_buckets))
    avg_buckets: dict[str, float] = {}
    for name in bucket_names:
        avg_buckets[name] = sum(m.get(name, 0.0) for m in monthly_buckets.values()) / month_count if monthly_buckets else 0.0

    avg_inflow = avg_buckets["income_inflows"] + avg_buckets["other_inflows"]
    avg_outflow = (
        avg_buckets["payroll_expenses"]
        + avg_buckets["operating_expenses"]
        + avg_buckets["tax_expenses"]
        + avg_buckets["interest_expenses"]
        + avg_buckets["capex_outflows"]
        + avg_buckets["financing_outflows"]
    )

    forecast_start = from_date or _add_months(_month_start(base_end), 1)
    opening_balance = (
        float(opening_balance_override)
        if opening_balance_override is not None
        else _cash_balance_as_of(db, company_id=company_id, as_of_date=base_end)
    )

    inflow_growth = float(inflow_growth_pct) / 100.0
    outflow_growth = float(outflow_growth_pct) / 100.0

    lines: list[dict] = []
    current_opening = opening_balance

    for idx in range(months):
        month_date = _add_months(forecast_start, idx)
        income_inflows = avg_buckets["income_inflows"] * ((1 + inflow_growth) ** idx)
        other_inflows = avg_buckets["other_inflows"] * ((1 + inflow_growth) ** idx)
        payroll_expenses = avg_buckets["payroll_expenses"] * ((1 + outflow_growth) ** idx)
        operating_expenses = avg_buckets["operating_expenses"] * ((1 + outflow_growth) ** idx)
        tax_expenses = avg_buckets["tax_expenses"] * ((1 + outflow_growth) ** idx)
        interest_expenses = avg_buckets["interest_expenses"] * ((1 + outflow_growth) ** idx)
        capex_outflows = avg_buckets["capex_outflows"] * ((1 + outflow_growth) ** idx)
        financing_outflows = avg_buckets["financing_outflows"] * ((1 + outflow_growth) ** idx)

        inflow = income_inflows + other_inflows
        outflow = payroll_expenses + operating_expenses + tax_expenses + interest_expenses + capex_outflows + financing_outflows
        net = inflow - outflow
        closing = current_opening + net

        lines.append(
            {
                "month": month_date.strftime("%Y-%m"),
                "opening_balance": round(current_opening, 2),
                "projected_income_inflows": round(income_inflows, 2),
                "projected_other_inflows": round(other_inflows, 2),
                "projected_inflows": round(inflow, 2),
                "projected_payroll_expenses": round(payroll_expenses, 2),
                "projected_operating_expenses": round(operating_expenses, 2),
                "projected_tax_expenses": round(tax_expenses, 2),
                "projected_interest_expenses": round(interest_expenses, 2),
                "projected_capex_outflows": round(capex_outflows, 2),
                "projected_financing_outflows": round(financing_outflows, 2),
                "projected_outflows": round(outflow, 2),
                "projected_net_cash": round(net, 2),
                "closing_balance": round(closing, 2),
            }
        )
        current_opening = closing

    return {
        "assumptions": {
            "history_start": history_start,
            "history_end": base_end,
            "forecast_start": forecast_start,
            "months": months,
            "avg_monthly_inflows": round(avg_inflow, 2),
            "avg_monthly_outflows": round(avg_outflow, 2),
            "avg_income_inflows": round(avg_buckets["income_inflows"], 2),
            "avg_other_inflows": round(avg_buckets["other_inflows"], 2),
            "avg_payroll_expenses": round(avg_buckets["payroll_expenses"], 2),
            "avg_operating_expenses": round(avg_buckets["operating_expenses"], 2),
            "avg_tax_expenses": round(avg_buckets["tax_expenses"], 2),
            "avg_interest_expenses": round(avg_buckets["interest_expenses"], 2),
            "avg_capex_outflows": round(avg_buckets["capex_outflows"], 2),
            "avg_financing_outflows": round(avg_buckets["financing_outflows"], 2),
            "inflow_growth_pct": round(float(inflow_growth_pct), 4),
            "outflow_growth_pct": round(float(outflow_growth_pct), 4),
            "opening_balance": round(opening_balance, 2),
        },
        "projection": lines,
    }


def bookkeeping_documents(db: Session, company_id: int) -> dict:
    unmatched = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id)
        .filter(models.BankTransaction.status == "unmatched")
        .order_by(models.BankTransaction.txn_date.asc())
        .all()
    )

    unmatched_docs = [
        {
            "id": txn.id,
            "date": txn.txn_date,
            "description": txn.description,
            "amount": txn.amount,
            "status": txn.status,
        }
        for txn in unmatched
    ]

    return {
        "general_ledger": general_ledger(db, company_id=company_id),
        "trial_balance": trial_balance(db, company_id=company_id),
        "profit_and_loss": profit_and_loss(db, company_id=company_id),
        "balance_sheet": balance_sheet(db, company_id=company_id),
        "unmatched_transactions": unmatched_docs,
    }

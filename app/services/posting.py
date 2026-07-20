from sqlalchemy.orm import Session

from app import models


BANK_ACCOUNT_CODE = "1000"
VAT_INPUT_ACCOUNT_CODE = "1300"
VAT_OUTPUT_ACCOUNT_CODE = "2100"


def _vat_split(gross: float, vat_rate_percent: float) -> tuple[float, float]:
    rate = vat_rate_percent / 100.0
    if rate <= 0:
        return gross, 0.0

    vat_amount = round(gross * rate / (1 + rate), 2)
    net_amount = round(gross - vat_amount, 2)
    return net_amount, vat_amount


def post_allocated_transactions(db: Session, company_id: int) -> tuple[int, int]:
    bank_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.code == BANK_ACCOUNT_CODE)
        .first()
    )
    if not bank_account:
        raise ValueError("Bank account (code 1000) not found in chart of accounts")

    vat_input_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.code == VAT_INPUT_ACCOUNT_CODE)
        .first()
    )
    vat_output_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.code == VAT_OUTPUT_ACCOUNT_CODE)
        .first()
    )

    txns = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id)
        .filter(models.BankTransaction.status == "allocated")
        .all()
    )

    posted = 0
    skipped = 0

    for txn in txns:
        exists = (
            db.query(models.JournalEntry)
            .filter(
                models.JournalEntry.company_id == company_id,
                models.JournalEntry.source == "bank",
                models.JournalEntry.source_id == txn.id,
            )
            .first()
        )
        if exists:
            skipped += 1
            continue

        if not txn.assigned_account_id:
            skipped += 1
            continue

        gross_amount = abs(txn.amount)
        vat_rate = float(txn.assigned_account.vat_rate if txn.assigned_account else 0.0)
        net_amount, vat_amount = _vat_split(gross_amount, vat_rate)
        memo = f"Bank txn: {txn.description}"

        entry = models.JournalEntry(
            company_id=company_id,
            entry_date=txn.txn_date,
            memo=memo,
            source="bank",
            source_id=txn.id,
        )
        db.add(entry)
        db.flush()

        # Negative amount = money out (expense/payment), positive = money in (income/receipt)
        if txn.amount < 0:
            lines = [models.JournalLine(entry_id=entry.id, account_id=txn.assigned_account_id, debit=net_amount, credit=0.0)]

            if vat_amount > 0:
                if not vat_input_account:
                    raise ValueError("VAT input account (code 1300) not found in chart of accounts")
                lines.append(
                    models.JournalLine(entry_id=entry.id, account_id=vat_input_account.id, debit=vat_amount, credit=0.0)
                )

            lines.append(models.JournalLine(entry_id=entry.id, account_id=bank_account.id, debit=0.0, credit=gross_amount))
        else:
            lines = [models.JournalLine(entry_id=entry.id, account_id=bank_account.id, debit=gross_amount, credit=0.0)]

            lines.append(
                models.JournalLine(entry_id=entry.id, account_id=txn.assigned_account_id, debit=0.0, credit=net_amount)
            )

            if vat_amount > 0:
                if not vat_output_account:
                    raise ValueError("VAT output account (code 2100) not found in chart of accounts")
                lines.append(
                    models.JournalLine(entry_id=entry.id, account_id=vat_output_account.id, debit=0.0, credit=vat_amount)
                )

        for line in lines:
            db.add(line)

        txn.status = "posted"
        posted += 1

    db.commit()
    return posted, skipped

from sqlalchemy.orm import Session

from app import models


def _extract_keywords(raw: str) -> list[str]:
    if not raw:
        return []

    normalized = raw.replace("|", ",").replace(";", ",").replace("\n", ",")
    return [x.strip().lower() for x in normalized.split(",") if x.strip()]


def apply_allocation_rules(db: Session, company_id: int) -> tuple[int, int]:
    rules = (
        db.query(models.AllocationRule)
        .filter(models.AllocationRule.company_id == company_id)
        .order_by(models.AllocationRule.priority.asc(), models.AllocationRule.id.asc())
        .all()
    )

    txns = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id)
        .filter(models.BankTransaction.status.in_(["imported", "unmatched"]))
        .all()
    )

    allocated = 0

    for txn in txns:
        match = None
        for rule in rules:
            keywords = _extract_keywords(rule.keyword)
            keyword_hit = any(k in txn.description.lower() for k in keywords)
            min_ok = rule.min_amount is None or txn.amount >= rule.min_amount
            max_ok = rule.max_amount is None or txn.amount <= rule.max_amount
            if keyword_hit and min_ok and max_ok:
                match = rule
                break

        if match:
            txn.assigned_account_id = match.account_id
            txn.status = "allocated"
            allocated += 1
        else:
            txn.status = "unmatched"

    db.commit()

    unmatched = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id)
        .filter(models.BankTransaction.status == "unmatched")
        .count()
    )
    return allocated, unmatched

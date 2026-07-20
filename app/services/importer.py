import csv
import hashlib
import logging
from datetime import datetime
from io import StringIO

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)


DATE_KEYS = ["date", "txn_date", "transaction_date", "value_date", "posting_date"]
DESC_KEYS = [
    "description",
    "narration",
    "details",
    "transaction_details",
    "transaction description",
    "memo",
    "particulars",
]
AMOUNT_KEYS = ["amount", "transaction_amount", "amt"]
DEBIT_KEYS = ["debit", "debits", "payment", "payments", "withdrawal", "money_out", "outflow"]
CREDIT_KEYS = ["credit", "credits", "deposit", "deposits", "money_in", "inflow"]
REF_KEYS = ["reference", "ref", "transaction_id", "id", "cheque_no"]
CUR_KEYS = ["currency", "ccy"]

DATE_FORMAT_MAP = {
    "yyyy-mm-dd": ["%Y-%m-%d"],
    "yyyy/mm/dd": ["%Y/%m/%d"],
    "dd/mm/yyyy": ["%d/%m/%Y"],
    "mm/dd/yyyy": ["%m/%d/%Y"],
    "dd-mm-yyyy": ["%d-%m-%Y"],
}

DEFAULT_DATE_PATTERNS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_row(row: dict) -> dict:
    normalized = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized[_normalize_key(str(key))] = (value or "").strip()
    return normalized


def _first_value(row: dict, keys: list[str]) -> str:
    for key in keys:
        if key in row and row[key]:
            return row[key]
    return ""


def _parse_date(date_raw: str, date_format: str | None = None):
    date_raw = date_raw.strip()
    patterns = []
    if date_format and date_format in DATE_FORMAT_MAP:
        patterns.extend(DATE_FORMAT_MAP[date_format])
    patterns.extend([p for p in DEFAULT_DATE_PATTERNS if p not in patterns])
    for pattern in patterns:
        try:
            return datetime.strptime(date_raw, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {date_raw}")


def _parse_amount_text(text: str) -> float:
    clean = text.strip().replace("\u00A0", " ")
    clean = clean.replace("$", "").replace("USD", "").replace("ZWL", "").replace("ZAR", "").strip()
    if clean.startswith("(") and clean.endswith(")"):
        clean = f"-{clean[1:-1]}"
    clean = clean.replace("−", "-")
    clean = clean.replace(" ", "")

    if "," in clean and "." in clean:
        # Use the right-most symbol as decimal separator and strip the other as thousands separators.
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "")
            clean = clean.replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        # Treat comma as decimal when there are 1-2 trailing digits, else as thousands separator.
        left, right = clean.rsplit(",", 1)
        if right.isdigit() and 1 <= len(right) <= 2:
            clean = f"{left}.{right}"
        else:
            clean = clean.replace(",", "")

    return float(clean)


def _parse_amount(
    row: dict,
    amount_mode: str = "auto",
    amount_keys: list[str] | None = None,
    debit_keys: list[str] | None = None,
    credit_keys: list[str] | None = None,
) -> float:
    amount_keys = amount_keys or AMOUNT_KEYS
    debit_keys = debit_keys or DEBIT_KEYS
    credit_keys = credit_keys or CREDIT_KEYS

    if amount_mode not in {"auto", "signed_amount", "debit_credit"}:
        amount_mode = "auto"

    if amount_mode in {"auto", "signed_amount"}:
        direct = _first_value(row, amount_keys)
        if direct:
            return _parse_amount_text(direct)

    if amount_mode in {"auto", "debit_credit"}:
        debit_raw = _first_value(row, debit_keys)
        credit_raw = _first_value(row, credit_keys)
        if debit_raw or credit_raw:
            # Bank exports often store debit/credit columns with explicit minus signs.
            # Normalize to magnitudes so direction is consistently credit - debit.
            debit = abs(_parse_amount_text(debit_raw)) if debit_raw else 0.0
            credit = abs(_parse_amount_text(credit_raw)) if credit_raw else 0.0
            return credit - debit

    raise ValueError("Missing amount columns")


def _prefixed_keys(default_keys: list[str], custom_key: str | None) -> list[str]:
    if not custom_key:
        return default_keys

    key = _normalize_key(custom_key)
    return [key] + [k for k in default_keys if k != key]


def _is_repeated_header_row(row: dict) -> bool:
    if not row:
        return False
    values = [str(v or "").strip().lower() for v in row.values()]
    if not any(values):
        return False
    expected_headers = {
        "date",
        "txn_date",
        "transaction_date",
        "description",
        "payments",
        "payment",
        "debit",
        "deposits",
        "deposit",
        "credit",
        "amount",
    }
    hits = sum(1 for v in values if v in expected_headers)
    return hits >= 3


def _get_reader(text: str):
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return csv.DictReader(StringIO(text), dialect=dialect)
    except csv.Error:
        return csv.DictReader(StringIO(text))


def _make_hash(company_id: int, txn_date: str, description: str, amount: str, reference: str) -> str:
    key = f"{company_id}|{txn_date}|{description.strip().lower()}|{amount}|{reference.strip().lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def import_bank_csv(
    db: Session,
    content: bytes,
    company_id: int,
    date_format: str | None = None,
    amount_mode: str = "auto",
    date_column: str | None = None,
    amount_column: str | None = None,
    debit_column: str | None = None,
    credit_column: str | None = None,
    description_column: str | None = None,
    reference_column: str | None = None,
    currency_column: str | None = None,
) -> tuple[int, int, int, list[dict]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = _get_reader(text)

    imported = 0
    skipped = 0
    skipped_invalid = 0
    errors: list[dict] = []
    seen_hashes: set[str] = set()

    date_keys = _prefixed_keys(DATE_KEYS, date_column)
    amount_keys = _prefixed_keys(AMOUNT_KEYS, amount_column)
    debit_keys = _prefixed_keys(DEBIT_KEYS, debit_column)
    credit_keys = _prefixed_keys(CREDIT_KEYS, credit_column)
    desc_keys = _prefixed_keys(DESC_KEYS, description_column)
    ref_keys = _prefixed_keys(REF_KEYS, reference_column)
    cur_keys = _prefixed_keys(CUR_KEYS, currency_column)

    for index, raw_row in enumerate(reader, start=2):
        try:
            row = _normalize_row(raw_row)

            if _is_repeated_header_row(row):
                logger.info("Skipping repeated header row at line %s", index)
                continue

            if not any(str(v or "").strip() for v in row.values()):
                continue

            txn_date_raw = _first_value(row, date_keys)
            description = _first_value(row, desc_keys)
            reference = _first_value(row, ref_keys)
            currency = (_first_value(row, cur_keys) or "USD").upper()

            if not txn_date_raw:
                skipped_invalid += 1
                errors.append(
                    {
                        "row": index,
                        "message": "Missing date column value",
                        "raw": row,
                    }
                )
                logger.warning("Skipping row %s: missing date. row=%s", index, row)
                continue

            if not description:
                description = reference or "BANK TRANSACTION"

            txn_date = _parse_date(txn_date_raw, date_format=date_format)
            amount = _parse_amount(
                row,
                amount_mode=amount_mode,
                amount_keys=amount_keys,
                debit_keys=debit_keys,
                credit_keys=credit_keys,
            )
            imported_hash = _make_hash(company_id, txn_date.isoformat(), description, str(amount), reference)

            if imported_hash in seen_hashes:
                skipped += 1
                continue

            exists = (
                db.query(models.BankTransaction)
                .filter(models.BankTransaction.company_id == company_id, models.BankTransaction.imported_hash == imported_hash)
                .first()
            )
            if exists:
                skipped += 1
                continue

            txn = models.BankTransaction(
                company_id=company_id,
                txn_date=txn_date,
                description=description,
                amount=amount,
                currency=currency,
                reference=reference,
                imported_hash=imported_hash,
                status="imported",
            )
            db.add(txn)
            seen_hashes.add(imported_hash)
            imported += 1
        except Exception as exc:
            skipped_invalid += 1
            errors.append(
                {
                    "row": index,
                    "message": str(exc),
                    "raw": _normalize_row(raw_row),
                }
            )
            logger.exception("Skipping invalid row %s due to parse error: %s raw_row=%s", index, exc, raw_row)

    db.commit()
    logger.info(
        "Import completed: imported=%s skipped_duplicates=%s skipped_invalid_rows=%s",
        imported,
        skipped,
        skipped_invalid,
    )
    return imported, skipped, skipped_invalid, errors

from pathlib import Path
import logging
from datetime import date, timedelta, datetime
import csv
import io
import json
import re
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from passlib.context import CryptContext
from jose import JWTError, jwt

from app import models, schemas
from app.database import Base, engine, get_db
from app.services.allocation import apply_allocation_rules
from app.services.importer import import_bank_csv
from app.services.finance import build_loan_schedule, months_between, straight_line_monthly_depreciation
from app.services.pdf_export import (
    build_invoice_pdf,
    build_employment_certificate_pdf,
    build_payroll_payslip_pdf,
    build_payroll_run_pdf,
    build_report_pdf,
    build_tax_certificate_pdf,
)
from app.services.posting import post_allocated_transactions
from app.services.reports import (
    balance_sheet,
    bookkeeping_documents,
    cash_flow_statement,
    cash_flow_projection,
    general_ledger,
    profit_and_loss,
    trial_balance,
)

# Auth constants
SECRET_KEY = "your-secret-key-here"  # In production, use environment variable
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def authenticate_user(db: Session, email: str, password: str):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        return False
    if not verify_password(password, user.password_hash):
        return False
    return user

def get_current_user(request: Request, db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=403,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise credentials_exception
        # Remove "Bearer " prefix if present
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

BASE_DIR = Path(__file__).resolve().parent
PAYROLL_DOCS_DIR = BASE_DIR / "uploads" / "payroll_documents"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Accounting MVP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text("INSERT OR IGNORE INTO companies (id, name) VALUES (1, 'Default Company')"))

        company_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(companies)"))]
        if "is_archived" not in company_cols:
            conn.execute(text("ALTER TABLE companies ADD COLUMN is_archived INTEGER DEFAULT 0"))
            conn.execute(text("UPDATE companies SET is_archived=0 WHERE is_archived IS NULL"))

        table_company_cols = {
            "accounts": "company_id",
            "bank_transactions": "company_id",
            "allocation_rules": "company_id",
            "journal_entries": "company_id",
            "fixed_assets": "company_id",
            "loans": "company_id",
            "bank_opening_balances": "company_id",
            "company_profile": "company_id",
        }

        for table_name, col_name in table_company_cols.items():
            cols = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})"))]
            if col_name not in cols:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} INTEGER DEFAULT 1"))
                conn.execute(text(f"UPDATE {table_name} SET {col_name}=1 WHERE {col_name} IS NULL"))

        acc_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(accounts)"))]
        if "vat_rate" not in acc_cols:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN vat_rate FLOAT DEFAULT 0.0"))

        try:
            conn.execute(text("DROP INDEX IF EXISTS ix_accounts_code"))
        except Exception:
            pass
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_company_code_idx ON accounts(company_id, code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_accounts_code ON accounts(code)"))

        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_company_profile_company_idx ON company_profile(company_id)"))

        payroll_run_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(payroll_runs)"))]
        payroll_run_alters = {
            "total_nssa": "ALTER TABLE payroll_runs ADD COLUMN total_nssa FLOAT DEFAULT 0.0",
            "total_pension": "ALTER TABLE payroll_runs ADD COLUMN total_pension FLOAT DEFAULT 0.0",
            "total_other_deductions": "ALTER TABLE payroll_runs ADD COLUMN total_other_deductions FLOAT DEFAULT 0.0",
            "total_sdl": "ALTER TABLE payroll_runs ADD COLUMN total_sdl FLOAT DEFAULT 0.0",
            "paye_rate": "ALTER TABLE payroll_runs ADD COLUMN paye_rate FLOAT DEFAULT 0.0",
            "nssa_rate": "ALTER TABLE payroll_runs ADD COLUMN nssa_rate FLOAT DEFAULT 0.0",
            "pension_rate": "ALTER TABLE payroll_runs ADD COLUMN pension_rate FLOAT DEFAULT 0.0",
            "sdl_rate": "ALTER TABLE payroll_runs ADD COLUMN sdl_rate FLOAT DEFAULT 0.0",
            "other_deduction_per_employee": "ALTER TABLE payroll_runs ADD COLUMN other_deduction_per_employee FLOAT DEFAULT 0.0",
            "payment_entry_id": "ALTER TABLE payroll_runs ADD COLUMN payment_entry_id INTEGER",
            "paid_date": "ALTER TABLE payroll_runs ADD COLUMN paid_date DATE",
        }
        for col, ddl in payroll_run_alters.items():
            if col not in payroll_run_cols:
                conn.execute(text(ddl))

        payroll_line_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(payroll_run_lines)"))]
        payroll_line_alters = {
            "nssa_amount": "ALTER TABLE payroll_run_lines ADD COLUMN nssa_amount FLOAT DEFAULT 0.0",
            "pension_amount": "ALTER TABLE payroll_run_lines ADD COLUMN pension_amount FLOAT DEFAULT 0.0",
            "other_deduction": "ALTER TABLE payroll_run_lines ADD COLUMN other_deduction FLOAT DEFAULT 0.0",
            "sdl_amount": "ALTER TABLE payroll_run_lines ADD COLUMN sdl_amount FLOAT DEFAULT 0.0",
            "total_deductions": "ALTER TABLE payroll_run_lines ADD COLUMN total_deductions FLOAT DEFAULT 0.0",
        }
        for col, ddl in payroll_line_alters.items():
            if col not in payroll_line_cols:
                conn.execute(text(ddl))

        payroll_employee_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(payroll_employees)"))]
        payroll_employee_alters = {
            "photo_url": "ALTER TABLE payroll_employees ADD COLUMN photo_url VARCHAR(500) DEFAULT ''",
            "id_number": "ALTER TABLE payroll_employees ADD COLUMN id_number VARCHAR(80) DEFAULT ''",
            "tax_number": "ALTER TABLE payroll_employees ADD COLUMN tax_number VARCHAR(80) DEFAULT ''",
            "email": "ALTER TABLE payroll_employees ADD COLUMN email VARCHAR(120) DEFAULT ''",
            "phone": "ALTER TABLE payroll_employees ADD COLUMN phone VARCHAR(60) DEFAULT ''",
            "position": "ALTER TABLE payroll_employees ADD COLUMN position VARCHAR(120) DEFAULT ''",
            "hire_date": "ALTER TABLE payroll_employees ADD COLUMN hire_date DATE",
            "bank_account": "ALTER TABLE payroll_employees ADD COLUMN bank_account VARCHAR(120) DEFAULT ''",
            "nssa_number": "ALTER TABLE payroll_employees ADD COLUMN nssa_number VARCHAR(80) DEFAULT ''",
            "pension_number": "ALTER TABLE payroll_employees ADD COLUMN pension_number VARCHAR(80) DEFAULT ''",
        }
        for col, ddl in payroll_employee_alters.items():
            if col not in payroll_employee_cols:
                conn.execute(text(ddl))

        invoice_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(invoices)"))]
        invoice_alters = {
            "customer_id": "ALTER TABLE invoices ADD COLUMN customer_id INTEGER",
            "outstanding_balance": "ALTER TABLE invoices ADD COLUMN outstanding_balance FLOAT DEFAULT 0.0",
            "sent_date": "ALTER TABLE invoices ADD COLUMN sent_date DATE",
        }
        for col, ddl in invoice_alters.items():
            if col not in invoice_cols:
                conn.execute(text(ddl))

        invoice_line_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(invoice_lines)"))]
        if "inventory_item_id" not in invoice_line_cols:
            conn.execute(text("ALTER TABLE invoice_lines ADD COLUMN inventory_item_id INTEGER"))

        if "outstanding_balance" in invoice_cols:
            conn.execute(text("UPDATE invoices SET outstanding_balance = COALESCE(total, 0) WHERE outstanding_balance IS NULL OR outstanding_balance = 0"))

        conn.commit()


@app.post("/auth/register", response_model=schemas.UserOut)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email, password_hash=hashed_password, full_name=user.full_name)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/auth/login", response_model=schemas.Token)
def login_user(user: schemas.UserLogin, response: Response, db: Session = Depends(get_db)):
    db_user = authenticate_user(db, user.email, user.password)
    if not db_user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": db_user.email}, expires_delta=access_token_expires
    )
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/auth/logout")
def logout_user(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "Logged out successfully"}


@app.get("/auth/me", response_model=schemas.UserOut)
def get_current_user_info(current_user: models.User = Depends(get_current_user)):
    return current_user


@app.get("/health")
def health_check():
    return {"status": "ok"}


def _resolve_company(db: Session, company_id: int | None) -> models.Company:
    cid = company_id or 1
    company = db.query(models.Company).filter(models.Company.id == cid, models.Company.is_archived.is_(False)).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def _get_company_profile(db: Session, company_id: int) -> models.CompanyProfile:
    profile = (
        db.query(models.CompanyProfile)
        .filter(models.CompanyProfile.company_id == company_id)
        .order_by(models.CompanyProfile.id.asc())
        .first()
    )
    if profile:
        return profile

    company = _resolve_company(db, company_id)
    profile = models.CompanyProfile(company_id=company.id, company_name=company.name or "My Company", currency="USD")
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _company_profile_data(profile: models.CompanyProfile) -> dict:
    return {
        "company_name": profile.company_name,
        "address": profile.address,
        "email": profile.email,
        "phone": profile.phone,
        "tax_number": profile.tax_number,
        "currency": profile.currency,
    }


def _ensure_default_tax_brackets(db: Session, company_id: int):
    exists = db.query(models.PayrollTaxBracket).filter(models.PayrollTaxBracket.company_id == company_id).first()
    if exists:
        return

    defaults = [
        (0.0, 100.0, 0.0, 1),
        (100.0, 300.0, 20.0, 2),
        (300.0, 1000.0, 25.0, 3),
        (1000.0, None, 30.0, 4),
    ]
    for lower, upper, rate, idx in defaults:
        db.add(
            models.PayrollTaxBracket(
                company_id=company_id,
                lower_limit=lower,
                upper_limit=upper,
                rate_percent=rate,
                order_index=idx,
            )
        )
    db.commit()


def _compute_progressive_tax(gross: float, brackets: list[models.PayrollTaxBracket]) -> float:
    taxable = max(float(gross or 0.0), 0.0)
    tax = 0.0
    sorted_brackets = sorted(brackets, key=lambda b: (b.order_index, b.lower_limit))
    for b in sorted_brackets:
        lower = float(b.lower_limit or 0.0)
        upper = float(b.upper_limit) if b.upper_limit is not None else None
        if taxable <= lower:
            continue
        slice_upper = taxable if upper is None else min(taxable, upper)
        taxable_portion = max(slice_upper - lower, 0.0)
        if taxable_portion <= 0:
            continue
        tax += taxable_portion * float(b.rate_percent or 0.0) / 100.0
    return round(tax, 2)


def _safe_slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    return clean.strip("-") or "file"


def _payroll_employee_payload(emp: models.PayrollEmployee) -> dict:
    return {
        "id": emp.id,
        "employee_code": emp.employee_code,
        "full_name": emp.full_name,
        "photo_url": emp.photo_url,
        "id_number": emp.id_number,
        "tax_number": emp.tax_number,
        "email": emp.email,
        "phone": emp.phone,
        "position": emp.position,
        "hire_date": emp.hire_date,
        "bank_account": emp.bank_account,
        "nssa_number": emp.nssa_number,
        "pension_number": emp.pension_number,
        "default_gross_salary": float(emp.default_gross_salary or 0.0),
        "tax_rate": float(emp.tax_rate or 0.0),
        "active": emp.active,
    }


def _next_invoice_number(db: Session, company_id: int) -> str:
    last = (
        db.query(models.Invoice)
        .filter(models.Invoice.company_id == company_id)
        .order_by(models.Invoice.id.desc())
        .first()
    )
    next_id = (last.id + 1) if last else 1
    return f"INV-{next_id:05d}"


def _invoice_out(inv: models.Invoice) -> dict:
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "customer_name": inv.customer_name,
        "customer_email": inv.customer_email,
        "issue_date": inv.issue_date,
        "due_date": inv.due_date,
        "status": inv.status,
        "currency": inv.currency,
        "subtotal": float(inv.subtotal or 0.0),
        "tax_total": float(inv.tax_total or 0.0),
        "total": float(inv.total or 0.0),
        "outstanding_balance": float(inv.outstanding_balance or 0.0),
        "notes": inv.notes,
        "sent_date": inv.sent_date,
        "paid_date": inv.paid_date,
        "line_count": len(inv.lines or []),
    }


def _ensure_period_open(db: Session, company_id: int, txn_date: date):
    lock = db.query(models.PeriodLock).filter(models.PeriodLock.company_id == company_id).first()
    if lock and lock.locked_until and txn_date <= lock.locked_until:
        raise HTTPException(status_code=400, detail=f"Period is locked up to {lock.locked_until}")


def _recalculate_invoice_status(db: Session, inv: models.Invoice):
    paid_total = (
        db.query(func.coalesce(func.sum(models.InvoicePayment.amount), 0.0))
        .filter(models.InvoicePayment.company_id == inv.company_id, models.InvoicePayment.invoice_id == inv.id)
        .scalar()
        or 0.0
    )
    outstanding = round(max(float(inv.total or 0.0) - float(paid_total), 0.0), 2)
    inv.outstanding_balance = outstanding

    if outstanding <= 0:
        inv.status = "paid"
        if not inv.paid_date:
            inv.paid_date = date.today()
    else:
        inv.paid_date = None
        if inv.sent_date:
            inv.status = "sent"
        if inv.due_date < date.today():
            inv.status = "overdue"


def _refresh_overdue_invoices(db: Session, company_id: int):
    rows = (
        db.query(models.Invoice)
        .filter(
            models.Invoice.company_id == company_id,
            models.Invoice.status.in_(["draft", "sent", "partial", "overdue"]),
            models.Invoice.outstanding_balance > 0,
        )
        .all()
    )
    changed = 0
    for inv in rows:
        old = inv.status
        if inv.due_date < date.today():
            inv.status = "overdue"
        elif inv.sent_date:
            inv.status = "sent"
        else:
            inv.status = "draft"
        if old != inv.status:
            changed += 1
    if changed:
        db.commit()


def _bank_balance_summary(db: Session, company_id: int) -> dict:
    opening = (
        db.query(models.BankOpeningBalance)
        .filter(models.BankOpeningBalance.company_id == company_id)
        .order_by(models.BankOpeningBalance.balance_date.desc(), models.BankOpeningBalance.id.desc())
        .first()
    )

    opening_amount = float(opening.amount) if opening else 0.0
    opening_date = opening.balance_date if opening else None

    inflows = (
        db.query(func.coalesce(func.sum(models.BankTransaction.amount), 0.0))
        .filter(models.BankTransaction.company_id == company_id)
        .filter(models.BankTransaction.amount > 0)
        .scalar()
        or 0.0
    )
    outflows_raw = (
        db.query(func.coalesce(func.sum(models.BankTransaction.amount), 0.0))
        .filter(models.BankTransaction.company_id == company_id)
        .filter(models.BankTransaction.amount < 0)
        .scalar()
        or 0.0
    )
    outflows = abs(float(outflows_raw))
    net = float(inflows) - outflows
    closing = opening_amount + net

    earliest_txn = (
        db.query(models.BankTransaction.txn_date)
        .filter(models.BankTransaction.company_id == company_id)
        .order_by(models.BankTransaction.txn_date.asc(), models.BankTransaction.id.asc())
        .first()
    )
    earliest_txn_date = earliest_txn[0] if earliest_txn else None
    opening_missing = opening_date is None and earliest_txn_date is not None
    warning = None
    if opening_missing:
        warning = "No opening balance set. Set opening balance at or before your first transaction date."
    elif opening_date and earliest_txn_date and opening_date > earliest_txn_date:
        warning = "Opening balance date is after first transaction date. Review opening balance date."

    return {
        "opening_balance_date": opening_date,
        "opening_balance": round(opening_amount, 2),
        "total_inflows": round(float(inflows), 2),
        "total_outflows": round(outflows, 2),
        "net_movement": round(net, 2),
        "closing_balance": round(closing, 2),
        "opening_balance_missing": opening_missing,
        "suggested_opening_balance_date": earliest_txn_date,
        "warning": warning,
    }


def _running_balance_timeline(db: Session, company_id: int) -> dict:
    opening = (
        db.query(models.BankOpeningBalance)
        .filter(models.BankOpeningBalance.company_id == company_id)
        .order_by(models.BankOpeningBalance.balance_date.asc(), models.BankOpeningBalance.id.asc())
        .first()
    )

    opening_amount = float(opening.amount) if opening else 0.0
    opening_date = opening.balance_date if opening else None

    txns = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id)
        .order_by(models.BankTransaction.txn_date.asc(), models.BankTransaction.id.asc())
        .all()
    )

    running = opening_amount
    rows: list[dict] = []
    for txn in txns:
        running += float(txn.amount)
        rows.append(
            {
                "date": txn.txn_date,
                "description": txn.description,
                "amount": round(float(txn.amount), 2),
                "running_balance": round(running, 2),
            }
        )

    summary = _bank_balance_summary(db, company_id=company_id)
    return {
        "opening_balance_date": opening_date,
        "opening_balance": round(opening_amount, 2),
        "rows": rows,
        "closing_balance": round(running, 2),
        "opening_balance_missing": summary.get("opening_balance_missing", False),
        "suggested_opening_balance_date": summary.get("suggested_opening_balance_date"),
        "warning": summary.get("warning"),
    }


def _report_to_csv(report_name: str, data):
    output = io.StringIO()
    writer = csv.writer(output)

    if report_name == "trial-balance":
        writer.writerow(["account_code", "account_name", "debit", "credit", "net"])
        for row in data:
            writer.writerow([row["account_code"], row["account_name"], row["debit"], row["credit"], row["net"]])
    elif report_name == "profit-loss":
        writer.writerow(["section", "code", "name", "amount"])
        for row in data.get("income", []):
            writer.writerow(["income", row["code"], row["name"], row["amount"]])
        for row in data.get("expenses", []):
            writer.writerow(["expense", row["code"], row["name"], row["amount"]])
        writer.writerow(["summary", "", "total_income", data.get("total_income", 0)])
        writer.writerow(["summary", "", "total_expense", data.get("total_expense", 0)])
        writer.writerow(["summary", "", "net_profit", data.get("net_profit", 0)])
    elif report_name == "balance-sheet":
        writer.writerow(["section", "code", "name", "amount"])
        for row in data.get("current_assets", []):
            writer.writerow(["current_asset", row["code"], row["name"], row["amount"]])
        for row in data.get("non_current_assets", []):
            writer.writerow(["non_current_asset", row["code"], row["name"], row["amount"]])
        for row in data.get("current_liabilities", []):
            writer.writerow(["current_liability", row["code"], row["name"], row["amount"]])
        for row in data.get("non_current_liabilities", []):
            writer.writerow(["non_current_liability", row["code"], row["name"], row["amount"]])
        for row in data.get("equity", []):
            writer.writerow(["equity", row["code"], row["name"], row["amount"]])
        writer.writerow(["summary", "", "retained_earnings", data.get("retained_earnings", 0)])
        writer.writerow(["summary", "", "total_current_assets", data.get("total_current_assets", 0)])
        writer.writerow(["summary", "", "total_non_current_assets", data.get("total_non_current_assets", 0)])
        writer.writerow(["summary", "", "total_assets", data.get("total_assets", 0)])
        writer.writerow(["summary", "", "total_current_liabilities", data.get("total_current_liabilities", 0)])
        writer.writerow(["summary", "", "total_non_current_liabilities", data.get("total_non_current_liabilities", 0)])
        writer.writerow(["summary", "", "total_liabilities", data.get("total_liabilities", 0)])
        writer.writerow(["summary", "", "total_equity", data.get("total_equity", 0)])
        writer.writerow(["summary", "", "balanced", data.get("balanced", False)])
    elif report_name == "cash-flow":
        writer.writerow(["section", "date", "description", "account", "amount"])
        for row in data.get("operating_activities", []):
            writer.writerow(["operating", row.get("date"), row.get("description"), row.get("account"), row.get("amount")])
        for row in data.get("investing_activities", []):
            writer.writerow(["investing", row.get("date"), row.get("description"), row.get("account"), row.get("amount")])
        for row in data.get("financing_activities", []):
            writer.writerow(["financing", row.get("date"), row.get("description"), row.get("account"), row.get("amount")])
        writer.writerow(["summary", "", "net_cash_from_operating", "", data.get("net_cash_from_operating", 0)])
        writer.writerow(["summary", "", "net_cash_from_investing", "", data.get("net_cash_from_investing", 0)])
        writer.writerow(["summary", "", "net_cash_from_financing", "", data.get("net_cash_from_financing", 0)])
        writer.writerow(["summary", "", "net_increase_in_cash", "", data.get("net_increase_in_cash", 0)])
        writer.writerow(["summary", "", "opening_cash_balance", "", data.get("opening_cash_balance", 0)])
        writer.writerow(["summary", "", "closing_cash_balance", "", data.get("closing_cash_balance", 0)])
    elif report_name == "cash-flow-projection":
        writer.writerow(
            [
                "month",
                "opening_balance",
                "projected_income_inflows",
                "projected_other_inflows",
                "projected_inflows",
                "projected_payroll_expenses",
                "projected_operating_expenses",
                "projected_tax_expenses",
                "projected_interest_expenses",
                "projected_capex_outflows",
                "projected_financing_outflows",
                "projected_outflows",
                "projected_net_cash",
                "closing_balance",
            ]
        )
        for row in data.get("projection", []):
            writer.writerow(
                [
                    row.get("month"),
                    row.get("opening_balance"),
                    row.get("projected_income_inflows"),
                    row.get("projected_other_inflows"),
                    row.get("projected_inflows"),
                    row.get("projected_payroll_expenses"),
                    row.get("projected_operating_expenses"),
                    row.get("projected_tax_expenses"),
                    row.get("projected_interest_expenses"),
                    row.get("projected_capex_outflows"),
                    row.get("projected_financing_outflows"),
                    row.get("projected_outflows"),
                    row.get("projected_net_cash"),
                    row.get("closing_balance"),
                ]
            )
    elif report_name == "general-ledger":
        writer.writerow(["entry_id", "entry_date", "memo", "source", "source_id", "account_code", "account_name", "debit", "credit"])
        for entry in data:
            for line in entry.get("lines", []):
                writer.writerow(
                    [
                        entry.get("id"),
                        entry.get("entry_date"),
                        entry.get("memo"),
                        entry.get("source"),
                        entry.get("source_id"),
                        line.get("account_code"),
                        line.get("account_name"),
                        line.get("debit"),
                        line.get("credit"),
                    ]
                )
    elif report_name == "bank-balance":
        writer.writerow(["opening_balance_date", "opening_balance", "total_inflows", "total_outflows", "net_movement", "closing_balance"])
        writer.writerow(
            [
                data.get("opening_balance_date"),
                data.get("opening_balance"),
                data.get("total_inflows"),
                data.get("total_outflows"),
                data.get("net_movement"),
                data.get("closing_balance"),
            ]
        )
    else:
        raise HTTPException(status_code=404, detail="Unknown report")

    output.seek(0)
    return output


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/companies", response_model=list[schemas.CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    rows = db.query(models.Company).filter(models.Company.is_archived.is_(False)).order_by(models.Company.name.asc()).all()
    return [{"id": r.id, "name": r.name} for r in rows]


@app.get("/companies/recycle-bin", response_model=list[schemas.CompanyOut])
def list_archived_companies(db: Session = Depends(get_db)):
    rows = db.query(models.Company).filter(models.Company.is_archived.is_(True)).order_by(models.Company.name.asc()).all()
    return [{"id": r.id, "name": r.name} for r in rows]


@app.post("/companies", response_model=schemas.CompanyOut)
def create_company(payload: schemas.CompanyCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name is required")

    exists = db.query(models.Company).filter(func.lower(models.Company.name) == name.lower()).first()
    if exists:
        if exists.is_archived:
            exists.is_archived = False
            db.commit()
            db.refresh(exists)
        return {"id": exists.id, "name": exists.name}

    company = models.Company(name=name)
    db.add(company)
    db.commit()
    db.refresh(company)
    return {"id": company.id, "name": company.name}


@app.delete("/companies/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_db)):
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if company.id == 1:
        raise HTTPException(status_code=400, detail="Default company cannot be deleted")

    if company.is_archived:
        return {"archived": company_id}

    company.is_archived = True
    db.commit()
    return {"archived": company_id}


def _seed_sample_chart(db: Session, company_id: int) -> int:
    company = _resolve_company(db, company_id)
    sample_accounts = [
        ("1000", "Bank", "Asset", 0.0),
        ("1100", "Accounts Receivable", "Asset", 0.0),
        ("1300", "VAT Input", "Asset", 0.0),
        ("1400", "Fixed Assets", "Asset", 0.0),
        ("2000", "Accounts Payable", "Liability", 0.0),
        ("2100", "VAT Output", "Liability", 0.0),
        ("2200", "Loan Payable", "Liability", 0.0),
        ("3000", "Owner Equity", "Equity", 0.0),
        ("4000", "Sales Revenue", "Income", 15.0),
        ("5000", "Office Expense", "Expense", 15.0),
        ("5100", "Bank Charges", "Expense", 0.0),
        ("5200", "Transport Expense", "Expense", 15.0),
        ("5300", "Interest Expense", "Expense", 0.0),
        ("5400", "Income Tax Expense", "Expense", 0.0),
        ("5500", "Depreciation Expense", "Expense", 0.0),
    ]

    created = 0
    for code, name, category, vat_rate in sample_accounts:
        exists = (
            db.query(models.Account)
            .filter(models.Account.company_id == company.id, models.Account.code == code)
            .first()
        )
        if exists:
            continue
        db.add(models.Account(company_id=company.id, code=code, name=name, category=category, vat_rate=vat_rate))
        created += 1

    db.commit()
    return created


def _seed_sample_rules(db: Session, company_id: int) -> int:
    company = _resolve_company(db, company_id)
    code_to_id = {a.code: a.id for a in db.query(models.Account).filter(models.Account.company_id == company.id).all()}
    starter_rules = [
        ("Transport - Uber", "uber", "5200", 10),
        ("Office Expense - Office Depot", "office", "5000", 20),
        ("Bank Fee", "fee", "5100", 30),
        ("Sales Revenue - Stripe", "stripe", "4000", 40),
        ("Interest Expense", "interest", "5300", 50),
        ("Loan Interest", "loan interest", "5300", 51),
        ("Income Tax", "tax", "5400", 60),
        ("Loan Proceeds", "loan", "2200", 70),
    ]

    created = 0
    for name, keyword, account_code, priority in starter_rules:
        account_id = code_to_id.get(account_code)
        if not account_id:
            continue

        exists = (
            db.query(models.AllocationRule)
            .filter(
                models.AllocationRule.company_id == company.id,
                models.AllocationRule.keyword == keyword,
                models.AllocationRule.account_id == account_id,
            )
            .first()
        )
        if exists:
            continue

        db.add(
            models.AllocationRule(
                company_id=company.id,
                name=name,
                keyword=keyword,
                account_id=account_id,
                priority=priority,
            )
        )
        created += 1

    db.commit()
    return created


def _seed_operational_data(db: Session, company_id: int) -> dict:
    company = _resolve_company(db, company_id)
    created = {
        "opening_balances": 0,
        "transactions": 0,
        "customers": 0,
        "inventory_items": 0,
        "invoices": 0,
        "invoice_payments": 0,
        "assets": 0,
        "loans": 0,
    }

    account_by_code = {
        a.code: a
        for a in db.query(models.Account).filter(models.Account.company_id == company.id).all()
    }

    if not account_by_code:
        return created

    month_start = date.today().replace(day=1)
    opening_exists = (
        db.query(models.BankOpeningBalance)
        .filter(
            models.BankOpeningBalance.company_id == company.id,
            models.BankOpeningBalance.balance_date == month_start,
        )
        .first()
    )
    if not opening_exists:
        db.add(
            models.BankOpeningBalance(
                company_id=company.id,
                balance_date=month_start,
                amount=2500.0,
                note="Unified seed opening balance",
            )
        )
        created["opening_balances"] += 1

    customer_samples = [
        ("CUST-SEED-001", "Acme Retail", "billing@acmeretail.com"),
        ("CUST-SEED-002", "Greenline Traders", "accounts@greenline.co"),
    ]
    customers = {}
    for code, name, email in customer_samples:
        row = (
            db.query(models.Customer)
            .filter(models.Customer.company_id == company.id, models.Customer.customer_code == code)
            .first()
        )
        if not row:
            row = models.Customer(
                company_id=company.id,
                customer_code=code,
                name=name,
                email=email,
                phone="",
                address="",
                tax_number="",
                credit_limit=5000.0,
                active=True,
            )
            db.add(row)
            db.flush()
            created["customers"] += 1
        customers[code] = row

    item_samples = [
        ("SKU-SEED-001", "Consulting Package", 300.0, 15.0, 20.0),
        ("SKU-SEED-002", "Support Retainer", 120.0, 15.0, 40.0),
    ]
    items = {}
    for sku, name, unit_price, tax_rate, qty in item_samples:
        row = (
            db.query(models.InventoryItem)
            .filter(models.InventoryItem.company_id == company.id, models.InventoryItem.sku == sku)
            .first()
        )
        if not row:
            row = models.InventoryItem(
                company_id=company.id,
                sku=sku,
                name=name,
                description="Seeded item",
                unit_price=unit_price,
                tax_rate=tax_rate,
                quantity_on_hand=qty,
                min_stock_level=5.0,
                active=True,
            )
            db.add(row)
            db.flush()
            created["inventory_items"] += 1
        items[sku] = row

    invoice_number = "INV-SEED-0001"
    invoice = (
        db.query(models.Invoice)
        .filter(models.Invoice.company_id == company.id, models.Invoice.invoice_number == invoice_number)
        .first()
    )
    if not invoice:
        line_item = items.get("SKU-SEED-001")
        qty = 2.0
        unit_price = float(line_item.unit_price if line_item else 300.0)
        tax_rate = float(line_item.tax_rate if line_item else 15.0)
        subtotal = round(qty * unit_price, 2)
        tax_total = round(subtotal * tax_rate / 100.0, 2)
        total = round(subtotal + tax_total, 2)
        issue_date = date.today()
        due_date = issue_date + timedelta(days=14)

        invoice = models.Invoice(
            company_id=company.id,
            customer_id=customers["CUST-SEED-001"].id,
            invoice_number=invoice_number,
            customer_name=customers["CUST-SEED-001"].name,
            customer_email=customers["CUST-SEED-001"].email,
            issue_date=issue_date,
            due_date=due_date,
            status="partial",
            currency="USD",
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
            outstanding_balance=round(total - 200.0, 2),
            notes="Unified seed invoice",
            sent_date=issue_date,
            paid_date=None,
        )
        db.add(invoice)
        db.flush()

        db.add(
            models.InvoiceLine(
                invoice_id=invoice.id,
                description="Seed invoice line",
                quantity=qty,
                unit_price=unit_price,
                tax_rate=tax_rate,
                income_account_id=account_by_code.get("4000").id if account_by_code.get("4000") else None,
                inventory_item_id=line_item.id if line_item else None,
                line_subtotal=subtotal,
                tax_amount=tax_total,
                line_total=total,
            )
        )
        db.add(
            models.InvoicePayment(
                company_id=company.id,
                invoice_id=invoice.id,
                payment_date=issue_date,
                amount=200.0,
                reference="SEED-PAY-001",
                notes="Unified seed payment",
            )
        )
        created["invoices"] += 1
        created["invoice_payments"] += 1

    asset_exists = (
        db.query(models.FixedAsset)
        .filter(models.FixedAsset.company_id == company.id, models.FixedAsset.name == "Seed Delivery Van")
        .first()
    )
    if not asset_exists and account_by_code.get("1400") and account_by_code.get("5500"):
        db.add(
            models.FixedAsset(
                company_id=company.id,
                name="Seed Delivery Van",
                asset_type="Vehicle",
                purchase_date=date.today() - timedelta(days=180),
                cost=12000.0,
                useful_life_years=5,
                salvage_value=1500.0,
                asset_account_id=account_by_code["1400"].id,
                depreciation_expense_account_id=account_by_code["5500"].id,
                status="active",
            )
        )
        created["assets"] += 1

    loan_exists = (
        db.query(models.Loan)
        .filter(models.Loan.company_id == company.id, models.Loan.lender_name == "Seed Commercial Bank")
        .first()
    )
    if not loan_exists and account_by_code.get("2200") and account_by_code.get("5300"):
        db.add(
            models.Loan(
                company_id=company.id,
                lender_name="Seed Commercial Bank",
                principal=15000.0,
                annual_interest_rate=14.0,
                start_date=date.today() - timedelta(days=120),
                term_months=36,
                liability_account_id=account_by_code["2200"].id,
                interest_expense_account_id=account_by_code["5300"].id,
                status="active",
            )
        )
        created["loans"] += 1

    txn_samples = [
        ("SEED-BANK-001", "Client receipt - Acme", 850.0, "4000"),
        ("SEED-BANK-002", "Loan repayment to Seed Commercial Bank", -420.0, "2200"),
        ("SEED-BANK-003", "Monthly internet and office", -95.0, "5000"),
    ]
    for ref, description, amount, account_code in txn_samples:
        existing = (
            db.query(models.BankTransaction)
            .filter(models.BankTransaction.company_id == company.id, models.BankTransaction.reference == ref)
            .first()
        )
        if existing:
            continue
        assigned = account_by_code.get(account_code)
        db.add(
            models.BankTransaction(
                company_id=company.id,
                txn_date=date.today(),
                description=description,
                amount=amount,
                currency="USD",
                reference=ref,
                imported_hash=f"seed-all-{company.id}-{ref.lower()}",
                status="allocated" if assigned else "imported",
                assigned_account_id=assigned.id if assigned else None,
            )
        )
        created["transactions"] += 1

    db.commit()
    return created


@app.post("/setup/seed-all")
def seed_all_modules(company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    chart_created = _seed_sample_chart(db=db, company_id=company_id)
    rules_created = _seed_sample_rules(db=db, company_id=company_id)
    payroll_employees_created = _seed_sample_payroll_employees(db=db, company_id=company_id)
    payroll_data = _seed_sample_payroll_data(db=db, company_id=company_id)
    operational = _seed_operational_data(db=db, company_id=company_id)

    return {
        "chart_accounts_created": chart_created,
        "rules_created": rules_created,
        "payroll_employees_created": payroll_employees_created,
        "payroll_runs_created": payroll_data.get("runs_created", 0),
        "payroll_employees_used": payroll_data.get("employees_used", 0),
        **operational,
    }


@app.get("/company/profile")
def get_company_profile(company_id: int = 1, db: Session = Depends(get_db)):
    p = _get_company_profile(db, company_id)
    return {
        "company_name": p.company_name,
        "address": p.address,
        "email": p.email,
        "phone": p.phone,
        "tax_number": p.tax_number,
        "currency": p.currency,
    }


@app.post("/company/profile")
def update_company_profile(payload: schemas.CompanyProfileUpdate, company_id: int = 1, db: Session = Depends(get_db)):
    company = _resolve_company(db, company_id)
    p = _get_company_profile(db, company_id)
    company.name = payload.company_name.strip() or company.name
    p.company_name = payload.company_name.strip() or "My Company"
    p.address = payload.address.strip()
    p.email = payload.email.strip()
    p.phone = payload.phone.strip()
    p.tax_number = payload.tax_number.strip()
    p.currency = payload.currency.strip().upper() or "USD"
    db.commit()
    db.refresh(p)
    return {
        "company_name": p.company_name,
        "address": p.address,
        "email": p.email,
        "phone": p.phone,
        "tax_number": p.tax_number,
        "currency": p.currency,
    }


@app.post("/accounts")
def create_account(payload: schemas.AccountCreate, company_id: int = 1, db: Session = Depends(get_db)):
    company = _resolve_company(db, company_id)
    exists = (
        db.query(models.Account)
        .filter(models.Account.company_id == company.id, models.Account.code == payload.code)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Account code already exists")

    if payload.vat_rate < 0 or payload.vat_rate > 100:
        raise HTTPException(status_code=400, detail="vat_rate must be between 0 and 100")

    account = models.Account(
        company_id=company.id,
        code=payload.code,
        name=payload.name,
        category=payload.category,
        vat_rate=payload.vat_rate,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return {
        "id": account.id,
        "code": account.code,
        "name": account.name,
        "category": account.category,
        "vat_rate": account.vat_rate,
    }


@app.get("/accounts")
def list_accounts(company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    rows = db.query(models.Account).filter(models.Account.company_id == company_id).order_by(models.Account.code.asc()).all()
    return [
        {
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "category": r.category,
            "vat_rate": r.vat_rate,
        }
        for r in rows
    ]


@app.delete("/accounts/{account_id}")
def delete_account(account_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    account = db.query(models.Account).filter(models.Account.company_id == company_id, models.Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    rule_refs = (
        db.query(func.count(models.AllocationRule.id))
        .filter(models.AllocationRule.company_id == company_id, models.AllocationRule.account_id == account_id)
        .scalar()
        or 0
    )
    txn_refs = (
        db.query(func.count(models.BankTransaction.id))
        .filter(models.BankTransaction.company_id == company_id, models.BankTransaction.assigned_account_id == account_id)
        .scalar()
        or 0
    )
    line_refs = (
        db.query(func.count(models.JournalLine.id))
        .join(models.JournalEntry, models.JournalEntry.id == models.JournalLine.entry_id)
        .filter(models.JournalEntry.company_id == company_id, models.JournalLine.account_id == account_id)
        .scalar()
        or 0
    )
    invoice_line_refs = (
        db.query(func.count(models.InvoiceLine.id))
        .join(models.Invoice, models.Invoice.id == models.InvoiceLine.invoice_id)
        .filter(models.Invoice.company_id == company_id, models.InvoiceLine.income_account_id == account_id)
        .scalar()
        or 0
    )

    if rule_refs or txn_refs or line_refs or invoice_line_refs:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cannot delete account because it is already in use",
                "usage": {
                    "allocation_rules": rule_refs,
                    "assigned_transactions": txn_refs,
                    "journal_lines": line_refs,
                    "invoice_lines": invoice_line_refs,
                },
            },
        )

    db.delete(account)
    db.commit()
    return {"deleted": account_id}


@app.post("/invoices", response_model=schemas.InvoiceDetailOut)
def create_invoice(payload: schemas.InvoiceCreate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    _ensure_period_open(db, company_id, payload.issue_date)

    customer_name = payload.customer_name.strip()
    if not customer_name:
        raise HTTPException(status_code=400, detail="customer_name is required")
    if payload.due_date < payload.issue_date:
        raise HTTPException(status_code=400, detail="due_date must be on/after issue_date")
    if not payload.lines:
        raise HTTPException(status_code=400, detail="Invoice must have at least one line")

    invoice_number = (payload.invoice_number or "").strip() or _next_invoice_number(db, company_id)
    duplicate = (
        db.query(models.Invoice)
        .filter(models.Invoice.company_id == company_id, models.Invoice.invoice_number == invoice_number)
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="Invoice number already exists")

    customer_id = payload.customer_id
    if customer_id:
        customer = db.query(models.Customer).filter(models.Customer.company_id == company_id, models.Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        if not customer_name:
            customer_name = customer.name

    invoice = models.Invoice(
        company_id=company_id,
        customer_id=customer_id,
        invoice_number=invoice_number,
        customer_name=customer_name,
        customer_email=payload.customer_email.strip(),
        issue_date=payload.issue_date,
        due_date=payload.due_date,
        status="draft",
        currency=(payload.currency or "USD").strip().upper() or "USD",
        notes=payload.notes.strip(),
    )
    db.add(invoice)
    db.flush()

    subtotal = 0.0
    tax_total = 0.0
    for idx, ln in enumerate(payload.lines, start=1):
        desc = ln.description.strip()
        qty = float(ln.quantity or 0.0)
        unit = float(ln.unit_price or 0.0)
        rate = float(ln.tax_rate or 0.0)
        if not desc:
            raise HTTPException(status_code=400, detail=f"Line {idx}: description is required")
        if qty <= 0:
            raise HTTPException(status_code=400, detail=f"Line {idx}: quantity must be > 0")
        if unit < 0:
            raise HTTPException(status_code=400, detail=f"Line {idx}: unit_price must be >= 0")
        if rate < 0 or rate > 100:
            raise HTTPException(status_code=400, detail=f"Line {idx}: tax_rate must be between 0 and 100")

        if ln.income_account_id:
            income_account = (
                db.query(models.Account)
                .filter(models.Account.company_id == company_id, models.Account.id == ln.income_account_id)
                .first()
            )
            if not income_account:
                raise HTTPException(status_code=404, detail=f"Line {idx}: income account not found")

        item_id = ln.inventory_item_id
        if item_id:
            item = db.query(models.InventoryItem).filter(models.InventoryItem.company_id == company_id, models.InventoryItem.id == item_id).first()
            if not item:
                raise HTTPException(status_code=404, detail=f"Line {idx}: inventory item not found")
            if float(item.quantity_on_hand or 0.0) < qty:
                raise HTTPException(status_code=400, detail=f"Line {idx}: insufficient stock for item {item.sku}")
            item.quantity_on_hand = round(float(item.quantity_on_hand or 0.0) - qty, 2)

        line_subtotal = round(qty * unit, 2)
        line_tax = round(line_subtotal * rate / 100.0, 2)
        line_total = round(line_subtotal + line_tax, 2)

        db.add(
            models.InvoiceLine(
                invoice_id=invoice.id,
                description=desc,
                quantity=qty,
                unit_price=unit,
                tax_rate=rate,
                income_account_id=ln.income_account_id,
                inventory_item_id=item_id,
                line_subtotal=line_subtotal,
                tax_amount=line_tax,
                line_total=line_total,
            )
        )
        subtotal += line_subtotal
        tax_total += line_tax

    invoice.subtotal = round(subtotal, 2)
    invoice.tax_total = round(tax_total, 2)
    invoice.total = round(invoice.subtotal + invoice.tax_total, 2)
    invoice.outstanding_balance = invoice.total

    db.commit()
    db.refresh(invoice)

    return {
        **_invoice_out(invoice),
        "lines": [
            {
                "id": line.id,
                "description": line.description,
                "quantity": float(line.quantity or 0.0),
                "unit_price": float(line.unit_price or 0.0),
                "tax_rate": float(line.tax_rate or 0.0),
                "income_account_id": line.income_account_id,
                "inventory_item_id": line.inventory_item_id,
                "line_subtotal": float(line.line_subtotal or 0.0),
                "tax_amount": float(line.tax_amount or 0.0),
                "line_total": float(line.line_total or 0.0),
            }
            for line in (invoice.lines or [])
        ],
    }


@app.get("/invoices", response_model=list[schemas.InvoiceOut])
def list_invoices(company_id: int = 1, status: str | None = None, q: str | None = None, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    _refresh_overdue_invoices(db, company_id)
    query = db.query(models.Invoice).filter(models.Invoice.company_id == company_id)
    if status:
        query = query.filter(models.Invoice.status == status.strip().lower())
    if q:
        needle = f"%{q.strip()}%"
        query = query.filter((models.Invoice.customer_name.ilike(needle)) | (models.Invoice.invoice_number.ilike(needle)))

    rows = query.order_by(models.Invoice.issue_date.desc(), models.Invoice.id.desc()).all()
    return [_invoice_out(inv) for inv in rows]


@app.get("/invoices/{invoice_id}", response_model=schemas.InvoiceDetailOut)
def get_invoice(invoice_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    inv = db.query(models.Invoice).filter(models.Invoice.company_id == company_id, models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {
        **_invoice_out(inv),
        "lines": [
            {
                "id": line.id,
                "description": line.description,
                "quantity": float(line.quantity or 0.0),
                "unit_price": float(line.unit_price or 0.0),
                "tax_rate": float(line.tax_rate or 0.0),
                "income_account_id": line.income_account_id,
                "inventory_item_id": line.inventory_item_id,
                "line_subtotal": float(line.line_subtotal or 0.0),
                "tax_amount": float(line.tax_amount or 0.0),
                "line_total": float(line.line_total or 0.0),
            }
            for line in (inv.lines or [])
        ],
    }


@app.get("/invoices/{invoice_id}/download")
def download_invoice(invoice_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    inv = db.query(models.Invoice).filter(models.Invoice.company_id == company_id, models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    profile = _get_company_profile(db, company_id)
    invoice_payload = {
        **_invoice_out(inv),
        "lines": [
            {
                "id": line.id,
                "description": line.description,
                "quantity": float(line.quantity or 0.0),
                "unit_price": float(line.unit_price or 0.0),
                "tax_rate": float(line.tax_rate or 0.0),
                "income_account_id": line.income_account_id,
                "inventory_item_id": line.inventory_item_id,
                "line_subtotal": float(line.line_subtotal or 0.0),
                "tax_amount": float(line.tax_amount or 0.0),
                "line_total": float(line.line_total or 0.0),
            }
            for line in (inv.lines or [])
        ],
    }

    pdf_bytes = build_invoice_pdf(invoice_payload, _company_profile_data(profile))
    safe_number = _safe_slug(inv.invoice_number or f"invoice-{inv.id}")
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={safe_number}.pdf"},
    )


@app.post("/invoices/{invoice_id}/mark-paid", response_model=schemas.InvoiceOut)
def mark_invoice_paid(
    invoice_id: int,
    payload: schemas.InvoiceMarkPaidRequest,
    company_id: int = 1,
    db: Session = Depends(get_db),
):
    inv = db.query(models.Invoice).filter(models.Invoice.company_id == company_id, models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    _ensure_period_open(db, company_id, payload.paid_date or date.today())
    if inv.outstanding_balance > 0:
        db.add(
            models.InvoicePayment(
                company_id=company_id,
                invoice_id=inv.id,
                payment_date=payload.paid_date or date.today(),
                amount=float(inv.outstanding_balance or 0.0),
                reference="mark-paid",
                notes="Auto settlement from mark-paid action",
            )
        )
    _recalculate_invoice_status(db, inv)
    db.commit()
    db.refresh(inv)
    return _invoice_out(inv)


@app.post("/invoices/{invoice_id}/send", response_model=schemas.InvoiceOut)
def send_invoice(invoice_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    inv = db.query(models.Invoice).filter(models.Invoice.company_id == company_id, models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.status == "paid":
        return _invoice_out(inv)

    inv.sent_date = date.today()
    inv.status = "overdue" if inv.due_date < date.today() else "sent"
    db.commit()
    db.refresh(inv)
    return _invoice_out(inv)


@app.post("/invoices/{invoice_id}/payments", response_model=schemas.InvoicePaymentOut)
def add_invoice_payment(
    invoice_id: int,
    payload: schemas.InvoicePaymentCreate,
    company_id: int = 1,
    db: Session = Depends(get_db),
):
    inv = db.query(models.Invoice).filter(models.Invoice.company_id == company_id, models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    _ensure_period_open(db, company_id, payload.payment_date)
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be > 0")
    if float(inv.outstanding_balance or 0.0) <= 0:
        raise HTTPException(status_code=400, detail="Invoice is already fully paid")

    payment = models.InvoicePayment(
        company_id=company_id,
        invoice_id=invoice_id,
        payment_date=payload.payment_date,
        amount=round(float(payload.amount), 2),
        reference=payload.reference.strip(),
        notes=payload.notes.strip(),
    )
    db.add(payment)
    db.flush()

    _recalculate_invoice_status(db, inv)
    if inv.status != "paid" and inv.sent_date:
        inv.status = "partial" if inv.outstanding_balance < inv.total else inv.status

    db.commit()
    db.refresh(payment)
    return {
        "id": payment.id,
        "invoice_id": payment.invoice_id,
        "payment_date": payment.payment_date,
        "amount": float(payment.amount or 0.0),
        "reference": payment.reference,
        "notes": payment.notes,
        "created_at": payment.created_at,
    }


@app.get("/invoices/{invoice_id}/payments", response_model=list[schemas.InvoicePaymentOut])
def list_invoice_payments(invoice_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    rows = (
        db.query(models.InvoicePayment)
        .filter(models.InvoicePayment.company_id == company_id, models.InvoicePayment.invoice_id == invoice_id)
        .order_by(models.InvoicePayment.payment_date.desc(), models.InvoicePayment.id.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "invoice_id": p.invoice_id,
            "payment_date": p.payment_date,
            "amount": float(p.amount or 0.0),
            "reference": p.reference,
            "notes": p.notes,
            "created_at": p.created_at,
        }
        for p in rows
    ]


@app.post("/customers", response_model=schemas.CustomerOut)
def create_customer(payload: schemas.CustomerCreate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    code = payload.customer_code.strip()
    name = payload.name.strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="customer_code and name are required")

    exists = db.query(models.Customer).filter(models.Customer.company_id == company_id, models.Customer.customer_code == code).first()
    if exists:
        raise HTTPException(status_code=400, detail="Customer code already exists")

    customer = models.Customer(
        company_id=company_id,
        customer_code=code,
        name=name,
        email=payload.email.strip(),
        phone=payload.phone.strip(),
        address=payload.address.strip(),
        tax_number=payload.tax_number.strip(),
        credit_limit=float(payload.credit_limit or 0.0),
        active=payload.active,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return {
        "id": customer.id,
        "customer_code": customer.customer_code,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "address": customer.address,
        "tax_number": customer.tax_number,
        "credit_limit": float(customer.credit_limit or 0.0),
        "active": customer.active,
    }


@app.get("/customers", response_model=list[schemas.CustomerOut])
def list_customers(company_id: int = 1, q: str | None = None, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    query = db.query(models.Customer).filter(models.Customer.company_id == company_id)
    if q:
        needle = f"%{q.strip()}%"
        query = query.filter((models.Customer.name.ilike(needle)) | (models.Customer.customer_code.ilike(needle)))
    rows = query.order_by(models.Customer.name.asc(), models.Customer.id.asc()).all()
    return [
        {
            "id": c.id,
            "customer_code": c.customer_code,
            "name": c.name,
            "email": c.email,
            "phone": c.phone,
            "address": c.address,
            "tax_number": c.tax_number,
            "credit_limit": float(c.credit_limit or 0.0),
            "active": c.active,
        }
        for c in rows
    ]


@app.post("/inventory/items", response_model=schemas.InventoryItemOut)
def create_inventory_item(payload: schemas.InventoryItemCreate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    sku = payload.sku.strip()
    name = payload.name.strip()
    if not sku or not name:
        raise HTTPException(status_code=400, detail="sku and name are required")
    exists = db.query(models.InventoryItem).filter(models.InventoryItem.company_id == company_id, models.InventoryItem.sku == sku).first()
    if exists:
        raise HTTPException(status_code=400, detail="SKU already exists")

    item = models.InventoryItem(
        company_id=company_id,
        sku=sku,
        name=name,
        description=payload.description.strip(),
        unit_price=float(payload.unit_price or 0.0),
        tax_rate=float(payload.tax_rate or 0.0),
        quantity_on_hand=float(payload.quantity_on_hand or 0.0),
        min_stock_level=float(payload.min_stock_level or 0.0),
        active=payload.active,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "sku": item.sku,
        "name": item.name,
        "description": item.description,
        "unit_price": float(item.unit_price or 0.0),
        "tax_rate": float(item.tax_rate or 0.0),
        "quantity_on_hand": float(item.quantity_on_hand or 0.0),
        "min_stock_level": float(item.min_stock_level or 0.0),
        "active": item.active,
    }


@app.get("/inventory/items", response_model=list[schemas.InventoryItemOut])
def list_inventory_items(company_id: int = 1, q: str | None = None, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    query = db.query(models.InventoryItem).filter(models.InventoryItem.company_id == company_id)
    if q:
        needle = f"%{q.strip()}%"
        query = query.filter((models.InventoryItem.name.ilike(needle)) | (models.InventoryItem.sku.ilike(needle)))
    rows = query.order_by(models.InventoryItem.name.asc(), models.InventoryItem.id.asc()).all()
    return [
        {
            "id": item.id,
            "sku": item.sku,
            "name": item.name,
            "description": item.description,
            "unit_price": float(item.unit_price or 0.0),
            "tax_rate": float(item.tax_rate or 0.0),
            "quantity_on_hand": float(item.quantity_on_hand or 0.0),
            "min_stock_level": float(item.min_stock_level or 0.0),
            "active": item.active,
        }
        for item in rows
    ]


@app.get("/reports/ar-aging", response_model=schemas.AgingSummary)
def ar_aging_report(as_of: date | None = None, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    cutoff = as_of or date.today()

    invoices = (
        db.query(models.Invoice)
        .filter(models.Invoice.company_id == company_id, models.Invoice.outstanding_balance > 0)
        .all()
    )

    by_customer: dict[str, dict[str, float]] = {}

    def add_bucket(customer: str, bucket: str, amount: float):
        row = by_customer.setdefault(customer, {
            "current": 0.0,
            "days_1_30": 0.0,
            "days_31_60": 0.0,
            "days_61_90": 0.0,
            "days_over_90": 0.0,
            "total": 0.0,
        })
        row[bucket] += amount
        row["total"] += amount

    for inv in invoices:
        amount = float(inv.outstanding_balance or 0.0)
        if amount <= 0:
            continue
        days = (cutoff - inv.due_date).days
        if days <= 0:
            bucket = "current"
        elif days <= 30:
            bucket = "days_1_30"
        elif days <= 60:
            bucket = "days_31_60"
        elif days <= 90:
            bucket = "days_61_90"
        else:
            bucket = "days_over_90"
        add_bucket(inv.customer_name or "Unknown", bucket, amount)

    lines = [
        {
            "customer_name": name,
            "current": round(vals["current"], 2),
            "days_1_30": round(vals["days_1_30"], 2),
            "days_31_60": round(vals["days_31_60"], 2),
            "days_61_90": round(vals["days_61_90"], 2),
            "days_over_90": round(vals["days_over_90"], 2),
            "total": round(vals["total"], 2),
        }
        for name, vals in sorted(by_customer.items(), key=lambda x: x[0].lower())
    ]

    totals = {
        "customer_name": "TOTAL",
        "current": round(sum(x["current"] for x in lines), 2),
        "days_1_30": round(sum(x["days_1_30"] for x in lines), 2),
        "days_31_60": round(sum(x["days_31_60"] for x in lines), 2),
        "days_61_90": round(sum(x["days_61_90"] for x in lines), 2),
        "days_over_90": round(sum(x["days_over_90"] for x in lines), 2),
        "total": round(sum(x["total"] for x in lines), 2),
    }

    return {
        "as_of": cutoff,
        "totals": totals,
        "by_customer": lines,
    }


@app.post("/period-lock", response_model=schemas.PeriodLockOut)
def upsert_period_lock(payload: schemas.PeriodLockUpdate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    lock = db.query(models.PeriodLock).filter(models.PeriodLock.company_id == company_id).first()
    if not lock:
        lock = models.PeriodLock(company_id=company_id)
        db.add(lock)
    lock.locked_until = payload.locked_until
    lock.note = payload.note.strip()
    db.commit()
    return {"locked_until": lock.locked_until, "note": lock.note}


@app.get("/period-lock", response_model=schemas.PeriodLockOut)
def get_period_lock(company_id: int = 1, db: Session = Depends(get_db)):
    lock = db.query(models.PeriodLock).filter(models.PeriodLock.company_id == company_id).first()
    if not lock:
        return {"locked_until": None, "note": ""}
    return {"locked_until": lock.locked_until, "note": lock.note}


@app.post("/recurring-invoices", response_model=schemas.RecurringInvoiceTemplateOut)
def create_recurring_invoice(payload: schemas.RecurringInvoiceTemplateCreate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    freq = payload.frequency.strip().lower()
    if freq not in {"monthly", "weekly", "quarterly"}:
        raise HTTPException(status_code=400, detail="frequency must be monthly, weekly, or quarterly")
    if not payload.lines:
        raise HTTPException(status_code=400, detail="Recurring template must include lines")

    template = models.RecurringInvoiceTemplate(
        company_id=company_id,
        customer_id=payload.customer_id,
        template_name=payload.template_name.strip(),
        frequency=freq,
        next_run_date=payload.next_run_date,
        currency=(payload.currency or "USD").strip().upper(),
        notes=payload.notes.strip(),
        lines_json=json.dumps([line.dict() for line in payload.lines]),
        active=payload.active,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return {
        "id": template.id,
        "customer_id": template.customer_id,
        "template_name": template.template_name,
        "frequency": template.frequency,
        "next_run_date": template.next_run_date,
        "currency": template.currency,
        "notes": template.notes,
        "lines": [schemas.InvoiceLineCreate(**x).dict() for x in json.loads(template.lines_json or "[]")],
        "active": template.active,
    }


@app.get("/recurring-invoices", response_model=list[schemas.RecurringInvoiceTemplateOut])
def list_recurring_invoices(company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    rows = (
        db.query(models.RecurringInvoiceTemplate)
        .filter(models.RecurringInvoiceTemplate.company_id == company_id)
        .order_by(models.RecurringInvoiceTemplate.template_name.asc(), models.RecurringInvoiceTemplate.id.asc())
        .all()
    )
    return [
        {
            "id": t.id,
            "customer_id": t.customer_id,
            "template_name": t.template_name,
            "frequency": t.frequency,
            "next_run_date": t.next_run_date,
            "currency": t.currency,
            "notes": t.notes,
            "lines": [schemas.InvoiceLineCreate(**x).dict() for x in json.loads(t.lines_json or "[]")],
            "active": t.active,
        }
        for t in rows
    ]


@app.post("/recurring-invoices/run")
def run_recurring_invoices(company_id: int = 1, run_date: date | None = None, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    today = run_date or date.today()
    rows = (
        db.query(models.RecurringInvoiceTemplate)
        .filter(
            models.RecurringInvoiceTemplate.company_id == company_id,
            models.RecurringInvoiceTemplate.active.is_(True),
            models.RecurringInvoiceTemplate.next_run_date <= today,
        )
        .all()
    )

    created = 0
    for t in rows:
        lines = [schemas.InvoiceLineCreate(**x) for x in json.loads(t.lines_json or "[]")]
        customer = None
        if t.customer_id:
            customer = db.query(models.Customer).filter(models.Customer.company_id == company_id, models.Customer.id == t.customer_id).first()

        payload = schemas.InvoiceCreate(
            customer_id=t.customer_id,
            customer_name=customer.name if customer else t.template_name,
            customer_email=customer.email if customer else "",
            issue_date=t.next_run_date,
            due_date=t.next_run_date + timedelta(days=14),
            currency=t.currency,
            notes=t.notes,
            lines=lines,
        )
        create_invoice(payload, company_id=company_id, db=db)
        created += 1

        if t.frequency == "weekly":
            t.next_run_date = t.next_run_date + timedelta(days=7)
        elif t.frequency == "quarterly":
            t.next_run_date = t.next_run_date + timedelta(days=90)
        else:
            t.next_run_date = t.next_run_date + timedelta(days=30)

    db.commit()
    return {"created": created}


@app.post("/invoices/reminders/run", response_model=schemas.ReminderRunOut)
def run_invoice_reminders(company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    _refresh_overdue_invoices(db, company_id)
    overdue = (
        db.query(models.Invoice)
        .filter(models.Invoice.company_id == company_id, models.Invoice.status == "overdue", models.Invoice.outstanding_balance > 0)
        .all()
    )

    reminders = []
    for inv in overdue:
        sent_to = inv.customer_email or ""
        log = models.ReminderLog(
            company_id=company_id,
            invoice_id=inv.id,
            reminder_type="overdue",
            sent_to=sent_to,
            status="queued",
        )
        db.add(log)
        reminders.append(
            {
                "invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "customer": inv.customer_name,
                "email": sent_to,
                "outstanding": float(inv.outstanding_balance or 0.0),
            }
        )
    db.commit()
    return {"queued": len(reminders), "reminders": reminders}


@app.post("/rules")
def create_rule(payload: schemas.RuleCreate, company_id: int = 1, db: Session = Depends(get_db)):
    account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.account_id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    rule = models.AllocationRule(
        company_id=company_id,
        name=payload.name,
        keyword=payload.keyword,
        min_amount=payload.min_amount,
        max_amount=payload.max_amount,
        account_id=payload.account_id,
        priority=payload.priority,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "name": rule.name}


@app.get("/rules")
def list_rules(company_id: int = 1, db: Session = Depends(get_db)):
    rows = (
        db.query(models.AllocationRule)
        .filter(models.AllocationRule.company_id == company_id)
        .order_by(models.AllocationRule.priority.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "keyword": r.keyword,
            "keywords": [x.strip() for x in r.keyword.replace("|", ",").replace(";", ",").split(",") if x.strip()],
            "account_id": r.account_id,
            "account_name": r.account.name if r.account else None,
            "priority": r.priority,
        }
        for r in rows
    ]


@app.post("/rules/{rule_id}/keywords")
def add_rule_keyword(rule_id: int, payload: schemas.RuleKeywordAddRequest, company_id: int = 1, db: Session = Depends(get_db)):
    rule = (
        db.query(models.AllocationRule)
        .filter(models.AllocationRule.company_id == company_id, models.AllocationRule.id == rule_id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    new_kw = payload.keyword.strip()
    if not new_kw:
        raise HTTPException(status_code=400, detail="Keyword cannot be empty")

    existing = [x.strip() for x in rule.keyword.replace("|", ",").replace(";", ",").split(",") if x.strip()]
    exists_lower = {x.lower() for x in existing}
    if new_kw.lower() not in exists_lower:
        existing.append(new_kw)
        rule.keyword = ", ".join(existing)
        db.commit()
        db.refresh(rule)

    return {
        "id": rule.id,
        "name": rule.name,
        "keyword": rule.keyword,
        "keywords": [x.strip() for x in rule.keyword.replace("|", ",").replace(";", ",").split(",") if x.strip()],
    }


@app.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    rule = (
        db.query(models.AllocationRule)
        .filter(models.AllocationRule.company_id == company_id, models.AllocationRule.id == rule_id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}


@app.get("/bank/transactions")
def list_bank_transactions(
    company_id: int = 1,
    q: str | None = None,
    account_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    _resolve_company(db, company_id)

    if account_id is not None:
        account = (
            db.query(models.Account)
            .filter(models.Account.company_id == company_id, models.Account.id == account_id)
            .first()
        )
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

    query = db.query(models.BankTransaction).filter(models.BankTransaction.company_id == company_id)

    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(
            (models.BankTransaction.description.ilike(needle))
            | (models.BankTransaction.reference.ilike(needle))
        )

    if account_id is not None:
        query = query.filter(models.BankTransaction.assigned_account_id == account_id)

    if from_date:
        query = query.filter(models.BankTransaction.txn_date >= from_date)
    if to_date:
        query = query.filter(models.BankTransaction.txn_date <= to_date)

    rows = query.order_by(models.BankTransaction.txn_date.desc(), models.BankTransaction.id.desc()).all()
    return [_bank_transaction_payload(txn) for txn in rows]


@app.get("/bank/transactions/download")
def download_bank_transactions(
    company_id: int = 1,
    format: str = "csv",
    q: str | None = None,
    account_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    _resolve_company(db, company_id)

    if account_id is not None:
        account = (
            db.query(models.Account)
            .filter(models.Account.company_id == company_id, models.Account.id == account_id)
            .first()
        )
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

    query = db.query(models.BankTransaction).filter(models.BankTransaction.company_id == company_id)

    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(
            (models.BankTransaction.description.ilike(needle))
            | (models.BankTransaction.reference.ilike(needle))
        )

    if account_id is not None:
        query = query.filter(models.BankTransaction.assigned_account_id == account_id)

    if from_date:
        query = query.filter(models.BankTransaction.txn_date >= from_date)
    if to_date:
        query = query.filter(models.BankTransaction.txn_date <= to_date)

    rows = query.order_by(models.BankTransaction.txn_date.desc(), models.BankTransaction.id.desc()).all()
    data = [_bank_transaction_payload(txn) for txn in rows]

    if format == "json":
        raw = json.dumps(data, default=str, indent=2)
        return StreamingResponse(
            iter([raw]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=bank-transactions.json"},
        )

    if format != "csv":
        raise HTTPException(status_code=400, detail="Only csv or json formats are supported")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "txn_date", "description", "reference", "amount", "currency", "status", "account"])
    for row in data:
        writer.writerow(
            [
                row["id"],
                row["txn_date"],
                row["description"],
                row["reference"],
                row["amount"],
                row["currency"],
                row["status"],
                row["assigned_account_name"] or "",
            ]
        )

    total_amount = round(sum(float(x["amount"] or 0.0) for x in data), 2)
    writer.writerow([])
    writer.writerow(["", "", "TOTAL", "", total_amount, "", "", ""])

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bank-transactions.csv"},
    )


def _bank_transaction_payload(txn: models.BankTransaction) -> dict:
    return {
        "id": txn.id,
        "txn_date": txn.txn_date,
        "description": txn.description,
        "amount": txn.amount,
        "currency": txn.currency,
        "reference": txn.reference,
        "status": txn.status,
        "assigned_account_id": txn.assigned_account_id,
        "assigned_account_name": txn.assigned_account.name if txn.assigned_account else None,
        "assigned_account_vat_rate": txn.assigned_account.vat_rate if txn.assigned_account else None,
        "type_hint": "income" if txn.amount > 0 else "expense",
    }


@app.post("/bank/transactions")
def create_bank_transaction(
    payload: schemas.BankTransactionCreate, company_id: int = 1, db: Session = Depends(get_db)
):
    _resolve_company(db, company_id)

    description = payload.description.strip()
    currency = (payload.currency or "USD").strip().upper()[:10] or "USD"
    reference = (payload.reference or "").strip()[:100]

    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    assigned_account = None
    if payload.assigned_account_id:
        assigned_account = (
            db.query(models.Account)
            .filter(models.Account.company_id == company_id, models.Account.id == payload.assigned_account_id)
            .first()
        )
        if not assigned_account:
            raise HTTPException(status_code=404, detail="Assigned account not found")

    _ensure_period_open(db, company_id, payload.txn_date)

    txn = models.BankTransaction(
        company_id=company_id,
        txn_date=payload.txn_date,
        description=description,
        amount=float(payload.amount),
        currency=currency,
        reference=reference,
        imported_hash=f"manual-{company_id}-{uuid4().hex}",
        status="allocated" if assigned_account else "imported",
        assigned_account_id=assigned_account.id if assigned_account else None,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return _bank_transaction_payload(txn)


@app.put("/bank/transactions/{transaction_id}")
def update_bank_transaction(
    transaction_id: int,
    payload: schemas.BankTransactionUpdate,
    company_id: int = 1,
    db: Session = Depends(get_db),
):
    _resolve_company(db, company_id)

    txn = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id, models.BankTransaction.id == transaction_id)
        .first()
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.status == "posted":
        raise HTTPException(status_code=400, detail="Cannot edit a posted transaction")

    description = payload.description.strip()
    currency = (payload.currency or "USD").strip().upper()[:10] or "USD"
    reference = (payload.reference or "").strip()[:100]
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    assigned_account = None
    if payload.assigned_account_id:
        assigned_account = (
            db.query(models.Account)
            .filter(models.Account.company_id == company_id, models.Account.id == payload.assigned_account_id)
            .first()
        )
        if not assigned_account:
            raise HTTPException(status_code=404, detail="Assigned account not found")

    _ensure_period_open(db, company_id, payload.txn_date)

    txn.txn_date = payload.txn_date
    txn.description = description
    txn.amount = float(payload.amount)
    txn.currency = currency
    txn.reference = reference
    txn.assigned_account_id = assigned_account.id if assigned_account else None
    txn.status = "allocated" if assigned_account else "imported"

    db.commit()
    db.refresh(txn)
    return _bank_transaction_payload(txn)


@app.delete("/bank/transactions/{transaction_id}")
def delete_bank_transaction(transaction_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)

    txn = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id, models.BankTransaction.id == transaction_id)
        .first()
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.status == "posted":
        raise HTTPException(status_code=400, detail="Cannot delete a posted transaction")

    _ensure_period_open(db, company_id, txn.txn_date)
    db.delete(txn)
    db.commit()
    return {"deleted": transaction_id}


@app.post("/bank/transactions/{transaction_id}/assign")
def assign_bank_transaction(
    transaction_id: int, payload: schemas.TransactionAssignRequest, company_id: int = 1, db: Session = Depends(get_db)
):
    txn = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id, models.BankTransaction.id == transaction_id)
        .first()
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.status == "posted":
        raise HTTPException(status_code=400, detail="Cannot reassign a posted transaction")

    account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.account_id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    txn.assigned_account_id = payload.account_id
    txn.status = "allocated"

    created_rule_id = None
    if payload.create_rule or payload.auto_rule:
        keyword = (payload.rule_keyword or txn.description).strip()
        if not keyword:
            raise HTTPException(status_code=400, detail="rule_keyword cannot be empty")

        exists = (
            db.query(models.AllocationRule)
            .filter(
                models.AllocationRule.company_id == company_id,
                models.AllocationRule.keyword == keyword,
                models.AllocationRule.account_id == payload.account_id,
            )
            .first()
        )

        if not exists:
            rule = models.AllocationRule(
                company_id=company_id,
                name=(payload.rule_name or f"Auto rule - {keyword}").strip(),
                keyword=keyword,
                account_id=payload.account_id,
                priority=payload.priority,
            )
            db.add(rule)
            db.flush()
            created_rule_id = rule.id

    db.commit()
    return {
        "transaction_id": txn.id,
        "status": txn.status,
        "assigned_account_id": txn.assigned_account_id,
        "created_rule_id": created_rule_id,
    }


@app.get("/bank/hints")
def bank_transaction_hints(company_id: int = 1, db: Session = Depends(get_db)):
    rows = (
        db.query(models.BankTransaction)
        .filter(models.BankTransaction.company_id == company_id)
        .order_by(models.BankTransaction.txn_date.desc(), models.BankTransaction.id.desc())
        .all()
    )
    hints = []

    for txn in rows:
        desc = txn.description.lower()
        acct = (txn.assigned_account.name.lower() if txn.assigned_account else "")
        suggestion = None

        loan_tokens = ["loan", "ln", "borrowing", "finance", "note"]
        interest_tokens = ["interest", "intrest", "finance charge", "loan charge"]
        tax_tokens = ["tax", "vat", "income tax", "withholding", "levy"]

        if any(t in desc for t in loan_tokens) or "loan" in acct:
            suggestion = "Looks like loan-related transaction. Consider Loan Payable or Interest Expense."
        elif any(t in desc for t in interest_tokens) or "interest" in acct:
            suggestion = "Looks like interest charge. Consider Interest Expense account."
        elif any(t in desc for t in tax_tokens) or "tax" in acct:
            suggestion = "Looks like tax payment. Consider Income Tax Expense account."

        if suggestion:
            hints.append(
                {
                    "transaction_id": txn.id,
                    "description": txn.description,
                    "amount": txn.amount,
                    "status": txn.status,
                    "suggestion": suggestion,
                }
            )

    return hints


@app.post("/bank/opening-balance")
def set_opening_balance(payload: schemas.OpeningBalanceCreate, company_id: int = 1, db: Session = Depends(get_db)):
    entry = models.BankOpeningBalance(
        company_id=company_id,
        balance_date=payload.balance_date,
        amount=payload.amount,
        note=payload.note,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {
        "id": entry.id,
        "balance_date": entry.balance_date,
        "amount": entry.amount,
        "note": entry.note,
    }


@app.get("/bank/balance-summary", response_model=schemas.BankBalanceSummary)
def get_bank_balance_summary(company_id: int = 1, db: Session = Depends(get_db)):
    return _bank_balance_summary(db, company_id=company_id)


@app.get("/bank/running-balance")
def get_running_balance(company_id: int = 1, db: Session = Depends(get_db)):
    return _running_balance_timeline(db, company_id=company_id)


@app.post("/bank/import", response_model=schemas.ImportResult)
async def import_bank_statement(
    file: UploadFile = File(...),
    company_id: int = 1,
    date_format: str | None = Form(None),
    amount_mode: str = Form("auto"),
    date_column: str | None = Form(None),
    amount_column: str | None = Form(None),
    debit_column: str | None = Form(None),
    credit_column: str | None = Form(None),
    description_column: str | None = Form(None),
    reference_column: str | None = Form(None),
    currency_column: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported for now")

    # Ensure import uses a valid company scope and avoids DB integrity errors.
    _resolve_company(db, company_id)

    content = await file.read()
    logger.info("Import request received: filename=%s bytes=%s", file.filename, len(content))
    try:
        imported, skipped, skipped_invalid, errors = import_bank_csv(
            db,
            content,
            company_id=company_id,
            date_format=date_format,
            amount_mode=amount_mode,
            date_column=date_column,
            amount_column=amount_column,
            debit_column=debit_column,
            credit_column=credit_column,
            description_column=description_column,
            reference_column=reference_column,
            currency_column=currency_column,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Import failed for company_id=%s filename=%s", company_id, file.filename)
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}") from exc

    return schemas.ImportResult(
        imported=imported,
        skipped_duplicates=skipped,
        skipped_invalid_rows=skipped_invalid,
        errors=errors,
    )


@app.post("/bookkeeping/allocate", response_model=schemas.AllocationResult)
def allocate_transactions(company_id: int = 1, db: Session = Depends(get_db)):
    allocated, unmatched = apply_allocation_rules(db, company_id=company_id)
    logger.info("Allocation run completed: allocated=%s unmatched=%s", allocated, unmatched)
    return schemas.AllocationResult(allocated=allocated, unmatched=unmatched)


@app.post("/bookkeeping/post", response_model=schemas.PostingResult)
def post_transactions(company_id: int = 1, db: Session = Depends(get_db)):
    try:
        posted, skipped = post_allocated_transactions(db, company_id=company_id)
    except ValueError as exc:
        logger.exception("Posting failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("Posting run completed: posted=%s skipped=%s", posted, skipped)
    return schemas.PostingResult(posted=posted, skipped=skipped)


@app.post("/assets")
def create_asset(payload: schemas.FixedAssetCreate, company_id: int = 1, db: Session = Depends(get_db)):
    asset_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.asset_account_id)
        .first()
    )
    dep_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.depreciation_expense_account_id)
        .first()
    )

    if not asset_account or not dep_account:
        raise HTTPException(status_code=404, detail="Asset or depreciation account not found")

    if payload.useful_life_years <= 0:
        raise HTTPException(status_code=400, detail="useful_life_years must be greater than 0")

    asset = models.FixedAsset(
        company_id=company_id,
        name=payload.name,
        asset_type=payload.asset_type,
        purchase_date=payload.purchase_date,
        cost=payload.cost,
        useful_life_years=payload.useful_life_years,
        salvage_value=payload.salvage_value,
        asset_account_id=payload.asset_account_id,
        depreciation_expense_account_id=payload.depreciation_expense_account_id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"id": asset.id, "name": asset.name}


@app.get("/assets")
def list_assets(company_id: int = 1, db: Session = Depends(get_db)):
    today = date.today()
    rows = (
        db.query(models.FixedAsset)
        .filter(models.FixedAsset.company_id == company_id)
        .order_by(models.FixedAsset.purchase_date.asc(), models.FixedAsset.id.asc())
        .all()
    )
    data = []
    for asset in rows:
        monthly_dep = straight_line_monthly_depreciation(asset.cost, asset.salvage_value, asset.useful_life_years)
        elapsed_months = min(months_between(asset.purchase_date, today), asset.useful_life_years * 12)
        accumulated = round(monthly_dep * elapsed_months, 2)
        book_value = round(max(asset.cost - accumulated, asset.salvage_value), 2)
        data.append(
            {
                "id": asset.id,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "purchase_date": asset.purchase_date,
                "cost": asset.cost,
                "useful_life_years": asset.useful_life_years,
                "salvage_value": asset.salvage_value,
                "monthly_depreciation": monthly_dep,
                "accumulated_depreciation": accumulated,
                "book_value": book_value,
                "asset_account_name": asset.asset_account.name,
                "depreciation_expense_account_name": asset.depreciation_expense_account.name,
                "status": asset.status,
            }
        )
    return data


@app.post("/loans")
def create_loan(payload: schemas.LoanCreate, company_id: int = 1, db: Session = Depends(get_db)):
    liab_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.liability_account_id)
        .first()
    )
    int_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.interest_expense_account_id)
        .first()
    )

    if not liab_account or not int_account:
        raise HTTPException(status_code=404, detail="Liability or interest expense account not found")

    if payload.term_months <= 0:
        raise HTTPException(status_code=400, detail="term_months must be greater than 0")

    loan = models.Loan(
        company_id=company_id,
        lender_name=payload.lender_name,
        principal=payload.principal,
        annual_interest_rate=payload.annual_interest_rate,
        start_date=payload.start_date,
        term_months=payload.term_months,
        liability_account_id=payload.liability_account_id,
        interest_expense_account_id=payload.interest_expense_account_id,
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return {"id": loan.id, "lender_name": loan.lender_name}


@app.get("/loans")
def list_loans(company_id: int = 1, db: Session = Depends(get_db)):
    rows = (
        db.query(models.Loan)
        .filter(models.Loan.company_id == company_id)
        .order_by(models.Loan.start_date.asc(), models.Loan.id.asc())
        .all()
    )
    return [
        {
            "id": loan.id,
            "lender_name": loan.lender_name,
            "principal": loan.principal,
            "annual_interest_rate": loan.annual_interest_rate,
            "start_date": loan.start_date,
            "term_months": loan.term_months,
            "status": loan.status,
            "liability_account_name": loan.liability_account.name,
            "interest_expense_account_name": loan.interest_expense_account.name,
        }
        for loan in rows
    ]


@app.get("/loans/{loan_id}/schedule", response_model=list[schemas.LoanScheduleLine])
def loan_schedule(loan_id: int, months: int | None = None, company_id: int = 1, db: Session = Depends(get_db)):
    loan = db.query(models.Loan).filter(models.Loan.company_id == company_id, models.Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    schedule = build_loan_schedule(
        principal=loan.principal,
        annual_interest_rate=loan.annual_interest_rate,
        term_months=loan.term_months,
        months=months,
    )
    return schedule


@app.post("/payroll/employees")
def create_payroll_employee(payload: schemas.PayrollEmployeeCreate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)

    code = payload.employee_code.strip()
    name = payload.full_name.strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="employee_code and full_name are required")
    if payload.default_gross_salary < 0:
        raise HTTPException(status_code=400, detail="default_gross_salary must be >= 0")
    if payload.tax_rate < 0 or payload.tax_rate > 100:
        raise HTTPException(status_code=400, detail="tax_rate must be between 0 and 100")

    exists = (
        db.query(models.PayrollEmployee)
        .filter(models.PayrollEmployee.company_id == company_id, models.PayrollEmployee.employee_code == code)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Employee code already exists")

    employee = models.PayrollEmployee(
        company_id=company_id,
        employee_code=code,
        full_name=name,
        photo_url=payload.photo_url.strip(),
        id_number=payload.id_number.strip(),
        tax_number=payload.tax_number.strip(),
        email=payload.email.strip(),
        phone=payload.phone.strip(),
        position=payload.position.strip(),
        hire_date=payload.hire_date,
        bank_account=payload.bank_account.strip(),
        nssa_number=payload.nssa_number.strip(),
        pension_number=payload.pension_number.strip(),
        default_gross_salary=payload.default_gross_salary,
        tax_rate=payload.tax_rate,
        active=payload.active,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return _payroll_employee_payload(employee)


def _payroll_run_out(run: models.PayrollRun) -> schemas.PayrollRunOut:
    return schemas.PayrollRunOut(
        id=run.id,
        period_label=run.period_label,
        pay_date=run.pay_date,
        status=run.status,
        total_gross=float(run.total_gross or 0.0),
        total_tax=float(run.total_tax or 0.0),
        total_nssa=float(run.total_nssa or 0.0),
        total_pension=float(run.total_pension or 0.0),
        total_other_deductions=float(run.total_other_deductions or 0.0),
        total_sdl=float(run.total_sdl or 0.0),
        total_net=float(run.total_net or 0.0),
        paye_rate=float(run.paye_rate or 0.0),
        nssa_rate=float(run.nssa_rate or 0.0),
        pension_rate=float(run.pension_rate or 0.0),
        sdl_rate=float(run.sdl_rate or 0.0),
        other_deduction_per_employee=float(run.other_deduction_per_employee or 0.0),
        expense_account_id=run.expense_account_id,
        payable_account_id=run.payable_account_id,
        tax_liability_account_id=run.tax_liability_account_id,
        journal_entry_id=run.journal_entry_id,
        payment_entry_id=run.payment_entry_id,
        paid_date=run.paid_date,
        line_count=len(run.lines or []),
    )


def _payroll_run_detail(run: models.PayrollRun) -> dict:
    return {
        "id": run.id,
        "period_label": run.period_label,
        "pay_date": run.pay_date,
        "status": run.status,
        "total_gross": float(run.total_gross or 0.0),
        "total_tax": float(run.total_tax or 0.0),
        "total_nssa": float(run.total_nssa or 0.0),
        "total_pension": float(run.total_pension or 0.0),
        "total_other_deductions": float(run.total_other_deductions or 0.0),
        "total_sdl": float(run.total_sdl or 0.0),
        "total_net": float(run.total_net or 0.0),
        "paye_rate": float(run.paye_rate or 0.0),
        "nssa_rate": float(run.nssa_rate or 0.0),
        "pension_rate": float(run.pension_rate or 0.0),
        "sdl_rate": float(run.sdl_rate or 0.0),
        "other_deduction_per_employee": float(run.other_deduction_per_employee or 0.0),
        "expense_account_id": run.expense_account_id,
        "payable_account_id": run.payable_account_id,
        "tax_liability_account_id": run.tax_liability_account_id,
        "journal_entry_id": run.journal_entry_id,
        "payment_entry_id": run.payment_entry_id,
        "paid_date": run.paid_date,
        "lines": [
            {
                "id": ln.id,
                "employee_id": ln.employee_id,
                "employee_code": ln.employee.employee_code,
                "employee_name": ln.employee.full_name,
                "gross_pay": float(ln.gross_pay or 0.0),
                "tax_amount": float(ln.tax_amount or 0.0),
                "nssa_amount": float(ln.nssa_amount or 0.0),
                "pension_amount": float(ln.pension_amount or 0.0),
                "other_deduction": float(ln.other_deduction or 0.0),
                "sdl_amount": float(ln.sdl_amount or 0.0),
                "total_deductions": float(ln.total_deductions or 0.0),
                "net_pay": float(ln.net_pay or 0.0),
            }
            for ln in (run.lines or [])
        ],
    }


@app.get("/payroll/employees", response_model=list[schemas.PayrollEmployeeOut])
def list_payroll_employees(company_id: int = 1, q: str | None = None, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    query = db.query(models.PayrollEmployee).filter(models.PayrollEmployee.company_id == company_id)
    if q:
        needle = f"%{q.strip()}%"
        query = query.filter(
            (models.PayrollEmployee.full_name.ilike(needle))
            | (models.PayrollEmployee.employee_code.ilike(needle))
        )

    rows = query.order_by(models.PayrollEmployee.full_name.asc(), models.PayrollEmployee.id.asc()).all()
    return [_payroll_employee_payload(emp) for emp in rows]


@app.get("/payroll/employees/{employee_id}", response_model=schemas.PayrollEmployeeDetailOut)
def payroll_employee_detail(employee_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    emp = (
        db.query(models.PayrollEmployee)
        .filter(models.PayrollEmployee.company_id == company_id, models.PayrollEmployee.id == employee_id)
        .first()
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    lines = (
        db.query(models.PayrollRunLine, models.PayrollRun)
        .join(models.PayrollRun, models.PayrollRun.id == models.PayrollRunLine.payroll_run_id)
        .filter(models.PayrollRun.company_id == company_id, models.PayrollRunLine.employee_id == employee_id)
        .order_by(models.PayrollRun.pay_date.desc(), models.PayrollRun.id.desc())
        .all()
    )

    history = [
        {
            "payroll_run_id": run.id,
            "period_label": run.period_label,
            "pay_date": run.pay_date,
            "status": run.status,
            "gross_pay": float(line.gross_pay or 0.0),
            "tax_amount": float(line.tax_amount or 0.0),
            "net_pay": float(line.net_pay or 0.0),
        }
        for line, run in lines
    ]

    docs = (
        db.query(models.PayrollEmployeeDocument)
        .filter(
            models.PayrollEmployeeDocument.company_id == company_id,
            models.PayrollEmployeeDocument.employee_id == employee_id,
        )
        .order_by(models.PayrollEmployeeDocument.uploaded_at.desc(), models.PayrollEmployeeDocument.id.desc())
        .all()
    )

    return {
        "employee": _payroll_employee_payload(emp),
        "payroll_history": history,
        "documents": [
            {
                "id": d.id,
                "employee_id": d.employee_id,
                "doc_type": d.doc_type,
                "title": d.title,
                "original_filename": d.original_filename,
                "content_type": d.content_type,
                "file_size": int(d.file_size or 0),
                "uploaded_at": d.uploaded_at,
            }
            for d in docs
        ],
    }


@app.post("/payroll/employees/{employee_id}/documents", response_model=schemas.PayrollEmployeeDocumentOut)
async def upload_payroll_employee_document(
    employee_id: int,
    doc_type: str = Form("other"),
    title: str = Form(""),
    company_id: int = 1,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    _resolve_company(db, company_id)
    employee = (
        db.query(models.PayrollEmployee)
        .filter(models.PayrollEmployee.company_id == company_id, models.PayrollEmployee.id == employee_id)
        .first()
    )
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File exceeds 15MB size limit")

    employee_dir = PAYROLL_DOCS_DIR / f"company_{company_id}" / f"employee_{employee_id}"
    employee_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_slug(file.filename or "document")
    stored_name = f"{uuid4().hex}_{safe_name}"
    stored_path = employee_dir / stored_name
    stored_path.write_bytes(raw)

    doc = models.PayrollEmployeeDocument(
        company_id=company_id,
        employee_id=employee_id,
        doc_type=_safe_slug(doc_type or "other")[:60],
        title=(title or "").strip() or (file.filename or "Document"),
        original_filename=file.filename or "document",
        stored_filename=stored_name,
        file_path=str(stored_path),
        content_type=file.content_type or "application/octet-stream",
        file_size=len(raw),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return {
        "id": doc.id,
        "employee_id": doc.employee_id,
        "doc_type": doc.doc_type,
        "title": doc.title,
        "original_filename": doc.original_filename,
        "content_type": doc.content_type,
        "file_size": int(doc.file_size or 0),
        "uploaded_at": doc.uploaded_at,
    }


@app.get("/payroll/employees/{employee_id}/documents", response_model=list[schemas.PayrollEmployeeDocumentOut])
def list_payroll_employee_documents(employee_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    docs = (
        db.query(models.PayrollEmployeeDocument)
        .filter(
            models.PayrollEmployeeDocument.company_id == company_id,
            models.PayrollEmployeeDocument.employee_id == employee_id,
        )
        .order_by(models.PayrollEmployeeDocument.uploaded_at.desc(), models.PayrollEmployeeDocument.id.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "employee_id": d.employee_id,
            "doc_type": d.doc_type,
            "title": d.title,
            "original_filename": d.original_filename,
            "content_type": d.content_type,
            "file_size": int(d.file_size or 0),
            "uploaded_at": d.uploaded_at,
        }
        for d in docs
    ]


@app.get("/payroll/documents/{document_id}/download")
def download_payroll_employee_document(document_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    doc = (
        db.query(models.PayrollEmployeeDocument)
        .filter(models.PayrollEmployeeDocument.company_id == company_id, models.PayrollEmployeeDocument.id == document_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    path = Path(doc.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document file missing")

    return FileResponse(
        str(path),
        media_type=doc.content_type or "application/octet-stream",
        filename=doc.original_filename or doc.stored_filename,
    )


@app.post("/payroll/employees/bulk")
def create_payroll_employees_bulk(payload: schemas.PayrollEmployeesBulkCreate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    created = 0
    skipped = 0

    for item in payload.employees:
        code = item.employee_code.strip()
        name = item.full_name.strip()
        if not code or not name or item.default_gross_salary < 0:
            skipped += 1
            continue
        exists = (
            db.query(models.PayrollEmployee)
            .filter(models.PayrollEmployee.company_id == company_id, models.PayrollEmployee.employee_code == code)
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(
            models.PayrollEmployee(
                company_id=company_id,
                employee_code=code,
                full_name=name,
                photo_url=item.photo_url.strip(),
                id_number=item.id_number.strip(),
                tax_number=item.tax_number.strip(),
                email=item.email.strip(),
                phone=item.phone.strip(),
                position=item.position.strip(),
                hire_date=item.hire_date,
                bank_account=item.bank_account.strip(),
                nssa_number=item.nssa_number.strip(),
                pension_number=item.pension_number.strip(),
                default_gross_salary=item.default_gross_salary,
                tax_rate=item.tax_rate,
                active=item.active,
            )
        )
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped}


def _seed_sample_payroll_employees(db: Session, company_id: int) -> int:
    _resolve_company(db, company_id)
    sample = [
        ("EMP501", "Alex Moyo", 850.0, 20.0),
        ("EMP201", "Tariro Dube", 1200.0, 25.0),
        ("EMP301", "Nyasha Sibanda", 600.0, 15.0),
    ]
    created = 0
    for code, name, gross, tax in sample:
        exists = (
            db.query(models.PayrollEmployee)
            .filter(models.PayrollEmployee.company_id == company_id, models.PayrollEmployee.employee_code == code)
            .first()
        )
        if exists:
            continue
        db.add(
            models.PayrollEmployee(
                company_id=company_id,
                employee_code=code,
                full_name=name,
                photo_url="",
                default_gross_salary=gross,
                tax_rate=tax,
                active=True,
            )
        )
        created += 1
    db.commit()
    return created


def _seed_sample_payroll_data(db: Session, company_id: int) -> dict:
    _resolve_company(db, company_id)

    employee_count = db.query(models.PayrollEmployee).filter(models.PayrollEmployee.company_id == company_id).count()
    if employee_count == 0:
        _seed_sample_payroll_employees(db=db, company_id=company_id)

    employees = (
        db.query(models.PayrollEmployee)
        .filter(models.PayrollEmployee.company_id == company_id, models.PayrollEmployee.active.is_(True))
        .order_by(models.PayrollEmployee.id.asc())
        .limit(6)
        .all()
    )
    if not employees:
        raise HTTPException(status_code=400, detail="No active payroll employees to seed")

    expense = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.code == "5100")
        .first()
    )
    if not expense:
        expense = models.Account(company_id=company_id, code="5100", name="Payroll Expense", category="Expense", vat_rate=0.0)
        db.add(expense)
        db.flush()

    payable = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.code == "2100")
        .first()
    )
    if not payable:
        payable = models.Account(company_id=company_id, code="2100", name="Payroll Payable", category="Liability", vat_rate=0.0)
        db.add(payable)
        db.flush()

    tax_liability = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.code == "2110")
        .first()
    )
    if not tax_liability:
        tax_liability = models.Account(company_id=company_id, code="2110", name="PAYE Liability", category="Liability", vat_rate=0.0)
        db.add(tax_liability)
        db.flush()

    _ensure_default_tax_brackets(db, company_id)
    brackets = (
        db.query(models.PayrollTaxBracket)
        .filter(models.PayrollTaxBracket.company_id == company_id)
        .order_by(models.PayrollTaxBracket.order_index.asc(), models.PayrollTaxBracket.lower_limit.asc())
        .all()
    )

    today = date.today()
    run_specs = [
        (f"{today:%b %Y}", today.replace(day=25), "paid"),
        (f"{(today - timedelta(days=30)):%b %Y}", (today - timedelta(days=30)).replace(day=25), "posted"),
    ]

    created_runs = 0
    for period_label, pay_date, status in run_specs:
        exists = (
            db.query(models.PayrollRun)
            .filter(models.PayrollRun.company_id == company_id, models.PayrollRun.period_label == period_label)
            .first()
        )
        if exists:
            continue

        run = models.PayrollRun(
            company_id=company_id,
            period_label=period_label,
            pay_date=pay_date,
            status=status,
            expense_account_id=expense.id,
            payable_account_id=payable.id,
            tax_liability_account_id=tax_liability.id,
            paye_rate=0.0,
            nssa_rate=3.0,
            pension_rate=5.0,
            sdl_rate=1.0,
            other_deduction_per_employee=2.0,
        )
        db.add(run)
        db.flush()

        totals = {"gross": 0.0, "tax": 0.0, "nssa": 0.0, "pension": 0.0, "other": 0.0, "sdl": 0.0, "net": 0.0}
        for idx, emp in enumerate(employees, start=1):
            gross = round(float(emp.default_gross_salary or 0.0) + idx * 10.0, 2)
            tax = _compute_progressive_tax(gross, brackets)
            nssa = round(gross * 0.03, 2)
            pension = round(gross * 0.05, 2)
            other = 2.0
            sdl = round(gross * 0.01, 2)
            ded = round(tax + nssa + pension + other + sdl, 2)
            net = round(gross - ded, 2)

            db.add(
                models.PayrollRunLine(
                    payroll_run_id=run.id,
                    employee_id=emp.id,
                    gross_pay=gross,
                    tax_amount=tax,
                    nssa_amount=nssa,
                    pension_amount=pension,
                    other_deduction=other,
                    sdl_amount=sdl,
                    total_deductions=ded,
                    net_pay=net,
                )
            )

            totals["gross"] += gross
            totals["tax"] += tax
            totals["nssa"] += nssa
            totals["pension"] += pension
            totals["other"] += other
            totals["sdl"] += sdl
            totals["net"] += net

        run.total_gross = round(totals["gross"], 2)
        run.total_tax = round(totals["tax"], 2)
        run.total_nssa = round(totals["nssa"], 2)
        run.total_pension = round(totals["pension"], 2)
        run.total_other_deductions = round(totals["other"], 2)
        run.total_sdl = round(totals["sdl"], 2)
        run.total_net = round(totals["net"], 2)
        if status == "paid":
            run.paid_date = pay_date
        created_runs += 1

    db.commit()
    return {"runs_created": created_runs, "employees_used": len(employees)}


@app.get("/payroll/tax-brackets", response_model=list[schemas.PayrollTaxBracketOut])
def list_payroll_tax_brackets(company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    _ensure_default_tax_brackets(db, company_id)
    rows = (
        db.query(models.PayrollTaxBracket)
        .filter(models.PayrollTaxBracket.company_id == company_id)
        .order_by(models.PayrollTaxBracket.order_index.asc(), models.PayrollTaxBracket.lower_limit.asc())
        .all()
    )
    return [
        schemas.PayrollTaxBracketOut(
            id=r.id,
            lower_limit=float(r.lower_limit or 0.0),
            upper_limit=float(r.upper_limit) if r.upper_limit is not None else None,
            rate_percent=float(r.rate_percent or 0.0),
            order_index=r.order_index,
        )
        for r in rows
    ]


@app.post("/payroll/tax-brackets", response_model=list[schemas.PayrollTaxBracketOut])
def replace_payroll_tax_brackets(payload: schemas.PayrollTaxBracketsUpdate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    if not payload.brackets:
        raise HTTPException(status_code=400, detail="Provide at least one bracket")

    for b in payload.brackets:
        if b.rate_percent < 0 or b.rate_percent > 100:
            raise HTTPException(status_code=400, detail="Bracket rate must be between 0 and 100")
        if b.upper_limit is not None and b.upper_limit <= b.lower_limit:
            raise HTTPException(status_code=400, detail="upper_limit must be greater than lower_limit")

    db.query(models.PayrollTaxBracket).filter(models.PayrollTaxBracket.company_id == company_id).delete()
    db.flush()
    for b in payload.brackets:
        db.add(
            models.PayrollTaxBracket(
                company_id=company_id,
                lower_limit=b.lower_limit,
                upper_limit=b.upper_limit,
                rate_percent=b.rate_percent,
                order_index=b.order_index,
            )
        )
    db.commit()
    return list_payroll_tax_brackets(company_id=company_id, db=db)


@app.post("/payroll/runs", response_model=schemas.PayrollRunOut)
def create_payroll_run(payload: schemas.PayrollRunCreate, company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)

    expense_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.expense_account_id)
        .first()
    )
    payable_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.payable_account_id)
        .first()
    )
    tax_account = None
    if payload.tax_liability_account_id:
        tax_account = (
            db.query(models.Account)
            .filter(models.Account.company_id == company_id, models.Account.id == payload.tax_liability_account_id)
            .first()
        )

    if not expense_account or not payable_account:
        raise HTTPException(status_code=404, detail="Expense or payable account not found")
    if payload.tax_liability_account_id and not tax_account:
        raise HTTPException(status_code=404, detail="Tax liability account not found")

    employees_q = db.query(models.PayrollEmployee).filter(
        models.PayrollEmployee.company_id == company_id,
        models.PayrollEmployee.active == True,
    )
    if payload.employee_ids:
        employees_q = employees_q.filter(models.PayrollEmployee.id.in_(payload.employee_ids))
    employees = employees_q.order_by(models.PayrollEmployee.full_name.asc()).all()

    if not employees:
        raise HTTPException(status_code=400, detail="No active payroll employees found for this run")

    _ensure_default_tax_brackets(db, company_id)
    tax_brackets = (
        db.query(models.PayrollTaxBracket)
        .filter(models.PayrollTaxBracket.company_id == company_id)
        .order_by(models.PayrollTaxBracket.order_index.asc(), models.PayrollTaxBracket.lower_limit.asc())
        .all()
    )

    paye_rate_default = float(payload.paye_rate) if payload.paye_rate is not None else None
    nssa_rate = float(payload.nssa_rate or 0.0)
    pension_rate = float(payload.pension_rate or 0.0)
    sdl_rate = float(payload.sdl_rate or 0.0)
    other_deduction_per_employee = float(payload.other_deduction_per_employee or 0.0)

    for rate_name, rate_value in {
        "paye_rate": paye_rate_default,
        "nssa_rate": nssa_rate,
        "pension_rate": pension_rate,
        "sdl_rate": sdl_rate,
    }.items():
        if rate_value is not None and (rate_value < 0 or rate_value > 100):
            raise HTTPException(status_code=400, detail=f"{rate_name} must be between 0 and 100")
    if other_deduction_per_employee < 0:
        raise HTTPException(status_code=400, detail="other_deduction_per_employee must be >= 0")

    run = models.PayrollRun(
        company_id=company_id,
        period_label=payload.period_label.strip() or payload.pay_date.isoformat(),
        pay_date=payload.pay_date,
        status="draft",
        paye_rate=float(paye_rate_default or 0.0),
        nssa_rate=nssa_rate,
        pension_rate=pension_rate,
        sdl_rate=sdl_rate,
        other_deduction_per_employee=other_deduction_per_employee,
        expense_account_id=payload.expense_account_id,
        payable_account_id=payload.payable_account_id,
        tax_liability_account_id=payload.tax_liability_account_id,
    )
    db.add(run)
    db.flush()

    total_gross = 0.0
    total_tax = 0.0
    total_nssa = 0.0
    total_pension = 0.0
    total_other_deductions = 0.0
    total_sdl = 0.0
    total_net = 0.0
    for emp in employees:
        gross = round(float(emp.default_gross_salary or 0.0), 2)
        paye_rate = float(paye_rate_default if paye_rate_default is not None else (emp.tax_rate or 0.0))
        tax = round(gross * paye_rate / 100.0, 2) if paye_rate_default is not None else _compute_progressive_tax(gross, tax_brackets)
        nssa_amount = round(gross * nssa_rate / 100.0, 2)
        pension_amount = round(gross * pension_rate / 100.0, 2)
        sdl_amount = round(gross * sdl_rate / 100.0, 2)
        other_deduction = round(other_deduction_per_employee, 2)
        total_deductions = round(tax + nssa_amount + pension_amount + other_deduction, 2)
        net = round(max(gross - total_deductions, 0.0), 2)
        line = models.PayrollRunLine(
            payroll_run_id=run.id,
            employee_id=emp.id,
            gross_pay=gross,
            tax_amount=tax,
            nssa_amount=nssa_amount,
            pension_amount=pension_amount,
            other_deduction=other_deduction,
            sdl_amount=sdl_amount,
            total_deductions=total_deductions,
            net_pay=net,
        )
        db.add(line)
        total_gross += gross
        total_tax += tax
        total_nssa += nssa_amount
        total_pension += pension_amount
        total_other_deductions += other_deduction
        total_sdl += sdl_amount
        total_net += net

    run.total_gross = round(total_gross, 2)
    run.total_tax = round(total_tax, 2)
    run.total_nssa = round(total_nssa, 2)
    run.total_pension = round(total_pension, 2)
    run.total_other_deductions = round(total_other_deductions, 2)
    run.total_sdl = round(total_sdl, 2)
    run.total_net = round(total_net, 2)
    db.commit()
    db.refresh(run)
    return _payroll_run_out(run)


@app.get("/payroll/runs", response_model=list[schemas.PayrollRunOut])
def list_payroll_runs(company_id: int = 1, db: Session = Depends(get_db)):
    _resolve_company(db, company_id)
    rows = (
        db.query(models.PayrollRun)
        .filter(models.PayrollRun.company_id == company_id)
        .order_by(models.PayrollRun.pay_date.desc(), models.PayrollRun.id.desc())
        .all()
    )
    return [_payroll_run_out(run) for run in rows]


@app.get("/payroll/runs/{run_id}")
def get_payroll_run(run_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    run = db.query(models.PayrollRun).filter(models.PayrollRun.company_id == company_id, models.PayrollRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return _payroll_run_detail(run)


@app.post("/payroll/runs/{run_id}/post")
def post_payroll_run(run_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    run = db.query(models.PayrollRun).filter(models.PayrollRun.company_id == company_id, models.PayrollRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run.journal_entry_id:
        return {"status": "already-posted", "journal_entry_id": run.journal_entry_id}

    total_gross = float(run.total_gross or 0.0)
    total_tax = float(run.total_tax or 0.0)
    total_nssa = float(run.total_nssa or 0.0)
    total_pension = float(run.total_pension or 0.0)
    total_other = float(run.total_other_deductions or 0.0)
    total_sdl = float(run.total_sdl or 0.0)
    total_net = float(run.total_net or 0.0)
    if total_gross <= 0:
        raise HTTPException(status_code=400, detail="Payroll run total is zero")

    payable_credit = round(total_net, 2)
    statutory_credit = round(total_tax + total_nssa + total_pension + total_other + total_sdl, 2)
    if statutory_credit > 0 and not run.tax_liability_account_id:
        payable_credit = round(payable_credit + statutory_credit, 2)

    try:
        entry = models.JournalEntry(
            company_id=company_id,
            entry_date=run.pay_date,
            memo=f"Payroll - {run.period_label}",
            source="payroll",
            source_id=run.id,
        )
        db.add(entry)
        db.flush()

        db.add(models.JournalLine(entry_id=entry.id, account_id=run.expense_account_id, debit=round(total_gross + total_sdl, 2), credit=0.0))
        db.add(models.JournalLine(entry_id=entry.id, account_id=run.payable_account_id, debit=0.0, credit=payable_credit))
        if statutory_credit > 0 and run.tax_liability_account_id:
            db.add(models.JournalLine(entry_id=entry.id, account_id=run.tax_liability_account_id, debit=0.0, credit=statutory_credit))

        run.status = "posted"
        run.journal_entry_id = entry.id
        db.commit()
        return {"status": "posted", "journal_entry_id": entry.id}
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(models.JournalEntry)
            .filter(models.JournalEntry.company_id == company_id, models.JournalEntry.source == "payroll", models.JournalEntry.source_id == run.id)
            .first()
        )
        if existing:
            run.status = "posted"
            run.journal_entry_id = existing.id
            db.commit()
            return {"status": "already-posted", "journal_entry_id": existing.id}
        raise HTTPException(status_code=400, detail="Payroll posting failed due to duplicate journal source")


@app.post("/payroll/runs/{run_id}/pay")
def pay_payroll_run(run_id: int, payload: schemas.PayrollPayRequest, company_id: int = 1, db: Session = Depends(get_db)):
    run = db.query(models.PayrollRun).filter(models.PayrollRun.company_id == company_id, models.PayrollRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if not run.journal_entry_id:
        raise HTTPException(status_code=400, detail="Post payroll run first before payment")
    if run.payment_entry_id:
        return {"status": "already-paid", "payment_entry_id": run.payment_entry_id}

    bank_account = (
        db.query(models.Account)
        .filter(models.Account.company_id == company_id, models.Account.id == payload.bank_account_id)
        .first()
    )
    if not bank_account:
        raise HTTPException(status_code=404, detail="Bank account not found")

    amount = round(float(run.total_net or 0.0), 2)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Payroll net pay is zero")

    try:
        pay_entry = models.JournalEntry(
            company_id=company_id,
            entry_date=payload.payment_date,
            memo=f"Payroll payment - {run.period_label}",
            source="payroll-payment",
            source_id=run.id,
        )
        db.add(pay_entry)
        db.flush()

        db.add(models.JournalLine(entry_id=pay_entry.id, account_id=run.payable_account_id, debit=amount, credit=0.0))
        db.add(models.JournalLine(entry_id=pay_entry.id, account_id=payload.bank_account_id, debit=0.0, credit=amount))

        run.status = "paid"
        run.payment_entry_id = pay_entry.id
        run.paid_date = payload.payment_date
        db.commit()
        return {"status": "paid", "payment_entry_id": pay_entry.id}
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(models.JournalEntry)
            .filter(models.JournalEntry.company_id == company_id, models.JournalEntry.source == "payroll-payment", models.JournalEntry.source_id == run.id)
            .first()
        )
        if existing:
            run.status = "paid"
            run.payment_entry_id = existing.id
            run.paid_date = payload.payment_date
            db.commit()
            return {"status": "already-paid", "payment_entry_id": existing.id}
        raise HTTPException(status_code=400, detail="Payroll payment posting failed")


@app.get("/payroll/runs/{run_id}/summary")
def payroll_run_summary(run_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    run = db.query(models.PayrollRun).filter(models.PayrollRun.company_id == company_id, models.PayrollRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    return _payroll_run_detail(run)


@app.get("/payroll/runs/{run_id}/download")
def payroll_run_download(run_id: int, format: str = "pdf", company_id: int = 1, db: Session = Depends(get_db)):
    run = db.query(models.PayrollRun).filter(models.PayrollRun.company_id == company_id, models.PayrollRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    detail = _payroll_run_detail(run)
    profile = _get_company_profile(db, company_id)
    profile_data = {
        "company_name": profile.company_name,
        "address": profile.address,
        "email": profile.email,
        "phone": profile.phone,
        "tax_number": profile.tax_number,
        "currency": profile.currency,
    }

    if format == "json":
        return detail

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["run_id", "period", "pay_date", "status", "total_gross", "total_tax", "total_nssa", "total_pension", "total_other_deductions", "total_sdl", "total_net"])
        writer.writerow([
            detail["id"], detail["period_label"], detail["pay_date"], detail["status"], detail["total_gross"], detail["total_tax"], detail["total_nssa"], detail["total_pension"], detail["total_other_deductions"], detail["total_sdl"], detail["total_net"],
        ])
        writer.writerow([])
        writer.writerow(["employee_code", "employee_name", "gross", "paye", "nssa", "pension", "other_deduction", "sdl", "total_deductions", "net"])
        for ln in detail.get("lines", []):
            writer.writerow([
                ln.get("employee_code"),
                ln.get("employee_name"),
                ln.get("gross_pay"),
                ln.get("tax_amount"),
                ln.get("nssa_amount"),
                ln.get("pension_amount"),
                ln.get("other_deduction"),
                ln.get("sdl_amount"),
                ln.get("total_deductions"),
                ln.get("net_pay"),
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue().encode("utf-8")]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=payroll-run-{run.id}.csv"},
        )

    pdf_bytes = build_payroll_run_pdf(detail, profile_data)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=payroll-run-{run.id}.pdf"},
    )


@app.get("/payroll/runs/{run_id}/payslip/{employee_id}")
def payroll_payslip_download(run_id: int, employee_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    run = db.query(models.PayrollRun).filter(models.PayrollRun.company_id == company_id, models.PayrollRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    line = (
        db.query(models.PayrollRunLine)
        .join(models.PayrollEmployee, models.PayrollEmployee.id == models.PayrollRunLine.employee_id)
        .filter(models.PayrollRunLine.payroll_run_id == run.id, models.PayrollRunLine.employee_id == employee_id)
        .first()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Payslip employee line not found")

    detail = _payroll_run_detail(run)
    employee_line = next((ln for ln in detail.get("lines", []) if ln.get("employee_id") == employee_id), None)
    if not employee_line:
        raise HTTPException(status_code=404, detail="Payslip data not found")

    profile = _get_company_profile(db, company_id)
    profile_data = {
        "company_name": profile.company_name,
        "address": profile.address,
        "email": profile.email,
        "phone": profile.phone,
        "tax_number": profile.tax_number,
        "currency": profile.currency,
    }
    pdf_bytes = build_payroll_payslip_pdf(detail, employee_line, profile_data)
    safe_code = str(employee_line.get("employee_code") or employee_id)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=payslip-{run.id}-{safe_code}.pdf"},
    )


@app.get("/payroll/runs/{run_id}/tax-certificate/{employee_id}")
def payroll_tax_certificate_download(run_id: int, employee_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    run = db.query(models.PayrollRun).filter(models.PayrollRun.company_id == company_id, models.PayrollRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")

    detail = _payroll_run_detail(run)
    employee_line = next((ln for ln in detail.get("lines", []) if ln.get("employee_id") == employee_id), None)
    if not employee_line:
        raise HTTPException(status_code=404, detail="Tax certificate employee line not found")

    profile = _get_company_profile(db, company_id)
    pdf_bytes = build_tax_certificate_pdf(detail, employee_line, _company_profile_data(profile))
    safe_code = str(employee_line.get("employee_code") or employee_id)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=tax-certificate-{run.id}-{safe_code}.pdf"},
    )


@app.get("/payroll/employees/{employee_id}/employment-certificate")
def employment_certificate_download(employee_id: int, company_id: int = 1, db: Session = Depends(get_db)):
    emp = (
        db.query(models.PayrollEmployee)
        .filter(models.PayrollEmployee.company_id == company_id, models.PayrollEmployee.id == employee_id)
        .first()
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    profile = _get_company_profile(db, company_id)
    employee_data = {
        "employee_code": emp.employee_code,
        "full_name": emp.full_name,
        "default_gross_salary": emp.default_gross_salary,
        "tax_rate": emp.tax_rate,
        "active": emp.active,
    }
    pdf_bytes = build_employment_certificate_pdf(employee_data, _company_profile_data(profile), date.today().isoformat())
    safe_code = str(emp.employee_code or employee_id)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=employment-certificate-{safe_code}.pdf"},
    )


@app.get("/debug/pipeline-state")
def debug_pipeline_state(company_id: int = 1, db: Session = Depends(get_db)):
    tx_by_status = {
        row[0]: row[1]
        for row in (
            db.query(models.BankTransaction.status, func.count(models.BankTransaction.id))
            .filter(models.BankTransaction.company_id == company_id)
            .group_by(models.BankTransaction.status)
            .all()
        )
    }
    total_entries = db.query(func.count(models.JournalEntry.id)).filter(models.JournalEntry.company_id == company_id).scalar() or 0
    total_lines = db.query(func.count(models.JournalLine.id)).scalar() or 0
    total_rules = db.query(func.count(models.AllocationRule.id)).filter(models.AllocationRule.company_id == company_id).scalar() or 0
    total_accounts = db.query(func.count(models.Account.id)).filter(models.Account.company_id == company_id).scalar() or 0

    return {
        "accounts": total_accounts,
        "rules": total_rules,
        "bank_transactions_by_status": tx_by_status,
        "journal_entries": total_entries,
        "journal_lines": total_lines,
    }


@app.get("/reports/general-ledger")
def get_general_ledger(from_date: date | None = None, to_date: date | None = None, company_id: int = 1, db: Session = Depends(get_db)):
    return general_ledger(db, company_id=company_id, from_date=from_date, to_date=to_date)


@app.get("/reports/trial-balance", response_model=list[schemas.TrialBalanceLine])
def get_trial_balance(from_date: date | None = None, to_date: date | None = None, company_id: int = 1, db: Session = Depends(get_db)):
    return trial_balance(db, company_id=company_id, from_date=from_date, to_date=to_date)


@app.get("/reports/profit-loss")
def get_profit_and_loss(from_date: date | None = None, to_date: date | None = None, company_id: int = 1, db: Session = Depends(get_db)):
    return profit_and_loss(db, company_id=company_id, from_date=from_date, to_date=to_date)


@app.get("/reports/balance-sheet")
def get_balance_sheet(from_date: date | None = None, to_date: date | None = None, company_id: int = 1, db: Session = Depends(get_db)):
    return balance_sheet(db, company_id=company_id, from_date=from_date, to_date=to_date)


@app.get("/reports/cash-flow")
def get_cash_flow(from_date: date | None = None, to_date: date | None = None, company_id: int = 1, db: Session = Depends(get_db)):
    return cash_flow_statement(db, company_id=company_id, from_date=from_date, to_date=to_date)


@app.get("/reports/cash-flow-projection")
def get_cash_flow_projection(
    months: int = 12,
    from_date: date | None = None,
    to_date: date | None = None,
    company_id: int = 1,
    inflow_growth_pct: float = 0.0,
    outflow_growth_pct: float = 0.0,
    opening_balance_override: float | None = None,
    db: Session = Depends(get_db),
):
    return cash_flow_projection(
        db,
        company_id=company_id,
        months=months,
        from_date=from_date,
        to_date=to_date,
        inflow_growth_pct=inflow_growth_pct,
        outflow_growth_pct=outflow_growth_pct,
        opening_balance_override=opening_balance_override,
    )


@app.get("/reports/all")
def get_all_reports(from_date: date | None = None, to_date: date | None = None, company_id: int = 1, db: Session = Depends(get_db)):
    return {
        "bank_balance": _bank_balance_summary(db, company_id=company_id),
        "trial_balance": trial_balance(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "profit_and_loss": profit_and_loss(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "balance_sheet": balance_sheet(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "cash_flow": cash_flow_statement(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "cash_flow_projection": cash_flow_projection(db, company_id=company_id, months=12, from_date=None, to_date=to_date),
        "general_ledger": general_ledger(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "assets": list_assets(company_id=company_id, db=db),
        "loans": list_loans(company_id=company_id, db=db),
    }


@app.get("/reports/download/{report_name}")
def download_report(
    report_name: str,
    format: str = "csv",
    period_label: str | None = None,
    compare: bool = True,
    from_date: date | None = None,
    to_date: date | None = None,
    company_id: int = 1,
    months: int = 12,
    inflow_growth_pct: float = 0.0,
    outflow_growth_pct: float = 0.0,
    opening_balance_override: float | None = None,
    db: Session = Depends(get_db),
):
    report_map = {
        "trial-balance": trial_balance(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "profit-loss": profit_and_loss(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "balance-sheet": balance_sheet(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "cash-flow": cash_flow_statement(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "cash-flow-projection": cash_flow_projection(
            db,
            company_id=company_id,
            months=months,
            from_date=from_date,
            to_date=to_date,
            inflow_growth_pct=inflow_growth_pct,
            outflow_growth_pct=outflow_growth_pct,
            opening_balance_override=opening_balance_override,
        ),
        "general-ledger": general_ledger(db, company_id=company_id, from_date=from_date, to_date=to_date),
        "bank-balance": _bank_balance_summary(db, company_id=company_id),
        "all": get_all_reports(from_date=from_date, to_date=to_date, company_id=company_id, db=db),
    }

    if report_name not in report_map:
        raise HTTPException(status_code=404, detail="Report not found")

    data = report_map[report_name]
    if format == "json" or report_name == "all":
        raw = json.dumps(data, default=str, indent=2)
        return StreamingResponse(
            iter([raw]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={report_name}.json"},
        )

    if format == "pdf":
        if report_name == "all":
            raise HTTPException(status_code=400, detail="PDF export for 'all' is not supported. Download individual statements as PDF.")

        compare_data = None
        compare_label = None
        comparable_reports = {"trial-balance", "profit-loss", "balance-sheet", "cash-flow"}
        if compare and from_date and to_date and from_date <= to_date and report_name in comparable_reports:
            days = (to_date - from_date).days
            compare_to_date = from_date - timedelta(days=1)
            compare_from_date = compare_to_date - timedelta(days=days)
            compare_label = f"{compare_from_date.isoformat()} to {compare_to_date.isoformat()}"

            if report_name == "trial-balance":
                compare_data = trial_balance(db, company_id=company_id, from_date=compare_from_date, to_date=compare_to_date)
            elif report_name == "profit-loss":
                compare_data = profit_and_loss(db, company_id=company_id, from_date=compare_from_date, to_date=compare_to_date)
            elif report_name == "balance-sheet":
                compare_data = balance_sheet(db, company_id=company_id, from_date=compare_from_date, to_date=compare_to_date)
            elif report_name == "cash-flow":
                compare_data = cash_flow_statement(db, company_id=company_id, from_date=compare_from_date, to_date=compare_to_date)

        profile = _get_company_profile(db, company_id)
        company_data = {
            "company_name": profile.company_name,
            "address": profile.address,
            "email": profile.email,
            "phone": profile.phone,
            "tax_number": profile.tax_number,
            "currency": profile.currency,
        }
        pdf_bytes = build_report_pdf(
            report_name,
            data,
            company_data,
            period_label=period_label,
            compare_data=compare_data,
            compare_label=compare_label,
        )
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={report_name}.pdf"},
        )

    csv_buf = _report_to_csv(report_name, data)
    return StreamingResponse(
        csv_buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={report_name}.csv"},
    )


@app.get("/bookkeeping/documents")
def get_bookkeeping_documents(company_id: int = 1, db: Session = Depends(get_db)):
    return bookkeeping_documents(db, company_id=company_id)

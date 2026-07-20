from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30))
    vat_rate: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_accounts_company_code"),)

    company = relationship("Company")


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    reference: Mapped[str] = mapped_column(String(100), default="")
    imported_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="imported")
    assigned_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)

    company = relationship("Company")
    assigned_account = relationship("Account")


class AllocationRule(Base):
    __tablename__ = "allocation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    name: Mapped[str] = mapped_column(String(100))
    keyword: Mapped[str] = mapped_column(String(80), index=True)
    min_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    priority: Mapped[int] = mapped_column(Integer, default=100)

    company = relationship("Company")
    account = relationship("Account")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    memo: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(50), default="bank")
    source_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_journal_source"),)

    company = relationship("Company")
    lines = relationship("JournalLine", back_populates="entry", cascade="all, delete-orphan")


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    debit: Mapped[float] = mapped_column(Float, default=0.0)
    credit: Mapped[float] = mapped_column(Float, default=0.0)

    entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("Account")


class FixedAsset(Base):
    __tablename__ = "fixed_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    name: Mapped[str] = mapped_column(String(120), index=True)
    asset_type: Mapped[str] = mapped_column(String(60), default="General")
    purchase_date: Mapped[date] = mapped_column(Date, index=True)
    cost: Mapped[float] = mapped_column(Float)
    useful_life_years: Mapped[int] = mapped_column(Integer, default=5)
    salvage_value: Mapped[float] = mapped_column(Float, default=0.0)
    asset_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    depreciation_expense_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")

    company = relationship("Company")
    asset_account = relationship("Account", foreign_keys=[asset_account_id])
    depreciation_expense_account = relationship("Account", foreign_keys=[depreciation_expense_account_id])


class Loan(Base):
    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    lender_name: Mapped[str] = mapped_column(String(120), index=True)
    principal: Mapped[float] = mapped_column(Float)
    annual_interest_rate: Mapped[float] = mapped_column(Float, default=0.0)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    term_months: Mapped[int] = mapped_column(Integer)
    liability_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    interest_expense_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")

    company = relationship("Company")
    liability_account = relationship("Account", foreign_keys=[liability_account_id])
    interest_expense_account = relationship("Account", foreign_keys=[interest_expense_account_id])


class BankOpeningBalance(Base):
    __tablename__ = "bank_opening_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    balance_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company = relationship("Company")


class CompanyProfile(Base):
    __tablename__ = "company_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    company_name: Mapped[str] = mapped_column(String(160), default="My Company")
    address: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    tax_number: Mapped[str] = mapped_column(String(80), default="")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("company_id", name="uq_company_profile_company"),)

    company = relationship("Company")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    customer_code: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    email: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    tax_number: Mapped[str] = mapped_column(String(80), default="")
    credit_limit: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("company_id", "customer_code", name="uq_customer_company_code"),)

    company = relationship("Company")


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    sku: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    quantity_on_hand: Mapped[float] = mapped_column(Float, default=0.0)
    min_stock_level: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("company_id", "sku", name="uq_inventory_company_sku"),)

    company = relationship("Company")


class PayrollEmployee(Base):
    __tablename__ = "payroll_employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    employee_code: Mapped[str] = mapped_column(String(40), index=True)
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    photo_url: Mapped[str] = mapped_column(String(500), default="")
    id_number: Mapped[str] = mapped_column(String(80), default="")
    tax_number: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    position: Mapped[str] = mapped_column(String(120), default="")
    hire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bank_account: Mapped[str] = mapped_column(String(120), default="")
    nssa_number: Mapped[str] = mapped_column(String(80), default="")
    pension_number: Mapped[str] = mapped_column(String(80), default="")
    default_gross_salary: Mapped[float] = mapped_column(Float, default=0.0)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("company_id", "employee_code", name="uq_payroll_employee_company_code"),)

    company = relationship("Company")


class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    period_label: Mapped[str] = mapped_column(String(80), index=True)
    pay_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    total_gross: Mapped[float] = mapped_column(Float, default=0.0)
    total_tax: Mapped[float] = mapped_column(Float, default=0.0)
    total_nssa: Mapped[float] = mapped_column(Float, default=0.0)
    total_pension: Mapped[float] = mapped_column(Float, default=0.0)
    total_other_deductions: Mapped[float] = mapped_column(Float, default=0.0)
    total_sdl: Mapped[float] = mapped_column(Float, default=0.0)
    total_net: Mapped[float] = mapped_column(Float, default=0.0)
    paye_rate: Mapped[float] = mapped_column(Float, default=0.0)
    nssa_rate: Mapped[float] = mapped_column(Float, default=0.0)
    pension_rate: Mapped[float] = mapped_column(Float, default=0.0)
    sdl_rate: Mapped[float] = mapped_column(Float, default=0.0)
    other_deduction_per_employee: Mapped[float] = mapped_column(Float, default=0.0)
    expense_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    payable_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    tax_liability_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    payment_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entries.id"), nullable=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company = relationship("Company")
    expense_account = relationship("Account", foreign_keys=[expense_account_id])
    payable_account = relationship("Account", foreign_keys=[payable_account_id])
    tax_liability_account = relationship("Account", foreign_keys=[tax_liability_account_id])
    journal_entry = relationship("JournalEntry", foreign_keys=[journal_entry_id])
    payment_entry = relationship("JournalEntry", foreign_keys=[payment_entry_id])
    lines = relationship("PayrollRunLine", back_populates="payroll_run", cascade="all, delete-orphan")


class PayrollRunLine(Base):
    __tablename__ = "payroll_run_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("payroll_employees.id"), index=True)
    gross_pay: Mapped[float] = mapped_column(Float, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)
    nssa_amount: Mapped[float] = mapped_column(Float, default=0.0)
    pension_amount: Mapped[float] = mapped_column(Float, default=0.0)
    other_deduction: Mapped[float] = mapped_column(Float, default=0.0)
    sdl_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_deductions: Mapped[float] = mapped_column(Float, default=0.0)
    net_pay: Mapped[float] = mapped_column(Float, default=0.0)

    payroll_run = relationship("PayrollRun", back_populates="lines")
    employee = relationship("PayrollEmployee")


class PayrollTaxBracket(Base):
    __tablename__ = "payroll_tax_brackets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    lower_limit: Mapped[float] = mapped_column(Float, default=0.0)
    upper_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    order_index: Mapped[int] = mapped_column(Integer, default=1)

    company = relationship("Company")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PayrollEmployeeDocument(Base):
    __tablename__ = "payroll_employee_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    employee_id: Mapped[int] = mapped_column(ForeignKey("payroll_employees.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(60), default="other")
    title: Mapped[str] = mapped_column(String(160), default="")
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    stored_filename: Mapped[str] = mapped_column(String(255), default="")
    file_path: Mapped[str] = mapped_column(String(500), default="")
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company = relationship("Company")
    employee = relationship("PayrollEmployee")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(40), index=True)
    customer_name: Mapped[str] = mapped_column(String(160), index=True)
    customer_email: Mapped[str] = mapped_column(String(120), default="")
    issue_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    tax_total: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    outstanding_balance: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(String(255), default="")
    sent_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("company_id", "invoice_number", name="uq_invoice_company_number"),)

    company = relationship("Company")
    customer = relationship("Customer")
    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("InvoicePayment", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    income_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id"), nullable=True)
    line_subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, default=0.0)

    invoice = relationship("Invoice", back_populates="lines")
    income_account = relationship("Account")
    inventory_item = relationship("InventoryItem")


class InvoicePayment(Base):
    __tablename__ = "invoice_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    reference: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company = relationship("Company")
    invoice = relationship("Invoice", back_populates="payments")


class RecurringInvoiceTemplate(Base):
    __tablename__ = "recurring_invoice_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    template_name: Mapped[str] = mapped_column(String(120), index=True)
    frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    next_run_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    notes: Mapped[str] = mapped_column(String(255), default="")
    lines_json: Mapped[str] = mapped_column(String(4000), default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company = relationship("Company")
    customer = relationship("Customer")


class PeriodLock(Base):
    __tablename__ = "period_locks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    locked_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("company_id", name="uq_period_lock_company"),)

    company = relationship("Company")


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True, default=1)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    reminder_type: Mapped[str] = mapped_column(String(30), default="overdue")
    sent_to: Mapped[str] = mapped_column(String(120), default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(20), default="queued")

    company = relationship("Company")
    invoice = relationship("Invoice")

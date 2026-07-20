from datetime import date, datetime

from pydantic import BaseModel


class AccountCreate(BaseModel):
    code: str
    name: str
    category: str
    vat_rate: float = 0.0


class RuleCreate(BaseModel):
    name: str
    keyword: str
    min_amount: float | None = None
    max_amount: float | None = None
    account_id: int
    priority: int = 100


class ImportResult(BaseModel):
    imported: int
    skipped_duplicates: int
    skipped_invalid_rows: int = 0
    errors: list[dict] = []


class AllocationResult(BaseModel):
    allocated: int
    unmatched: int


class PostingResult(BaseModel):
    posted: int
    skipped: int


class TrialBalanceLine(BaseModel):
    account_code: str
    account_name: str
    debit: float
    credit: float
    net: float


class JournalLineOut(BaseModel):
    account_code: str
    account_name: str
    debit: float
    credit: float


class JournalEntryOut(BaseModel):
    id: int
    entry_date: date
    memo: str
    source: str
    source_id: int
    lines: list[JournalLineOut]


class FixedAssetCreate(BaseModel):
    name: str
    asset_type: str = "General"
    purchase_date: date
    cost: float
    useful_life_years: int = 5
    salvage_value: float = 0.0
    asset_account_id: int
    depreciation_expense_account_id: int


class LoanCreate(BaseModel):
    lender_name: str
    principal: float
    annual_interest_rate: float = 0.0
    start_date: date
    term_months: int
    liability_account_id: int
    interest_expense_account_id: int


class LoanScheduleLine(BaseModel):
    month: int
    payment: float
    interest: float
    principal: float
    balance: float


class OpeningBalanceCreate(BaseModel):
    balance_date: date
    amount: float
    note: str = ""


class BankBalanceSummary(BaseModel):
    opening_balance_date: date | None
    opening_balance: float
    total_inflows: float
    total_outflows: float
    net_movement: float
    closing_balance: float
    opening_balance_missing: bool = False
    suggested_opening_balance_date: date | None = None
    warning: str | None = None


class TransactionAssignRequest(BaseModel):
    account_id: int
    create_rule: bool = False
    auto_rule: bool = True
    rule_name: str | None = None
    rule_keyword: str | None = None
    priority: int = 100


class BankTransactionCreate(BaseModel):
    txn_date: date
    description: str
    amount: float
    currency: str = "USD"
    reference: str = ""
    assigned_account_id: int | None = None


class BankTransactionUpdate(BaseModel):
    txn_date: date
    description: str
    amount: float
    currency: str = "USD"
    reference: str = ""
    assigned_account_id: int | None = None


class RuleKeywordAddRequest(BaseModel):
    keyword: str


class CompanyProfileUpdate(BaseModel):
    company_name: str
    address: str = ""
    email: str = ""
    phone: str = ""
    tax_number: str = ""
    currency: str = "USD"


class CompanyCreate(BaseModel):
    name: str


class CompanyOut(BaseModel):
    id: int
    name: str


class PayrollEmployeeCreate(BaseModel):
    employee_code: str
    full_name: str
    photo_url: str = ""
    id_number: str = ""
    tax_number: str = ""
    email: str = ""
    phone: str = ""
    position: str = ""
    hire_date: date | None = None
    bank_account: str = ""
    nssa_number: str = ""
    pension_number: str = ""
    default_gross_salary: float
    tax_rate: float = 0.0
    active: bool = True


class PayrollEmployeeOut(BaseModel):
    id: int
    employee_code: str
    full_name: str
    photo_url: str = ""
    id_number: str = ""
    tax_number: str = ""
    email: str = ""
    phone: str = ""
    position: str = ""
    hire_date: date | None = None
    bank_account: str = ""
    nssa_number: str = ""
    pension_number: str = ""
    default_gross_salary: float
    tax_rate: float
    active: bool


class PayrollEmployeeHistoryLine(BaseModel):
    payroll_run_id: int
    period_label: str
    pay_date: date
    status: str
    gross_pay: float
    tax_amount: float
    net_pay: float


class PayrollEmployeeDocumentOut(BaseModel):
    id: int
    employee_id: int
    doc_type: str
    title: str
    original_filename: str
    content_type: str
    file_size: int
    uploaded_at: datetime


class PayrollEmployeeDetailOut(BaseModel):
    employee: PayrollEmployeeOut
    payroll_history: list[PayrollEmployeeHistoryLine]
    documents: list[PayrollEmployeeDocumentOut]


class PayrollRunCreate(BaseModel):
    period_label: str
    pay_date: date
    expense_account_id: int
    payable_account_id: int
    tax_liability_account_id: int | None = None
    paye_rate: float | None = None
    nssa_rate: float = 0.0
    pension_rate: float = 0.0
    sdl_rate: float = 0.0
    other_deduction_per_employee: float = 0.0
    employee_ids: list[int] | None = None


class PayrollRunLineOut(BaseModel):
    id: int
    employee_id: int
    employee_code: str
    employee_name: str
    gross_pay: float
    tax_amount: float
    nssa_amount: float
    pension_amount: float
    other_deduction: float
    sdl_amount: float
    total_deductions: float
    net_pay: float


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str


class UserLogin(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str


class PayrollRunOut(BaseModel):
    id: int
    period_label: str
    pay_date: date
    status: str
    total_gross: float
    total_tax: float
    total_nssa: float
    total_pension: float
    total_other_deductions: float
    total_sdl: float
    total_net: float
    paye_rate: float
    nssa_rate: float
    pension_rate: float
    sdl_rate: float
    other_deduction_per_employee: float
    expense_account_id: int
    payable_account_id: int
    tax_liability_account_id: int | None = None
    journal_entry_id: int | None = None
    payment_entry_id: int | None = None
    paid_date: date | None = None
    line_count: int = 0


class PayrollPayRequest(BaseModel):
    bank_account_id: int
    payment_date: date


class PayrollTaxBracketIn(BaseModel):
    lower_limit: float
    upper_limit: float | None = None
    rate_percent: float
    order_index: int = 1


class PayrollTaxBracketOut(BaseModel):
    id: int
    lower_limit: float
    upper_limit: float | None = None
    rate_percent: float
    order_index: int


class PayrollTaxBracketsUpdate(BaseModel):
    brackets: list[PayrollTaxBracketIn]


class PayrollEmployeesBulkCreate(BaseModel):
    employees: list[PayrollEmployeeCreate]


class InvoiceLineCreate(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float = 0.0
    tax_rate: float = 0.0
    income_account_id: int | None = None
    inventory_item_id: int | None = None


class InvoiceCreate(BaseModel):
    invoice_number: str | None = None
    customer_id: int | None = None
    customer_name: str
    customer_email: str = ""
    issue_date: date
    due_date: date
    currency: str = "USD"
    notes: str = ""
    lines: list[InvoiceLineCreate]


class InvoiceLineOut(BaseModel):
    id: int
    description: str
    quantity: float
    unit_price: float
    tax_rate: float
    income_account_id: int | None = None
    inventory_item_id: int | None = None
    line_subtotal: float
    tax_amount: float
    line_total: float


class InvoiceOut(BaseModel):
    id: int
    invoice_number: str
    customer_name: str
    customer_email: str
    issue_date: date
    due_date: date
    status: str
    currency: str
    subtotal: float
    tax_total: float
    total: float
    outstanding_balance: float
    notes: str
    sent_date: date | None = None
    paid_date: date | None = None
    line_count: int = 0


class InvoiceDetailOut(InvoiceOut):
    lines: list[InvoiceLineOut]


class InvoiceMarkPaidRequest(BaseModel):
    paid_date: date | None = None


class CustomerCreate(BaseModel):
    customer_code: str
    name: str
    email: str = ""
    phone: str = ""
    address: str = ""
    tax_number: str = ""
    credit_limit: float = 0.0
    active: bool = True


class CustomerOut(BaseModel):
    id: int
    customer_code: str
    name: str
    email: str
    phone: str
    address: str
    tax_number: str
    credit_limit: float
    active: bool


class InventoryItemCreate(BaseModel):
    sku: str
    name: str
    description: str = ""
    unit_price: float = 0.0
    tax_rate: float = 0.0
    quantity_on_hand: float = 0.0
    min_stock_level: float = 0.0
    active: bool = True


class InventoryItemOut(BaseModel):
    id: int
    sku: str
    name: str
    description: str
    unit_price: float
    tax_rate: float
    quantity_on_hand: float
    min_stock_level: float
    active: bool


class InvoicePaymentCreate(BaseModel):
    payment_date: date
    amount: float
    reference: str = ""
    notes: str = ""


class InvoicePaymentOut(BaseModel):
    id: int
    invoice_id: int
    payment_date: date
    amount: float
    reference: str
    notes: str
    created_at: datetime


class AgingBucketLine(BaseModel):
    customer_name: str
    current: float
    days_1_30: float
    days_31_60: float
    days_61_90: float
    days_over_90: float
    total: float


class AgingSummary(BaseModel):
    as_of: date
    totals: AgingBucketLine
    by_customer: list[AgingBucketLine]


class RecurringInvoiceTemplateCreate(BaseModel):
    customer_id: int | None = None
    template_name: str
    frequency: str = "monthly"
    next_run_date: date
    currency: str = "USD"
    notes: str = ""
    lines: list[InvoiceLineCreate]
    active: bool = True


class RecurringInvoiceTemplateOut(BaseModel):
    id: int
    customer_id: int | None = None
    template_name: str
    frequency: str
    next_run_date: date
    currency: str
    notes: str
    lines: list[InvoiceLineCreate]
    active: bool


class PeriodLockUpdate(BaseModel):
    locked_until: date | None = None
    note: str = ""


class PeriodLockOut(BaseModel):
    locked_until: date | None = None
    note: str


class ReminderRunOut(BaseModel):
    queued: int
    reminders: list[dict]

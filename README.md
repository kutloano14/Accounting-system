# Accounting MVP (Sage-style starter)

This project is a practical MVP for automated bookkeeping.

## What it does

- Imports bank statements from CSV.
- Applies keyword-based allocation rules to map transactions to ledger accounts.
- Posts double-entry journal entries automatically.
- Generates bookkeeping outputs:
  - General Ledger
  - Trial Balance
  - Profit and Loss
  - Balance Sheet
  - Unmatched transaction list

## Tech stack

- FastAPI
- SQLAlchemy
- SQLite (local MVP database)

## Quick start

1. Create and activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run API:

```bash
uvicorn app.main:app --reload --app-dir accounting-mvp
```

If your terminal is already inside `accounting-mvp`, use:

```bash
uvicorn app.main:app --reload
```

4. Open docs:

- http://127.0.0.1:8000/docs

5. Open dashboard:

- http://127.0.0.1:8000/

## MVP workflow

1. `POST /setup/sample-chart` to seed a starter chart of accounts.
2. `POST /rules` to add allocation rules.
3. `POST /bank/import` with CSV file.
4. `POST /bookkeeping/allocate` to auto-categorize imported transactions.
5. `POST /bookkeeping/post` to generate journal entries.
6. View reports with:
   - `GET /reports/general-ledger`
   - `GET /reports/trial-balance`
   - `GET /reports/profit-loss`
   - `GET /reports/balance-sheet`
   - `GET /bookkeeping/documents`

You can also do the same process from the dashboard at `/`.

## CSV format

Use headers (lowercase preferred):

- `date` (YYYY-MM-DD)
- `description`
- `amount` (negative = outflow, positive = inflow)
- `reference` (optional)
- `currency` (optional)

Example:

```csv
date,description,amount,reference,currency
2026-03-01,Uber Trip,-24.50,TXN-1,USD
2026-03-02,Stripe Payout,500.00,TXN-2,USD
2026-03-03,Bank Fee,-10.00,TXN-3,USD
```

## Notes

- This is an MVP foundation, not a final production accounting engine.
- Add authentication, approvals, audit trails, VAT rules, and period locking before production use.

from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app


client = TestClient(app)


def test_invoice_creation_allows_customer_name_to_be_filled_from_customer_and_partial_payment_marks_partial():
    with SessionLocal() as db:
        company = db.query(models.Company).filter(models.Company.id == 1).first()
        if company is None:
            company = models.Company(id=1, name="Default Company")
            db.add(company)
            db.commit()
            db.refresh(company)

        customer = db.query(models.Customer).filter(models.Customer.company_id == 1, models.Customer.email == "customer@example.com").first()
        if customer is None:
            customer = models.Customer(
                company_id=1,
                customer_code="CUST-INV-001",
                name="Invoice Customer",
                email="customer@example.com",
                phone="",
                address="",
                tax_number="",
                credit_limit=0.0,
                active=True,
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)

    create_response = client.post(
        "/invoices?company_id=1",
        json={
            "customer_id": customer.id,
            "customer_name": "",
            "customer_email": "customer@example.com",
            "issue_date": "2026-08-10",
            "due_date": "2026-08-20",
            "currency": "USD",
            "notes": "",
            "lines": [
                {"description": "Consulting", "quantity": 1, "unit_price": 100, "tax_rate": 0, "income_account_id": None}
            ],
        },
    )

    assert create_response.status_code == 200, create_response.text
    invoice = create_response.json()
    assert invoice["customer_name"] == "Invoice Customer"
    assert invoice["status"] == "draft"
    assert invoice["outstanding_balance"] == 100.0

    partial_response = client.post(
        f"/invoices/{invoice['id']}/payments?company_id=1",
        json={
            "payment_date": "2026-08-15",
            "amount": 25.0,
            "reference": "partial",
            "notes": "first payment",
        },
    )

    assert partial_response.status_code == 200, partial_response.text
    payment = partial_response.json()
    assert payment["amount"] == 25.0

    detail_response = client.get(f"/invoices/{invoice['id']}?company_id=1")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["status"] == "partial"
    assert detail["outstanding_balance"] == 75.0

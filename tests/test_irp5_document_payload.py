from app.services.pdf_export import build_irp5_context


def test_build_irp5_context_includes_identity_and_bank_details():
    payload = build_irp5_context(
        run_data={"period_label": "Oct 2025"},
        employee_line={"employee_name": "Jane Doe", "gross_pay": 1000.0, "tax_amount": 100.0},
        company_profile={"company_name": "Acme Ltd", "address": "1 Main Road", "email": "payroll@acme.co", "phone": "0123456789", "tax_number": "1234567890"},
        employee_details={
            "full_name": "Jane Doe",
            "initials": "J",
            "surname": "Doe",
            "address": "10 River Street",
            "nationality": "South African",
            "bank_account": "1234567890",
            "bank_name": "First National Bank",
            "bank_branch": "Pretoria",
            "bank_account_type": "Cheque",
        },
    )

    assert payload["employer"]["company_name"] == "Acme Ltd"
    assert payload["employee"]["full_name"] == "Jane Doe"
    assert payload["employee"]["initials"] == "J"
    assert payload["employee"]["surname"] == "Doe"
    assert payload["employee"]["bank_account"] == "1234567890"
    assert payload["employee"]["nationality"] == "South African"
    assert payload["certificate"]["certificate_type"] == "IRP5"
    assert payload["coded_amounts"]["tax_withheld"][0]["code"] == "4102"
    assert payload["coded_amounts"]["income_received"][0]["code"] == "3601"
    assert payload["coded_amounts"]["deductions_contributions"][2]["code"] == "4497"

from app.schemas import PayrollEmployeeOut
from app.services.pdf_export import build_irp5_context


def test_payroll_employee_out_keeps_profile_fields_for_the_ui():
    payload = PayrollEmployeeOut.model_validate({
        "id": 7,
        "employee_code": "EMP-7",
        "full_name": "Jane Doe",
        "initials": "J",
        "surname": "Doe",
        "address": "10 River Street",
        "nationality": "South African",
        "date_of_birth": "1990-01-01",
        "photo_url": "https://example.com/jane.png",
        "id_number": "9001010001087",
        "tax_number": "1234567890",
        "email": "jane@example.com",
        "phone": "0123456789",
        "position": "Manager",
        "hire_date": "2020-03-01",
        "bank_account": "1234567890",
        "bank_name": "FNB",
        "bank_branch": "Pretoria",
        "bank_account_type": "Cheque",
        "nssa_number": "NSSA-1",
        "pension_number": "PEN-1",
        "medical_aid_number": "MED-1",
        "medical_aid_employee_amount": 100.0,
        "medical_aid_employer_amount": 150.0,
        "sick_fund_number": "SICK-1",
        "sick_fund_amount": 50.0,
        "provident_fund_number": "PROV-1",
        "provident_fund_employee_rate": 5.0,
        "provident_fund_employer_rate": 7.0,
        "other_deduction_name": "Laptop",
        "other_deduction_amount": 200.0,
        "default_gross_salary": 25000.0,
        "tax_rate": 18.0,
        "active": True,
    })

    assert payload.initials == "J"
    assert payload.surname == "Doe"
    assert payload.address == "10 River Street"
    assert payload.nationality == "South African"


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


def test_build_irp5_context_uses_financial_year_details_for_yearly_certificate():
    payload = build_irp5_context(
        run_data={"period_label": "Feb 2026", "financial_year_label": "2025/2026"},
        employee_line={"employee_name": "Jane Doe", "gross_pay": 20000.0, "tax_amount": 1200.0},
        company_profile={"company_name": "Acme Ltd"},
        employee_details={"full_name": "Jane Doe"},
    )

    assert payload["certificate"]["year_of_assessment"] == "2026"
    assert payload["certificate"]["period_of_reconciliation"] == "202602"

from types import SimpleNamespace

from app.main import _build_import_run_line_values


def test_import_run_line_preserves_imported_net_when_policy_applied():
    line = SimpleNamespace(
        tax_amount=120.0,
        admin_levy=20.0,
        uif_amount=10.0,
        provident_fund=50.0,
        medical_insurance=5.0,
        sick_pay=7.0,
        other_deduction=8.0,
        company_uif=12.0,
        company_admin_levy=9.0,
        company_medical_aid=6.0,
        company_sick_pay=4.0,
        company_provident_fund=40.0,
        total_company_contributions=80.0,
        total_deductions=150.0,
        net_pay=850.0,
    )

    result = _build_import_run_line_values(
        line,
        basic_pay=1000.0,
        gross_pay=1000.0,
        tax_amount=120.0,
        use_policy=True,
        policy_employee_rate=5.0,
        policy_employer_rate=3.0,
    )

    assert result["net_pay"] == 850.0
    assert result["pension_amount"] == 50.0
    assert result["company_provident_amount"] == 30.0
    assert result["gross_pay"] == 1000.0
    assert result["total_deductions"] == 150.0

from app import models
from app.main import _apply_provident_rates_to_employee


def test_apply_provident_rates_to_employee_uses_policy_when_empty():
    employee = models.PayrollEmployee(employee_code="EMP999", full_name="Jane Doe", active=True)
    policy = models.PayrollProvidentPolicy(employee_rate=7.5, employer_rate=8.5, locked=True)

    _apply_provident_rates_to_employee(employee, policy)

    assert employee.provident_fund_employee_rate == 7.5
    assert employee.provident_fund_employer_rate == 8.5


def test_apply_provident_rates_to_employee_preserves_existing_values():
    employee = models.PayrollEmployee(
        employee_code="EMP998",
        full_name="John Doe",
        provident_fund_employee_rate=4.0,
        provident_fund_employer_rate=5.0,
        active=True,
    )
    policy = models.PayrollProvidentPolicy(employee_rate=7.5, employer_rate=8.5, locked=True)

    _apply_provident_rates_to_employee(employee, policy)

    assert employee.provident_fund_employee_rate == 4.0
    assert employee.provident_fund_employer_rate == 5.0

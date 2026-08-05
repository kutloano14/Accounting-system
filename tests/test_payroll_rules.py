import unittest

from app.services.payroll_rules import build_payroll_components


class PayrollRulesTests(unittest.TestCase):
    def test_employee_and_employer_rules_are_calculated_and_net_is_reduced(self):
        result = build_payroll_components(
            gross=1000.0,
            tax_amount=100.0,
            nssa_amount=30.0,
            pension_amount=50.0,
            sdl_amount=10.0,
            other_deduction=5.0,
            rules=[
                {"name": "Medical Aid", "scope": "employee", "calculation_type": "percentage_of_gross", "value": 5.0, "active": True},
                {"name": "Pension Top-Up", "scope": "employer", "calculation_type": "fixed_amount", "value": 25.0, "active": True},
                {"name": "Union Fee", "scope": "both", "calculation_type": "percentage_of_net", "value": 2.0, "active": True},
            ],
        )

        self.assertEqual(result["employee_deductions_total"], 260.1)
        self.assertEqual(result["employer_contributions_total"], 40.1)
        self.assertEqual(result["net_pay"], 739.9)
        self.assertEqual(len(result["components"]), 3)

    def test_percentage_of_tax_rule_uses_tax_base(self):
        result = build_payroll_components(
            gross=800.0,
            tax_amount=80.0,
            nssa_amount=0.0,
            pension_amount=0.0,
            sdl_amount=0.0,
            other_deduction=0.0,
            rules=[
                {"name": "Tax Levy", "scope": "employee", "calculation_type": "percentage_of_tax", "value": 10.0, "active": True}
            ],
        )

        self.assertEqual(result["employee_deductions_total"], 88.0)
        self.assertEqual(result["net_pay"], 712.0)


if __name__ == "__main__":
    unittest.main()

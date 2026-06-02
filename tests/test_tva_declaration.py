from datetime import date
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'omega_tva')
class TestTvaDeclaration(TransactionCase):
    """Tests de la déclaration de TVA — helpers, contraintes, workflow."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Declaration = cls.env['account.tva.declaration']

    # ── Calcul automatique des dates selon le régime ──────────────────────
    def test_mensuel_dates_january(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '01',
        })
        self.assertEqual(decl.date_start, date(2025, 1, 1))
        self.assertEqual(decl.date_end, date(2025, 1, 31))

    def test_mensuel_dates_february_leap_year(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2024',
            'periode_mois': '02',
        })
        self.assertEqual(decl.date_start, date(2024, 2, 1))
        self.assertEqual(decl.date_end, date(2024, 2, 29))

    def test_mensuel_dates_february_non_leap(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '02',
        })
        self.assertEqual(decl.date_end, date(2025, 2, 28))

    def test_trimestriel_dates_q1(self):
        decl = self.Declaration.create({
            'tva_regime': 'trimestriel',
            'periode_annee': '2025',
            'periode_trimestre': '1',
        })
        self.assertEqual(decl.date_start, date(2025, 1, 1))
        self.assertEqual(decl.date_end, date(2025, 3, 31))

    def test_trimestriel_dates_q4(self):
        decl = self.Declaration.create({
            'tva_regime': 'trimestriel',
            'periode_annee': '2025',
            'periode_trimestre': '4',
        })
        self.assertEqual(decl.date_start, date(2025, 10, 1))
        self.assertEqual(decl.date_end, date(2025, 12, 31))

    # ── Nom calculé ───────────────────────────────────────────────────────
    def test_name_mensuel(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '03',
        })
        self.assertIn('Mars', decl.name)
        self.assertIn('2025', decl.name)

    def test_name_trimestriel(self):
        decl = self.Declaration.create({
            'tva_regime': 'trimestriel',
            'periode_annee': '2025',
            'periode_trimestre': '2',
        })
        self.assertIn('T2', decl.name)
        self.assertIn('2025', decl.name)

    # ── Workflow validation ───────────────────────────────────────────────
    def test_validate_changes_state(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '04',
        })
        decl.action_validate()
        self.assertEqual(decl.state, 'done')

    def test_back_to_draft(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '05',
        })
        decl.action_validate()
        decl.action_draft()
        self.assertEqual(decl.state, 'draft')

    # ── Garde-fous métier : chevauchement et recalcul ─────────────────────
    def test_overlap_validated_raises(self):
        d1 = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '06',
        })
        d1.action_validate()

        d2 = self.Declaration.create({
            'tva_regime': 'trimestriel',
            'periode_annee': '2025',
            'periode_trimestre': '2',  # avril-mai-juin → chevauche d1
        })
        with self.assertRaises(UserError):
            d2.action_validate()

    def test_recompute_blocked_on_validated(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '07',
        })
        decl.action_validate()
        with self.assertRaises(UserError):
            decl.action_compute_tva()

    def test_export_xml_blocked_on_draft(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '08',
        })
        with self.assertRaises(UserError):
            decl.action_export_simpl_tva()

    # ── Conversion devise société ─────────────────────────────────────────
    def test_convert_to_company_currency_same_currency(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '09',
        })
        result = decl._convert_to_company_currency(
            1000.0, self.company.currency_id, date(2025, 9, 1)
        )
        self.assertEqual(result, 1000.0)

    def test_convert_to_company_currency_no_currency(self):
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '10',
        })
        result = decl._convert_to_company_currency(-500.0, False, date(2025, 10, 1))
        self.assertEqual(result, 500.0)  # abs

    # ── Helper _expand_taxes ──────────────────────────────────────────────
    def test_expand_taxes_simple_percent(self):
        tax = self.env['account.tax'].create({
            'name': 'Test TVA 20%',
            'amount': 20.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
        })
        decl = self.Declaration.create({
            'tva_regime': 'mensuel',
            'periode_annee': '2025',
            'periode_mois': '11',
        })
        expanded = decl._expand_taxes(tax)
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0].amount, 20.0)

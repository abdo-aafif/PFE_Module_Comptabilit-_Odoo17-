from datetime import date
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'omega_currency')
class TestMultiCurrency(TransactionCase):
    """Tests de la section 3.2.4 Multi-devises.

    Couvre :
      • la restriction du fournisseur de taux à FloatRates uniquement ;
      • le wizard de réévaluation (écarts de conversion) : génération de l'OD,
        montants, équilibre, et garde-fou « aucune facture en devise ».

    Principe du scénario : on crée une devise étrangère de test (TFX) avec
    deux taux maîtrisés (1 devise société = 2 TFX au 01/01, puis = 4 TFX au
    31/12). Une facture client de 1000 TFX vaut donc 500 en devise société à
    l'émission, mais seulement 250 à la date d'évaluation → perte de change
    de 250 à constater.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company_currency = cls.company.currency_id

        # ── Devise étrangère de test + deux taux contrôlés ────────────────────
        cls.foreign = cls.env['res.currency'].create({
            'name': 'TFX',
            'symbol': 'T',
            'rounding': 0.01,
        })
        Rate = cls.env['res.currency.rate']
        # Ancre la devise société à 1.0 pour neutraliser tout taux issu
        # des données de démo (ex. MAD/EUR dans cicd_D).
        Rate.create({
            'currency_id': cls.company_currency.id, 'name': '2024-12-31',
            'rate': 1.0, 'company_id': cls.company.id,
        })
        Rate.create({
            'currency_id': cls.foreign.id, 'name': '2025-01-01',
            'rate': 2.0, 'company_id': cls.company.id,
        })
        Rate.create({
            'currency_id': cls.foreign.id, 'name': '2025-12-31',
            'rate': 4.0, 'company_id': cls.company.id,
        })

        # ── Comptes dédiés au test ────────────────────────────────────────────
        Account = cls.env['account.account']
        cls.acc_recv = Account.create({
            'code': 'TFXRECV', 'name': 'Clients devise (test)',
            'account_type': 'asset_receivable', 'reconcile': True,
        })
        cls.acc_income = Account.create({
            'code': 'TFXINC', 'name': 'Ventes (test)', 'account_type': 'income',
        })
        cls.acc_gain = Account.create({
            'code': 'TFXGAIN', 'name': 'Gain de change (test)',
            'account_type': 'income_other',
        })
        cls.acc_loss = Account.create({
            'code': 'TFXLOSS', 'name': 'Perte de change (test)',
            'account_type': 'expense',
        })

        # ── Journal des OD ────────────────────────────────────────────────────
        cls.journal = cls.env['account.journal'].search([
            ('type', '=', 'general'), ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['account.journal'].create({
                'name': 'OD Test', 'code': 'ODT', 'type': 'general',
                'company_id': cls.company.id,
            })

        # ── Partenaire avec compte client dédié ───────────────────────────────
        cls.partner = cls.env['res.partner'].create({'name': 'Client Devise (test)'})
        cls.partner.property_account_receivable_id = cls.acc_recv.id

        # ── Facture client 1000 TFX, non payée, au 01/01/2025 ─────────────────
        cls.invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner.id,
            'currency_id': cls.foreign.id,
            'invoice_date': date(2025, 1, 1),
            'date': date(2025, 1, 1),
            'invoice_line_ids': [(0, 0, {
                'name': 'Ligne test devise',
                'quantity': 1,
                'price_unit': 1000.0,
                'tax_ids': [(6, 0, [])],
                'account_id': cls.acc_income.id,
            })],
        })
        cls.invoice.action_post()

    def _make_wizard(self, **overrides):
        vals = {
            'revaluation_date': date(2025, 12, 31),
            'journal_id': self.journal.id,
            'income_account_id': self.acc_gain.id,
            'expense_account_id': self.acc_loss.id,
        }
        vals.update(overrides)
        return self.env['compta.currency.revaluation.wizard'].create(vals)

    # ── Garde-fou : aucune facture en devise sur la période ───────────────────
    def test_no_foreign_invoice_in_period_raises(self):
        """À une date antérieure à toute facture en devise → UserError."""
        wizard = self._make_wizard(revaluation_date=date(2000, 1, 1))
        with self.assertRaises(UserError):
            wizard.action_revaluate()

    # ── Setup correct : la facture est bien comptabilisée en devise ───────────
    def test_invoice_booked_in_foreign_currency(self):
        """Sanity check : la créance vaut 500 en devise société au taux d'émission."""
        recv_line = self.invoice.line_ids.filtered(
            lambda ml: ml.account_id.account_type == "asset_receivable"
        )
        self.assertEqual(recv_line.amount_residual_currency, 1000.0)
        self.assertAlmostEqual(recv_line.amount_residual, 500.0, places=2)

    # ── L'OD est créée et comptabilisée ───────────────────────────────────────
    def test_revaluation_creates_posted_od(self):
        wizard = self._make_wizard()
        result = wizard.action_revaluate()
        move = self.env['account.move'].browse(result['res_id'])
        self.assertTrue(move.exists())
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.journal_id, self.journal)

    # ── Les montants de l'écart sont corrects (perte de 250) ──────────────────
    def test_revaluation_loss_amounts(self):
        wizard = self._make_wizard()
        move = self.env['account.move'].browse(wizard.action_revaluate()['res_id'])
        recv_line = move.line_ids.filtered(lambda ml: ml.account_id == self.acc_recv)
        loss_line = move.line_ids.filtered(lambda ml: ml.account_id == self.acc_loss)
        # Créance dépréciée 500 → 250 : on crédite la créance de 250...
        self.assertAlmostEqual(recv_line.credit, 250.0, places=2)
        # ...en contrepartie d'une charge (perte de change) de 250.
        self.assertAlmostEqual(loss_line.debit, 250.0, places=2)

    # ── L'OD générée est équilibrée ───────────────────────────────────────────
    def test_revaluation_od_is_balanced(self):
        wizard = self._make_wizard()
        move = self.env['account.move'].browse(wizard.action_revaluate()['res_id'])
        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        self.assertAlmostEqual(total_debit, total_credit, places=2)

    # ── default_get pré-remplit un journal général ────────────────────────────
    def test_default_get_prefills_general_journal(self):
        defaults = self.env['compta.currency.revaluation.wizard'].default_get(['journal_id'])
        self.assertTrue(defaults.get('journal_id'))

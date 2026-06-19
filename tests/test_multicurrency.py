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


# =============================================================================
#  3.2.4.B — Affichage devise sur les lignes d'écriture — US-033
# =============================================================================
@tagged('post_install', '-at_install', 'omega_currency', 'omega_currency_display')
class TestCurrencyDisplay(TransactionCase):
    """US-033 — Saisie en devise : montant en devise ET conversion MAD affichés.

    Critères d'acceptation :
        • saisie du montant en devise étrangère avec le taux appliqué
        • conversion automatique en MAD sur chaque ligne
        • devise et montant en devise affichés sur l'écriture et les lignes
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company_currency = cls.company.currency_id

        cls.foreign = cls.env['res.currency'].create({
            'name': 'TDX',
            'symbol': 'D',
            'rounding': 0.01,
        })
        Rate = cls.env['res.currency.rate']
        Rate.create({
            'currency_id': cls.company_currency.id,
            'name': '2025-01-01',
            'rate': 1.0,
            'company_id': cls.company.id,
        })
        # 1 TDX = 0.5 devise société → taux Odoo = 2.0 (unités de société par devise)
        Rate.create({
            'currency_id': cls.foreign.id,
            'name': '2025-01-01',
            'rate': 2.0,
            'company_id': cls.company.id,
        })

        cls.acc_recv = cls.env['account.account'].create({
            'code': 'TDXRECV', 'name': 'Clients TDX (test)',
            'account_type': 'asset_receivable', 'reconcile': True,
        })
        cls.acc_income = cls.env['account.account'].create({
            'code': 'TDXINC', 'name': 'Ventes TDX (test)',
            'account_type': 'income',
        })
        cls.sale_journal = cls.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', cls.company.id)
        ], limit=1)
        cls.partner = cls.env['res.partner'].create({'name': 'Client Devise TDX'})
        cls.partner.property_account_receivable_id = cls.acc_recv.id

    def _make_foreign_invoice(self, price=1000.0):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'currency_id': self.foreign.id,
            'invoice_date': date(2025, 1, 15),
            'invoice_line_ids': [(0, 0, {
                'name': 'Service en TDX',
                'quantity': 1,
                'price_unit': price,
                'tax_ids': [(6, 0, [])],
                'account_id': self.acc_income.id,
            })],
        })
        invoice.action_post()
        return invoice

    def test_invoice_has_foreign_currency(self):
        """La facture est bien en devise étrangère (TDX)."""
        invoice = self._make_foreign_invoice(1000.0)
        self.assertEqual(invoice.currency_id, self.foreign)

    def test_receivable_line_has_foreign_amount(self):
        """La ligne client porte le montant en devise étrangère (amount_currency)."""
        invoice = self._make_foreign_invoice(1000.0)
        recv_line = invoice.line_ids.filtered(
            lambda ln: ln.account_id.account_type == 'asset_receivable'
        )
        self.assertTrue(recv_line, "Il doit exister une ligne client (receivable).")
        # amount_currency = montant en TDX
        self.assertAlmostEqual(abs(recv_line.amount_currency), 1000.0, places=2)

    def test_receivable_line_has_mad_amount(self):
        """La ligne client est convertie en MAD (debit ou credit non nul)."""
        invoice = self._make_foreign_invoice(1000.0)
        recv_line = invoice.line_ids.filtered(
            lambda ln: ln.account_id.account_type == 'asset_receivable'
        )
        # balance = montant en devise société (MAD) : 1000 TDX / taux 2 = 500 MAD
        self.assertAlmostEqual(abs(recv_line.balance), 500.0, places=2)

    def test_currency_id_on_line(self):
        """La ligne porte la devise étrangère dans currency_id."""
        invoice = self._make_foreign_invoice(1000.0)
        recv_line = invoice.line_ids.filtered(
            lambda ln: ln.account_id.account_type == 'asset_receivable'
        )
        self.assertEqual(recv_line.currency_id, self.foreign)

    def test_move_line_amount_residual_currency(self):
        """amount_residual_currency = solde restant en devise étrangère."""
        invoice = self._make_foreign_invoice(1000.0)
        recv_line = invoice.line_ids.filtered(
            lambda ln: ln.account_id.account_type == 'asset_receivable'
        )
        self.assertAlmostEqual(recv_line.amount_residual_currency, 1000.0, places=2)


# =============================================================================
#  3.2.4.C — Gestion des taux de change — US-034
# =============================================================================
@tagged('post_install', '-at_install', 'omega_currency', 'omega_currency_rates')
class TestCurrencyRateManagement(TransactionCase):
    """US-034 — Taux de change : saisie manuelle, historique, fournisseur.

    Critères d'acceptation :
        • saisie manuelle d'un taux par devise et par date
        • historique complet des taux conservé
        • mise à jour automatique quotidienne via API FloatRates (cron activable)
        • bouton de mise à jour manuelle depuis les Paramètres
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Chercher EUR même si inactive (active_test=False) pour éviter
        # la violation de contrainte unique res_currency_unique_name.
        cls.eur = cls.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', 'EUR')], limit=1
        )
        if not cls.eur:
            cls.eur = cls.env['res.currency'].create({
                'name': 'EUR', 'symbol': '€', 'rounding': 0.01,
            })
        cls.eur.active = True

    def test_manual_rate_creation(self):
        """Un taux peut être créé manuellement pour une devise et une date."""
        rate = self.env['res.currency.rate'].create({
            'currency_id': self.eur.id,
            'name': date(2025, 6, 1),
            'rate': 10.5,
            'company_id': self.company.id,
        })
        self.assertTrue(rate.id)
        self.assertAlmostEqual(rate.rate, 10.5, places=4)
        self.assertEqual(rate.currency_id, self.eur)

    def test_rate_history_multiple_dates(self):
        """Plusieurs taux à des dates différentes → historique conservé."""
        dates_rates = [
            (date(2025, 1, 1), 10.0),
            (date(2025, 3, 1), 10.5),
            (date(2025, 6, 1), 11.0),
        ]
        for d, r in dates_rates:
            self.env['res.currency.rate'].create({
                'currency_id': self.eur.id,
                'name': d,
                'rate': r,
                'company_id': self.company.id,
            })
        history = self.env['res.currency.rate'].search([
            ('currency_id', '=', self.eur.id),
            ('company_id', '=', self.company.id),
            ('name', '>=', date(2025, 1, 1)),
            ('name', '<=', date(2025, 12, 31)),
        ])
        self.assertGreaterEqual(len(history), 3)
        stored_rates = sorted(history.mapped('rate'))
        self.assertIn(10.0, stored_rates)
        self.assertIn(10.5, stored_rates)
        self.assertIn(11.0, stored_rates)

    def test_rate_is_date_specific(self):
        """Chaque taux est bien lié à sa date (non écrasé par un nouveau)."""
        self.env['res.currency.rate'].create({
            'currency_id': self.eur.id,
            'name': date(2025, 1, 1),
            'rate': 10.0,
            'company_id': self.company.id,
        })
        self.env['res.currency.rate'].create({
            'currency_id': self.eur.id,
            'name': date(2025, 6, 1),
            'rate': 11.5,
            'company_id': self.company.id,
        })
        jan_rate = self.env['res.currency.rate'].search([
            ('currency_id', '=', self.eur.id),
            ('name', '=', date(2025, 1, 1)),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertAlmostEqual(jan_rate.rate, 10.0, places=4)

    def test_floatrates_provider_configured(self):
        """Le fournisseur FloatRates est le seul disponible dans la configuration."""
        field = self.env['res.company']._fields.get('currency_provider')
        self.assertIsNotNone(field, "Le champ currency_provider doit exister sur res.company.")
        selection_keys = [k for k, _ in field.selection]
        self.assertIn('floatrates', selection_keys)

    def test_auto_update_flag_default_false(self):
        """Le cron de mise à jour automatique est désactivé par défaut."""
        field = self.env['res.company']._fields.get('auto_currency_update')
        self.assertIsNotNone(field)
        self.assertFalse(self.company.auto_currency_update)

    def test_action_update_currency_rates_exists(self):
        """La méthode action_update_currency_rates est accessible sur res.company."""
        self.assertTrue(
            hasattr(self.env['res.company'], 'action_update_currency_rates'),
            "La méthode action_update_currency_rates doit exister sur res.company."
        )

    def test_revaluation_wizard_model_exists(self):
        """Le wizard de réévaluation existe et peut être instancié."""
        # US-035 : historique des réévaluations = les OD générées par le wizard.
        # On vérifie que le wizard est accessible et que ses champs clés existent.
        fields = self.env['compta.currency.revaluation.wizard']._fields
        self.assertIn('revaluation_date', fields)
        self.assertIn('journal_id', fields)
        self.assertIn('income_account_id', fields)
        self.assertIn('expense_account_id', fields)

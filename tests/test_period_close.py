# -*- coding: utf-8 -*-
"""Suite de tests fonctionnels — section 3.2.3 du CDC : Clôture Comptable.

Couverture :
    * Processus de clôture mensuelle / annuelle
    * Verrouillage des périodes (period_lock_date / fiscalyear_lock_date)
    * Génération automatique des à-nouveaux (PCGE marocain)
    * Contrôles de cohérence pré-clôture (balance, drafts, dotations)
"""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


# =============================================================================
#  Base partagée : comptes PCGE de test, journal, helpers
# =============================================================================
class _PeriodCloseCommon(TransactionCase):
    """Setup partagé : comptes PCGE marocains de test + journal + helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Close = cls.env["account.period.close"]
        cls.Wizard = cls.env["period.close.wizard"]
        cls.Move = cls.env["account.move"]

        Account = cls.env["account.account"]
        cls.account_bank = Account.create(
            {
                "code": "T5141",
                "name": "Test Banque",
                "account_type": "asset_cash",
                "reconcile": True,
                "company_id": cls.company.id,
            }
        )
        cls.account_income = Account.create(
            {
                "code": "T7111",
                "name": "Test Ventes",
                "account_type": "income",
                "company_id": cls.company.id,
            }
        )
        cls.account_expense = Account.create(
            {
                "code": "T6111",
                "name": "Test Achats",
                "account_type": "expense",
                "company_id": cls.company.id,
            }
        )
        # Comptes résultat PCGE — codes commencent par '1' pour passer
        # dans la branche "report à nouveau" du wizard.
        cls.account_benefit = Account.create(
            {
                "code": "T11910",
                "name": "Test Résultat net bénéfice",
                "account_type": "equity",
                "company_id": cls.company.id,
            }
        )
        cls.account_loss = Account.create(
            {
                "code": "T11990",
                "name": "Test Résultat net perte",
                "account_type": "equity",
                "company_id": cls.company.id,
            }
        )

        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)],
            limit=1,
        )

    def setUp(self):
        super().setUp()
        # Reset les verrous pour démarrer chaque test sur un état propre.
        self.company.sudo().write(
            {
                "period_lock_date": False,
                "fiscalyear_lock_date": False,
            }
        )

    # ── Helpers ──────────────────────────────────────────────────────────
    def _make_close(self, **overrides):
        """Crée directement un enregistrement historique (sans passer par le wizard)."""
        vals = {
            "close_type": "monthly",
            "date_from": date(2025, 1, 1),
            "date_to": date(2025, 1, 31),
            "date_close": date(2025, 2, 1),
        }
        vals.update(overrides)
        return self.Close.create(vals)

    def _make_move(self, mdate, debit_account, credit_account, amount, post=True, ref="Test"):
        """Crée une écriture équilibrée et la poste (par défaut)."""
        move = self.Move.create(
            {
                "journal_id": self.journal.id,
                "date": mdate,
                "ref": ref,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "account_id": debit_account.id,
                            "name": ref,
                            "debit": amount,
                            "credit": 0.0,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "account_id": credit_account.id,
                            "name": ref,
                            "debit": 0.0,
                            "credit": amount,
                        },
                    ),
                ],
            }
        )
        if post:
            move.action_post()
        return move

    def _make_revenue(self, mdate, amount, post=True):
        """Encaissement : débit banque / crédit produit."""
        return self._make_move(mdate, self.account_bank, self.account_income, amount, post=post, ref="Vente")

    def _make_expense(self, mdate, amount, post=True):
        """Charge payée : débit charge / crédit banque."""
        return self._make_move(mdate, self.account_expense, self.account_bank, amount, post=post, ref="Achat")

    def _make_wizard(self, **vals):
        """Instancie le wizard avec les comptes de test."""
        defaults = {
            "company_id": self.company.id,
            "close_type": "monthly",
            "date_from": date(2025, 1, 1),
            "date_to": date(2025, 1, 31),
            "opening_journal_id": self.journal.id,
            "account_result_id": self.account_benefit.id,
            "account_result_loss_id": self.account_loss.id,
            "generate_opening": True,
        }
        defaults.update(vals)
        return self.Wizard.create(defaults)

    def _run_close(self, **wizard_overrides):
        """Wizard → checks → close. Retourne le record account.period.close créé."""
        wiz = self._make_wizard(**wizard_overrides)
        wiz.action_run_checks()
        action = wiz.action_close_period()
        return self.Close.browse(action["res_id"])


# =============================================================================
#  3.2.3.A — Modèle account.period.close : CRUD + permissions
# =============================================================================
@tagged("post_install", "-at_install", "omega_close", "omega_close_crud")
class TestPeriodCloseCRUD(_PeriodCloseCommon):
    """Tests historiques : création, séquence, suppression, contraintes, accès."""

    def test_initial_state_is_draft(self):
        rec = self._make_close()
        self.assertEqual(rec.state, "draft")

    def test_sequence_name_assigned(self):
        rec = self._make_close()
        self.assertNotEqual(rec.name, "/")
        self.assertTrue(rec.name)

    def test_cannot_delete_done_closure(self):
        rec = self._make_close()
        rec.state = "done"
        with self.assertRaises(UserError):
            rec.unlink()

    def test_can_delete_draft_closure(self):
        rec = self._make_close()
        rec.unlink()  # ne doit pas lever

    def test_unique_done_closure_constraint(self):
        rec1 = self._make_close(close_type="monthly")
        rec1.state = "done"
        rec2 = self._make_close(close_type="monthly")
        with self.assertRaises(ValidationError):
            rec2.state = "done"

    def test_view_opening_move_requires_one(self):
        rec = self._make_close()
        with self.assertRaises(UserError):
            rec.action_view_opening_move()

    def test_unlock_requires_manager_group(self):
        """Seul un Account Manager peut déverrouiller."""
        user = self.env["res.users"].create(
            {
                "name": "Comptable test",
                "login": "comptable_test_unlock",
                "email": "test_unlock@test.local",
                "groups_id": [(6, 0, [self.env.ref("account.group_account_user").id])],
            }
        )
        rec = self._make_close()
        rec.state = "done"
        rec.note = "Motif test"
        with self.assertRaises(UserError):
            rec.with_user(user).action_unlock()

    def test_unlock_requires_state_done(self):
        rec = self._make_close()
        manager = self.env.ref("base.user_admin")
        with self.assertRaises(UserError):
            rec.with_user(manager).action_unlock()

    def test_unlock_requires_reason(self):
        rec = self._make_close()
        rec.state = "done"
        rec.note = "   "
        manager = self.env.ref("base.user_admin")
        with self.assertRaises(UserError):
            rec.with_user(manager).action_unlock()


# =============================================================================
#  3.2.3.B — Contrôles de cohérence pré-clôture
# =============================================================================
@tagged("post_install", "-at_install", "omega_close", "omega_close_checks")
class TestPreCloseChecks(_PeriodCloseCommon):
    """Tests de ``action_run_checks`` : balance, drafts, dotations, bancaire."""

    def test_run_checks_sets_checks_done_flag(self):
        wiz = self._make_wizard()
        wiz.action_run_checks()
        self.assertTrue(wiz.checks_done)

    def test_balance_check_ok_when_period_empty(self):
        """Aucune écriture dans la période ⇒ balance = 0 = équilibrée."""
        wiz = self._make_wizard()
        wiz.action_run_checks()
        self.assertTrue(wiz.check_balance)

    def test_balance_check_ok_with_balanced_moves(self):
        """Écritures équilibrées ⇒ check_balance = True."""
        self._make_revenue(date(2025, 1, 15), 5000.0)
        self._make_expense(date(2025, 1, 20), 2000.0)
        wiz = self._make_wizard()
        wiz.action_run_checks()
        self.assertTrue(wiz.check_balance)

    def test_draft_move_detected(self):
        """Écriture brouillon dans la période ⇒ check_no_draft = False."""
        self._make_revenue(date(2025, 1, 10), 1000.0, post=False)
        wiz = self._make_wizard()
        wiz.action_run_checks()
        self.assertFalse(wiz.check_no_draft)
        self.assertEqual(len(wiz.draft_move_ids), 1)

    def test_no_draft_when_all_posted(self):
        self._make_revenue(date(2025, 1, 10), 1000.0, post=True)
        wiz = self._make_wizard()
        wiz.action_run_checks()
        self.assertTrue(wiz.check_no_draft)

    def test_draft_outside_period_ignored(self):
        """Brouillon hors période ⇒ ne déclenche pas la détection."""
        self._make_revenue(date(2025, 3, 15), 1000.0, post=False)  # hors janvier
        wiz = self._make_wizard()  # janvier
        wiz.action_run_checks()
        self.assertTrue(wiz.check_no_draft)

    def test_run_checks_requires_dates(self):
        wiz = self._make_wizard()
        wiz.date_from = False
        with self.assertRaises(UserError):
            wiz.action_run_checks()

    def test_run_checks_dates_inverted_raises(self):
        wiz = self._make_wizard(
            date_from=date(2025, 1, 31),
            date_to=date(2025, 1, 1),
        )
        with self.assertRaises(UserError):
            wiz.action_run_checks()

    def test_all_checks_ok_aggregates_flags(self):
        """all_checks_ok = True quand tous les flags sont True."""
        wiz = self._make_wizard()
        wiz.action_run_checks()
        # Période vide → toutes les vérifs passent
        self.assertTrue(wiz.all_checks_ok)


# =============================================================================
#  3.2.3.C — Verrouillage des périodes
# =============================================================================
@tagged("post_install", "-at_install", "omega_close", "omega_close_lock")
class TestPeriodLocking(_PeriodCloseCommon):
    """Tests de la pose et levée des verrous mensuels / annuels."""

    def test_monthly_close_sets_period_lock(self):
        """Clôture mensuelle ⇒ company.period_lock_date = date_to."""
        self._run_close(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        self.assertEqual(self.company.period_lock_date, date(2025, 1, 31))

    def test_monthly_close_does_not_set_fiscalyear_lock(self):
        """Clôture mensuelle ⇒ verrou exercice fiscal reste vide."""
        self._run_close(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        self.assertFalse(self.company.fiscalyear_lock_date)

    def test_annual_close_sets_both_locks(self):
        """Clôture annuelle ⇒ pose les 2 verrous (période + exercice fiscal)."""
        self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        self.assertEqual(self.company.period_lock_date, date(2025, 12, 31))
        self.assertEqual(self.company.fiscalyear_lock_date, date(2025, 12, 31))

    def test_lock_date_never_regresses(self):
        """Clôturer une période antérieure ne doit pas reculer le verrou existant."""
        # 1) Clôture mars 2026 — pose un verrou au 31/03/2026
        self._run_close(close_type="monthly", date_from=date(2026, 3, 1), date_to=date(2026, 3, 31))
        self.assertEqual(self.company.period_lock_date, date(2026, 3, 31))
        # 2) Clôture janvier 2026 (antérieure) — le verrou doit RESTER au 31/03/2026
        self._run_close(close_type="monthly", date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
        self.assertEqual(self.company.period_lock_date, date(2026, 3, 31))

    def test_unlock_clears_matching_lock(self):
        """``action_unlock`` enlève le verrou s'il correspond à la clôture."""
        close = self._run_close(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        self.assertEqual(self.company.period_lock_date, date(2025, 1, 31))
        close.note = "Erreur de saisie à corriger"
        close.action_unlock()
        self.assertEqual(close.state, "cancelled")
        self.assertFalse(self.company.period_lock_date)

    def test_unlock_keeps_unrelated_lock(self):
        """``action_unlock`` ne touche pas un verrou non lié à cette clôture."""
        close = self._run_close(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        # Quelqu'un (manuellement) pose un verrou plus récent
        self.company.sudo().write({"period_lock_date": date(2026, 6, 30)})
        close.note = "Annulation"
        close.action_unlock()
        # Le verrou plus récent doit rester intact
        self.assertEqual(self.company.period_lock_date, date(2026, 6, 30))

    def test_close_record_stores_lock_dates(self):
        """L'enregistrement de clôture conserve les verrous appliqués."""
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        self.assertEqual(close.period_lock_date, date(2025, 12, 31))
        self.assertEqual(close.fiscalyear_lock_date, date(2025, 12, 31))


# =============================================================================
#  3.2.3.D — Génération automatique des à-nouveaux
# =============================================================================
@tagged("post_install", "-at_install", "omega_close", "omega_close_opening")
class TestOpeningEntries(_PeriodCloseCommon):
    """Tests de ``_generate_opening_entries`` : balance, résultat, comptabilisation."""

    def test_annual_close_creates_opening_move(self):
        """Clôture annuelle avec generate_opening=True ⇒ écriture à-nouveaux créée."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        self.assertTrue(close.opening_move_id)

    def test_monthly_close_does_not_create_opening_move(self):
        """Clôture mensuelle ⇒ pas d'à-nouveaux (réservé annuel)."""
        self._make_revenue(date(2025, 1, 15), 1000.0)
        close = self._run_close(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        self.assertFalse(close.opening_move_id)

    def test_opening_move_date_is_next_day(self):
        """La date de l'écriture à-nouveaux = lendemain de date_to."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        self.assertEqual(close.opening_move_id.date, date(2026, 1, 1))

    def test_opening_move_is_balanced(self):
        """L'écriture à-nouveaux est équilibrée (débit = crédit)."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        self._make_expense(date(2025, 7, 10), 4000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        move = close.opening_move_id
        total_debit = sum(move.line_ids.mapped("debit"))
        total_credit = sum(move.line_ids.mapped("credit"))
        self.assertAlmostEqual(total_debit, total_credit, places=2)

    def test_opening_move_state_draft(self):
        """L'écriture à-nouveaux est laissée en brouillon pour révision."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        self.assertEqual(close.opening_move_id.state, "draft")

    def test_opening_uses_selected_journal(self):
        """L'écriture utilise le journal choisi dans le wizard."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        self.assertEqual(close.opening_move_id.journal_id, self.journal)

    def test_benefit_credits_result_account(self):
        """Produits > Charges ⇒ bénéfice ⇒ crédit du compte résultat bénéfice."""
        self._make_revenue(date(2025, 6, 15), 10000.0)  # +10 000 produit
        self._make_expense(date(2025, 7, 10), 3000.0)  # +3 000 charge
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        result_lines = close.opening_move_id.line_ids.filtered(lambda ln: ln.account_id == self.account_benefit)
        self.assertEqual(len(result_lines), 1)
        # Bénéfice = 10 000 - 3 000 = 7 000 → crédit 119100
        self.assertAlmostEqual(result_lines.credit, 7000.0, places=2)
        self.assertAlmostEqual(result_lines.debit, 0.0, places=2)

    def test_loss_debits_result_loss_account(self):
        """Charges > Produits ⇒ perte ⇒ débit du compte résultat perte."""
        self._make_revenue(date(2025, 6, 15), 2000.0)  # +2 000 produit
        self._make_expense(date(2025, 7, 10), 5000.0)  # +5 000 charge
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        result_lines = close.opening_move_id.line_ids.filtered(lambda ln: ln.account_id == self.account_loss)
        self.assertEqual(len(result_lines), 1)
        # Perte = 5 000 - 2 000 = 3 000 → débit 119900
        self.assertAlmostEqual(result_lines.debit, 3000.0, places=2)
        self.assertAlmostEqual(result_lines.credit, 0.0, places=2)

    def test_balance_sheet_accounts_carried_forward(self):
        """Comptes de bilan (banque, etc.) sont reportés sur l'écriture à-nouveaux."""
        self._make_revenue(date(2025, 6, 15), 8000.0)  # banque +8 000
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        bank_lines = close.opening_move_id.line_ids.filtered(lambda ln: ln.account_id == self.account_bank)
        self.assertEqual(len(bank_lines), 1)
        # Banque débitrice de 8 000 → reportée en débit
        self.assertAlmostEqual(bank_lines.debit, 8000.0, places=2)

    def test_income_expense_accounts_not_carried(self):
        """Comptes 6 / 7 ne sont pas reportés individuellement, seulement via résultat."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        income_lines = close.opening_move_id.line_ids.filtered(lambda ln: ln.account_id == self.account_income)
        self.assertFalse(income_lines, "Le compte produit ne doit pas être reporté.")

    def test_post_opening_move(self):
        """``action_post_opening_move`` valide l'écriture à-nouveaux brouillon."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        self.assertEqual(close.opening_move_id.state, "draft")
        close.action_post_opening_move()
        self.assertEqual(close.opening_move_id.state, "posted")

    def test_post_opening_move_twice_raises(self):
        """Tentative de re-comptabiliser un à-nouveaux déjà posté ⇒ UserError."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        close.action_post_opening_move()
        with self.assertRaises(UserError):
            close.action_post_opening_move()

    def test_cancel_opening_move(self):
        """``action_cancel_opening_move`` supprime l'écriture (état brouillon)."""
        self._make_revenue(date(2025, 6, 15), 10000.0)
        close = self._run_close(close_type="annual", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31))
        self.assertTrue(close.opening_move_id)
        close.action_cancel_opening_move()
        self.assertFalse(close.opening_move_id)


# =============================================================================
#  3.2.3.E — Workflow de clôture (intégration)
# =============================================================================
@tagged("post_install", "-at_install", "omega_close", "omega_close_workflow")
class TestCloseWorkflow(_PeriodCloseCommon):
    """Tests d'intégration : enchaînement complet checks → close → history."""

    def test_close_blocked_without_checks(self):
        """Clôturer sans avoir lancé les contrôles ⇒ UserError."""
        wiz = self._make_wizard()
        with self.assertRaises(UserError):
            wiz.action_close_period()

    def test_close_blocked_if_drafts_in_period(self):
        """Brouillon dans la période bloque la clôture."""
        self._make_revenue(date(2025, 1, 10), 1000.0, post=False)
        wiz = self._make_wizard()
        wiz.action_run_checks()
        with self.assertRaises(UserError):
            wiz.action_close_period()

    def test_close_creates_history_record(self):
        """Une clôture réussie crée un enregistrement ``account.period.close`` 'done'."""
        close = self._run_close(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        self.assertTrue(close)
        self.assertEqual(close.state, "done")
        self.assertEqual(close.close_type, "monthly")
        self.assertEqual(close.date_from, date(2025, 1, 1))
        self.assertEqual(close.date_to, date(2025, 1, 31))

    def test_close_record_stores_check_results(self):
        """Les flags de contrôles sont stockés sur l'enregistrement historique."""
        close = self._run_close(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        self.assertTrue(close.check_balance)
        self.assertTrue(close.check_no_draft)
        self.assertTrue(close.check_depreciation)

    def test_double_close_same_period_blocked(self):
        """Re-clôturer la même période ⇒ UserError (déjà clôturée)."""
        self._run_close(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        # 2ᵉ tentative sur la même période
        wiz2 = self._make_wizard(close_type="monthly", date_from=date(2025, 1, 1), date_to=date(2025, 1, 31))
        wiz2.action_run_checks()
        with self.assertRaises(UserError):
            wiz2.action_close_period()

    def test_consecutive_monthly_closes(self):
        """Clôtures successives janvier puis février ⇒ verrou avance."""
        self._run_close(close_type="monthly", date_from=date(2027, 1, 1), date_to=date(2027, 1, 31))
        self.assertEqual(self.company.period_lock_date, date(2027, 1, 31))
        self._run_close(close_type="monthly", date_from=date(2027, 2, 1), date_to=date(2027, 2, 28))
        self.assertEqual(self.company.period_lock_date, date(2027, 2, 28))

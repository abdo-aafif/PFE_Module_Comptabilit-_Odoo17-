# -*- coding: utf-8 -*-
"""Suite de tests fonctionnels — section 3.1.2 du CDC : Écritures Comptables.

Couverture :
    * Saisie manuelle des écritures (journal entries)
    * Écritures automatiques depuis factures clients/fournisseurs
    * Lettrage des comptes (réconciliation)
    * Contre-passation d'écritures
    * Écritures récurrentes (abonnements, loyers)
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


class _ComptaTestCommon(TransactionCase):
    """Setup partagé : journal général + comptes charge / passif courant."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env["account.journal"].search(
            [
                ("type", "=", "general"),
                ("company_id", "=", cls.company.id),
            ],
            limit=1,
        )
        cls.account_a = cls.env["account.account"].search(
            [
                ("account_type", "=", "expense"),
                ("company_id", "=", cls.company.id),
            ],
            limit=1,
        )
        cls.account_b = cls.env["account.account"].search(
            [
                ("account_type", "=", "liability_current"),
                ("company_id", "=", cls.company.id),
            ],
            limit=1,
        )

    def _make_entry(self, amount=1000.0, post=False, **overrides):
        """Crée une écriture équilibrée débit account_a / crédit account_b."""
        vals = {
            "move_type": "entry",
            "journal_id": self.journal.id,
            "date": date(2025, 1, 1),
            "ref": "OD test",
            "line_ids": [
                (
                    0,
                    0,
                    {
                        "account_id": self.account_a.id,
                        "name": "Test",
                        "debit": amount,
                        "credit": 0.0,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "account_id": self.account_b.id,
                        "name": "Test",
                        "debit": 0.0,
                        "credit": amount,
                    },
                ),
            ],
        }
        vals.update(overrides)
        move = self.env["account.move"].create(vals)
        if post:
            move.action_post()
        return move


# =============================================================================
#  3.1.2.A — Saisie manuelle des écritures (OD)
# =============================================================================
@tagged("post_install", "-at_install", "omega_compta", "omega_manual_entry")
class TestManualJournalEntry(_ComptaTestCommon):
    """Saisie manuelle d'écritures (Opérations Diverses)."""

    def test_manual_entry_created_in_draft(self):
        move = self._make_entry()
        self.assertEqual(move.move_type, "entry")
        self.assertEqual(move.state, "draft")

    def test_manual_entry_is_balanced(self):
        move = self._make_entry(amount=1500.0)
        total_debit = sum(move.line_ids.mapped("debit"))
        total_credit = sum(move.line_ids.mapped("credit"))
        self.assertAlmostEqual(total_debit, total_credit)
        self.assertAlmostEqual(total_debit, 1500.0)

    def test_manual_entry_can_be_posted(self):
        move = self._make_entry(post=True)
        self.assertEqual(move.state, "posted")

    def test_unbalanced_entry_is_rejected(self):
        """Garde-fou comptable : Odoo rejette toute écriture déséquilibrée dès la création."""
        with self.assertRaises(UserError):
            self.env["account.move"].create(
                {
                    "move_type": "entry",
                    "journal_id": self.journal.id,
                    "date": date(2025, 1, 1),
                    "ref": "OD déséquilibrée",
                    "line_ids": [
                        (0, 0, {"account_id": self.account_a.id, "name": "X", "debit": 1000.0}),
                        (0, 0, {"account_id": self.account_b.id, "name": "X", "credit": 900.0}),
                    ],
                }
            )


# =============================================================================
#  3.1.2.B — Écritures automatiques depuis factures clients / fournisseurs
# =============================================================================
@tagged("post_install", "-at_install", "omega_compta", "omega_invoice_auto")
class TestInvoiceAutoEntries(_ComptaTestCommon):
    """Validation d'une facture ⇒ création automatique de l'écriture comptable."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Partenaire Test"})
        cls.sale_journal = cls.env["account.journal"].search(
            [
                ("type", "=", "sale"),
                ("company_id", "=", cls.company.id),
            ],
            limit=1,
        )
        cls.purchase_journal = cls.env["account.journal"].search(
            [
                ("type", "=", "purchase"),
                ("company_id", "=", cls.company.id),
            ],
            limit=1,
        )
        cls.income_account = cls.env["account.account"].search(
            [
                ("account_type", "=", "income"),
                ("company_id", "=", cls.company.id),
            ],
            limit=1,
        )
        cls.expense_account = cls.env["account.account"].search(
            [
                ("account_type", "=", "expense"),
                ("company_id", "=", cls.company.id),
            ],
            limit=1,
        )

    def test_customer_invoice_generates_balanced_entry(self):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "journal_id": self.sale_journal.id,
                "invoice_date": date(2025, 1, 1),
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Prestation",
                            "quantity": 1,
                            "price_unit": 1000.0,
                            "account_id": self.income_account.id,
                            "tax_ids": [(5, 0, 0)],  # désactive les taxes par défaut
                        },
                    )
                ],
            }
        )
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")
        self.assertAlmostEqual(sum(invoice.line_ids.mapped("balance")), 0.0)

    def test_customer_invoice_creates_receivable_line(self):
        """La facture client crée une ligne sur un compte client (receivable)."""
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "journal_id": self.sale_journal.id,
                "invoice_date": date(2025, 1, 1),
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Prestation",
                            "quantity": 1,
                            "price_unit": 1000.0,
                            "account_id": self.income_account.id,
                            "tax_ids": [(5, 0, 0)],
                        },
                    )
                ],
            }
        )
        invoice.action_post()
        receivable = invoice.line_ids.filtered(lambda line: line.account_id.account_type == "asset_receivable")
        self.assertEqual(len(receivable), 1)
        self.assertAlmostEqual(receivable.debit, 1000.0)

    def test_vendor_bill_creates_payable_line(self):
        """La facture fournisseur crée une ligne sur un compte fournisseur (payable)."""
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner.id,
                "journal_id": self.purchase_journal.id,
                "invoice_date": date(2025, 1, 1),
                "ref": "BILL-TEST-001",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Achat",
                            "quantity": 1,
                            "price_unit": 800.0,
                            "account_id": self.expense_account.id,
                            "tax_ids": [(5, 0, 0)],
                        },
                    )
                ],
            }
        )
        bill.action_post()
        payable = bill.line_ids.filtered(lambda line: line.account_id.account_type == "liability_payable")
        self.assertEqual(len(payable), 1)
        self.assertAlmostEqual(payable.credit, 800.0)


# =============================================================================
#  3.1.2.C — Lettrage des comptes (réconciliation)
# =============================================================================
@tagged("post_install", "-at_install", "omega_compta", "omega_lettrage")
class TestReconciliation(_ComptaTestCommon):
    """Lettrage de lignes sur un compte réconciliable."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.receivable = cls.env["account.account"].search(
            [
                ("account_type", "=", "asset_receivable"),
                ("company_id", "=", cls.company.id),
                ("reconcile", "=", True),
            ],
            limit=1,
        )

    def _make_pair(self, amount=1000.0):
        """Crée et poste 2 écritures opposées sur le compte réconciliable."""
        invoice_move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.journal.id,
                "date": date(2025, 1, 1),
                "ref": "Facture simulée",
                "line_ids": [
                    (0, 0, {"account_id": self.receivable.id, "name": "F", "debit": amount, "credit": 0.0}),
                    (0, 0, {"account_id": self.account_b.id, "name": "F", "debit": 0.0, "credit": amount}),
                ],
            }
        )
        payment_move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.journal.id,
                "date": date(2025, 1, 15),
                "ref": "Paiement simulé",
                "line_ids": [
                    (0, 0, {"account_id": self.receivable.id, "name": "P", "debit": 0.0, "credit": amount}),
                    (0, 0, {"account_id": self.account_b.id, "name": "P", "debit": amount, "credit": 0.0}),
                ],
            }
        )
        invoice_move.action_post()
        payment_move.action_post()
        return invoice_move, payment_move

    def test_reconcile_balanced_pair(self):
        """Deux lignes équilibrées sur le même compte ⇒ lettrage complet."""
        inv, pay = self._make_pair(amount=1000.0)
        lines = (inv.line_ids + pay.line_ids).filtered(lambda line: line.account_id == self.receivable)
        lines.reconcile()
        self.assertTrue(all(line.reconciled for line in lines))
        self.assertTrue(lines[0].full_reconcile_id)
        self.assertEqual(lines.mapped("full_reconcile_id"), lines[0].full_reconcile_id)

    def test_reconciled_lines_have_zero_residual(self):
        """Après lettrage : solde restant = 0 sur chaque ligne."""
        inv, pay = self._make_pair(amount=750.0)
        lines = (inv.line_ids + pay.line_ids).filtered(lambda line: line.account_id == self.receivable)
        lines.reconcile()
        for line in lines:
            self.assertAlmostEqual(line.amount_residual, 0.0)

    def test_unreconcile_restores_open_state(self):
        """Délettrage : les lignes redeviennent non lettrées et le solde réapparaît."""
        inv, pay = self._make_pair(amount=500.0)
        lines = (inv.line_ids + pay.line_ids).filtered(lambda line: line.account_id == self.receivable)
        lines.reconcile()
        self.assertTrue(all(line.reconciled for line in lines))

        lines.remove_move_reconcile()
        self.assertFalse(any(line.reconciled for line in lines))
        self.assertFalse(any(line.full_reconcile_id for line in lines))


# =============================================================================
#  3.1.2.D — Contre-passation d'écritures
# =============================================================================
@tagged("post_install", "-at_install", "omega_compta", "omega_reversal")
class TestReversal(_ComptaTestCommon):
    """Contre-passation : génération d'une écriture miroir débit/crédit inversés."""

    def test_reverse_creates_new_move(self):
        move = self._make_entry(amount=500.0, post=True)
        reversed_moves = move._reverse_moves(
            [
                {
                    "date": date(2025, 1, 31),
                    "ref": "Contre-passation",
                }
            ]
        )
        self.assertEqual(len(reversed_moves), 1)
        self.assertNotEqual(reversed_moves.id, move.id)

    def test_reverse_inverts_debit_and_credit(self):
        """Sur le compte qui était au débit, la contre-passation crédite, et inversement."""
        move = self._make_entry(amount=500.0, post=True)
        reversed_moves = move._reverse_moves(
            [
                {
                    "date": date(2025, 1, 31),
                    "ref": "Contre-passation",
                }
            ]
        )
        original_debits = sum(move.line_ids.mapped("debit"))
        original_credits = sum(move.line_ids.mapped("credit"))
        reverse_debits = sum(reversed_moves.line_ids.mapped("debit"))
        reverse_credits = sum(reversed_moves.line_ids.mapped("credit"))
        self.assertAlmostEqual(original_debits, reverse_credits)
        self.assertAlmostEqual(original_credits, reverse_debits)

    def test_reverse_preserves_accounts(self):
        """Les comptes utilisés dans la contre-passation sont identiques à l'originale."""
        move = self._make_entry(amount=500.0, post=True)
        reversed_moves = move._reverse_moves(
            [
                {
                    "date": date(2025, 1, 31),
                    "ref": "Contre-passation",
                }
            ]
        )
        self.assertEqual(
            set(move.line_ids.mapped("account_id.id")),
            set(reversed_moves.line_ids.mapped("account_id.id")),
        )

    def test_reverse_with_cancel_reconciles_originals(self):
        """`cancel=True` lettre automatiquement l'écriture d'origine avec son miroir."""
        receivable = self.env["account.account"].search(
            [
                ("account_type", "=", "asset_receivable"),
                ("reconcile", "=", True),
                ("company_id", "=", self.company.id),
            ],
            limit=1,
        )
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.journal.id,
                "date": date(2025, 1, 1),
                "ref": "OD pour test cancel",
                "line_ids": [
                    (0, 0, {"account_id": receivable.id, "name": "L", "debit": 500.0, "credit": 0.0}),
                    (0, 0, {"account_id": self.account_b.id, "name": "L", "debit": 0.0, "credit": 500.0}),
                ],
            }
        )
        move.action_post()

        reversed_moves = move._reverse_moves(
            [{"date": date(2025, 1, 31), "ref": "Contre-passation cancel"}],
            cancel=True,
        )
        self.assertEqual(reversed_moves.state, "posted")
        receivable_lines = (move.line_ids + reversed_moves.line_ids).filtered(
            lambda line: line.account_id == receivable
        )
        self.assertTrue(all(line.reconciled for line in receivable_lines))


# =============================================================================
#  3.1.2.E — Écritures récurrentes (abonnements, loyers)
# =============================================================================
@tagged("post_install", "-at_install", "omega_compta", "omega_recurring")
class TestAccountRecurring(_ComptaTestCommon):
    """Tests du modèle ``account.recurring`` (abonnements / loyers)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_move = cls.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": cls.journal.id,
                "date": date(2025, 1, 1),
                "ref": "Modèle loyer mensuel",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "account_id": cls.account_a.id,
                            "name": "Loyer",
                            "debit": 5000.0,
                            "credit": 0.0,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "account_id": cls.account_b.id,
                            "name": "Loyer",
                            "debit": 0.0,
                            "credit": 5000.0,
                        },
                    ),
                ],
            }
        )

    def _make_recurring(self, **overrides):
        vals = {
            "name": "Loyer mensuel test",
            "journal_id": self.journal.id,
            "move_id": self.template_move.id,
            "date_start": date(2025, 1, 1),
            "date_next": date(2025, 1, 1),
            "interval_number": 1,
            "interval_type": "months",
        }
        vals.update(overrides)
        return self.env["account.recurring"].create(vals)

    # ── Cycle de vie ──────────────────────────────────────────────────
    def test_initial_state_is_draft(self):
        rec = self._make_recurring()
        self.assertEqual(rec.state, "draft")

    def test_action_start_changes_state(self):
        rec = self._make_recurring()
        rec.action_start()
        self.assertEqual(rec.state, "running")

    def test_stop_changes_state(self):
        rec = self._make_recurring()
        rec.action_start()
        rec.action_stop()
        self.assertEqual(rec.state, "done")

    # ── Garde-fou métier ──────────────────────────────────────────────
    def test_generate_move_only_if_running(self):
        rec = self._make_recurring()
        rec.action_generate_move()
        self.assertEqual(len(rec.generated_move_ids), 0)

        rec.action_start()
        rec.action_generate_move()
        self.assertEqual(len(rec.generated_move_ids), 1)
        generated = rec.generated_move_ids[0]
        self.assertEqual(generated.recurring_id, rec)
        self.assertIn("(Généré)", generated.ref)

    # ── Avance de date pour chaque périodicité ────────────────────────
    def test_next_date_advances_by_days(self):
        rec = self._make_recurring(interval_type="days", interval_number=7)
        rec.action_start()
        rec.action_generate_move()
        self.assertEqual(rec.date_next, date(2025, 1, 8))

    def test_next_date_advances_by_weeks(self):
        rec = self._make_recurring(interval_type="weeks", interval_number=2)
        rec.action_start()
        rec.action_generate_move()
        self.assertEqual(rec.date_next, date(2025, 1, 15))

    def test_next_date_advances_by_one_month(self):
        rec = self._make_recurring()
        rec.action_start()
        rec.action_generate_move()
        self.assertEqual(rec.date_next, date(2025, 2, 1))

    def test_next_date_advances_by_one_year(self):
        rec = self._make_recurring(interval_type="years", interval_number=1)
        rec.action_start()
        rec.action_generate_move()
        self.assertEqual(rec.date_next, date(2026, 1, 1))

    # ── Génération en chaîne (2 cycles consécutifs) ───────────────────
    def test_multiple_successive_generations(self):
        rec = self._make_recurring()
        rec.action_start()
        rec.action_generate_move()
        rec.action_generate_move()
        self.assertEqual(len(rec.generated_move_ids), 2)
        self.assertEqual(rec.date_next, date(2025, 3, 1))

    # ── Sécurité comptable ────────────────────────────────────────────
    def test_generated_move_is_in_draft_state(self):
        """L'écriture générée reste en brouillon (auto_post='no')."""
        rec = self._make_recurring()
        rec.action_start()
        rec.action_generate_move()
        self.assertEqual(rec.generated_move_ids[0].state, "draft")

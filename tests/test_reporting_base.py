# -*- coding: utf-8 -*-
"""Suite de tests fonctionnels — section 3.1.6 du CDC : Reporting de Base.

Couverture :
    * Balance générale          (compta.balance.generale)
    * Grand livre                (compta.grand.livre)
    * Balance âgée clients/fourn (compta.balance.agee)
    * Journal centralisateur     (compta.journal.centralisateur)

Stratégie d'isolation :
    Chaque test crée ses propres comptes et journaux (codes ``TR6...``)
    pour que les agrégations ne soient pas polluées par des écritures
    pré-existantes de la base. Les recherches filtrent toujours sur ces
    objets dédiés.
"""

from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged


class _ReportsCommon(TransactionCase):
    """Setup partagé : comptes, journaux et partenaire dédiés."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Account = cls.env["account.account"]
        Journal = cls.env["account.journal"]

        cls.account_charge = Account.create({
            "code": "TR6CHG",
            "name": "Test Charge 3.1.6",
            "account_type": "expense",
            "company_id": cls.company.id,
        })
        cls.account_produit = Account.create({
            "code": "TR6PDT",
            "name": "Test Produit 3.1.6",
            "account_type": "income",
            "company_id": cls.company.id,
        })
        cls.account_client = Account.create({
            "code": "TR6CLI",
            "name": "Test Client 3.1.6",
            "account_type": "asset_receivable",
            "reconcile": True,
            "company_id": cls.company.id,
        })
        cls.account_fourn = Account.create({
            "code": "TR6FRN",
            "name": "Test Fourn 3.1.6",
            "account_type": "liability_payable",
            "reconcile": True,
            "company_id": cls.company.id,
        })

        cls.journal_general = Journal.create({
            "name": "Test OD 3.1.6",
            "code": "TR6",
            "type": "general",
            "company_id": cls.company.id,
        })
        cls.journal_vente = Journal.create({
            "name": "Test Vente 3.1.6",
            "code": "TR6V",
            "type": "sale",
            "company_id": cls.company.id,
        })
        cls.journal_achat = Journal.create({
            "name": "Test Achat 3.1.6",
            "code": "TR6A",
            "type": "purchase",
            "company_id": cls.company.id,
        })

        cls.partner = cls.env["res.partner"].create({
            "name": "Partner Test 3.1.6",
            "property_account_receivable_id": cls.account_client.id,
            "property_account_payable_id": cls.account_fourn.id,
        })

    # ── Helpers ──────────────────────────────────────────────────────────
    def _make_entry(self, amount=1000.0, account_debit=None, account_credit=None,
                    journal=None, entry_date=None, post=True, ref="OD test 3.1.6"):
        """Crée une écriture équilibrée 1 ligne débit / 1 ligne crédit."""
        account_debit = account_debit or self.account_charge
        account_credit = account_credit or self.account_fourn
        journal = journal or self.journal_general
        entry_date = entry_date or date(2030, 6, 1)
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": journal.id,
            "date": entry_date,
            "ref": ref,
            "line_ids": [
                (0, 0, {
                    "account_id": account_debit.id,
                    "name": "D",
                    "debit": amount,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "account_id": account_credit.id,
                    "name": "C",
                    "debit": 0.0,
                    "credit": amount,
                }),
            ],
        })
        if post:
            move.action_post()
        return move

    def _make_customer_invoice(self, amount=1000.0, invoice_date=None,
                               invoice_date_due=None, post=True):
        """Crée une facture client sans taxe (HT = TTC)."""
        invoice_date = invoice_date or date(2030, 6, 15)
        vals = {
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "journal_id": self.journal_vente.id,
            "invoice_date": invoice_date,
            "invoice_line_ids": [(0, 0, {
                "name": "Ligne",
                "quantity": 1,
                "price_unit": amount,
                "account_id": self.account_produit.id,
                "tax_ids": [(5, 0, 0)],
            })],
        }
        if invoice_date_due:
            vals["invoice_date_due"] = invoice_date_due
        invoice = self.env["account.move"].create(vals)
        if post:
            invoice.action_post()
        return invoice

    def _make_vendor_bill(self, amount=1000.0, invoice_date=None,
                          invoice_date_due=None, post=True):
        """Crée une facture fournisseur sans taxe."""
        invoice_date = invoice_date or date(2030, 6, 15)
        vals = {
            "move_type": "in_invoice",
            "partner_id": self.partner.id,
            "journal_id": self.journal_achat.id,
            "invoice_date": invoice_date,
            "ref": f"BILL-{invoice_date.isoformat()}",
            "invoice_line_ids": [(0, 0, {
                "name": "Ligne",
                "quantity": 1,
                "price_unit": amount,
                "account_id": self.account_charge.id,
                "tax_ids": [(5, 0, 0)],
            })],
        }
        if invoice_date_due:
            vals["invoice_date_due"] = invoice_date_due
        bill = self.env["account.move"].create(vals)
        if post:
            bill.action_post()
        return bill


# =============================================================================
#  3.1.6.A — Balance Générale
# =============================================================================
@tagged("post_install", "-at_install", "omega_reports", "omega_balance_generale")
class TestBalanceGenerale(_ReportsCommon):
    """Vue ``compta.balance.generale`` : Débit / Crédit / Solde par compte."""

    def _balance(self, account):
        return self.env["compta.balance.generale"].search([
            ("account_id", "=", account.id),
            ("company_id", "=", self.company.id),
        ], limit=1)

    def test_compte_debite_apparait(self):
        """Écriture validée ⇒ compte débité présent dans la balance."""
        self._make_entry(amount=1500.0)
        ligne = self._balance(self.account_charge)
        self.assertTrue(ligne, "Le compte débité doit apparaître dans la balance")
        self.assertAlmostEqual(ligne.debit, 1500.0, places=2)
        self.assertAlmostEqual(ligne.credit, 0.0, places=2)
        self.assertAlmostEqual(ligne.balance, 1500.0, places=2)

    def test_compte_credite_apparait(self):
        """Écriture validée ⇒ compte crédité (solde négatif)."""
        self._make_entry(amount=800.0)
        ligne = self._balance(self.account_fourn)
        self.assertTrue(ligne)
        self.assertAlmostEqual(ligne.debit, 0.0, places=2)
        self.assertAlmostEqual(ligne.credit, 800.0, places=2)
        self.assertAlmostEqual(ligne.balance, -800.0, places=2)

    def test_aggregation_multiples_ecritures(self):
        """N écritures sur le même compte ⇒ somme cumulée."""
        self._make_entry(amount=500.0)
        self._make_entry(amount=700.0)
        self._make_entry(amount=300.0)
        ligne = self._balance(self.account_charge)
        self.assertAlmostEqual(ligne.debit, 1500.0, places=2)
        self.assertAlmostEqual(ligne.balance, 1500.0, places=2)

    def test_balance_egale_debit_moins_credit(self):
        """Formule : Solde = Débit − Crédit."""
        self._make_entry(amount=1000.0)
        self._make_entry(
            amount=400.0,
            account_debit=self.account_fourn,
            account_credit=self.account_charge,
        )
        ligne = self._balance(self.account_charge)
        self.assertAlmostEqual(ligne.debit, 1000.0, places=2)
        self.assertAlmostEqual(ligne.credit, 400.0, places=2)
        self.assertAlmostEqual(ligne.balance, 600.0, places=2)

    def test_ecriture_brouillon_exclue(self):
        """Écriture en brouillon ⇒ absente de la balance (état posted requis)."""
        self._make_entry(amount=1000.0, post=False)
        ligne = self._balance(self.account_charge)
        self.assertFalse(ligne, "Aucune ligne ne doit apparaître pour les brouillons")


# =============================================================================
#  3.1.6.B — Grand Livre
# =============================================================================
@tagged("post_install", "-at_install", "omega_reports", "omega_grand_livre")
class TestGrandLivre(_ReportsCommon):
    """Vue ``compta.grand.livre`` : 1 ligne par écriture, solde progressif."""

    def _lignes(self, account):
        return self.env["compta.grand.livre"].search([
            ("account_id", "=", account.id),
            ("company_id", "=", self.company.id),
        ], order="date, id")

    def test_une_ligne_par_ecriture(self):
        """1 OD (2 lignes) ⇒ 2 lignes au grand livre (1 par compte)."""
        self._make_entry(amount=1000.0)
        lignes = self.env["compta.grand.livre"].search([
            ("account_id", "in", [self.account_charge.id, self.account_fourn.id]),
            ("company_id", "=", self.company.id),
        ])
        self.assertEqual(len(lignes), 2)

    def test_champs_remplis(self):
        """Date, journal, partenaire et libellé sont disponibles."""
        move = self._make_entry(amount=1000.0)
        lignes = self._lignes(self.account_charge)
        self.assertEqual(len(lignes), 1)
        gl = lignes[0]
        self.assertEqual(gl.move_id, move)
        self.assertEqual(gl.journal_id, self.journal_general)
        self.assertEqual(gl.date, move.date)
        self.assertAlmostEqual(gl.debit, 1000.0, places=2)
        self.assertAlmostEqual(gl.credit, 0.0, places=2)

    def test_solde_progressif(self):
        """Le solde cumule les lignes du compte triées par date/id."""
        self._make_entry(amount=500.0, entry_date=date(2030, 6, 1))
        self._make_entry(amount=300.0, entry_date=date(2030, 6, 5))
        self._make_entry(amount=200.0, entry_date=date(2030, 6, 10))
        lignes = self._lignes(self.account_charge)
        self.assertEqual(len(lignes), 3)
        self.assertAlmostEqual(lignes[0].balance, 500.0, places=2)
        self.assertAlmostEqual(lignes[1].balance, 800.0, places=2)
        self.assertAlmostEqual(lignes[2].balance, 1000.0, places=2)

    def test_brouillon_exclu(self):
        """Lignes d'écritures brouillon ⇒ absentes du grand livre."""
        self._make_entry(amount=1000.0, post=False)
        lignes = self._lignes(self.account_charge)
        self.assertFalse(lignes)


# =============================================================================
#  3.1.6.C — Balance Âgée Clients / Fournisseurs
# =============================================================================
@tagged("post_install", "-at_install", "omega_reports", "omega_balance_agee")
class TestBalanceAgee(_ReportsCommon):
    """Vue ``compta.balance.agee`` : ventilation 0-30 / 30-60 / 60-90 / +90."""

    def _lignes(self, account_type="asset_receivable"):
        return self.env["compta.balance.agee"].search([
            ("partner_id", "=", self.partner.id),
            ("account_type", "=", account_type),
            ("company_id", "=", self.company.id),
        ])

    def test_facture_non_payee_apparait(self):
        """Facture client non lettrée ⇒ ligne dans la balance âgée."""
        today = date.today()
        self._make_customer_invoice(
            amount=1000.0,
            invoice_date=today - timedelta(days=15),
            invoice_date_due=today - timedelta(days=15),
        )
        lignes = self._lignes("asset_receivable")
        self.assertEqual(len(lignes), 1)
        self.assertAlmostEqual(lignes.total, 1000.0, places=2)

    def test_tranche_0_30(self):
        """Échéance −15 j ⇒ tranche 0-30."""
        today = date.today()
        self._make_customer_invoice(
            amount=500.0,
            invoice_date=today - timedelta(days=15),
            invoice_date_due=today - timedelta(days=15),
        )
        ligne = self._lignes("asset_receivable")
        self.assertAlmostEqual(ligne.jour_0_30, 500.0, places=2)
        self.assertAlmostEqual(ligne.jour_30_60, 0.0, places=2)
        self.assertAlmostEqual(ligne.jour_60_90, 0.0, places=2)
        self.assertAlmostEqual(ligne.jour_plus_90, 0.0, places=2)

    def test_tranche_30_60(self):
        """Échéance −45 j ⇒ tranche 30-60."""
        today = date.today()
        self._make_customer_invoice(
            amount=600.0,
            invoice_date=today - timedelta(days=60),
            invoice_date_due=today - timedelta(days=45),
        )
        ligne = self._lignes("asset_receivable")
        self.assertAlmostEqual(ligne.jour_30_60, 600.0, places=2)
        self.assertAlmostEqual(ligne.jour_0_30, 0.0, places=2)

    def test_tranche_60_90(self):
        """Échéance −75 j ⇒ tranche 60-90."""
        today = date.today()
        self._make_customer_invoice(
            amount=700.0,
            invoice_date=today - timedelta(days=90),
            invoice_date_due=today - timedelta(days=75),
        )
        ligne = self._lignes("asset_receivable")
        self.assertAlmostEqual(ligne.jour_60_90, 700.0, places=2)

    def test_tranche_plus_90(self):
        """Échéance −120 j ⇒ tranche +90."""
        today = date.today()
        self._make_customer_invoice(
            amount=800.0,
            invoice_date=today - timedelta(days=130),
            invoice_date_due=today - timedelta(days=120),
        )
        ligne = self._lignes("asset_receivable")
        self.assertAlmostEqual(ligne.jour_plus_90, 800.0, places=2)

    def test_total_egale_somme_tranches(self):
        """Total = somme des 4 tranches (vérification d'invariant)."""
        today = date.today()
        self._make_customer_invoice(
            amount=100.0, invoice_date=today - timedelta(days=15),
            invoice_date_due=today - timedelta(days=15),
        )
        self._make_customer_invoice(
            amount=200.0, invoice_date=today - timedelta(days=60),
            invoice_date_due=today - timedelta(days=45),
        )
        self._make_customer_invoice(
            amount=300.0, invoice_date=today - timedelta(days=90),
            invoice_date_due=today - timedelta(days=75),
        )
        self._make_customer_invoice(
            amount=400.0, invoice_date=today - timedelta(days=130),
            invoice_date_due=today - timedelta(days=120),
        )
        ligne = self._lignes("asset_receivable")
        somme = (ligne.jour_0_30 + ligne.jour_30_60
                 + ligne.jour_60_90 + ligne.jour_plus_90)
        self.assertAlmostEqual(somme, ligne.total, places=2)
        self.assertAlmostEqual(ligne.total, 1000.0, places=2)

    def test_facture_fournisseur_dans_balance_fournisseur(self):
        """Facture fournisseur non payée ⇒ ligne dans la balance âgée fourn."""
        today = date.today()
        self._make_vendor_bill(
            amount=500.0,
            invoice_date=today - timedelta(days=15),
            invoice_date_due=today - timedelta(days=15),
        )
        ligne = self._lignes("liability_payable")
        self.assertEqual(len(ligne), 1)
        self.assertAlmostEqual(ligne.total, 500.0, places=2)

    def test_filtre_client_exclut_fournisseur(self):
        """Le filtre asset_receivable ignore les factures fournisseurs."""
        today = date.today()
        self._make_customer_invoice(
            amount=300.0,
            invoice_date=today - timedelta(days=15),
            invoice_date_due=today - timedelta(days=15),
        )
        self._make_vendor_bill(
            amount=999.0,
            invoice_date=today - timedelta(days=15),
            invoice_date_due=today - timedelta(days=15),
        )
        ligne_client = self._lignes("asset_receivable")
        self.assertAlmostEqual(ligne_client.total, 300.0, places=2)


# =============================================================================
#  3.1.6.D — Journal Centralisateur
# =============================================================================
@tagged("post_install", "-at_install", "omega_reports", "omega_centralisateur")
class TestJournalCentralisateur(_ReportsCommon):
    """Vue ``compta.journal.centralisateur`` : Débit/Crédit par journal."""

    def _ligne(self, journal):
        return self.env["compta.journal.centralisateur"].search([
            ("journal_id", "=", journal.id),
            ("company_id", "=", self.company.id),
        ], limit=1)

    def test_aggregation_par_journal(self):
        """N écritures dans le même journal ⇒ ligne unique avec total."""
        self._make_entry(amount=500.0)
        self._make_entry(amount=300.0)
        self._make_entry(amount=200.0)
        ligne = self._ligne(self.journal_general)
        self.assertTrue(ligne)
        self.assertAlmostEqual(ligne.debit, 1000.0, places=2)
        self.assertAlmostEqual(ligne.credit, 1000.0, places=2)

    def test_journal_sans_ecriture_apparait_a_zero(self):
        """LEFT JOIN : un journal sans écriture reste visible avec 0/0."""
        ligne = self._ligne(self.journal_vente)
        self.assertTrue(ligne, "Un journal vide doit apparaître (LEFT JOIN)")
        self.assertAlmostEqual(ligne.debit, 0.0, places=2)
        self.assertAlmostEqual(ligne.credit, 0.0, places=2)

    def test_brouillon_exclu(self):
        """Écriture brouillon ⇒ non comptée dans le centralisateur."""
        self._make_entry(amount=1000.0, post=False)
        ligne = self._ligne(self.journal_general)
        self.assertAlmostEqual(ligne.debit, 0.0, places=2)
        self.assertAlmostEqual(ligne.credit, 0.0, places=2)

    def test_journal_equilibre(self):
        """Journal équilibré : total Débit = total Crédit."""
        self._make_entry(amount=1234.0)
        self._make_entry(amount=567.0)
        ligne = self._ligne(self.journal_general)
        self.assertAlmostEqual(ligne.debit, ligne.credit, places=2)
        self.assertAlmostEqual(ligne.debit, 1801.0, places=2)

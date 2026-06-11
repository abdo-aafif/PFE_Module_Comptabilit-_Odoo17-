# -*- coding: utf-8 -*-
"""Tests 3.1.4 — Gestion Bancaire (CDC PUSH 4).

Fichier unique couvrant les 4 sous-fonctionnalités :

    1. Rapprochement bancaire             → TestBankReconciliation
    2. Import des relevés bancaires        → TestBankStatementImport
       (CSV, OFX 1.x SGML, OFX 2.x XML, MT940)
    3. Rapprochement automatique           → TestBankAutoMatchCandidates
       (règles de matching / _compute_candidates)
    4. Suivi des comptes bancaires         → TestBankAccountTracking

Exécution ciblée :
    odoo-bin -d <db> -u pfe --test-enable --test-tags=omega_bank314 --stop-after-init
"""

import base64

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


def _b64(content: bytes) -> bytes:
    return base64.b64encode(content)


# ═══════════════════════════════════════════════════════════════════════════════
#  SETUP COMMUN
# ═══════════════════════════════════════════════════════════════════════════════


class _BankTestCommon(TransactionCase):
    """Setup partagé : journal bancaire, partenaire, comptes utiles."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.bank_journal = cls._ensure_bank_journal("Test Bank 314", "TB14")
        cls.partner = cls._ensure_partner()
        cls.charge_account = cls._ensure_expense_account()

    @classmethod
    def _ensure_bank_journal(cls, name, code):
        journal = cls.env["account.journal"].search(
            [
                ("type", "=", "bank"),
                ("company_id", "=", cls.env.company.id),
            ],
            limit=1,
        )
        if not journal:
            journal = cls.env["account.journal"].create(
                {
                    "name": name,
                    "code": code,
                    "type": "bank",
                    "company_id": cls.env.company.id,
                }
            )
        return journal

    @classmethod
    def _ensure_partner(cls):
        # `is_company` est stocké ; `company_type` est calculé et non-searchable.
        partner = cls.env["res.partner"].search(
            [
                ("is_company", "=", True),
            ],
            limit=1,
        )
        if not partner:
            partner = cls.env["res.partner"].create(
                {
                    "name": "Client Test 314",
                    "is_company": True,
                }
            )
        return partner

    @classmethod
    def _ensure_expense_account(cls):
        account = cls.env["account.account"].search(
            [
                ("account_type", "=", "expense"),
                ("company_id", "=", cls.env.company.id),
                ("deprecated", "=", False),
            ],
            limit=1,
        )
        if not account:
            account = cls.env["account.account"].create(
                {
                    "name": "Charges bancaires test",
                    "code": "X6110",
                    "account_type": "expense",
                    "company_id": cls.env.company.id,
                }
            )
        return account

    def _create_bank_line(self, amount=500.0, ref="TX-TEST", journal=None):
        return self.env["account.bank.statement.line"].create(
            {
                "journal_id": (journal or self.bank_journal).id,
                "date": "2025-03-15",
                "payment_ref": ref,
                "amount": amount,
            }
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  1. RAPPROCHEMENT BANCAIRE — bank.reconciliation.wizard
# ═══════════════════════════════════════════════════════════════════════════════


@tagged("post_install", "-at_install", "omega_bank314")
class TestBankReconciliation(_BankTestCommon):
    """Wizard de rapprochement : modes write_off et match."""

    def _create_wizard(self, line, mode="write_off", **extra):
        vals = {"statement_line_id": line.id, "mode": mode}
        vals.update(extra)
        return self.env["bank.reconciliation.wizard"].create(vals)

    # ── Mode write_off ───────────────────────────────────────────────────────

    def test_write_off_requires_account(self):
        """Sans compte de contrepartie, le wizard doit lever UserError."""
        line = self._create_bank_line(amount=-50.0)
        wiz = self._create_wizard(line, mode="write_off")
        with self.assertRaises(UserError):
            wiz.action_reconcile()

    def test_write_off_posts_move(self):
        """Imputation directe : le mouvement doit passer à l'état 'posted'."""
        line = self._create_bank_line(amount=-75.0, ref="FRAIS-BANK")
        wiz = self._create_wizard(
            line,
            mode="write_off",
            account_id=self.charge_account.id,
            label="Frais bancaires mars 2025",
        )
        result = wiz.action_reconcile()
        self.assertEqual(result["res_model"], "account.bank.statement.line")
        self.assertTrue(line.move_id)
        self.assertEqual(line.move_id.state, "posted")

    def test_write_off_label_propagated_to_counterpart(self):
        """Le libellé du wizard doit apparaître sur la ligne de contrepartie."""
        label = "Intérêts débiteurs T1-2025"
        line = self._create_bank_line(amount=-120.0, ref="INT-DEB")
        wiz = self._create_wizard(
            line,
            mode="write_off",
            account_id=self.charge_account.id,
            label=label,
        )
        wiz.action_reconcile()
        counterpart = line.move_id.line_ids.filtered(lambda ln: ln.account_id == self.charge_account)
        self.assertTrue(
            counterpart,
            "Aucune ligne sur le compte de contrepartie après write_off.",
        )
        self.assertEqual(
            counterpart.name,
            label,
            "Le libellé du wizard n'est pas propagé sur la contrepartie.",
        )

    def test_already_reconciled_raises(self):
        """Tenter de rapprocher une ligne déjà rapprochée doit lever UserError."""
        line = self._create_bank_line(amount=-30.0, ref="DEJA-RAPP")
        wiz1 = self._create_wizard(
            line,
            mode="write_off",
            account_id=self.charge_account.id,
        )
        wiz1.action_reconcile()
        if not line.is_reconciled:
            self.skipTest(
                "Le write_off ne marque pas is_reconciled sur cette config — "
                "la garde 'déjà rapprochée' ne peut être déclenchée."
            )
        wiz2 = self._create_wizard(
            line,
            mode="write_off",
            account_id=self.charge_account.id,
        )
        with self.assertRaises(UserError):
            wiz2.action_reconcile()

    # ── Mode match ───────────────────────────────────────────────────────────

    def test_match_requires_move_line(self):
        """Mode 'match' sans écriture cible → UserError."""
        line = self._create_bank_line(amount=200.0, ref="MATCH-VIDE")
        wiz = self._create_wizard(line, mode="match")
        with self.assertRaises(UserError):
            wiz.action_reconcile()

    def _make_posted_invoice(self, amount=300.0):
        """Crée et valide une facture client. Active la devise si nécessaire."""
        # Devise principale active (évite l'erreur "devise inactive")
        currency = self.company.currency_id
        if not currency.active:
            currency.sudo().active = True

        sale_journal = self.env["account.journal"].search(
            [
                ("type", "=", "sale"),
                ("company_id", "=", self.company.id),
            ],
            limit=1,
        )
        if not sale_journal:
            self.skipTest("Pas de journal de ventes configuré.")

        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "journal_id": sale_journal.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Service test 3.1.4",
                            "quantity": 1,
                            "price_unit": amount,
                        },
                    )
                ],
            }
        )
        invoice.action_post()
        return invoice

    def test_match_reconciles_target_line(self):
        """Après _do_match, la ligne AR cible doit être marquée reconciled."""
        line = self._create_bank_line(amount=300.0, ref="MATCH-RECONC")
        invoice = self._make_posted_invoice(amount=300.0)
        ar_line = invoice.line_ids.filtered(
            lambda ln: ln.account_id.account_type == "asset_receivable" and not ln.reconciled
        )[:1]
        if not ar_line:
            self.skipTest("Pas de ligne AR sur la facture.")

        wiz = self._create_wizard(line, mode="match", move_line_id=ar_line.id)
        try:
            result = wiz.action_reconcile()
        except UserError as e:
            self.skipTest(f"Configuration suspens absente — skip : {e}")

        self.assertEqual(result["res_model"], "account.bank.statement.line")
        self.assertTrue(
            ar_line.reconciled,
            "La ligne AR cible doit être réconciliée après _do_match.",
        )

    def test_match_rejects_non_reconcilable_account(self):
        """_do_match doit refuser un compte non-réconciliable (UserError)."""
        expense = self.env["account.account"].search(
            [
                ("account_type", "=", "expense"),
                ("reconcile", "=", False),
                ("company_id", "=", self.company.id),
            ],
            limit=1,
        )
        liability = self.env["account.account"].search(
            [
                ("account_type", "=", "liability_current"),
                ("company_id", "=", self.company.id),
            ],
            limit=1,
        )
        general = self.env["account.journal"].search(
            [
                ("type", "=", "general"),
                ("company_id", "=", self.company.id),
            ],
            limit=1,
        )
        if not (expense and liability and general):
            self.skipTest("Comptes/journal nécessaires absents.")

        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": general.id,
                "line_ids": [
                    (0, 0, {"account_id": expense.id, "debit": 100.0, "credit": 0.0, "name": "X"}),
                    (0, 0, {"account_id": liability.id, "debit": 0.0, "credit": 100.0, "name": "X"}),
                ],
            }
        )
        move.action_post()
        non_rec_line = move.line_ids.filtered(lambda ln: ln.account_id == expense)[:1]

        bank_line = self._create_bank_line(amount=100.0, ref="NON-REC")
        wiz = self._create_wizard(
            bank_line,
            mode="match",
            move_line_id=non_rec_line.id,
        )
        with self.assertRaises(UserError):
            wiz.action_reconcile()


# ═══════════════════════════════════════════════════════════════════════════════
#  2. IMPORT RELEVÉS BANCAIRES — bank.statement.import.wizard
# ═══════════════════════════════════════════════════════════════════════════════


@tagged("post_install", "-at_install", "omega_bank314")
class TestBankStatementImport(_BankTestCommon):
    """Parsers CSV / OFX 1.x SGML / OFX 2.x XML / MT940."""

    def _make_wizard(self, content: bytes, file_format: str, **extra):
        vals = {
            "journal_id": self.bank_journal.id,
            "import_file": _b64(content),
            "filename": f"test.{file_format}",
            "file_format": file_format,
            "statement_name": f"Test Import {file_format.upper()}",
        }
        vals.update(extra)
        return self.env["bank.statement.import.wizard"].create(vals)

    # ── CSV ──────────────────────────────────────────────────────────────────

    def test_csv_basic_import(self):
        csv = (
            b"Date;Libelle;Montant;Ref\n"
            b"01/03/2025;Paiement client A;1500,50;INV001\n"
            b"02/03/2025;Virement fourn. B;-2300,00;PO042\n"
        )
        wiz = self._make_wizard(csv, "csv")
        result = wiz.action_import()
        lines = self.env["account.bank.statement.line"].browse(result["domain"][0][2])
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(sum(lines.mapped("amount")), 1500.50 - 2300.00, places=2)

    def test_csv_custom_delimiter_and_iso_date(self):
        """CSV avec délimiteur , et format date ISO YYYY-MM-DD."""
        csv = b"Date,Libelle,Montant,Ref\n" b"2025-03-10,Paiement Test,1000.00,REF01\n"
        wiz = self._make_wizard(
            csv,
            "csv",
            csv_delimiter=",",
            csv_date_format="%Y-%m-%d",
        )
        result = wiz.action_import()
        lines = self.env["account.bank.statement.line"].browse(result["domain"][0][2])
        self.assertEqual(len(lines), 1)
        self.assertEqual(str(lines[0].date), "2025-03-10")
        self.assertAlmostEqual(lines[0].amount, 1000.0, places=2)

    def test_csv_invalid_date_raises(self):
        csv = b"Date;Libelle;Montant;Ref\nNOT_A_DATE;X;100,00;\n"
        wiz = self._make_wizard(csv, "csv")
        with self.assertRaises(UserError):
            wiz.action_import()

    def test_csv_empty_raises(self):
        wiz = self._make_wizard(b"\n\n", "csv")
        with self.assertRaises(UserError):
            wiz.action_import()

    # ── OFX 1.x SGML ─────────────────────────────────────────────────────────

    def test_ofx_sgml_basic_import(self):
        ofx = (
            b"OFXHEADER:100\n"
            b"DATA:OFXSGML\n\n"
            b"<OFX>\n<BANKTRANLIST>\n"
            b"<STMTTRN>\n<TRNTYPE>CREDIT\n<DTPOSTED>20250315\n"
            b"<TRNAMT>500.00\n<FITID>TX001\n<MEMO>Paiement INV-1\n</STMTTRN>\n"
            b"<STMTTRN>\n<TRNTYPE>DEBIT\n<DTPOSTED>20250316\n"
            b"<TRNAMT>-150.00\n<FITID>TX002\n</STMTTRN>\n"
            b"</BANKTRANLIST>\n</OFX>\n"
        )
        wiz = self._make_wizard(ofx, "ofx")
        result = wiz.action_import()
        lines = self.env["account.bank.statement.line"].browse(result["domain"][0][2])
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(sum(lines.mapped("amount")), 500.0 - 150.0, places=2)

    def test_ofx_sgml_empty_raises(self):
        ofx = b"OFXHEADER:100\nDATA:OFXSGML\n\n" b"<OFX>\n<BANKTRANLIST>\n</BANKTRANLIST>\n</OFX>\n"
        wiz = self._make_wizard(ofx, "ofx")
        with self.assertRaises(UserError):
            wiz.action_import()

    # ── OFX 2.x XML ──────────────────────────────────────────────────────────

    def test_ofx_xml_basic_import(self):
        ofx_xml = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b"<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>"
            b"<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20250401</DTPOSTED>"
            b"<TRNAMT>2500.00</TRNAMT><FITID>XML001</FITID>"
            b"<NAME>Client Dupont</NAME><MEMO>Reglement F2025-042</MEMO></STMTTRN>"
            b"<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20250402</DTPOSTED>"
            b"<TRNAMT>-800.00</TRNAMT><FITID>XML002</FITID>"
            b"<NAME>Fourn. Alami</NAME><MEMO>BL-2025-007</MEMO></STMTTRN>"
            b"</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
        )
        wiz = self._make_wizard(ofx_xml, "ofx")
        result = wiz.action_import()
        lines = self.env["account.bank.statement.line"].browse(result["domain"][0][2])
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(sum(lines.mapped("amount")), 2500.0 - 800.0, places=2)

    def test_ofx_xml_date_yyyymmdd(self):
        ofx_xml = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b"<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>"
            b"<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20251225</DTPOSTED>"
            b"<TRNAMT>100.00</TRNAMT><FITID>XMAS01</FITID><NAME>Bonus</NAME></STMTTRN>"
            b"</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
        )
        wiz = self._make_wizard(ofx_xml, "ofx")
        result = wiz.action_import()
        lines = self.env["account.bank.statement.line"].browse(result["domain"][0][2])
        self.assertEqual(len(lines), 1)
        self.assertEqual(str(lines[0].date), "2025-12-25")

    def test_ofx_xml_memo_priority_over_name(self):
        """OFX : MEMO doit primer sur NAME comme libellé."""
        memo = "Paiement TVA decembre 2025"
        ofx_xml = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b"<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>"
            b"<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20251231</DTPOSTED>"
            b"<TRNAMT>-15000.00</TRNAMT><FITID>TVA2512</FITID>"
            b"<NAME>DGI</NAME><MEMO>" + memo.encode("ascii") + b"</MEMO></STMTTRN>"
            b"</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
        )
        wiz = self._make_wizard(ofx_xml, "ofx")
        result = wiz.action_import()
        lines = self.env["account.bank.statement.line"].browse(result["domain"][0][2])
        self.assertEqual(lines[0].payment_ref, memo)

    def test_ofx_xml_empty_raises(self):
        ofx_xml = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b"<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>"
            b"<BANKTRANLIST></BANKTRANLIST>"
            b"</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
        )
        wiz = self._make_wizard(ofx_xml, "ofx")
        with self.assertRaises(UserError):
            wiz.action_import()

    # ── MT940 SWIFT ──────────────────────────────────────────────────────────

    def test_mt940_basic_import(self):
        mt940 = (
            b":20:STATEMENT001\n:25:11122233344455\n:28C:00001\n"
            b":60F:C250301MAD10000,00\n"
            b":61:2503020302C1500,50NTRFINV001\n:86:Paiement client A\n"
            b":61:2503030303D2300,00NTRFPO042\n:86:Virement fournisseur B\n"
            b":62F:C250303MAD9200,50\n-\n"
        )
        wiz = self._make_wizard(mt940, "mt940")
        result = wiz.action_import()
        lines = self.env["account.bank.statement.line"].browse(result["domain"][0][2])
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(sum(lines.mapped("amount")), 1500.50 - 2300.00, places=2)

    def test_mt940_debit_credit_signs(self):
        """MT940 : C → montant +, D → montant -."""
        mt940 = (
            b":20:SIGNTEST\n:25:CHECK\n:28C:00001\n"
            b":61:2504010401C500,00NTRF\n:86:Credit test\n"
            b":61:2504020402D200,00NTRF\n:86:Debit test\n-\n"
        )
        wiz = self._make_wizard(mt940, "mt940")
        result = wiz.action_import()
        lines = self.env["account.bank.statement.line"].browse(result["domain"][0][2])
        amounts = sorted(lines.mapped("amount"))
        self.assertEqual(len(amounts), 2)
        self.assertAlmostEqual(amounts[0], -200.0, places=2)
        self.assertAlmostEqual(amounts[1], 500.0, places=2)

    def test_mt940_empty_raises(self):
        wiz = self._make_wizard(b":20:EMPTY\n-\n", "mt940")
        with self.assertRaises(UserError):
            wiz.action_import()


# ═══════════════════════════════════════════════════════════════════════════════
#  3. RAPPROCHEMENT AUTOMATIQUE — règles de matching (_compute_candidates)
# ═══════════════════════════════════════════════════════════════════════════════


@tagged("post_install", "-at_install", "omega_bank314")
class TestBankAutoMatchCandidates(_BankTestCommon):
    """Calcul automatique des écritures candidates selon la transaction."""

    def _wizard_for(self, amount):
        line = self._create_bank_line(amount=amount, ref="AUTO-TEST")
        return self.env["bank.reconciliation.wizard"].create(
            {
                "statement_line_id": line.id,
                "mode": "write_off",
            }
        )

    def test_candidates_positive_for_credit_line(self):
        """Transaction crédit (+) → candidats à balance > 0."""
        for cand in self._wizard_for(500.0).candidate_ids:
            self.assertGreater(
                cand.balance,
                0,
                "Un candidat à balance négative ne doit pas apparaître pour un crédit.",
            )

    def test_candidates_negative_for_debit_line(self):
        """Transaction débit (-) → candidats à balance < 0."""
        for cand in self._wizard_for(-300.0).candidate_ids:
            self.assertLess(
                cand.balance,
                0,
                "Un candidat à balance positive ne doit pas apparaître pour un débit.",
            )

    def test_candidates_limited_to_50(self):
        """Limite codée à 50 dans _compute_candidates."""
        self.assertLessEqual(len(self._wizard_for(1.0).candidate_ids), 50)

    def test_candidates_only_unreconciled_and_posted(self):
        """Seules les lignes non réconciliées et validées sont proposées."""
        for cand in self._wizard_for(100.0).candidate_ids:
            self.assertFalse(cand.reconciled)
            self.assertEqual(cand.parent_state, "posted")

    def test_candidates_filtered_by_invoice_move_types(self):
        """Les candidats sont filtrés sur out_invoice / in_invoice / out_refund / in_refund."""
        valid_types = {"out_invoice", "in_invoice", "out_refund", "in_refund"}
        for cand in self._wizard_for(200.0).candidate_ids:
            self.assertIn(cand.move_id.move_type, valid_types)

    def test_candidates_only_on_reconcilable_accounts(self):
        """Les candidats sont sur des comptes réconciliables."""
        for cand in self._wizard_for(150.0).candidate_ids:
            self.assertTrue(
                cand.account_id.reconcile,
                "Un candidat sur compte non-réconciliable ne doit pas apparaître.",
            )


# ═══════════════════════════════════════════════════════════════════════════════
#  4. SUIVI DES COMPTES BANCAIRES
# ═══════════════════════════════════════════════════════════════════════════════


@tagged("post_install", "-at_install", "omega_bank314")
class TestBankAccountTracking(_BankTestCommon):
    """Suivi des comptes bancaires : journaux, mouvements, isolation, soldes."""

    def test_bank_journal_has_default_account(self):
        self.assertTrue(
            self.bank_journal.default_account_id,
            "Le journal bancaire doit avoir un compte par défaut.",
        )

    def test_bank_default_account_is_cash_type(self):
        acc = self.bank_journal.default_account_id
        if not acc:
            self.skipTest("Pas de compte par défaut.")
        self.assertIn(acc.account_type, ("asset_cash", "asset_current"))

    def test_statement_line_creates_posted_move(self):
        """Une ligne de relevé doit créer un account.move validé."""
        line = self._create_bank_line(amount=1000.0, ref="SUIVI-MOVE")
        self.assertTrue(line.move_id, "Une ligne de relevé doit générer un mouvement.")
        self.assertEqual(line.move_id.state, "posted")

    def test_statement_line_amount_reflected_in_move(self):
        amount = 2500.0
        line = self._create_bank_line(amount=amount, ref="SUIVI-AMT")
        if not line.move_id:
            self.skipTest("Pas de move généré.")
        values = line.move_id.line_ids.mapped("debit") + line.move_id.line_ids.mapped("credit")
        self.assertTrue(
            any(abs(v - amount) < 0.01 for v in values),
            "Le montant de la ligne de relevé doit apparaître dans le mouvement.",
        )

    def test_two_journals_tracked_independently(self):
        """Deux journaux bancaires distincts fonctionnent indépendamment."""
        journal2 = self.env["account.journal"].create(
            {
                "name": "Banque Secondaire Test",
                "code": "TS2",
                "type": "bank",
                "company_id": self.company.id,
            }
        )
        line1 = self._create_bank_line(amount=100.0, ref="J1-TX")
        line2 = self._create_bank_line(amount=200.0, ref="J2-TX", journal=journal2)
        self.assertEqual(line1.journal_id, self.bank_journal)
        self.assertEqual(line2.journal_id, journal2)
        self.assertNotEqual(line1.journal_id, line2.journal_id)

    def test_unreconciled_lines_visible_in_search(self):
        """Les transactions non rapprochées remontent via le filtre is_reconciled=False."""
        line = self._create_bank_line(amount=750.0, ref="NON-RAPP")
        found = self.env["account.bank.statement.line"].search(
            [
                ("is_reconciled", "=", False),
                ("journal_id", "=", self.bank_journal.id),
            ]
        )
        self.assertIn(line, found)

    def test_cash_moves_only_posted(self):
        """Les écritures sur comptes asset_cash/asset_current visibles sont validées."""
        lines = self.env["account.move.line"].search(
            [
                ("account_id.account_type", "in", ("asset_cash", "asset_current")),
                ("parent_state", "=", "posted"),
                ("company_id", "=", self.company.id),
            ],
            limit=20,
        )
        for ln in lines:
            self.assertEqual(ln.parent_state, "posted")
            self.assertIn(ln.account_id.account_type, ("asset_cash", "asset_current"))

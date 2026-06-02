import base64
import xml.etree.ElementTree as ET
from datetime import date

from odoo.exceptions import UserError
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


# =============================================================================
#  Base partagée pour les tests fonctionnels de calcul TVA et d'export XML.
#  Crée taxes marocaines, partenaire, journaux, comptes et helpers
#  facture / paiement / déclaration.
# =============================================================================
class _TvaComputeCommon(TransactionCase):
    """Setup réutilisable :
      * VAT société renseigné (devient ``<identifiantFiscal>`` dans le XML)
      * Partenaire avec ICE (devient ``<mpIdentifiant>``)
      * Taxes marocaines 20 / 14 / 10 / 7 / 0 % (sale + purchase)
      * Helpers : ``_make_invoice``, ``_pay_invoice``, ``_make_declaration``
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.vat = '12345678'
        cls.Declaration = cls.env['account.tva.declaration']

        cls.sale_journal = cls.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', cls.company.id),
        ], limit=1)
        cls.purchase_journal = cls.env['account.journal'].search([
            ('type', '=', 'purchase'), ('company_id', '=', cls.company.id),
        ], limit=1)
        cls.bank_journal = cls.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')), ('company_id', '=', cls.company.id),
        ], limit=1)

        cls.income_account = cls.env['account.account'].search([
            ('account_type', '=', 'income'), ('company_id', '=', cls.company.id),
        ], limit=1)
        cls.expense_account = cls.env['account.account'].search([
            ('account_type', '=', 'expense'), ('company_id', '=', cls.company.id),
        ], limit=1)
        cls.receivable_account = cls.env['account.account'].search([
            ('account_type', '=', 'asset_receivable'),
            ('company_id', '=', cls.company.id), ('reconcile', '=', True),
        ], limit=1)
        cls.payable_account = cls.env['account.account'].search([
            ('account_type', '=', 'liability_payable'),
            ('company_id', '=', cls.company.id), ('reconcile', '=', True),
        ], limit=1)

        cls.partner = cls.env['res.partner'].create({
            'name': 'Partenaire Test TVA',
            'vat': '001234567000089',
            'property_account_receivable_id': cls.receivable_account.id,
            'property_account_payable_id': cls.payable_account.id,
        })

        # Taux marocains : 20, 14, 10, 7, 0 — ventes et achats séparés
        cls.tva_sale = {}
        cls.tva_purchase = {}
        for rate in (20, 14, 10, 7, 0):
            cls.tva_sale[rate] = cls.env['account.tax'].create({
                'name': f'Test TVA Vente {rate}%',
                'amount': float(rate),
                'amount_type': 'percent',
                'type_tax_use': 'sale',
                'company_id': cls.company.id,
            })
            cls.tva_purchase[rate] = cls.env['account.tax'].create({
                'name': f'Test TVA Achat {rate}%',
                'amount': float(rate),
                'amount_type': 'percent',
                'type_tax_use': 'purchase',
                'company_id': cls.company.id,
            })

    # ── Helpers ──────────────────────────────────────────────────────────
    def _make_invoice(self, move_type, price=1000.0, tax_rate=20, invoice_date=None):
        """Crée et poste une facture (vente/achat ou avoir) à un seul taux."""
        invoice_date = invoice_date or date(2030, 6, 15)
        is_sale = move_type in ('out_invoice', 'out_refund')
        journal = self.sale_journal if is_sale else self.purchase_journal
        account = self.income_account if is_sale else self.expense_account
        tax = (self.tva_sale if is_sale else self.tva_purchase)[tax_rate]
        invoice = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner.id,
            'journal_id': journal.id,
            'invoice_date': invoice_date,
            'invoice_line_ids': [(0, 0, {
                'name': 'Ligne test',
                'quantity': 1,
                'price_unit': price,
                'account_id': account.id,
                'tax_ids': [(6, 0, [tax.id])],
            })],
        })
        invoice.action_post()
        return invoice

    def _pay_invoice(self, invoice, payment_date, amount=None):
        """Crée une écriture banque ↔ client/fournisseur et la lettre.
        ``payment_date`` devient ``max_date`` du partial reconcile lu par le
        calcul cash basis.
        """
        amount = amount if amount is not None else invoice.amount_total
        ar_ap_line = invoice.line_ids.filtered(lambda l: l.account_id.account_type in (
            'asset_receivable', 'liability_payable',
        ))
        # Le paiement doit créer le signe opposé sur le compte client/fournisseur
        if ar_ap_line.debit > 0:
            pay_debit, pay_credit = 0.0, amount
        else:
            pay_debit, pay_credit = amount, 0.0

        bank_account = self.bank_journal.default_account_id
        payment_move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.bank_journal.id,
            'date': payment_date,
            'ref': f'Paiement {invoice.name}',
            'line_ids': [
                (0, 0, {
                    'account_id': ar_ap_line.account_id.id,
                    'name': 'Paiement',
                    'debit': pay_debit,
                    'credit': pay_credit,
                    'partner_id': self.partner.id,
                }),
                (0, 0, {
                    'account_id': bank_account.id,
                    'name': 'Paiement',
                    'debit': pay_credit,
                    'credit': pay_debit,
                }),
            ],
        })
        payment_move.action_post()

        pay_line = payment_move.line_ids.filtered(
            lambda l: l.account_id == ar_ap_line.account_id
        )
        (ar_ap_line + pay_line).reconcile()
        return payment_move

    def _make_declaration(self, regime='mensuel', year='2030', mois='06', trimestre='2'):
        vals = {'tva_regime': regime, 'periode_annee': year}
        if regime == 'mensuel':
            vals['periode_mois'] = mois
        else:
            vals['periode_trimestre'] = trimestre
        return self.Declaration.create(vals)


# =============================================================================
#  3.1.5.B — Calcul automatique de la TVA (cash basis)
#  Couvre : collectée, déductible, à payer, paiement partiel, avoir, audit
# =============================================================================
@tagged('post_install', '-at_install', 'omega_tva', 'omega_tva_compute')
class TestTvaCompute(_TvaComputeCommon):
    """Validation du moteur ``action_compute_tva`` selon l'encaissement."""

    def test_collectee_facture_vente_payee(self):
        """Facture client payée dans la période ⇒ TVA collectée."""
        invoice = self._make_invoice('out_invoice', price=1000, tax_rate=20)
        self._pay_invoice(invoice, payment_date=date(2030, 6, 20))
        decl = self._make_declaration()
        decl.action_compute_tva()
        self.assertAlmostEqual(decl.tva_collectee, 200.0, places=2)
        self.assertAlmostEqual(decl.tva_deductible, 0.0, places=2)
        self.assertAlmostEqual(decl.tva_a_payer, 200.0, places=2)

    def test_deductible_facture_achat_payee(self):
        """Facture fournisseur payée dans la période ⇒ TVA déductible."""
        invoice = self._make_invoice('in_invoice', price=1000, tax_rate=20)
        self._pay_invoice(invoice, payment_date=date(2030, 6, 20))
        decl = self._make_declaration()
        decl.action_compute_tva()
        self.assertAlmostEqual(decl.tva_collectee, 0.0, places=2)
        self.assertAlmostEqual(decl.tva_deductible, 200.0, places=2)
        self.assertAlmostEqual(decl.tva_a_payer, -200.0, places=2)

    def test_tva_a_payer_balance(self):
        """TVA à payer = TVA collectée − TVA déductible."""
        sale = self._make_invoice('out_invoice', price=1000, tax_rate=20)
        self._pay_invoice(sale, payment_date=date(2030, 6, 10))
        purchase = self._make_invoice('in_invoice', price=500, tax_rate=20)
        self._pay_invoice(purchase, payment_date=date(2030, 6, 20))
        decl = self._make_declaration()
        decl.action_compute_tva()
        self.assertAlmostEqual(decl.tva_collectee, 200.0, places=2)
        self.assertAlmostEqual(decl.tva_deductible, 100.0, places=2)
        self.assertAlmostEqual(decl.tva_a_payer, 100.0, places=2)

    def test_facture_non_payee_ignoree_cash_basis(self):
        """Facture postée mais non payée ⇒ exclue (régime encaissement)."""
        self._make_invoice('in_invoice', price=1000, tax_rate=20)
        decl = self._make_declaration()
        decl.action_compute_tva()
        self.assertAlmostEqual(decl.tva_deductible, 0.0, places=2)
        self.assertEqual(decl.detail_count, 0)

    def test_paiement_partiel_proportionnel(self):
        """Paiement à 50 % ⇒ TVA imputée = 50 % de la TVA de la facture."""
        invoice = self._make_invoice('in_invoice', price=1000, tax_rate=20)
        # TTC = 1200 ; paye 600 ⇒ proportion = 0.5
        self._pay_invoice(invoice, payment_date=date(2030, 6, 20), amount=600.0)
        decl = self._make_declaration()
        decl.action_compute_tva()
        self.assertAlmostEqual(decl.tva_deductible, 100.0, places=2)
        self.assertEqual(len(decl.detail_ids), 1)
        self.assertAlmostEqual(decl.detail_ids.proportion, 0.5, places=4)

    def test_avoir_fournisseur_tva_negative(self):
        """Avoir fournisseur (in_refund) payé ⇒ TVA déductible négative."""
        refund = self._make_invoice('in_refund', price=500, tax_rate=20)
        self._pay_invoice(refund, payment_date=date(2030, 6, 20))
        decl = self._make_declaration()
        decl.action_compute_tva()
        self.assertAlmostEqual(decl.tva_deductible, -100.0, places=2)

    def test_details_audit_par_facture_lettrage(self):
        """``detail_ids`` (audit DGI) : 1 ligne par couple facture / lettrage."""
        invoice = self._make_invoice('in_invoice', price=1000, tax_rate=20)
        self._pay_invoice(invoice, payment_date=date(2030, 6, 20))
        decl = self._make_declaration()
        decl.action_compute_tva()
        self.assertEqual(decl.detail_count, 1)
        det = decl.detail_ids
        self.assertEqual(det.invoice_id, invoice)
        self.assertEqual(det.type_tva, 'deductible')
        self.assertAlmostEqual(det.taux, 20.0, places=2)
        self.assertAlmostEqual(det.tva_amount, 200.0, places=2)


# =============================================================================
#  3.1.5.C — Taux marocains : 20 %, 14 %, 10 %, 7 %, 0 %
# =============================================================================
@tagged('post_install', '-at_install', 'omega_tva', 'omega_tva_rates')
class TestTvaTauxMarocains(_TvaComputeCommon):
    """Le moteur doit gérer les 5 taux marocains et la ventilation multi-taux."""

    def _compute_purchase_at_rate(self, rate, expected_tva):
        invoice = self._make_invoice('in_invoice', price=1000, tax_rate=rate)
        self._pay_invoice(invoice, payment_date=date(2030, 6, 20))
        decl = self._make_declaration()
        decl.action_compute_tva()
        self.assertAlmostEqual(decl.tva_deductible, expected_tva, places=2)
        return decl

    def test_taux_20_pct(self):
        self._compute_purchase_at_rate(20, 200.0)

    def test_taux_14_pct(self):
        self._compute_purchase_at_rate(14, 140.0)

    def test_taux_10_pct(self):
        self._compute_purchase_at_rate(10, 100.0)

    def test_taux_7_pct(self):
        self._compute_purchase_at_rate(7, 70.0)

    def test_taux_0_pct_exoneration(self):
        """Taux 0 % (exonération) ⇒ aucune ligne et aucune TVA imputée."""
        decl = self._compute_purchase_at_rate(0, 0.0)
        self.assertEqual(len(decl.line_ids), 0)

    def test_facture_multi_taux_ventilation(self):
        """Facture avec lignes à 20 % et 10 % ⇒ ventilation en 2 lignes."""
        invoice = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.purchase_journal.id,
            'invoice_date': date(2030, 6, 15),
            'invoice_line_ids': [
                (0, 0, {
                    'name': 'Ligne 20%',
                    'quantity': 1, 'price_unit': 1000.0,
                    'account_id': self.expense_account.id,
                    'tax_ids': [(6, 0, [self.tva_purchase[20].id])],
                }),
                (0, 0, {
                    'name': 'Ligne 10%',
                    'quantity': 1, 'price_unit': 500.0,
                    'account_id': self.expense_account.id,
                    'tax_ids': [(6, 0, [self.tva_purchase[10].id])],
                }),
            ],
        })
        invoice.action_post()
        self._pay_invoice(invoice, payment_date=date(2030, 6, 20))
        decl = self._make_declaration()
        decl.action_compute_tva()

        self.assertAlmostEqual(decl.tva_deductible, 250.0, places=2)
        l_20 = decl.line_ids.filtered(lambda l: abs(l.taux - 20.0) < 0.01)
        l_10 = decl.line_ids.filtered(lambda l: abs(l.taux - 10.0) < 0.01)
        self.assertEqual(len(l_20), 1)
        self.assertEqual(len(l_10), 1)
        self.assertAlmostEqual(l_20.montant_tva, 200.0, places=2)
        self.assertAlmostEqual(l_10.montant_tva, 50.0, places=2)


# =============================================================================
#  3.1.5.D — Export XML SIMPL-TVA (Relevé des Déductions DGI)
# =============================================================================
@tagged('post_install', '-at_install', 'omega_tva', 'omega_tva_export')
class TestTvaExportXml(_TvaComputeCommon):
    """Génération du fichier XML SIMPL-TVA pour télédéclaration."""

    def _prepare(self, regime='mensuel', mois='06', trimestre='2',
                 invoice_date=None, payment_date=None):
        invoice = self._make_invoice(
            'in_invoice', price=1000, tax_rate=20,
            invoice_date=invoice_date or date(2030, 6, 15),
        )
        self._pay_invoice(invoice, payment_date=payment_date or date(2030, 6, 20))
        decl = self._make_declaration(
            regime=regime, year='2030', mois=mois, trimestre=trimestre,
        )
        decl.action_compute_tva()
        decl.action_validate()
        decl.action_export_simpl_tva()
        return invoice, decl

    def _read_xml(self, decl):
        return base64.b64decode(decl.edi_file_data).decode('utf-8')

    # ── Génération du fichier ─────────────────────────────────────────────
    def test_export_genere_fichier_xml(self):
        _, decl = self._prepare()
        self.assertTrue(decl.edi_file_data)
        self.assertTrue(decl.edi_file_name)
        self.assertTrue(decl.edi_generated_on)

    def test_export_nom_fichier_mensuel(self):
        _, decl = self._prepare(regime='mensuel', mois='06')
        self.assertEqual(decl.edi_file_name, 'SIMPL_TVA_2030_06.xml')

    def test_export_nom_fichier_trimestriel(self):
        _, decl = self._prepare(
            regime='trimestriel', trimestre='2',
            invoice_date=date(2030, 5, 15), payment_date=date(2030, 5, 20),
        )
        self.assertEqual(decl.edi_file_name, 'SIMPL_TVA_T2_2030.xml')

    # ── Structure XML ─────────────────────────────────────────────────────
    def test_export_xml_structure(self):
        _, decl = self._prepare()
        root = ET.fromstring(self._read_xml(decl))
        self.assertEqual(root.tag, 'DeclarationReleveDeduction')
        for tag in ('identifiantFiscal', 'annee', 'periode', 'regime',
                    'releveDeductions'):
            self.assertIsNotNone(root.find(tag),
                                 f"Balise <{tag}> absente du XML")

    def test_export_xml_identifiant_fiscal(self):
        _, decl = self._prepare()
        root = ET.fromstring(self._read_xml(decl))
        self.assertEqual(root.find('identifiantFiscal').text, '12345678')

    def test_export_xml_annee_et_periode(self):
        _, decl = self._prepare(regime='mensuel', mois='06')
        root = ET.fromstring(self._read_xml(decl))
        self.assertEqual(root.find('annee').text, '2030')
        self.assertEqual(root.find('periode').text, '06')

    def test_export_xml_regime_mensuel_egal_1(self):
        _, decl = self._prepare(regime='mensuel')
        root = ET.fromstring(self._read_xml(decl))
        self.assertEqual(root.find('regime').text, '1')

    def test_export_xml_regime_trimestriel_egal_2(self):
        _, decl = self._prepare(
            regime='trimestriel', trimestre='2',
            invoice_date=date(2030, 5, 15), payment_date=date(2030, 5, 20),
        )
        root = ET.fromstring(self._read_xml(decl))
        self.assertEqual(root.find('regime').text, '2')

    # ── Contenu des lignes de déduction ───────────────────────────────────
    def test_export_xml_montants_corrects(self):
        _, decl = self._prepare()
        root = ET.fromstring(self._read_xml(decl))
        rd = root.find('releveDeductions/rdDeduction')
        self.assertIsNotNone(rd)
        self.assertAlmostEqual(float(rd.find('montantHT').text), 1000.0, places=2)
        self.assertAlmostEqual(float(rd.find('tauxTva').text), 20.0, places=2)
        self.assertAlmostEqual(float(rd.find('montantTva').text), 200.0, places=2)

    def test_export_xml_ice_fournisseur(self):
        _, decl = self._prepare()
        root = ET.fromstring(self._read_xml(decl))
        rd = root.find('releveDeductions/rdDeduction')
        self.assertEqual(rd.find('mpIdentifiant').text, '001234567000089')

    def test_export_xml_date_paiement_egale_max_date(self):
        """``datePaiement`` doit être la date du lettrage, pas celle de la facture."""
        _, decl = self._prepare(
            invoice_date=date(2030, 6, 5),
            payment_date=date(2030, 6, 25),
        )
        root = ET.fromstring(self._read_xml(decl))
        rd = root.find('releveDeductions/rdDeduction')
        self.assertEqual(rd.find('dateFacture').text, '2030-06-05')
        self.assertEqual(rd.find('datePaiement').text, '2030-06-25')

    def test_export_xml_filtre_deductibles_seulement(self):
        """Le Relevé des Déductions n'inclut que les achats (pas les ventes)."""
        sale = self._make_invoice('out_invoice', price=2000, tax_rate=20)
        self._pay_invoice(sale, payment_date=date(2030, 6, 10))
        purchase = self._make_invoice('in_invoice', price=1000, tax_rate=20)
        self._pay_invoice(purchase, payment_date=date(2030, 6, 20))

        decl = self._make_declaration()
        decl.action_compute_tva()
        decl.action_validate()
        decl.action_export_simpl_tva()

        root = ET.fromstring(self._read_xml(decl))
        rds = root.findall('releveDeductions/rdDeduction')
        self.assertEqual(len(rds), 1)
        self.assertAlmostEqual(float(rds[0].find('montantHT').text), 1000.0, places=2)

    def test_export_xml_caracteres_speciaux_echappes(self):
        """Caractères XML spéciaux (& < >) dans le nom du partenaire échappés."""
        self.partner.name = 'Tests & Co <Spécial>'
        _, decl = self._prepare()
        xml_str = self._read_xml(decl)
        # Doit rester parsable
        root = ET.fromstring(xml_str)
        designation = root.find('releveDeductions/rdDeduction/designationBien').text
        self.assertIn('Tests & Co', designation)
        # Aucun '&' ne doit subsister hors d'une entité (&amp;, &lt;, &gt;, etc.)
        residual = xml_str.replace('&amp;', '').replace('&lt;', '').replace('&gt;', '')
        residual = residual.replace('&quot;', '').replace('&apos;', '')
        self.assertNotIn('&', residual)

    # ── Garde-fou d'export ────────────────────────────────────────────────
    def test_export_bloque_si_aucun_detail(self):
        """Export refusé sur une déclaration validée mais non calculée."""
        decl = self._make_declaration()
        decl.action_validate()
        with self.assertRaises(UserError):
            decl.action_export_simpl_tva()

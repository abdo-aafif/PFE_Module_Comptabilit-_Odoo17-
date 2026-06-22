# -*- coding: utf-8 -*-
"""Suite de tests fonctionnels — section 3.2.1 du CDC : États Financiers.

Couverture :
    * Bilan (actif / passif) — équation comptable, sections, soldes
    * Compte de Résultat (CPC) — rubriques, calcul du résultat net
    * Tableau de Flux de Trésorerie — exploitation, investissement, financement
    * États financiers personnalisables (report builder + safe_eval)

Stratégie d'isolation :
    Les modèles utilisent du SQL par préfixe de code (PCGE marocain). Les
    comptes de test démarrent par le bon digit (5XX trésorerie, 7XX produits,
    6XX charges, etc.) avec suffixe ``Z`` pour rester uniques face à l10n_ma.
"""

from datetime import date

from odoo.tests.common import TransactionCase, tagged


# =============================================================================
#  Base partagée : comptes PCGE, journal, helpers
# =============================================================================
class _FinancialTestCommon(TransactionCase):
    """Comptes PCGE marocains de test + journal général + helpers de moves."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Move = cls.env["account.move"]
        cls.Wizard = cls.env["financial.statement.wizard"]

        Account = cls.env["account.account"]
        cls.account_capital = Account.create(
            {
                "code": "111Z",
                "name": "Test Capital social",
                "account_type": "equity",
                "company_id": cls.company.id,
            }
        )
        cls.account_bank = Account.create(
            {
                "code": "514Z",
                "name": "Test Banque",
                "account_type": "asset_cash",
                "reconcile": True,
                "company_id": cls.company.id,
            }
        )
        cls.account_vente = Account.create(
            {
                "code": "711Z",
                "name": "Test Ventes marchandises",
                "account_type": "income",
                "company_id": cls.company.id,
            }
        )
        cls.account_achat = Account.create(
            {
                "code": "611Z",
                "name": "Test Achats marchandises",
                "account_type": "expense",
                "company_id": cls.company.id,
            }
        )
        cls.account_immo = Account.create(
            {
                "code": "231Z",
                "name": "Test Matériel et outillage",
                "account_type": "asset_fixed",
                "company_id": cls.company.id,
            }
        )
        cls.account_client = Account.create(
            {
                "code": "342Z",
                "name": "Test Clients",
                "account_type": "asset_receivable",
                "reconcile": True,
                "company_id": cls.company.id,
            }
        )
        cls.account_fourn = Account.create(
            {
                "code": "441Z",
                "name": "Test Fournisseurs",
                "account_type": "liability_payable",
                "reconcile": True,
                "company_id": cls.company.id,
            }
        )

        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)],
            limit=1,
        )

    # ── Helpers ──────────────────────────────────────────────────────────
    def _make_move(self, mdate, debit_acc, credit_acc, amount, post=True, ref="Test"):
        move = self.Move.create(
            {
                "journal_id": self.journal.id,
                "date": mdate,
                "ref": ref,
                "line_ids": [
                    (0, 0, {"account_id": debit_acc.id, "name": ref, "debit": amount, "credit": 0.0}),
                    (0, 0, {"account_id": credit_acc.id, "name": ref, "debit": 0.0, "credit": amount}),
                ],
            }
        )
        if post:
            move.action_post()
        return move

    def _inject_capital(self, mdate, amount):
        """Apport en capital : débit banque / crédit capital."""
        return self._make_move(mdate, self.account_bank, self.account_capital, amount, ref="Capital")

    def _make_revenue(self, mdate, amount):
        """Encaissement vente : débit banque / crédit ventes."""
        return self._make_move(mdate, self.account_bank, self.account_vente, amount, ref="Vente")

    def _make_expense(self, mdate, amount):
        """Achat payé : débit achats / crédit banque."""
        return self._make_move(mdate, self.account_achat, self.account_bank, amount, ref="Achat")

    def _make_acquisition_immo(self, mdate, amount):
        """Acquisition immobilisation : débit immo / crédit banque."""
        return self._make_move(mdate, self.account_immo, self.account_bank, amount, ref="Acquisition immo")

    def _make_wizard(self, **overrides):
        vals = {
            "date_from": date(2030, 1, 1),
            "date_to": date(2030, 12, 31),
        }
        vals.update(overrides)
        return self.Wizard.create(vals)

    def _find_amount(self, lines, label):
        """Retourne le montant de la ligne dont ``name`` == label, sinon None."""
        for ln in lines:
            if ln.name == label:
                return ln.amount
        return None


# =============================================================================
#  3.2.1.A — Tests basiques (existants, refactorisés)
# =============================================================================
@tagged("post_install", "-at_install", "omega_statements", "omega_statements_basic")
class TestFinancialStatementsBasic(_FinancialTestCommon):
    """Tests basiques : génération de lignes, sections présentes."""

    def test_compute_bilan_no_error(self):
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        self.assertTrue(wiz.bilan_line_ids)

    def test_compute_cpc_no_error(self):
        wiz = self._make_wizard()
        wiz.action_compute_cpc()
        self.assertTrue(wiz.cpc_line_ids)

    def test_compute_flux_no_error(self):
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        self.assertTrue(wiz.flux_line_ids)

    def test_bilan_has_actif_and_passif_sections(self):
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        sections = wiz.bilan_line_ids.mapped("section")
        self.assertIn("actif", sections)
        self.assertIn("passif", sections)

    def test_bilan_has_total_actif_line(self):
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        names = wiz.bilan_line_ids.mapped("name")
        self.assertIn("TOTAL ACTIF", names)
        self.assertIn("TOTAL PASSIF", names)

    def test_cpc_has_required_sections(self):
        wiz = self._make_wizard()
        wiz.action_compute_cpc()
        names = wiz.cpc_line_ids.mapped("name")
        expected_keywords = [
            "PRODUITS D'EXPLOITATION",
            "CHARGES D'EXPLOITATION",
            "RÉSULTAT D'EXPLOITATION",
            "PRODUITS FINANCIERS",
            "CHARGES FINANCIÈRES",
            "RÉSULTAT NET",
        ]
        for kw in expected_keywords:
            self.assertTrue(any(kw in n for n in names), f"Mot-clé CPC manquant : {kw}")

    def test_flux_has_required_sections(self):
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        names = wiz.flux_line_ids.mapped("name")
        self.assertTrue(any("ACTIVITÉ" in n for n in names))
        self.assertTrue(any("INVESTISSEMENTS" in n for n in names))
        self.assertTrue(any("FINANCEMENT" in n for n in names))
        self.assertTrue(any("VARIATION NETTE DE TRÉSORERIE" in n for n in names))

    def test_balance_at_zero_on_unused_prefix(self):
        wiz = self._make_wizard()
        balance = wiz._balance_at(["ZZZ_UNUSED"], date(2030, 12, 31), self.company.id)
        self.assertEqual(balance, 0.0)

    def test_balance_at_empty_prefixes(self):
        wiz = self._make_wizard()
        balance = wiz._balance_at([], date(2030, 12, 31), self.company.id)
        self.assertEqual(balance, 0.0)


# =============================================================================
#  3.2.1.B — Bilan (actif / passif)
# =============================================================================
@tagged("post_install", "-at_install", "omega_statements", "omega_statements_bilan")
class TestBilan(_FinancialTestCommon):
    """Tests du Bilan : équation comptable, soldes par section."""

    def test_equation_actif_egale_passif(self):
        """Capital 100k + résultat 30k = banque 130k (actif = passif)."""
        wiz0 = self._make_wizard()
        wiz0.action_compute_bilan()
        actif0 = self._find_amount(wiz0.bilan_line_ids, "TOTAL ACTIF") or 0.0

        self._inject_capital(date(2030, 1, 1), 100000.0)
        self._make_revenue(date(2030, 6, 15), 50000.0)
        self._make_expense(date(2030, 7, 20), 20000.0)
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        total_actif = self._find_amount(wiz.bilan_line_ids, "TOTAL ACTIF")
        total_passif = self._find_amount(wiz.bilan_line_ids, "TOTAL PASSIF")
        self.assertAlmostEqual(total_actif, total_passif, places=2)
        self.assertAlmostEqual(total_actif - actif0, 130000.0, places=2)

    def test_banque_dans_tresorerie_actif(self):
        """Le solde banque (514Z) apparaît dans la trésorerie actif."""
        wiz0 = self._make_wizard()
        wiz0.action_compute_bilan()
        tres0 = self._find_amount(wiz0.bilan_line_ids, "Total Trésorerie - Actif") or 0.0

        self._inject_capital(date(2030, 1, 1), 80000.0)
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        total_tres = self._find_amount(wiz.bilan_line_ids, "Total Trésorerie - Actif")
        self.assertAlmostEqual(total_tres - tres0, 80000.0, places=2)

    def test_capital_dans_financement_permanent(self):
        """Le capital social (111Z) apparaît dans les capitaux propres."""
        self._inject_capital(date(2030, 1, 1), 80000.0)
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        capital = self._find_amount(wiz.bilan_line_ids, "Capital social ou personnel")
        self.assertAlmostEqual(capital, 80000.0, places=2)

    def test_fournisseur_dans_passif_circulant(self):
        """Dette fournisseur (441Z) apparaît dans le passif circulant."""
        # Achat à crédit : débit charge / crédit fournisseur
        self._make_move(date(2030, 6, 1), self.account_achat, self.account_fourn, 5000.0)
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        dettes = self._find_amount(wiz.bilan_line_ids, "Dettes du passif circulant")
        self.assertAlmostEqual(dettes, 5000.0, places=2)

    def test_client_dans_actif_circulant(self):
        """Créance client (342Z) apparaît dans l'actif circulant."""
        wiz0 = self._make_wizard()
        wiz0.action_compute_bilan()
        creances0 = self._find_amount(wiz0.bilan_line_ids, "Créances de l'actif circulant (net)") or 0.0

        # Vente à crédit : débit client / crédit produit
        self._make_move(date(2030, 6, 1), self.account_client, self.account_vente, 7000.0)
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        creances = self._find_amount(wiz.bilan_line_ids, "Créances de l'actif circulant (net)")
        self.assertAlmostEqual(creances - creances0, 7000.0, places=2)

    def test_immobilisation_dans_actif_immobilise(self):
        """L'immobilisation (231Z) apparaît dans l'actif immobilisé corporel."""
        self._inject_capital(date(2030, 1, 1), 100000.0)
        self._make_acquisition_immo(date(2030, 2, 1), 30000.0)
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        immo_corp = self._find_amount(wiz.bilan_line_ids, "Immobilisations corporelles (net)")
        self.assertAlmostEqual(immo_corp, 30000.0, places=2)

    def test_resultat_exercice_calcule(self):
        """Le résultat de l'exercice apparaît côté passif (capitaux propres)."""
        wiz0 = self._make_wizard()
        wiz0.action_compute_bilan()
        resultat0 = self._find_amount(wiz0.bilan_line_ids, "Résultat net de l'exercice (±)") or 0.0

        self._inject_capital(date(2030, 1, 1), 100000.0)
        self._make_revenue(date(2030, 6, 1), 50000.0)
        self._make_expense(date(2030, 6, 20), 20000.0)
        wiz = self._make_wizard()
        wiz.action_compute_bilan()
        resultat = self._find_amount(wiz.bilan_line_ids, "Résultat net de l'exercice (±)")
        self.assertAlmostEqual(resultat - resultat0, 30000.0, places=2)


# =============================================================================
#  3.2.1.C — Compte de Résultat (CPC)
# =============================================================================
@tagged("post_install", "-at_install", "omega_statements", "omega_statements_cpc")
class TestCPC(_FinancialTestCommon):
    """Tests du Compte de Produits et Charges (PCGE marocain)."""

    def test_ventes_dans_produits_exploitation(self):
        """Vente 711Z → ligne 'Ventes de marchandises'."""
        self._make_revenue(date(2030, 6, 15), 50000.0)
        wiz = self._make_wizard()
        wiz.action_compute_cpc()
        ventes = self._find_amount(wiz.cpc_line_ids, "Ventes de marchandises")
        self.assertAlmostEqual(ventes, 50000.0, places=2)

    def test_achats_dans_charges_exploitation(self):
        """Achat 611Z → ligne 'Achats revendus de marchandises'."""
        self._make_expense(date(2030, 6, 20), 20000.0)
        wiz = self._make_wizard()
        wiz.action_compute_cpc()
        achats = self._find_amount(wiz.cpc_line_ids, "Achats revendus de marchandises")
        self.assertAlmostEqual(achats, 20000.0, places=2)

    def test_resultat_exploitation_calcule(self):
        """Résultat d'exploitation = Produits − Charges d'exploitation."""
        self._make_revenue(date(2030, 6, 15), 50000.0)
        self._make_expense(date(2030, 6, 20), 20000.0)
        wiz = self._make_wizard()
        wiz.action_compute_cpc()
        res_expl = self._find_amount(wiz.cpc_line_ids, "RÉSULTAT D'EXPLOITATION  (I − II)")
        self.assertAlmostEqual(res_expl, 30000.0, places=2)

    def test_resultat_net_egal_produits_moins_charges(self):
        """Résultat net = produits totaux − charges totales (hors IS dans ce test)."""
        self._make_revenue(date(2030, 6, 15), 50000.0)
        self._make_expense(date(2030, 6, 20), 20000.0)
        wiz = self._make_wizard()
        wiz.action_compute_cpc()
        res_net = self._find_amount(wiz.cpc_line_ids, "RÉSULTAT NET DE L'EXERCICE")
        self.assertAlmostEqual(res_net, 30000.0, places=2)

    def test_cpc_seulement_sur_periode(self):
        """Les mouvements hors période n'apparaissent pas dans le CPC."""
        # Mouvement en 2031 (hors période 2030)
        self._make_revenue(date(2031, 3, 1), 99999.0)
        wiz = self._make_wizard(date_from=date(2030, 1, 1), date_to=date(2030, 12, 31))
        wiz.action_compute_cpc()
        ventes = self._find_amount(wiz.cpc_line_ids, "Ventes de marchandises")
        self.assertAlmostEqual(ventes, 0.0, places=2)

    def test_cpc_perte_quand_charges_superieures(self):
        """Charges > produits ⇒ résultat net négatif (perte)."""
        self._make_revenue(date(2030, 6, 15), 10000.0)
        self._make_expense(date(2030, 6, 20), 30000.0)
        wiz = self._make_wizard()
        wiz.action_compute_cpc()
        res_net = self._find_amount(wiz.cpc_line_ids, "RÉSULTAT NET DE L'EXERCICE")
        self.assertAlmostEqual(res_net, -20000.0, places=2)


# =============================================================================
#  3.2.1.D — Tableau de Flux de Trésorerie
# =============================================================================
@tagged("post_install", "-at_install", "omega_statements", "omega_statements_flux")
class TestFluxTresorerie(_FinancialTestCommon):
    """Tests du Tableau de Flux : A (exploitation), B (investissement), C (financement)."""

    def test_tresorerie_debut_periode(self):
        """La trésorerie début reflète le solde banque avant la période."""
        wiz0 = self._make_wizard(date_from=date(2030, 1, 1), date_to=date(2030, 12, 31))
        wiz0.action_compute_flux()
        tresor0 = self._find_amount(wiz0.flux_line_ids, "Trésorerie nette – début de période") or 0.0

        self._inject_capital(date(2029, 12, 1), 100000.0)
        wiz = self._make_wizard(date_from=date(2030, 1, 1), date_to=date(2030, 12, 31))
        wiz.action_compute_flux()
        tresor_debut = self._find_amount(wiz.flux_line_ids, "Trésorerie nette – début de période")
        self.assertAlmostEqual(tresor_debut - tresor0, 100000.0, places=2)

    def test_tresorerie_fin_periode(self):
        """Trésorerie fin = début + variation totale."""
        wiz0 = self._make_wizard(date_from=date(2030, 1, 1), date_to=date(2030, 12, 31))
        wiz0.action_compute_flux()
        tresor_fin0 = self._find_amount(wiz0.flux_line_ids, "Trésorerie nette – fin de période") or 0.0

        self._inject_capital(date(2029, 12, 1), 100000.0)
        self._make_revenue(date(2030, 6, 15), 50000.0)
        self._make_expense(date(2030, 7, 20), 20000.0)
        wiz = self._make_wizard(date_from=date(2030, 1, 1), date_to=date(2030, 12, 31))
        wiz.action_compute_flux()
        tresor_fin = self._find_amount(wiz.flux_line_ids, "Trésorerie nette – fin de période")
        self.assertAlmostEqual(tresor_fin - tresor_fin0, 130000.0, places=2)

    def test_flux_exploitation_inclut_resultat_net(self):
        """Le flux d'exploitation contient le résultat net de la période."""
        self._make_revenue(date(2030, 6, 15), 50000.0)
        self._make_expense(date(2030, 7, 20), 20000.0)
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        res_net = self._find_amount(wiz.flux_line_ids, "Résultat net de l'exercice")
        self.assertAlmostEqual(res_net, 30000.0, places=2)

    def test_acquisition_immobilisation_dans_flux_investissement(self):
        """Acquisition immo apparaît en sortie de cash dans flux investissement."""
        self._inject_capital(date(2029, 12, 1), 100000.0)
        self._make_acquisition_immo(date(2030, 3, 1), 30000.0)
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        acquisitions = self._find_amount(wiz.flux_line_ids, "Acquisitions d'immobilisations")
        # Signe négatif : sortie de cash
        self.assertAlmostEqual(acquisitions, -30000.0, places=2)

    def test_variation_egale_somme_flux_abc(self):
        """Variation nette = Flux A + B + C."""
        self._inject_capital(date(2029, 12, 1), 100000.0)
        self._make_revenue(date(2030, 6, 15), 50000.0)
        self._make_expense(date(2030, 7, 20), 20000.0)
        self._make_acquisition_immo(date(2030, 3, 1), 10000.0)
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        # Les sous-totaux A/B/C sont désormais portés par les en-têtes de section
        # (cf. _get_flux_lines : plus de lignes « FLUX NET … » redondantes).
        flux_a = self._find_amount(wiz.flux_line_ids, "A.  FLUX DE TRÉSORERIE LIÉ À L'ACTIVITÉ")
        flux_b = self._find_amount(wiz.flux_line_ids, "B.  FLUX DE TRÉSORERIE LIÉ AUX INVESTISSEMENTS")
        flux_c = self._find_amount(wiz.flux_line_ids, "C.  FLUX DE TRÉSORERIE LIÉ AU FINANCEMENT")
        var = self._find_amount(wiz.flux_line_ids, "VARIATION NETTE DE TRÉSORERIE  (A+B+C)")
        self.assertAlmostEqual(var, flux_a + flux_b + flux_c, places=2)

    def test_apport_capital_pendant_periode_dans_flux_financement(self):
        """Augmentation de capital pendant la période ⇒ flux de financement."""
        self._inject_capital(date(2030, 3, 15), 50000.0)
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        aug_cap = self._find_amount(wiz.flux_line_ids, "Augmentations de capital")
        self.assertAlmostEqual(aug_cap, 50000.0, places=2)

    def test_caf_egale_resultat_net_sans_retraitement(self):
        """Sans dotation/reprise/cession, la CAF = résultat net (palier 5220)."""
        self._make_revenue(date(2030, 6, 15), 50000.0)
        self._make_expense(date(2030, 7, 20), 20000.0)
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        res_net = self._find_amount(wiz.flux_line_ids, "Résultat net de l'exercice")
        caf = self._find_amount(wiz.flux_line_ids, "CAPACITÉ D'AUTOFINANCEMENT (CAF)")
        self.assertAlmostEqual(caf, res_net, places=2)
        self.assertAlmostEqual(caf, 30000.0, places=2)

    def test_financement_emprunt_presente_en_brut(self):
        """Émissions et remboursements d'emprunts sur deux lignes distinctes (§5212)."""
        emprunt = self.env["account.account"].create({
            "code": "148Z",
            "name": "Test Emprunt",
            "account_type": "liability_non_current",
            "company_id": self.company.id,
        })
        # Émission : encaissement de l'emprunt (débit banque / crédit emprunt)
        self._make_move(date(2030, 2, 1), self.account_bank, emprunt, 80000.0, ref="Émission emprunt")
        # Remboursement partiel (débit emprunt / crédit banque)
        self._make_move(date(2030, 9, 1), emprunt, self.account_bank, 30000.0, ref="Remboursement emprunt")
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        emissions = self._find_amount(wiz.flux_line_ids, "Émissions d'emprunts")
        remboursements = self._find_amount(wiz.flux_line_ids, "Remboursements d'emprunts")
        self.assertAlmostEqual(emissions, 80000.0, places=2)        # entrée de cash
        self.assertAlmostEqual(remboursements, -30000.0, places=2)  # sortie de cash

    def test_reprise_subvention_neutralisee_dans_caf(self):
        """La reprise de subvention (757), produit non monétaire, est retirée de la CAF."""
        rep_subv_acc = self.env["account.account"].create({
            "code": "757Z",
            "name": "Test Reprise subvention d'investissement",
            "account_type": "income_other",
            "company_id": self.company.id,
        })
        # Quote-part de subvention virée au résultat (crédit 757)
        self._make_move(date(2030, 5, 1), self.account_bank, rep_subv_acc, 10000.0, ref="Reprise subv")
        wiz = self._make_wizard()
        wiz.action_compute_flux()
        ligne = self._find_amount(wiz.flux_line_ids, "Reprise de subvention d'investissement")
        # Neutralisation : le produit non monétaire est soustrait (signe négatif)
        self.assertAlmostEqual(ligne, -10000.0, places=2)


# =============================================================================
#  3.2.1.E — États financiers personnalisables (Report Builder)
# =============================================================================
@tagged("post_install", "-at_install", "omega_statements", "omega_statements_builder")
class TestCustomReportBuilder(_FinancialTestCommon):
    """Tests du moteur de rapports personnalisés (lignes account/formula/section)."""

    def _create_report(self, name="Test Report"):
        return self.env["custom.financial.report"].create({"name": name})

    def _add_line(self, report, **vals):
        defaults = {
            "report_id": report.id,
            "sequence": 10,
            "line_type": "account",
            "name": "Ligne",
        }
        defaults.update(vals)
        return self.env["custom.financial.report.line"].create(defaults)

    def _make_result_wizard(self, report):
        return self.env["custom.report.result.wizard"].create(
            {
                "report_id": report.id,
                "date_from": date(2030, 1, 1),
                "date_to": date(2030, 12, 31),
            }
        )

    # ── Création du template ──────────────────────────────────────────────
    def test_create_report_with_lines(self):
        report = self._create_report()
        self._add_line(report, name="Ligne 1", code="L1", account_prefixes="711")
        self._add_line(report, sequence=20, name="Ligne 2", code="L2", account_prefixes="611")
        self.assertEqual(len(report.line_ids), 2)

    # ── Type 'account' : calcul depuis préfixes ───────────────────────────
    def test_compute_account_line_period(self):
        """Ligne account avec balance_type=period et préfixe 711."""
        self._make_revenue(date(2030, 6, 15), 5000.0)
        report = self._create_report()
        self._add_line(
            report,
            name="Ventes",
            code="VENTES",
            account_prefixes="711",
            sign="-1",
            balance_type="period",
        )
        wiz = self._make_result_wizard(report)
        wiz.action_compute()
        self.assertEqual(len(wiz.result_ids), 1)
        self.assertAlmostEqual(wiz.result_ids[0].amount, 5000.0, places=2)

    def test_compute_account_line_cumul(self):
        """Ligne account avec balance_type=cumul cumule depuis l'origine."""
        # Baseline avant injection
        report0 = self._create_report()
        self._add_line(report0, name="Banque cumul", code="BANK", account_prefixes="514", sign="1", balance_type="cumul")
        wiz0 = self._make_result_wizard(report0)
        wiz0.action_compute()
        baseline = wiz0.result_ids[0].amount if wiz0.result_ids else 0.0

        # Apport en 2029 (avant période du wizard)
        self._inject_capital(date(2029, 6, 1), 100000.0)
        report = self._create_report()
        self._add_line(
            report,
            name="Banque cumul",
            code="BANK",
            account_prefixes="514",
            sign="1",
            balance_type="cumul",
        )
        wiz = self._make_result_wizard(report)
        wiz.action_compute()
        # cumul → inclut l'apport de 2029 même si hors période
        self.assertAlmostEqual(wiz.result_ids[0].amount - baseline, 100000.0, places=2)

    # ── Type 'formula' : safe_eval avec codes de lignes ───────────────────
    def test_compute_formula_line_uses_codes(self):
        """Formule combine les codes des lignes précédentes."""
        self._make_revenue(date(2030, 6, 15), 5000.0)
        self._make_expense(date(2030, 6, 20), 2000.0)
        report = self._create_report()
        self._add_line(
            report,
            sequence=10,
            name="Ventes",
            code="VENTES",
            account_prefixes="711",
            sign="-1",
        )
        self._add_line(
            report,
            sequence=20,
            name="Achats",
            code="ACHATS",
            account_prefixes="611",
            sign="1",
        )
        self._add_line(
            report,
            sequence=30,
            name="Marge",
            code="MARGE",
            line_type="formula",
            formula="VENTES - ACHATS",
        )
        wiz = self._make_result_wizard(report)
        wiz.action_compute()
        results = wiz.result_ids.sorted("sequence")
        self.assertAlmostEqual(results[0].amount, 5000.0, places=2)
        self.assertAlmostEqual(results[1].amount, 2000.0, places=2)
        self.assertAlmostEqual(results[2].amount, 3000.0, places=2)

    def test_formula_with_undefined_code_returns_zero(self):
        """Formule invalide ⇒ pas de crash, amount = 0."""
        report = self._create_report()
        self._add_line(
            report,
            sequence=10,
            name="Bad",
            code="BAD",
            line_type="formula",
            formula="UNKNOWN_CODE * 2",
        )
        wiz = self._make_result_wizard(report)
        wiz.action_compute()
        self.assertAlmostEqual(wiz.result_ids[0].amount, 0.0, places=2)

    def test_formula_safe_eval_blocks_dangerous_calls(self):
        """safe_eval doit bloquer les appels dangereux (RCE)."""
        report = self._create_report()
        self._add_line(
            report,
            sequence=10,
            name="Pwn",
            code="PWN",
            line_type="formula",
            formula='__import__("os").system("echo BAD")',
        )
        wiz = self._make_result_wizard(report)
        # Ne doit pas crasher, ne doit pas exécuter __import__
        wiz.action_compute()
        self.assertAlmostEqual(wiz.result_ids[0].amount, 0.0, places=2)

    # ── Type 'section' : ligne sans montant ───────────────────────────────
    def test_section_line_has_no_amount(self):
        """Une ligne 'section' n'affiche pas de montant (has_amount=False)."""
        report = self._create_report()
        self._add_line(report, sequence=10, name="EN-TÊTE", line_type="section")
        wiz = self._make_result_wizard(report)
        wiz.action_compute()
        self.assertEqual(len(wiz.result_ids), 1)
        self.assertFalse(wiz.result_ids[0].has_amount)

    def test_spacer_line_has_no_amount(self):
        """Une ligne 'spacer' n'affiche pas de montant."""
        report = self._create_report()
        self._add_line(report, sequence=10, name=" ", line_type="spacer")
        wiz = self._make_result_wizard(report)
        wiz.action_compute()
        self.assertFalse(wiz.result_ids[0].has_amount)

    # ── Préservation de l'ordre / sequence ────────────────────────────────
    def test_lines_respect_sequence(self):
        """Les résultats respectent la séquence définie sur les lignes."""
        report = self._create_report()
        self._add_line(report, sequence=30, name="Troisième", code="C", account_prefixes="711")
        self._add_line(report, sequence=10, name="Premier", code="A", account_prefixes="611")
        self._add_line(report, sequence=20, name="Deuxième", code="B", account_prefixes="514")
        wiz = self._make_result_wizard(report)
        wiz.action_compute()
        ordered_names = wiz.result_ids.sorted("sequence").mapped("name")
        self.assertEqual(ordered_names, ["Premier", "Deuxième", "Troisième"])

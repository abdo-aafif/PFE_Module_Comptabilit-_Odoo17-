# -*- coding: utf-8 -*-
"""Suite de tests fonctionnels — section 3.2.2 du CDC : Gestion des Immobilisations.

Couverture :
    * Fiche immobilisation (acquisition, mise en service, catégorie, comptes obligatoires)
    * Calcul automatique des amortissements (linéaire + dégressif CGI marocain)
    * Tableau d'amortissement (dates, séquence, méthode, comptabilisation)
    * Cession / mise au rebut (wizard : VNC, plus/moins-value, écritures)
"""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import Form, TransactionCase, tagged


# =============================================================================
#  Base partagée : comptes + journal + catégorie + helpers
# =============================================================================
class _AssetTestCommon(TransactionCase):
    """Setup partagé : comptes (immo, amort, dotation, gain, perte, clients
    divers), journal général, catégorie d'immobilisation et helpers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        Account = cls.env["account.account"]
        cls.account_immo = Account.create(
            {
                "code": "T2340",
                "name": "Test Matériel de transport",
                "account_type": "asset_fixed",
                "company_id": cls.company.id,
            }
        )
        cls.account_amort = Account.create(
            {
                "code": "T2834",
                "name": "Test Amort. matériel de transport",
                "account_type": "asset_fixed",
                "company_id": cls.company.id,
            }
        )
        cls.account_dotation = Account.create(
            {
                "code": "T6194",
                "name": "Test Dotations amort.",
                "account_type": "expense_depreciation",
                "company_id": cls.company.id,
            }
        )
        cls.account_gain = Account.create(
            {
                "code": "T7513",
                "name": "Test Produit de cession des immo",
                "account_type": "income_other",
                "company_id": cls.company.id,
            }
        )
        cls.account_loss = Account.create(
            {
                "code": "T6513",
                "name": "Test VNA des immo cédées",
                "account_type": "expense",
                "company_id": cls.company.id,
            }
        )
        cls.account_clients_divers = Account.create(
            {
                "code": "T3481",
                "name": "Test Clients divers (cession)",
                "account_type": "asset_receivable",
                "reconcile": True,
                "company_id": cls.company.id,
            }
        )

        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", cls.company.id)],
            limit=1,
        )

        cls.category = cls.env["account.asset.category"].create(
            {
                "name": "Test Véhicules",
                "code": "TVEH",
                "account_asset_id": cls.account_immo.id,
                "account_depreciation_id": cls.account_amort.id,
                "account_expense_id": cls.account_dotation.id,
                "account_gain_id": cls.account_gain.id,
                "account_loss_id": cls.account_loss.id,
                "journal_id": cls.journal.id,
                "method": "linear",
                "duration_years": 5,
            }
        )

    # ── Helpers ──────────────────────────────────────────────────────────
    def _make_asset(self, **overrides):
        """Crée une immobilisation avec tous les champs et comptes nécessaires."""
        vals = {
            "name": "Véhicule test",
            "category_id": self.category.id,
            "acquisition_date": date(2025, 1, 1),
            "commissioning_date": date(2025, 1, 1),
            "acquisition_value": 100000.0,
            "method": "linear",
            "duration_years": 5,
            "account_asset_id": self.account_immo.id,
            "account_depreciation_id": self.account_amort.id,
            "account_expense_id": self.account_dotation.id,
            "account_gain_id": self.account_gain.id,
            "account_loss_id": self.account_loss.id,
            "journal_id": self.journal.id,
        }
        vals.update(overrides)
        return self.env["account.asset"].create(vals)

    def _make_validated_asset(self, **overrides):
        asset = self._make_asset(**overrides)
        asset.action_validate()
        return asset


# =============================================================================
#  3.2.2.A — Calcul automatique des amortissements (linéaire + dégressif)
# =============================================================================
@tagged("post_install", "-at_install", "omega_assets", "omega_assets_compute")
class TestAssetDepreciation(_AssetTestCommon):
    """Tests des algorithmes d'amortissement linéaire et dégressif (CGI marocain)."""

    # ── Linéaire ──────────────────────────────────────────────────────────
    def test_linear_full_year_5_years(self):
        """Linéaire 100 000 / 5 ans, mise en service 01/01 : 5 lignes de 20 000."""
        asset = self._make_asset()
        asset.action_compute_depreciation()
        lines = asset.depreciation_line_ids.sorted("sequence")
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertAlmostEqual(line.depreciation_amount, 20000.0, places=2)
        self.assertAlmostEqual(sum(lines.mapped("depreciation_amount")), 100000.0, places=2)

    def test_linear_prorata_first_year(self):
        """Linéaire avec prorata : mise en service 01/07 → 1ère année 6/12."""
        asset = self._make_asset(
            acquisition_date=date(2025, 7, 1),
            commissioning_date=date(2025, 7, 1),
        )
        asset.action_compute_depreciation()
        lines = asset.depreciation_line_ids.sorted("sequence")
        self.assertGreaterEqual(len(lines), 5)
        self.assertAlmostEqual(sum(lines.mapped("depreciation_amount")), 100000.0, places=2)
        self.assertAlmostEqual(lines[0].depreciation_amount, 10000.0, places=2)

    def test_linear_residual_value(self):
        """Valeur résiduelle 10 000 → base amortissable = 90 000."""
        asset = self._make_asset(residual_value=10000.0)
        asset.action_compute_depreciation()
        lines = asset.depreciation_line_ids
        self.assertAlmostEqual(sum(lines.mapped("depreciation_amount")), 90000.0, places=2)

    # ── Dégressif (CGI Marocain) ──────────────────────────────────────────
    def test_degressive_coefficient_5_years(self):
        """Dégressif sur 5 ans → coefficient = 2,0 (CGI art. 7)."""
        asset = self._make_asset(method="degressive", duration_years=5)
        asset.action_compute_depreciation()
        lines = asset.depreciation_line_ids.sorted("sequence")
        # 1ère dotation = 100 000 × (1/5 × 2) = 40 000
        self.assertAlmostEqual(lines[0].depreciation_amount, 40000.0, places=2)
        self.assertAlmostEqual(sum(lines.mapped("depreciation_amount")), 100000.0, places=2)

    def test_degressive_coefficient_3_years(self):
        """Dégressif ≤ 4 ans → coefficient = 1,5."""
        asset = self._make_asset(method="degressive", duration_years=3)
        asset.action_compute_depreciation()
        lines = asset.depreciation_line_ids.sorted("sequence")
        # 1ère dotation = 100 000 × (1/3 × 1,5) = 50 000
        self.assertAlmostEqual(lines[0].depreciation_amount, 50000.0, places=2)
        self.assertAlmostEqual(sum(lines.mapped("depreciation_amount")), 100000.0, places=2)

    def test_degressive_coefficient_long_duration(self):
        """Dégressif > 6 ans → coefficient = 3,0."""
        asset = self._make_asset(method="degressive", duration_years=10)
        asset.action_compute_depreciation()
        lines = asset.depreciation_line_ids.sorted("sequence")
        # 1ère dotation = 100 000 × (1/10 × 3) = 30 000
        self.assertAlmostEqual(lines[0].depreciation_amount, 30000.0, places=2)

    def test_degressive_switch_to_linear(self):
        """Le basculement automatique au linéaire se produit en fin de période."""
        asset = self._make_asset(method="degressive", duration_years=5)
        asset.action_compute_depreciation()
        methods = asset.depreciation_line_ids.mapped("method_used")
        self.assertIn(
            "linear_switch",
            methods,
            "Le tableau dégressif doit basculer au linéaire en fin de période.",
        )

    # ── Contraintes (fiche immobilisation) ────────────────────────────────
    def test_negative_acquisition_value_raises(self):
        with self.assertRaises(ValidationError):
            self._make_asset(acquisition_value=-1000.0)

    def test_zero_acquisition_value_raises(self):
        with self.assertRaises(ValidationError):
            self._make_asset(acquisition_value=0.0)

    def test_negative_residual_value_raises(self):
        with self.assertRaises(ValidationError):
            self._make_asset(residual_value=-100.0)

    def test_residual_greater_than_acquisition_raises(self):
        with self.assertRaises(ValidationError):
            self._make_asset(acquisition_value=10000.0, residual_value=15000.0)

    def test_commissioning_before_acquisition_raises(self):
        with self.assertRaises(ValidationError):
            self._make_asset(
                acquisition_date=date(2025, 6, 1),
                commissioning_date=date(2025, 1, 1),
            )

    def test_zero_duration_raises(self):
        with self.assertRaises(ValidationError):
            self._make_asset(duration_years=0)

    # ── Workflow ──────────────────────────────────────────────────────────
    def test_validate_changes_state_to_open(self):
        asset = self._make_asset()
        asset.action_validate()
        self.assertEqual(asset.state, "open")
        self.assertTrue(asset.depreciation_line_ids)

    def test_compute_values_after_posting_one_line(self):
        asset = self._make_asset()
        asset.action_validate()
        first_line = asset.depreciation_line_ids.sorted("sequence")[0]
        first_line.action_post()
        asset.invalidate_recordset(["value_depreciated", "value_residual"])
        self.assertAlmostEqual(asset.value_depreciated, 20000.0, places=2)
        self.assertAlmostEqual(asset.value_residual, 80000.0, places=2)


# =============================================================================
#  3.2.2.B — Fiche immobilisation : catégorie et comptes obligatoires
# =============================================================================
@tagged("post_install", "-at_install", "omega_assets", "omega_assets_category")
class TestAssetCategory(_AssetTestCommon):
    """La catégorie pré-remplit les comptes et la méthode lors de l'onchange."""

    def _new_form(self):
        form = Form(self.env["account.asset"])
        form.name = "Asset via Form"
        form.acquisition_date = date(2025, 1, 1)
        form.commissioning_date = date(2025, 1, 1)
        form.acquisition_value = 50000.0
        return form

    def test_category_propage_comptes(self):
        """Sélection de la catégorie → tous les comptes propagés sur la fiche."""
        form = self._new_form()
        form.category_id = self.category
        asset = form.save()
        self.assertEqual(asset.account_asset_id, self.account_immo)
        self.assertEqual(asset.account_depreciation_id, self.account_amort)
        self.assertEqual(asset.account_expense_id, self.account_dotation)
        self.assertEqual(asset.account_gain_id, self.account_gain)
        self.assertEqual(asset.account_loss_id, self.account_loss)
        self.assertEqual(asset.journal_id, self.journal)

    def test_category_propage_methode_et_duree(self):
        """Méthode et durée par défaut héritées de la catégorie."""
        cat_degressive = self.env["account.asset.category"].create(
            {
                "name": "Test Mat. Industriel",
                "account_asset_id": self.account_immo.id,
                "account_depreciation_id": self.account_amort.id,
                "account_expense_id": self.account_dotation.id,
                "journal_id": self.journal.id,
                "method": "degressive",
                "duration_years": 8,
            }
        )
        form = self._new_form()
        form.category_id = cat_degressive
        asset = form.save()
        self.assertEqual(asset.method, "degressive")
        self.assertEqual(asset.duration_years, 8)

    def test_validate_sans_journal_raises(self):
        """`_check_required_accounts` : journal obligatoire pour valider."""
        asset = self._make_asset()
        asset.journal_id = False
        with self.assertRaises(UserError):
            asset.action_validate()

    def test_validate_sans_compte_dotation_raises(self):
        """`_check_required_accounts` : compte de dotation obligatoire."""
        asset = self._make_asset()
        asset.account_expense_id = False
        with self.assertRaises(UserError):
            asset.action_validate()

    def test_validate_sans_compte_amortissement_raises(self):
        asset = self._make_asset()
        asset.account_depreciation_id = False
        with self.assertRaises(UserError):
            asset.action_validate()


# =============================================================================
#  3.2.2.C — Tableau d'amortissement (contenu détaillé)
# =============================================================================
@tagged("post_install", "-at_install", "omega_assets", "omega_assets_schedule")
class TestAssetSchedule(_AssetTestCommon):
    """Structure du tableau : dates, séquences, méthode, VNC progressive."""

    def test_dates_fin_exercice(self):
        """Linéaire : chaque ligne tombe au 31/12 de l'année concernée."""
        asset = self._make_validated_asset()
        lines = asset.depreciation_line_ids.sorted("sequence")
        for idx, line in enumerate(lines):
            self.assertEqual(
                line.depreciation_date,
                date(2025 + idx, 12, 31),
                f"Ligne {line.sequence} : date attendue 31/12/{2025 + idx}",
            )

    def test_sequence_croissante(self):
        """Les séquences sont 1, 2, 3, ... sans trou."""
        asset = self._make_validated_asset()
        sequences = asset.depreciation_line_ids.sorted("sequence").mapped("sequence")
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)))

    def test_cumul_amortissements_progresse(self):
        """``cumulated_amount`` doit croître monotonement jusqu'à la base."""
        asset = self._make_validated_asset()
        lines = asset.depreciation_line_ids.sorted("sequence")
        precedent = 0.0
        for line in lines:
            self.assertGreaterEqual(line.cumulated_amount, precedent)
            precedent = line.cumulated_amount
        # Dernière ligne : cumul = valeur d'acquisition (résiduelle = 0)
        self.assertAlmostEqual(lines[-1].cumulated_amount, 100000.0, places=2)

    def test_vnc_decroit_jusqu_a_residuelle(self):
        """``remaining_value`` (VNC fiche) décroît et finit à la valeur résiduelle."""
        asset = self._make_validated_asset(residual_value=5000.0)
        lines = asset.depreciation_line_ids.sorted("sequence")
        for i in range(1, len(lines)):
            self.assertLessEqual(lines[i].remaining_value, lines[i - 1].remaining_value)
        self.assertAlmostEqual(lines[-1].remaining_value, 5000.0, places=2)

    def test_method_used_linear_marker(self):
        """Toutes les lignes d'un linéaire portent ``method_used='linear'``."""
        asset = self._make_validated_asset()
        for line in asset.depreciation_line_ids:
            self.assertEqual(line.method_used, "linear")

    def test_method_used_degressive_mixte(self):
        """Dégressif : un mélange ``degressive`` + ``linear_switch`` en fin."""
        asset = self._make_validated_asset(method="degressive", duration_years=5)
        used = asset.depreciation_line_ids.mapped("method_used")
        self.assertIn("degressive", used)
        self.assertIn("linear_switch", used)

    def test_depreciation_count_field(self):
        """Le compteur calculé renvoie le nombre de lignes."""
        asset = self._make_validated_asset()
        self.assertEqual(asset.depreciation_count, len(asset.depreciation_line_ids))


# =============================================================================
#  3.2.2.D — Comptabilisation des dotations (action_post / action_unpost)
# =============================================================================
@tagged("post_install", "-at_install", "omega_assets", "omega_assets_posting")
class TestDepreciationPosting(_AssetTestCommon):
    """Comptabilisation d'une dotation : écriture équilibrée + clôture auto."""

    def test_action_post_creates_balanced_move(self):
        """L'écriture produite est équilibrée (débit = crédit)."""
        asset = self._make_validated_asset()
        ligne = asset.depreciation_line_ids.sorted("sequence")[0]
        ligne.action_post()
        move = ligne.move_id
        self.assertTrue(move)
        total_debit = sum(move.line_ids.mapped("debit"))
        total_credit = sum(move.line_ids.mapped("credit"))
        self.assertAlmostEqual(total_debit, total_credit, places=2)
        self.assertAlmostEqual(total_debit, 20000.0, places=2)

    def test_action_post_uses_correct_accounts(self):
        """Débit compte de dotation (619x) / crédit compte d'amort. (28xx)."""
        asset = self._make_validated_asset()
        ligne = asset.depreciation_line_ids.sorted("sequence")[0]
        ligne.action_post()
        debits = ligne.move_id.line_ids.filtered(lambda ln: ln.debit > 0)
        credits = ligne.move_id.line_ids.filtered(lambda ln: ln.credit > 0)
        self.assertEqual(debits.account_id, self.account_dotation)
        self.assertEqual(credits.account_id, self.account_amort)

    def test_action_post_sets_state_and_move_id(self):
        """Après comptabilisation : ``state='posted'`` et ``move_id`` renseigné."""
        asset = self._make_validated_asset()
        ligne = asset.depreciation_line_ids.sorted("sequence")[0]
        ligne.action_post()
        self.assertEqual(ligne.state, "posted")
        self.assertTrue(ligne.move_id)
        self.assertEqual(ligne.move_id.state, "posted")

    def test_action_post_deja_posted_raises(self):
        """Tentative de double comptabilisation ⇒ UserError."""
        asset = self._make_validated_asset()
        ligne = asset.depreciation_line_ids.sorted("sequence")[0]
        ligne.action_post()
        with self.assertRaises(UserError):
            ligne.action_post()

    def test_all_lines_posted_closes_asset(self):
        """Toutes les dotations comptabilisées ⇒ l'actif passe à 'close'."""
        asset = self._make_validated_asset()
        for ligne in asset.depreciation_line_ids.sorted("sequence"):
            ligne.action_post()
        self.assertEqual(asset.state, "close")

    def test_unpost_reopens_close_asset(self):
        """Annuler la dernière ligne d'un actif clôturé le ramène à 'open'."""
        asset = self._make_validated_asset()
        for ligne in asset.depreciation_line_ids.sorted("sequence"):
            ligne.action_post()
        self.assertEqual(asset.state, "close")
        derniere = asset.depreciation_line_ids.sorted("sequence")[-1]
        derniere.action_unpost()
        self.assertEqual(derniere.state, "draft")
        self.assertEqual(asset.state, "open")

    def test_set_draft_bloque_si_lignes_postees(self):
        """``action_set_draft`` refuse si des lignes sont comptabilisées."""
        asset = self._make_validated_asset()
        asset.depreciation_line_ids.sorted("sequence")[0].action_post()
        with self.assertRaises(UserError):
            asset.action_set_draft()

    def test_recompute_bloque_si_lignes_postees(self):
        """``action_compute_depreciation`` refuse de recalculer après comptabilisation."""
        asset = self._make_validated_asset()
        asset.depreciation_line_ids.sorted("sequence")[0].action_post()
        with self.assertRaises(UserError):
            asset.action_compute_depreciation()


# =============================================================================
#  3.2.2.E — Cession / Mise au rebut (wizard)
# =============================================================================
@tagged("post_install", "-at_install", "omega_assets", "omega_assets_disposal")
class TestAssetDisposal(_AssetTestCommon):
    """Wizard ``account.asset.disposal.wizard`` : VNC, +/- value, écriture."""

    def _make_wizard(self, asset, **vals):
        defaults = {
            "asset_id": asset.id,
            "disposal_date": date(2027, 12, 31),
            "disposal_type": "sale",
            "sale_price": 0.0,
            "account_receivable_id": self.account_clients_divers.id,
        }
        defaults.update(vals)
        return self.env["account.asset.disposal.wizard"].create(defaults)

    def _post_lines_until(self, asset, last_sequence):
        """Comptabilise les lignes 1..last_sequence (inclus) dans l'ordre."""
        for ligne in asset.depreciation_line_ids.sorted("sequence"):
            if ligne.sequence <= last_sequence:
                ligne.action_post()

    # ── Calcul VNC ────────────────────────────────────────────────────────
    def test_wizard_vnc_aucune_dotation_postee(self):
        """Sans dotation comptabilisée : VNC = valeur d'acquisition."""
        asset = self._make_validated_asset()
        wiz = self._make_wizard(asset, disposal_date=date(2025, 6, 30))
        self.assertAlmostEqual(wiz.vnc, 100000.0, places=2)
        self.assertAlmostEqual(wiz.value_depreciated, 0.0, places=2)

    def test_wizard_vnc_apres_2_dotations_postees(self):
        """2 dotations × 20 000 comptabilisées : VNC = 60 000."""
        asset = self._make_validated_asset()
        self._post_lines_until(asset, 2)
        wiz = self._make_wizard(asset)
        self.assertAlmostEqual(wiz.value_depreciated, 40000.0, places=2)
        self.assertAlmostEqual(wiz.vnc, 60000.0, places=2)

    # ── Résultat (plus/moins-value) ───────────────────────────────────────
    def test_wizard_resultat_plus_value(self):
        """Prix de cession > VNC ⇒ plus-value."""
        asset = self._make_validated_asset()
        self._post_lines_until(asset, 3)  # VNC = 40 000
        wiz = self._make_wizard(asset, sale_price=70000.0)
        self.assertAlmostEqual(wiz.result_amount, 30000.0, places=2)
        self.assertEqual(wiz.result_type, "gain")

    def test_wizard_resultat_moins_value(self):
        """Prix de cession < VNC ⇒ moins-value."""
        asset = self._make_validated_asset()
        self._post_lines_until(asset, 2)  # VNC = 60 000
        wiz = self._make_wizard(asset, sale_price=40000.0)
        self.assertAlmostEqual(wiz.result_amount, -20000.0, places=2)
        self.assertEqual(wiz.result_type, "loss")

    def test_wizard_resultat_neutre(self):
        """Prix de cession = VNC ⇒ résultat neutre."""
        asset = self._make_validated_asset()
        self._post_lines_until(asset, 2)  # VNC = 60 000
        wiz = self._make_wizard(asset, sale_price=60000.0)
        self.assertAlmostEqual(wiz.result_amount, 0.0, places=2)
        self.assertEqual(wiz.result_type, "zero")

    def test_wizard_rebut_perte_egale_vnc(self):
        """Mise au rebut ⇒ perte = VNC entière."""
        asset = self._make_validated_asset()
        self._post_lines_until(asset, 2)  # VNC = 60 000
        wiz = self._make_wizard(asset, disposal_type="rebut")
        self.assertAlmostEqual(wiz.result_amount, -60000.0, places=2)

    # ── Action dispose : transition d'état ───────────────────────────────
    def test_dispose_change_state_to_disposed(self):
        """Après ``action_dispose`` : état = 'disposed' + date enregistrée."""
        asset = self._make_validated_asset()
        wiz = self._make_wizard(asset, sale_price=50000.0)
        wiz.action_dispose()
        self.assertEqual(asset.state, "disposed")
        self.assertEqual(asset.disposal_date, date(2027, 12, 31))

    def test_dispose_cree_disposal_move(self):
        """Une écriture comptable est créée et liée à l'actif."""
        asset = self._make_validated_asset()
        wiz = self._make_wizard(asset, sale_price=50000.0)
        wiz.action_dispose()
        self.assertTrue(asset.disposal_move_id)
        self.assertEqual(asset.disposal_move_id.state, "posted")

    # ── Action dispose : équilibre & comptes ──────────────────────────────
    def test_dispose_move_equilibre_cession(self):
        """L'écriture de cession est équilibrée (débit = crédit)."""
        asset = self._make_validated_asset()
        wiz = self._make_wizard(asset, sale_price=70000.0)
        wiz.action_dispose()
        move = asset.disposal_move_id
        total_debit = sum(move.line_ids.mapped("debit"))
        total_credit = sum(move.line_ids.mapped("credit"))
        self.assertAlmostEqual(total_debit, total_credit, places=2)

    def test_dispose_move_equilibre_rebut(self):
        """Mise au rebut : écriture équilibrée également."""
        asset = self._make_validated_asset()
        wiz = self._make_wizard(asset, disposal_type="rebut")
        wiz.action_dispose()
        move = asset.disposal_move_id
        total_debit = sum(move.line_ids.mapped("debit"))
        total_credit = sum(move.line_ids.mapped("credit"))
        self.assertAlmostEqual(total_debit, total_credit, places=2)

    def test_dispose_cession_credite_compte_immo(self):
        """Le compte d'immobilisation est soldé (crédit = valeur d'acquisition)."""
        asset = self._make_validated_asset()
        wiz = self._make_wizard(asset, sale_price=50000.0)
        wiz.action_dispose()
        immo_lines = asset.disposal_move_id.line_ids.filtered(lambda ln: ln.account_id == self.account_immo)
        self.assertAlmostEqual(sum(immo_lines.mapped("credit")), 100000.0, places=2)

    def test_dispose_rebut_pas_de_produit_cession(self):
        """Mise au rebut : pas de ligne sur le compte 7513 (produit de cession)."""
        asset = self._make_validated_asset()
        wiz = self._make_wizard(asset, disposal_type="rebut")
        wiz.action_dispose()
        gain_lines = asset.disposal_move_id.line_ids.filtered(lambda ln: ln.account_id == self.account_gain)
        self.assertFalse(gain_lines)

    # ── Action dispose : comptabilisation des lignes pendantes ────────────
    def test_dispose_comptabilise_lignes_pendantes(self):
        """Les lignes draft antérieures à la date de cession sont posted."""
        asset = self._make_validated_asset()
        # Aucune ligne postée — disposal date = 2027-12-31
        # Lignes 1 (2025), 2 (2026), 3 (2027) doivent être comptabilisées
        wiz = self._make_wizard(asset, sale_price=40000.0)
        wiz.action_dispose()
        # On compte les lignes encore présentes et leur état
        lignes_postees = asset.depreciation_line_ids.filtered(lambda ln: ln.state == "posted")
        self.assertEqual(len(lignes_postees), 3)
        # Lignes 4 et 5 (2028, 2029) doivent avoir été supprimées
        self.assertEqual(len(asset.depreciation_line_ids), 3)

    def test_dispose_prorata_annee_cession(self):
        """Cession en milieu d'année : la dotation de l'année est prorata temporis."""
        asset = self._make_validated_asset()
        # Cession au 30/06/2027 ⇒ dotation 2027 = 20 000 × 6/12 = 10 000
        wiz = self._make_wizard(
            asset,
            disposal_date=date(2027, 6, 30),
            sale_price=50000.0,
        )
        wiz.action_dispose()
        lignes = asset.depreciation_line_ids.sorted("sequence")
        # Lignes 1 (2025), 2 (2026) entières + 3 prorata 6 mois
        self.assertEqual(len(lignes), 3)
        self.assertAlmostEqual(lignes[0].depreciation_amount, 20000.0, places=2)
        self.assertAlmostEqual(lignes[1].depreciation_amount, 20000.0, places=2)
        self.assertAlmostEqual(lignes[2].depreciation_amount, 10000.0, places=2)
        self.assertEqual(lignes[2].depreciation_date, date(2027, 6, 30))

    # ── Action dispose : garde-fou ────────────────────────────────────────
    def test_dispose_bloque_si_actif_en_brouillon(self):
        """Cession refusée si l'actif n'est pas 'En service' ou 'Clôturé'."""
        asset = self._make_asset()  # reste en 'draft'
        wiz = self._make_wizard(asset, sale_price=50000.0)
        with self.assertRaises(UserError):
            wiz.action_dispose()

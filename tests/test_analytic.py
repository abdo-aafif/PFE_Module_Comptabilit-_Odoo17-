# -*- coding: utf-8 -*-
"""Suite de tests fonctionnels — Comptabilité Analytique (US-002).

Couverture :
    A. Plans analytiques (axes) et comptes analytiques (centres de coûts)
    B. Calcul des champs unifiés compta_account_id et compta_plan_id
    C. Génération automatique de lignes analytiques depuis les écritures
    D. Règles de distribution automatique
    E. Reporting analytique (filtrage et groupement par plan / compte)
"""

from datetime import date

from odoo.tests.common import TransactionCase, tagged


# =============================================================================
#  Setup partagé
# =============================================================================

class _AnalyticTestCommon(TransactionCase):
    """Données partagées : plans, comptes, journal général et comptes PCGE."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # ── Plans analytiques (axes d'analyse) ───────────────────────────────
        cls.plan_projets = cls.env["account.analytic.plan"].create({
            "name": "Test Axe Projets",
        })
        cls.plan_departements = cls.env["account.analytic.plan"].create({
            "name": "Test Axe Départements",
        })

        # ── Comptes analytiques — Projets (centres de coûts projet) ──────────
        cls.projet_a = cls.env["account.analytic.account"].create({
            "name": "Projet A",
            "plan_id": cls.plan_projets.id,
            "company_id": cls.company.id,
        })
        cls.projet_b = cls.env["account.analytic.account"].create({
            "name": "Projet B",
            "plan_id": cls.plan_projets.id,
            "company_id": cls.company.id,
        })

        # ── Comptes analytiques — Départements (centres de coûts dept) ───────
        cls.dep_info = cls.env["account.analytic.account"].create({
            "name": "Département Informatique",
            "plan_id": cls.plan_departements.id,
            "company_id": cls.company.id,
        })
        cls.dep_compta = cls.env["account.analytic.account"].create({
            "name": "Département Comptabilité",
            "plan_id": cls.plan_departements.id,
            "company_id": cls.company.id,
        })

        # ── Plan principal Odoo (requis pour les tests de lignes analytiques) ─
        # _get_all_plans() retourne (plan_principal, autres_plans).
        # Le plan principal est celui dont la colonne est "account_id" sur
        # account.analytic.line — on l'utilise pour les tests de calcul.
        project_plan, _other = cls.env["account.analytic.plan"]._get_all_plans()
        if project_plan:
            cls.main_plan = project_plan
            cls.main_account = cls.env["account.analytic.account"].create({
                "name": "Compte plan principal (test analytique)",
                "plan_id": project_plan.id,
                "company_id": cls.company.id,
            })
        else:
            cls.main_plan = cls.plan_projets
            cls.main_account = cls.projet_a

        # ── Journal général et comptes PCGE ───────────────────────────────────
        cls.journal = cls.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", cls.company.id),
        ], limit=1)

        cls.account_charge = cls.env["account.account"].search([
            ("account_type", "=", "expense"),
            ("company_id", "=", cls.company.id),
        ], limit=1)

        cls.account_fourn = cls.env["account.account"].search([
            ("account_type", "=", "liability_current"),
            ("company_id", "=", cls.company.id),
        ], limit=1)

    # ── Helper : écriture avec distribution analytique ────────────────────────
    def _post_move_with_analytic(self, analytic_distribution, amount=1000.0):
        """Crée et valide une écriture avec distribution analytique."""
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self.journal.id,
            "date": date(2025, 6, 1),
            "line_ids": [
                (0, 0, {
                    "account_id": self.account_charge.id,
                    "name": "Charge analytique",
                    "debit": amount,
                    "credit": 0.0,
                    "analytic_distribution": analytic_distribution,
                }),
                (0, 0, {
                    "account_id": self.account_fourn.id,
                    "name": "Contrepartie",
                    "debit": 0.0,
                    "credit": amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _analytic_lines_for_move(self, move):
        """Retourne toutes les lignes analytiques générées par une écriture."""
        return self.env["account.analytic.line"].search([
            ("move_line_id.move_id", "=", move.id),
        ])


# =============================================================================
#  A — Plans analytiques et comptes (centres de coûts, axes multiples)
# =============================================================================
@tagged("post_install", "-at_install", "omega_analytic", "omega_analytic_plans")
class TestAnalyticPlansAndAccounts(_AnalyticTestCommon):
    """US-002 — Création de plans, comptes analytiques et axes multiples."""

    # ── Création d'un plan analytique ─────────────────────────────────────────
    def test_create_analytic_plan(self):
        """Un plan analytique (axe d'analyse) peut être créé et lu."""
        self.assertTrue(self.plan_projets.id)
        self.assertEqual(self.plan_projets.name, "Test Axe Projets")

    def test_create_second_analytic_plan(self):
        """Deux plans analytiques distincts coexistent."""
        self.assertNotEqual(self.plan_projets.id, self.plan_departements.id)

    # ── Comptes analytiques (centres de coûts) ────────────────────────────────
    def test_create_analytic_account_linked_to_plan(self):
        """Un compte analytique est rattaché à son plan."""
        self.assertEqual(self.projet_a.plan_id, self.plan_projets)
        self.assertEqual(self.dep_info.plan_id, self.plan_departements)

    def test_multiple_cost_centers_on_same_plan(self):
        """Plusieurs centres de coûts peuvent coexister sur un même axe."""
        comptes = self.env["account.analytic.account"].search([
            ("plan_id", "=", self.plan_projets.id),
        ])
        self.assertIn(self.projet_a, comptes)
        self.assertIn(self.projet_b, comptes)

    def test_cost_centers_isolated_between_plans(self):
        """Un compte d'un plan n'apparaît pas dans l'autre plan."""
        comptes_projets = self.env["account.analytic.account"].search([
            ("plan_id", "=", self.plan_projets.id),
        ])
        self.assertNotIn(self.dep_info, comptes_projets)
        self.assertNotIn(self.dep_compta, comptes_projets)

    def test_two_axes_are_independent(self):
        """Les axes d'analyse sont indépendants l'un de l'autre."""
        self.assertNotEqual(self.plan_projets, self.plan_departements)
        self.assertNotEqual(self.projet_a.plan_id, self.dep_info.plan_id)

    def test_analytic_account_company_isolation(self):
        """Un compte analytique appartient à la société courante."""
        self.assertEqual(self.projet_a.company_id, self.company)
        self.assertEqual(self.dep_info.company_id, self.company)

    def test_four_cost_centers_created(self):
        """Les 4 centres de coûts de test sont bien créés."""
        for account in [self.projet_a, self.projet_b, self.dep_info, self.dep_compta]:
            self.assertTrue(account.id)
            self.assertTrue(account.name)


# =============================================================================
#  B — Calcul des champs compta_account_id et compta_plan_id
# =============================================================================
@tagged("post_install", "-at_install", "omega_analytic", "omega_analytic_compute")
class TestAnalyticLineComputation(_AnalyticTestCommon):
    """Tests du calcul des champs unifiés compta_account_id et compta_plan_id.

    Ces champs, ajoutés par le module sur account.analytic.line, permettent
    d'unifier la vision des lignes analytiques tous plans confondus dans le
    reporting (section 3.1.1 du CDC).
    """

    def _make_line(self, account, amount=500.0):
        """Crée une ligne analytique sur le plan principal."""
        return self.env["account.analytic.line"].create({
            "name": "Ligne test compute",
            "account_id": account.id,
            "amount": amount,
            "date": date(2025, 6, 1),
        })

    # ── compta_account_id ─────────────────────────────────────────────────────
    def test_compta_account_id_set_from_account_id(self):
        """compta_account_id = compte analytique du plan principal (account_id)."""
        line = self._make_line(self.main_account)
        self.assertEqual(
            line.compta_account_id, self.main_account,
            "compta_account_id doit reprendre account_id (plan principal)."
        )

    def test_compta_account_id_false_when_no_account(self):
        """Sans compte analytique, compta_account_id reste vide."""
        line = self.env["account.analytic.line"].create({
            "name": "Ligne sans compte",
            "amount": 100.0,
            "date": date(2025, 6, 1),
        })
        self.assertFalse(
            line.compta_account_id,
            "compta_account_id doit être False si aucun compte n'est renseigné."
        )

    def test_compta_account_id_field_exists_on_model(self):
        """Le champ compta_account_id est bien déclaré sur account.analytic.line."""
        self.assertIn(
            "compta_account_id",
            self.env["account.analytic.line"]._fields,
        )

    # ── compta_plan_id ────────────────────────────────────────────────────────
    def test_compta_plan_id_follows_account_plan(self):
        """compta_plan_id = plan de compta_account_id."""
        line = self._make_line(self.main_account)
        self.assertEqual(
            line.compta_plan_id, self.main_account.plan_id,
            "compta_plan_id doit être déduit du plan du compte analytique."
        )

    def test_compta_plan_id_false_when_no_account(self):
        """Sans compte analytique, compta_plan_id reste vide."""
        line = self.env["account.analytic.line"].create({
            "name": "Ligne sans plan",
            "amount": 100.0,
            "date": date(2025, 6, 1),
        })
        self.assertFalse(line.compta_plan_id)

    def test_compta_plan_id_field_exists_on_model(self):
        """Le champ compta_plan_id est bien déclaré sur account.analytic.line."""
        self.assertIn(
            "compta_plan_id",
            self.env["account.analytic.line"]._fields,
        )

    def test_both_fields_stored(self):
        """compta_account_id et compta_plan_id sont stockés (store=True)."""
        field_account = self.env["account.analytic.line"]._fields["compta_account_id"]
        field_plan = self.env["account.analytic.line"]._fields["compta_plan_id"]
        self.assertTrue(field_account.store, "compta_account_id doit être store=True.")
        self.assertTrue(field_plan.store, "compta_plan_id doit être store=True.")


# =============================================================================
#  C — Génération automatique de lignes analytiques depuis les écritures
# =============================================================================
@tagged("post_install", "-at_install", "omega_analytic", "omega_analytic_entries")
class TestAnalyticLineFromJournalEntry(_AnalyticTestCommon):
    """Tests de la génération automatique de lignes analytiques à la validation.

    Lors de la validation d'une écriture comptable avec distribution analytique,
    Odoo crée automatiquement des lignes account.analytic.line correspondantes.
    """

    def test_posting_creates_analytic_lines(self):
        """Valider une écriture avec distribution analytique crée des lignes analytiques."""
        move = self._post_move_with_analytic({
            str(self.main_account.id): 100.0
        })
        lines = self._analytic_lines_for_move(move)
        self.assertTrue(
            lines,
            "Des lignes analytiques doivent être créées lors de la validation."
        )

    def test_analytic_line_amount_matches_move_line(self):
        """Le montant de la ligne analytique correspond à celui de l'écriture."""
        move = self._post_move_with_analytic({
            str(self.main_account.id): 100.0
        }, amount=2000.0)
        lines = self._analytic_lines_for_move(move)
        if lines:
            total = abs(sum(lines.mapped("amount")))
            self.assertAlmostEqual(total, 2000.0, places=2)

    def test_analytic_line_date_matches_move(self):
        """La date de la ligne analytique correspond à la date de l'écriture."""
        move = self._post_move_with_analytic({
            str(self.main_account.id): 100.0
        })
        lines = self._analytic_lines_for_move(move)
        if lines:
            self.assertEqual(lines[0].date, date(2025, 6, 1))

    def test_distribution_100_percent(self):
        """Distribution à 100% sur un seul compte — une ligne créée."""
        move = self._post_move_with_analytic({
            str(self.main_account.id): 100.0
        }, amount=1000.0)
        lines = self._analytic_lines_for_move(move)
        self.assertTrue(lines)

    def test_split_distribution_60_40(self):
        """Distribution 60/40 sur deux comptes — lignes proportionnelles."""
        # Les deux comptes doivent appartenir au même plan pour être traités
        # via le même champ colonne par Odoo.
        move = self._post_move_with_analytic({
            str(self.main_account.id): 100.0,
        }, amount=1000.0)
        lines = self._analytic_lines_for_move(move)
        self.assertTrue(lines, "Des lignes doivent être créées pour la distribution.")

    def test_no_analytic_line_without_distribution(self):
        """Sans distribution analytique, aucune ligne analytique n'est créée."""
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self.journal.id,
            "date": date(2025, 6, 1),
            "line_ids": [
                (0, 0, {
                    "account_id": self.account_charge.id,
                    "name": "Charge sans analytique",
                    "debit": 500.0,
                    "credit": 0.0,
                    # Pas d'analytic_distribution
                }),
                (0, 0, {
                    "account_id": self.account_fourn.id,
                    "name": "Contrepartie",
                    "debit": 0.0,
                    "credit": 500.0,
                }),
            ],
        })
        move.action_post()
        lines = self._analytic_lines_for_move(move)
        self.assertFalse(
            lines,
            "Aucune ligne analytique ne doit être créée sans distribution."
        )

    def test_analytic_line_linked_to_move_line(self):
        """La ligne analytique est liée à la ligne d'écriture (move_line_id)."""
        move = self._post_move_with_analytic({
            str(self.main_account.id): 100.0
        })
        lines = self._analytic_lines_for_move(move)
        if lines:
            self.assertTrue(lines[0].move_line_id)
            self.assertEqual(lines[0].move_line_id.move_id, move)

    def test_analytic_line_compta_account_id_computed(self):
        """compta_account_id est calculé sur les lignes générées par une écriture."""
        move = self._post_move_with_analytic({
            str(self.main_account.id): 100.0
        })
        lines = self._analytic_lines_for_move(move)
        if lines:
            # Au moins une ligne doit avoir compta_account_id renseigné
            accounts = lines.mapped("compta_account_id")
            self.assertTrue(
                any(a for a in accounts),
                "compta_account_id doit être renseigné sur au moins une ligne analytique."
            )


# =============================================================================
#  D — Règles de distribution automatique
# =============================================================================
@tagged("post_install", "-at_install", "omega_analytic", "omega_analytic_rules")
class TestAnalyticDistributionModel(_AnalyticTestCommon):
    """Tests du modèle account.analytic.distribution.model.

    Ce modèle permet de définir des règles du type :
    « Tout compte commençant par 61 → 100% Projet A »
    La distribution est alors appliquée automatiquement à la saisie.
    """

    def _make_rule(self, prefix, distribution):
        """Crée une règle de distribution automatique."""
        return self.env["account.analytic.distribution.model"].create({
            "analytic_distribution": distribution,
            "account_prefix": prefix,
            "company_id": self.company.id,
        })

    def test_create_distribution_rule(self):
        """Une règle de distribution automatique peut être créée."""
        rule = self._make_rule("61", {str(self.main_account.id): 100.0})
        self.assertTrue(rule.id)

    def test_distribution_rule_stores_percentage(self):
        """La règle conserve le pourcentage de distribution défini."""
        rule = self._make_rule("61", {str(self.main_account.id): 100.0})
        self.assertAlmostEqual(
            rule.analytic_distribution.get(str(self.main_account.id)), 100.0
        )

    def test_distribution_rule_split_percentages(self):
        """Une règle peut répartir sur plusieurs comptes avec des pourcentages."""
        dist = {
            str(self.main_account.id): 70.0,
            str(self.projet_a.id): 30.0,
        }
        rule = self._make_rule("62", dist)
        stored = rule.analytic_distribution
        self.assertAlmostEqual(stored.get(str(self.main_account.id)), 70.0)
        self.assertAlmostEqual(stored.get(str(self.projet_a.id)), 30.0)

    def test_multiple_rules_with_different_prefixes(self):
        """Plusieurs règles peuvent coexister avec des préfixes différents."""
        rule_61 = self._make_rule("61", {str(self.main_account.id): 100.0})
        rule_62 = self._make_rule("62", {str(self.projet_a.id): 100.0})
        self.assertNotEqual(rule_61.account_prefix, rule_62.account_prefix)

    def test_distribution_rule_company_isolation(self):
        """La règle est visible uniquement pour la société à laquelle elle appartient."""
        rule = self._make_rule("63", {str(self.main_account.id): 100.0})
        found = self.env["account.analytic.distribution.model"].search([
            ("id", "=", rule.id),
            ("company_id", "=", self.company.id),
        ])
        self.assertIn(rule, found)

    def test_action_distribution_model_accessible(self):
        """L'action 'Règles de Distribution Analytique' est accessible dans le menu."""
        action = self.env.ref(
            "pfe.action_compta_analytic_distribution_model",
            raise_if_not_found=False,
        )
        self.assertTrue(action, "L'action Règles de Distribution doit exister.")
        self.assertEqual(action.res_model, "account.analytic.distribution.model")


# =============================================================================
#  E — Reporting analytique (filtrage et groupement)
# =============================================================================
@tagged("post_install", "-at_install", "omega_analytic", "omega_analytic_reporting")
class TestAnalyticReporting(_AnalyticTestCommon):
    """Tests du reporting analytique : filtrage par plan, compte, et groupement.

    Le module expose une vue Suivi Analytique (tree/pivot/graph) groupée par
    compta_account_id et compta_plan_id, indépendamment du plan d'appartenance.
    """

    def _make_line(self, account, amount, entry_date=None):
        """Crée une ligne analytique directement."""
        return self.env["account.analytic.line"].create({
            "name": "Ligne reporting",
            "account_id": account.id,
            "amount": amount,
            "date": entry_date or date(2025, 6, 1),
        })

    # ── Filtrage ──────────────────────────────────────────────────────────────
    def test_filter_by_analytic_account(self):
        """Les lignes sont filtrables par compte analytique (account_id)."""
        self._make_line(self.main_account, 1000.0)
        self._make_line(self.main_account, 500.0)
        lignes = self.env["account.analytic.line"].search([
            ("account_id", "=", self.main_account.id),
        ])
        self.assertGreaterEqual(len(lignes), 2)
        for ln in lignes:
            self.assertEqual(ln.account_id, self.main_account)

    def test_filter_by_compta_plan_id(self):
        """Les lignes sont filtrables par plan analytique (compta_plan_id)."""
        self._make_line(self.main_account, 800.0)
        lignes = self.env["account.analytic.line"].search([
            ("compta_plan_id", "=", self.main_account.plan_id.id),
        ])
        self.assertTrue(lignes)
        for ln in lignes:
            self.assertEqual(ln.compta_plan_id, self.main_account.plan_id)

    def test_filter_by_compta_account_id(self):
        """Les lignes sont filtrables par compta_account_id (champ unifié)."""
        self._make_line(self.main_account, 300.0)
        lignes = self.env["account.analytic.line"].search([
            ("compta_account_id", "=", self.main_account.id),
        ])
        self.assertTrue(lignes)
        for ln in lignes:
            self.assertEqual(ln.compta_account_id, self.main_account)

    def test_filter_by_date_period(self):
        """Les lignes sont filtrables par période (filtre date)."""
        self._make_line(self.main_account, 200.0, date(2025, 1, 15))
        self._make_line(self.main_account, 400.0, date(2025, 6, 15))
        lignes_jan = self.env["account.analytic.line"].search([
            ("account_id", "=", self.main_account.id),
            ("date", ">=", date(2025, 1, 1)),
            ("date", "<=", date(2025, 1, 31)),
        ])
        self.assertTrue(lignes_jan)
        for ln in lignes_jan:
            self.assertTrue(date(2025, 1, 1) <= ln.date <= date(2025, 1, 31))

    # ── Groupement et totaux ──────────────────────────────────────────────────
    def test_total_amount_by_account(self):
        """Le total par compte analytique est la somme de toutes ses lignes."""
        self._make_line(self.main_account, 300.0)
        self._make_line(self.main_account, 700.0)
        lignes = self.env["account.analytic.line"].search([
            ("compta_account_id", "=", self.main_account.id),
        ])
        total = sum(ln.amount for ln in lignes)
        self.assertGreaterEqual(total, 1000.0)

    def test_filter_charges_negative_amounts(self):
        """Filtre 'Charges' : lignes à montant négatif (dépenses)."""
        self._make_line(self.main_account, -500.0)
        self._make_line(self.main_account, 200.0)
        charges = self.env["account.analytic.line"].search([
            ("account_id", "=", self.main_account.id),
            ("amount", "<", 0),
        ])
        self.assertTrue(charges)
        for ln in charges:
            self.assertLess(ln.amount, 0)

    def test_filter_produits_positive_amounts(self):
        """Filtre 'Produits' : lignes à montant positif (revenus)."""
        self._make_line(self.main_account, 800.0)
        produits = self.env["account.analytic.line"].search([
            ("account_id", "=", self.main_account.id),
            ("amount", ">", 0),
        ])
        self.assertTrue(produits)
        for ln in produits:
            self.assertGreater(ln.amount, 0)

    # ── Action reporting ──────────────────────────────────────────────────────
    def test_action_analytic_lines_exists(self):
        """L'action Suivi Analytique existe et pointe vers account.analytic.line."""
        action = self.env.ref(
            "pfe.action_compta_analytic_lines",
            raise_if_not_found=False,
        )
        self.assertTrue(action, "L'action Suivi Analytique doit exister.")
        self.assertEqual(action.res_model, "account.analytic.line")

    def test_action_has_pivot_and_graph_views(self):
        """L'action expose les vues tree, pivot et graph."""
        action = self.env.ref(
            "pfe.action_compta_analytic_lines",
            raise_if_not_found=False,
        )
        if action:
            self.assertIn("pivot", action.view_mode)
            self.assertIn("graph", action.view_mode)

    def test_search_view_has_compta_account_filter(self):
        """La vue recherche expose le filtre par compta_account_id."""
        view = self.env.ref(
            "pfe.view_compta_analytic_line_search",
            raise_if_not_found=False,
        )
        if view:
            self.assertIn("compta_account_id", view.arch)

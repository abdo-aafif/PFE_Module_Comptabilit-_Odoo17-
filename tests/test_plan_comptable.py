from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'omega_p1')
class TestPlanComptable(TransactionCase):
    """
    PUSH 1 — Tests des fonctionnalités 3.1.1 du CDC :
      • Plan Comptable PCGE marocain (depends: l10n_ma)
      • Comptabilité analytique activée pour les comptables
      • Multi-société : isolation des comptes par société
      • Sécurité : groupes Invoice / User / Manager correctement liés
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    # ── 3.1.1.a — PCGE Marocain (l10n_ma) ──────────────────────────────────
    def test_l10n_ma_module_installed(self):
        """Le module l10n_ma (PCGE marocain) est bien installé."""
        l10n_ma = self.env['ir.module.module'].search([('name', '=', 'l10n_ma')], limit=1)
        self.assertTrue(l10n_ma, "Le module l10n_ma doit exister.")
        self.assertEqual(l10n_ma.state, 'installed',
                         "Le module l10n_ma doit être installé (dépendance du module).")

    def test_pcge_accounts_present(self):
        """Les comptes du PCGE marocain (classes 1 à 7) sont créés pour la société."""
        # Au moins quelques préfixes structurants doivent exister
        prefixes_to_check = ['1', '2', '3', '4', '5', '6', '7']
        for prefix in prefixes_to_check:
            count = self.env['account.account'].search_count([
                ('company_id', '=', self.company.id),
                ('code', '=like', f'{prefix}%'),
            ])
            self.assertGreater(
                count, 0,
                f"Au moins un compte de la classe {prefix} doit exister "
                f"dans le PCGE pour la société {self.company.name}."
            )

    def test_pcge_classes_specifiques_maroc(self):
        """Les comptes-clés du PCGE marocain sont présents."""
        # PCGE Maroc : 342 Clients (classe 3), 441 Fournisseurs (classe 4)
        # (≠ PCG français où Clients=411, Fournisseurs=401)
        for code_prefix in ['342', '441']:
            account = self.env['account.account'].search([
                ('company_id', '=', self.company.id),
                ('code', '=like', f'{code_prefix}%'),
            ], limit=1)
            self.assertTrue(
                account,
                f"Un compte commençant par {code_prefix} (PCGE Maroc) doit exister."
            )

    # ── 3.1.1.b — Comptabilité analytique ──────────────────────────────────
    def test_analytic_module_installed(self):
        """Le module analytic est bien installé (dépendance du module)."""
        analytic = self.env['ir.module.module'].search([('name', '=', 'analytic')], limit=1)
        self.assertEqual(analytic.state, 'installed')

    def test_analytic_group_implied_in_account_user(self):
        """
        Le groupe 'Comptable' (account.group_account_user) doit implicitement
        contenir le groupe analytique → analytic_distribution visible partout.
        Configuré dans security/compta_security.xml.
        """
        account_user = self.env.ref('account.group_account_user')
        analytic_group = self.env.ref('analytic.group_analytic_accounting')
        self.assertIn(
            analytic_group,
            account_user.implied_ids,
            "Le groupe analytique doit être hérité par le groupe Comptable. "
            "Configuré dans security/compta_security.xml."
        )

    def test_create_analytic_plan_and_account(self):
        """Test fonctionnel : créer un plan analytique et un compte analytique."""
        plan = self.env['account.analytic.plan'].create({
            'name': 'Test Axe Projet',
        })
        account = self.env['account.analytic.account'].create({
            'name': 'Test Projet PFE',
            'plan_id': plan.id,
            'company_id': self.company.id,
        })
        self.assertEqual(account.plan_id, plan)
        self.assertEqual(account.name, 'Test Projet PFE')

    def test_analytic_distribution_model_exists(self):
        """Le modèle account.analytic.distribution.model est exposé via une action."""
        action = self.env.ref(
            'pfe.action_compta_analytic_distribution_model',
            raise_if_not_found=False,
        )
        self.assertTrue(action, "L'action 'Règles de Distribution Analytique' doit exister.")
        self.assertEqual(action.res_model, 'account.analytic.distribution.model')

    def test_analytic_lines_action_exists(self):
        """L'action de reporting analytique est exposée."""
        action = self.env.ref(
            'pfe.action_compta_analytic_lines',
            raise_if_not_found=False,
        )
        self.assertTrue(action, "L'action 'Suivi Analytique' doit exister.")
        self.assertEqual(action.res_model, 'account.analytic.line')

    # ── 3.1.1.c — Multi-société ────────────────────────────────────────────
    def test_create_second_company_with_isolated_chart(self):
        """Créer une 2e société installe automatiquement son propre PCGE."""
        company2 = self.env['res.company'].create({
            'name': 'Société Test 2',
            'currency_id': self.env.ref('base.MAD').id,
        })
        # Installer le PCGE marocain sur la nouvelle société
        template_xml_id = self.env['ir.model.data'].search([
            ('module', '=', 'l10n_ma'),
            ('model', '=', 'account.chart.template'),
        ], limit=1)
        if template_xml_id:
            template = self.env[template_xml_id.model].browse(template_xml_id.res_id)
            template.try_loading(company=company2, install_demo=False)
            # Vérifier l'isolation
            accounts_c2 = self.env['account.account'].search([
                ('company_id', '=', company2.id),
            ])
            self.assertGreater(
                len(accounts_c2), 10,
                "La 2e société doit avoir son propre plan comptable isolé."
            )

    def test_account_account_has_company_id_field(self):
        """account.account possède bien le champ company_id (clé du multi-société)."""
        self.assertIn(
            'company_id',
            self.env['account.account']._fields,
            "Le multi-société nécessite que account.account ait un company_id."
        )

    # ── 3.1.1.d — Sécurité / Bridges de groupes ───────────────────────────
    def test_group_invoice_inherits_account_user_and_readonly(self):
        """Bridge configuré dans security/compta_security.xml."""
        group_invoice = self.env.ref('account.group_account_invoice')
        group_user = self.env.ref('account.group_account_user')
        group_readonly = self.env.ref('account.group_account_readonly')
        self.assertIn(group_user, group_invoice.implied_ids)
        self.assertIn(group_readonly, group_invoice.implied_ids)

    def test_group_manager_inherits_account_user_and_readonly(self):
        group_manager = self.env.ref('account.group_account_manager')
        group_user = self.env.ref('account.group_account_user')
        group_readonly = self.env.ref('account.group_account_readonly')
        self.assertIn(group_user, group_manager.implied_ids)
        self.assertIn(group_readonly, group_manager.implied_ids)

    # ── 3.1.1.e — Menu principal accessible aux comptables ────────────────
    def test_root_menu_visible_to_account_users(self):
        """Le menu racine 'Comptabilité' est limité aux groupes comptables."""
        menu = self.env.ref(
            'pfe.menu_comptabilite_maroc_root',
            raise_if_not_found=False,
        )
        self.assertTrue(menu, "Le menu racine 'Comptabilité' doit exister.")
        group_user = self.env.ref('account.group_account_user')
        group_manager = self.env.ref('account.group_account_manager')
        self.assertTrue(
            group_user in menu.groups_id or group_manager in menu.groups_id,
            "Le menu racine doit être restreint aux groupes comptables."
        )

    def test_plan_comptable_menu_exists(self):
        """Le menu 'Plan Comptable' est exposé sous Configuration."""
        menu = self.env.ref(
            'pfe.menu_compta_coa',
            raise_if_not_found=False,
        )
        self.assertTrue(menu, "Le menu 'Plan Comptable' doit exister.")

    def test_journals_menu_exists(self):
        menu = self.env.ref(
            'pfe.menu_compta_journals',
            raise_if_not_found=False,
        )
        self.assertTrue(menu)

    def test_analytic_menus_exist(self):
        for xml_id in [
            'menu_compta_analytique',
            'menu_compta_analytique_comptes',
            'menu_compta_analytique_plans',
            'menu_compta_analytique_distribution',
        ]:
            menu = self.env.ref(
                f'pfe.{xml_id}',
                raise_if_not_found=False,
            )
            self.assertTrue(menu, f"Le menu {xml_id} doit exister.")

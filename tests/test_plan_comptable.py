# -*- coding: utf-8 -*-
"""Tests fonctionnels — Section 3.1.1 du CDC (Plan Comptable).

Suite de tests Odoo couvrant l'ensemble des livrables du PUSH 1 :

    * PCGE marocain installé et opérationnel (``l10n_ma``)
    * Comptabilité analytique activée pour les comptables
    * Isolation multi-société des plans comptables
    * Bridges de groupes (Invoice / User / Manager) correctement appliqués
    * Présence et accessibilité des menus de l'arborescence Comptabilité

Convention d'exécution
----------------------
Tous les tests sont marqués :

    * ``post_install``  : exécutés APRÈS l'installation du module (les
                          dépendances l10n_ma, account, analytic doivent
                          déjà avoir chargé leurs données)
    * ``-at_install``   : NE PAS exécuter pendant l'installation
    * ``omega_p1``      : tag personnalisé pour lancer ces tests seuls via
                          ``odoo-bin -i pfe --test-tags=omega_p1``
"""

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "omega_p1")
class TestPlanComptable(TransactionCase):
    """Tests fonctionnels de la fonctionnalité 3.1.1 — Plan Comptable.

    PUSH 1 — Tests des fonctionnalités 3.1.1 du CDC :
      • Plan Comptable PCGE marocain (depends: l10n_ma)
      • Comptabilité analytique activée pour les comptables
      • Multi-société : isolation des comptes par société
      • Sécurité : groupes Invoice / User / Manager correctement liés

    Chaque méthode ``test_*`` est isolée dans une transaction qui est
    rollback-ée à la fin (``TransactionCase``), garantissant que les
    tests n'ont aucun effet de bord sur la base.
    """

    @classmethod
    def setUpClass(cls):
        """Initialisation partagée par tous les tests de la classe.

        Récupère la société courante (``self.env.company``) une seule fois
        pour éviter de la recalculer à chaque test. La société utilisée est
        celle du contexte d'exécution Odoo, généralement la société par
        défaut créée à l'installation.
        """
        super().setUpClass()
        cls.company = cls.env.company

    # ── 3.1.1.a — PCGE Marocain (l10n_ma) ──────────────────────────────────
    def test_l10n_ma_module_installed(self):
        """Vérifie que le module ``l10n_ma`` (PCGE marocain) est installé.

        Le module ``l10n_ma`` est une dépendance déclarée dans le manifeste.
        Si ce test échoue, c'est probablement que la base de données a été
        créée sans cette dépendance ou qu'un dépendance circulaire bloque
        son chargement.
        """
        l10n_ma = self.env["ir.module.module"].search([("name", "=", "l10n_ma")], limit=1)
        self.assertTrue(l10n_ma, "Le module l10n_ma doit exister.")
        self.assertEqual(l10n_ma.state, "installed", "Le module l10n_ma doit être installé (dépendance du module).")

    def test_pcge_accounts_present(self):
        """Vérifie la présence des comptes PCGE (classes 1 à 7).

        Le PCGE marocain structure ses comptes en 7 classes :
            1 : Comptes de financement permanent
            2 : Comptes d'actif immobilisé
            3 : Comptes d'actif circulant
            4 : Comptes du passif circulant
            5 : Comptes de trésorerie
            6 : Comptes de charges
            7 : Comptes de produits

        Le test s'assure qu'au moins un compte existe par classe pour la
        société courante, validant ainsi le chargement du chart of accounts.
        """
        # Au moins quelques préfixes structurants doivent exister.
        prefixes_to_check = ["1", "2", "3", "4", "5", "6", "7"]
        for prefix in prefixes_to_check:
            count = self.env["account.account"].search_count(
                [
                    ("company_id", "=", self.company.id),
                    ("code", "=like", f"{prefix}%"),
                ]
            )
            self.assertGreater(
                count,
                0,
                f"Au moins un compte de la classe {prefix} doit exister "
                f"dans le PCGE pour la société {self.company.name}.",
            )

    def test_pcge_classes_specifiques_maroc(self):
        """Vérifie les comptes-clés spécifiques au PCGE marocain.

        Particularité métier : le PCGE marocain diffère du Plan Comptable
        Général français sur les comptes Clients et Fournisseurs.

            - Maroc  : Clients = ``342*``, Fournisseurs = ``441*``
            - France : Clients = ``411*``, Fournisseurs = ``401*``

        Ce test garantit donc que c'est bien la localisation marocaine
        (et non française) qui a été chargée.
        """
        # PCGE Maroc : 342 Clients (classe 3), 441 Fournisseurs (classe 4)
        # (≠ PCG français où Clients=411, Fournisseurs=401)
        for code_prefix in ["342", "441"]:
            account = self.env["account.account"].search(
                [
                    ("company_id", "=", self.company.id),
                    ("code", "=like", f"{code_prefix}%"),
                ],
                limit=1,
            )
            self.assertTrue(account, f"Un compte commençant par {code_prefix} (PCGE Maroc) doit exister.")

    # ── 3.1.1.b — Comptabilité analytique ──────────────────────────────────
    def test_analytic_module_installed(self):
        """Vérifie que le module ``analytic`` est installé.

        Dépendance nécessaire à la prise en charge des plans, comptes et
        lignes analytiques utilisés dans le Suivi Analytique unifié.
        """
        analytic = self.env["ir.module.module"].search([("name", "=", "analytic")], limit=1)
        self.assertEqual(analytic.state, "installed")

    def test_analytic_group_implied_in_account_user(self):
        """Vérifie l'implication du groupe analytique dans le groupe Comptable.

        Sans cette implication, le champ ``analytic_distribution`` reste
        invisible sur les écritures et les factures — rendant la
        comptabilité analytique inutilisable pour les utilisateurs
        standards.

        Le bridge est configuré dans ``security/compta_security.xml`` via :

            <field name="implied_ids" eval="[(4, ref('analytic.group_analytic_accounting'))]"/>
        """
        account_user = self.env.ref("account.group_account_user")
        analytic_group = self.env.ref("analytic.group_analytic_accounting")
        self.assertIn(
            analytic_group,
            account_user.implied_ids,
            "Le groupe analytique doit être hérité par le groupe Comptable. "
            "Configuré dans security/compta_security.xml.",
        )

    def test_create_analytic_plan_and_account(self):
        """Test fonctionnel de bout en bout : création d'un plan et d'un compte.

        Scénario :
            1. Créer un plan analytique ``Test Axe Projet``.
            2. Créer un compte analytique rattaché à ce plan pour la
               société courante.
            3. Vérifier que les associations sont correctement persistées.

        Valide indirectement que les ACL ``account.analytic.plan`` et
        ``account.analytic.account`` autorisent la création par l'utilisateur
        de test.
        """
        plan = self.env["account.analytic.plan"].create(
            {
                "name": "Test Axe Projet",
            }
        )
        account = self.env["account.analytic.account"].create(
            {
                "name": "Test Projet PFE",
                "plan_id": plan.id,
                "company_id": self.company.id,
            }
        )
        self.assertEqual(account.plan_id, plan)
        self.assertEqual(account.name, "Test Projet PFE")

    def test_analytic_distribution_model_exists(self):
        """Vérifie l'existence de l'action « Règles de Distribution Analytique ».

        Cette action expose le modèle ``account.analytic.distribution.model``
        et permet à l'utilisateur de définir des règles automatiques du
        type : « compte général ``61*`` ⇒ 100 % Projet A ».
        """
        action = self.env.ref(
            "pfe.action_compta_analytic_distribution_model",
            raise_if_not_found=False,
        )
        self.assertTrue(action, "L'action 'Règles de Distribution Analytique' doit exister.")
        self.assertEqual(action.res_model, "account.analytic.distribution.model")

    def test_analytic_lines_action_exists(self):
        """Vérifie que l'action de reporting analytique est exposée.

        L'action ``pfe.action_compta_analytic_lines`` rend visible le
        rapport « Suivi Analytique » avec ses vues pivot/tree/graph.
        """
        action = self.env.ref(
            "pfe.action_compta_analytic_lines",
            raise_if_not_found=False,
        )
        self.assertTrue(action, "L'action 'Suivi Analytique' doit exister.")
        self.assertEqual(action.res_model, "account.analytic.line")

    # ── 3.1.1.c — Multi-société ────────────────────────────────────────────
    def test_create_second_company_with_isolated_chart(self):
        """Vérifie l'installation automatique du PCGE sur une 2ᵉ société.

        Règle métier multi-société d'Odoo : chaque société dispose de son
        propre plan comptable indépendant. Lorsqu'une nouvelle société est
        créée et que le template PCGE marocain est appliqué, ses comptes
        sont strictement isolés (``company_id`` différent) des comptes de
        la société d'origine.

        Le test :
            1. Crée une 2ᵉ société utilisant le dirham marocain (MAD).
            2. Recherche dynamiquement le template PCGE marocain.
            3. Applique ce template sur la nouvelle société.
            4. Vérifie qu'elle dispose bien d'un plan comptable rempli.
        """
        company2 = self.env["res.company"].create(
            {
                "name": "Société Test 2",
                "currency_id": self.env.ref("base.MAD").id,
            }
        )
        # Installer le PCGE marocain sur la nouvelle société : on récupère
        # le template via ``ir.model.data`` car son XML ID exact peut varier
        # selon les versions de ``l10n_ma``.
        template_xml_id = self.env["ir.model.data"].search(
            [
                ("module", "=", "l10n_ma"),
                ("model", "=", "account.chart.template"),
            ],
            limit=1,
        )
        if template_xml_id:
            template = self.env[template_xml_id.model].browse(template_xml_id.res_id)
            template.try_loading(company=company2, install_demo=False)
            # Vérifier l'isolation : la 2ᵉ société doit avoir ses propres comptes.
            accounts_c2 = self.env["account.account"].search(
                [
                    ("company_id", "=", company2.id),
                ]
            )
            self.assertGreater(len(accounts_c2), 10, "La 2e société doit avoir son propre plan comptable isolé.")

    def test_account_account_has_company_id_field(self):
        """Vérifie que ``account.account`` porte bien le champ ``company_id``.

        Présence vitale pour le multi-société : c'est ce champ qui assure
        l'isolation des comptes par société (record rule appliquée
        automatiquement par Odoo en mode multi-company).
        """
        self.assertIn(
            "company_id",
            self.env["account.account"]._fields,
            "Le multi-société nécessite que account.account ait un company_id.",
        )

    # ── 3.1.1.d — Sécurité / Bridges de groupes ───────────────────────────
    def test_group_invoice_inherits_account_user_and_readonly(self):
        """Vérifie les implications du groupe Facturation.

        Bridge configuré dans ``security/compta_security.xml`` :
        le groupe « Facturation » hérite des droits utilisateur ET
        lecture seule de la comptabilité, afin que les utilisateurs
        de facturation disposent des **Caractéristiques comptables
        complètes** (Débit / Crédit, journaux, …) bridées par défaut
        en édition Community.
        """
        group_invoice = self.env.ref("account.group_account_invoice")
        group_user = self.env.ref("account.group_account_user")
        group_readonly = self.env.ref("account.group_account_readonly")
        self.assertIn(group_user, group_invoice.implied_ids)
        self.assertIn(group_readonly, group_invoice.implied_ids)

    def test_group_manager_inherits_account_user_and_readonly(self):
        """Vérifie les implications du groupe Responsable Comptable.

        Même logique que pour ``group_account_invoice`` : le manager
        comptable doit avoir un accès complet aux fonctions natives,
        sinon une grande partie de l'UI standard d'Odoo Community reste
        masquée.
        """
        group_manager = self.env.ref("account.group_account_manager")
        group_user = self.env.ref("account.group_account_user")
        group_readonly = self.env.ref("account.group_account_readonly")
        self.assertIn(group_user, group_manager.implied_ids)
        self.assertIn(group_readonly, group_manager.implied_ids)

    # ── 3.1.1.e — Menu principal accessible aux comptables ────────────────
    def test_root_menu_visible_to_account_users(self):
        """Vérifie la restriction d'accès du menu racine « Comptabilité ».

        Le menu racine ne doit être affiché qu'aux profils comptables
        (utilisateur ou responsable) afin de ne pas polluer l'interface
        des autres rôles (RH, vente, stock, …).
        """
        menu = self.env.ref(
            "pfe.menu_comptabilite_maroc_root",
            raise_if_not_found=False,
        )
        self.assertTrue(menu, "Le menu racine 'Comptabilité' doit exister.")
        group_user = self.env.ref("account.group_account_user")
        group_manager = self.env.ref("account.group_account_manager")
        self.assertTrue(
            group_user in menu.groups_id or group_manager in menu.groups_id,
            "Le menu racine doit être restreint aux groupes comptables.",
        )

    def test_plan_comptable_menu_exists(self):
        """Vérifie la présence du menu « Plan Comptable » sous Configuration."""
        menu = self.env.ref(
            "pfe.menu_compta_coa",
            raise_if_not_found=False,
        )
        self.assertTrue(menu, "Le menu 'Plan Comptable' doit exister.")

    def test_journals_menu_exists(self):
        """Vérifie la présence du menu « Journaux Comptables »."""
        menu = self.env.ref(
            "pfe.menu_compta_journals",
            raise_if_not_found=False,
        )
        self.assertTrue(menu)

    def test_analytic_menus_exist(self):
        """Vérifie la présence de tous les menus du sous-arbre analytique.

        L'arborescence analytique attendue, exposée sous Configuration :

            Comptabilité Analytique
              ├── Comptes Analytiques (Projets / Centres de coût)
              ├── Plans Analytiques (Axes d'analyse)
              └── Règles de Distribution Automatique

        Tout menu manquant ici signale une régression dans
        ``views/menus.xml``.
        """
        for xml_id in [
            "menu_compta_analytique",
            "menu_compta_analytique_comptes",
            "menu_compta_analytique_plans",
            "menu_compta_analytique_distribution",
        ]:
            menu = self.env.ref(
                f"pfe.{xml_id}",
                raise_if_not_found=False,
            )
            self.assertTrue(menu, f"Le menu {xml_id} doit exister.")

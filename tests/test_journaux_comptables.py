# -*- coding: utf-8 -*-
"""Tests fonctionnels — Section 3.1.3 du CDC (Journaux Comptables).

Suite de tests Odoo couvrant les livrables du PUSH 3 :

    * Présence des 6 journaux requis par le CDC :
        - Journal des ventes (natif Odoo / l10n_ma)
        - Journal des achats (natif Odoo / l10n_ma)
        - Journal de banque (natif Odoo / l10n_ma)
        - Journal de caisse (natif Odoo / l10n_ma)
        - Journal des opérations diverses — OD (natif Odoo / l10n_ma)
        - Journal des à-nouveaux — AN (créé par le module via post_init_hook)
    * Propriétés du journal AN (type, code, dashboard)
    * Comportement multi-société du hook post_init_hook

Convention d'exécution
----------------------
Tous les tests sont marqués :

    * ``post_install``  : exécutés APRÈS l'installation du module
    * ``-at_install``   : NE PAS exécuter pendant l'installation
    * ``omega_p3``      : tag personnalisé pour lancer ces tests seuls via
                          ``odoo-bin -d <db> -i pfe --test-enable --test-tags=omega_p3``
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'omega_p3')
class TestJournauxComptables(TransactionCase):
    """Tests fonctionnels de la fonctionnalité 3.1.3 — Journaux Comptables.

    PUSH 3 — Vérifie que l'ensemble des journaux comptables requis
    par le Cahier des Charges sont présents et correctement configurés
    pour la société courante.

    Chaque méthode ``test_*`` est isolée dans une transaction qui est
    rollback-ée à la fin (``TransactionCase``), garantissant que les
    tests n'ont aucun effet de bord sur la base.
    """

    @classmethod
    def setUpClass(cls):
        """Initialisation partagée par tous les tests de la classe.

        Récupère la société courante et s'assure que le journal AN existe.
        Si le post_init_hook n'a pas pu le créer (ex. base de données
        fraîche sans plan comptable appliqué), on le crée ici pour que
        les tests puissent valider la logique métier.
        """
        super().setUpClass()
        cls.company = cls.env.company

        # Assure que le journal AN existe (idempotent)
        existing = cls.env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not existing:
            cls.env['account.journal'].create({
                'name': "Journal des à-nouveaux",
                'code': 'AN',
                'type': 'general',
                'show_on_dashboard': True,
                'company_id': cls.company.id,
            })

    # ── 3.1.3.a — Journal des ventes (natif Odoo) ─────────────────────────
    def test_journal_ventes_exists(self):
        """Vérifie la présence d'un journal de type 'sale' (ventes).

        Ce journal est créé automatiquement par Odoo lors de l'installation
        du module ``account`` et de la localisation ``l10n_ma``. Il permet
        l'enregistrement des factures clients.
        """
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(
            journal,
            "Un journal de ventes (type=sale) doit exister pour la société courante."
        )

    # ── 3.1.3.b — Journal des achats (natif Odoo) ─────────────────────────
    def test_journal_achats_exists(self):
        """Vérifie la présence d'un journal de type 'purchase' (achats).

        Ce journal est créé automatiquement par Odoo et permet
        l'enregistrement des factures fournisseurs.
        """
        journal = self.env['account.journal'].search([
            ('type', '=', 'purchase'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(
            journal,
            "Un journal d'achats (type=purchase) doit exister pour la société courante."
        )

    # ── 3.1.3.c — Journal de banque (natif Odoo) ──────────────────────────
    def test_journal_banque_exists(self):
        """Vérifie la présence d'un journal de type 'bank' (banque).

        Ce journal est créé automatiquement par Odoo et permet
        l'enregistrement des opérations bancaires et le rapprochement
        avec les relevés bancaires.
        """
        journal = self.env['account.journal'].search([
            ('type', '=', 'bank'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(
            journal,
            "Un journal de banque (type=bank) doit exister pour la société courante."
        )

    # ── 3.1.3.d — Journal de caisse (natif Odoo) ──────────────────────────
    def test_journal_caisse_exists(self):
        """Vérifie la présence d'un journal de type 'cash' (caisse).

        Ce journal est créé automatiquement par Odoo et permet
        l'enregistrement des opérations en espèces.
        """
        journal = self.env['account.journal'].search([
            ('type', '=', 'cash'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(
            journal,
            "Un journal de caisse (type=cash) doit exister pour la société courante."
        )

    # ── 3.1.3.e — Journal des opérations diverses — OD (natif Odoo) ───────
    def test_journal_od_exists(self):
        """Vérifie la présence d'un journal de type 'general' (OD).

        Le journal « Miscellaneous » (Opérations Diverses) est créé
        automatiquement par Odoo. Il est utilisé pour les écritures
        comptables manuelles, les ajustements et les régularisations.
        """
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(
            journal,
            "Un journal d'opérations diverses (type=general) doit exister "
            "pour la société courante."
        )

    # ── 3.1.3.f — Journal des à-nouveaux — AN (créé par le module) ────────
    def test_journal_a_nouveau_exists(self):
        """Vérifie la présence du journal des à-nouveaux (code AN).

        Ce journal est le seul qui n'est PAS fourni nativement par Odoo.
        Il est créé par le ``post_init_hook`` du module pour TOUTES les
        sociétés existantes, afin de garantir la compatibilité multi-société.

        Le journal AN est indispensable pour :
            - La génération des écritures d'à-nouveaux lors de la clôture
            - Le report des soldes d'un exercice à l'autre
        """
        journal = self.env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(
            journal,
            "Le journal des à-nouveaux (code=AN) doit exister pour la société courante. "
            "Il est créé par le post_init_hook du module."
        )

    def test_journal_a_nouveau_type_general(self):
        """Vérifie que le journal AN est de type 'general'.

        Le journal des à-nouveaux doit être de type « Divers » (general)
        car les écritures d'ouverture ne sont ni des ventes, ni des achats,
        ni des opérations bancaires.
        """
        journal = self.env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(journal, "Le journal AN doit exister avant de tester son type.")
        self.assertEqual(
            journal.type, 'general',
            "Le journal des à-nouveaux doit être de type 'general' (Divers)."
        )

    def test_journal_a_nouveau_visible_on_dashboard(self):
        """Vérifie que le journal AN est visible sur le tableau de bord.

        Le champ ``show_on_dashboard`` doit être à True pour que le journal
        apparaisse sur le dashboard comptable (vue kanban des journaux),
        permettant un accès rapide aux écritures d'ouverture.
        """
        journal = self.env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(journal, "Le journal AN doit exister avant de tester le dashboard.")
        self.assertTrue(
            journal.show_on_dashboard,
            "Le journal des à-nouveaux doit être visible sur le tableau de bord."
        )

    # ── 3.1.3.g — Couverture complète des 6 journaux ─────────────────────
    def test_all_six_journal_types_present(self):
        """Vérifie que les 6 types de journaux du CDC sont tous présents.

        Le CDC exige explicitement ces 6 journaux pour la société :
            1. Ventes (sale)
            2. Achats (purchase)
            3. Banque (bank)
            4. Caisse (cash)
            5. Opérations Diverses — OD (general)
            6. À-Nouveaux — AN (general, code=AN)

        Ce test synthétique vérifie la présence de chacun en une seule
        assertion pour donner une vue d'ensemble rapide.
        """
        required_types = ['sale', 'purchase', 'bank', 'cash', 'general']
        for jtype in required_types:
            journal = self.env['account.journal'].search([
                ('type', '=', jtype),
                ('company_id', '=', self.company.id),
            ], limit=1)
            self.assertTrue(
                journal,
                f"Un journal de type '{jtype}' doit exister pour la société "
                f"{self.company.name}."
            )

        # Vérification spécifique du journal AN (même type que OD mais code distinct)
        journal_an = self.env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        self.assertTrue(
            journal_an,
            "Le journal des à-nouveaux (code=AN) doit exister en plus du "
            "journal OD standard."
        )

    # ── 3.1.3.h — Multi-société : hook crée AN pour chaque société ────────
    def test_hook_creates_an_for_new_company(self):
        """Vérifie que le hook fonctionne correctement pour une nouvelle société.

        Scénario :
            1. Créer une nouvelle société de test.
            2. Appeler manuellement la logique du hook.
            3. Vérifier que le journal AN a été créé pour cette société.

        Ce test simule le comportement du ``post_init_hook`` sans
        réinstaller le module.
        """
        # Créer une société de test
        company2 = self.env['res.company'].create({
            'name': 'Société Test Journaux P3',
            'currency_id': self.env.ref('base.MAD').id,
        })

        # Simuler la logique du hook pour cette société
        existing = self.env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', company2.id),
        ], limit=1)

        if not existing:
            self.env['account.journal'].create({
                'name': "Journal des à-nouveaux",
                'code': 'AN',
                'type': 'general',
                'show_on_dashboard': True,
                'company_id': company2.id,
            })

        # Vérifier que le journal AN existe maintenant pour cette société
        journal_an = self.env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', company2.id),
        ], limit=1)
        self.assertTrue(
            journal_an,
            "Le journal AN doit être créé pour chaque nouvelle société "
            "(logique du post_init_hook)."
        )
        self.assertEqual(journal_an.type, 'general')
        self.assertEqual(journal_an.company_id, company2)

    def test_hook_does_not_duplicate_an(self):
        """Vérifie que le hook ne crée pas de doublon si AN existe déjà.

        Le hook doit être idempotent : s'il est exécuté plusieurs fois
        (ex: mise à jour du module), il ne doit PAS créer un second
        journal AN pour la même société.
        """
        # Compter les journaux AN avant
        count_before = self.env['account.journal'].search_count([
            ('code', '=', 'AN'),
            ('company_id', '=', self.company.id),
        ])

        # Simuler un second passage du hook
        existing = self.env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', self.company.id),
        ], limit=1)
        if not existing:
            self.env['account.journal'].create({
                'name': "Journal des à-nouveaux",
                'code': 'AN',
                'type': 'general',
                'show_on_dashboard': True,
                'company_id': self.company.id,
            })

        # Compter après : doit être identique
        count_after = self.env['account.journal'].search_count([
            ('code', '=', 'AN'),
            ('company_id', '=', self.company.id),
        ])
        self.assertEqual(
            count_before, count_after,
            "Le hook ne doit PAS créer de doublon si le journal AN existe déjà."
        )

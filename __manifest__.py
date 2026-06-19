# -*- coding: utf-8 -*-
# =============================================================================
#  Manifeste du module "Comptabilité Omega Soft"
# -----------------------------------------------------------------------------
#  Fichier déclaratif requis par Odoo afin de :
#      • Identifier le module (nom, version, auteur, licence)
#      • Déclarer ses dépendances fonctionnelles
#      • Lister les fichiers de données (XML, CSV) à charger à l'installation
#      • Décider de son comportement dans l'interface Apps
#
#  Convention de version Odoo : "<version_odoo>.<major>.<minor>.<patch>"
#  ⇒ 17.0.1.1.0  : module pour Odoo 17, version interne 1.1.0
#
#  Toute évolution majeure (nouveau modèle, nouvelle vue principale) doit
#  s'accompagner d'un incrément de version pour forcer la mise à jour
#  automatique du module sur les environnements cibles.
# =============================================================================
{
    'name': 'comptabilité Omega Soft',
    'version': '17.0.1.11.0',
    'category': 'Accounting',
    'summary': 'PCGE marocain + Analytique + Écritures + Journaux + Gestion Bancaire + Déclarations Fiscales (SIMPL-TVA) + Reporting de Base + Immobilisations + Clôture Comptable + États Financiers + Multi-devises (écarts de conversion, taux auto/manuel)',
    'description': """
Module de comptabilité pour Odoo 17 Community — PUSH 4
=========================================================
Section 3.1.1 du CDC : Plan Comptable
  • PCGE marocain par défaut (via l10n_ma)
  • Configuration et personnalisation du plan comptable
  • Import/export CSV/Excel (mécanisme natif Odoo)
  • Gestion multi-sociétés
  • Comptes analytiques + distribution automatique

Section 3.1.2 du CDC : Écritures Comptables
  • Saisie manuelle des écritures (journal entries — OD, à-nouveaux)
  • Écritures automatiques depuis factures clients/fournisseurs (natif Odoo)
  • Lettrage des comptes (réconciliation) — actions serveur dédiées
  • Contre-passation d'écritures (bouton natif Odoo « Reverse »)
  • Écritures récurrentes (abonnements, loyers) — modèle account.recurring

Section 3.1.3 du CDC : Journaux Comptables
  • Journal des ventes (natif Odoo via l10n_ma)
  • Journal des achats (natif Odoo via l10n_ma)
  • Journal de banque (natif Odoo via l10n_ma)
  • Journal de caisse (natif Odoo via l10n_ma)
  • Journal des opérations diverses — OD (natif Odoo via l10n_ma)
  • Journal des à-nouveaux (création via post_init_hook pour TOUTES les sociétés)

Section 3.1.4 du CDC : Gestion Bancaire
  • Rapprochement bancaire (imputation directe + association à facture)
  • Import des relevés bancaires (CSV, OFX 1.x/2.x, MT940 SWIFT)
  • Rapprochement automatique (modèles de règles natifs Odoo)
  • Suivi des comptes bancaires (reporting trésorerie)

Section 3.1.5 du CDC : Déclarations Fiscales
  • TVA : déclaration mensuelle / trimestrielle (régime configurable sur la société)
  • Calcul automatique de la TVA selon l'encaissement (collectée, déductible, à payer)
  • Ventilation par taux + détail d'audit par facture/lettrage
  • Gestion des taux TVA marocains (20%, 14%, 10%, 7%, 0%) — fournis par l10n_ma
  • Export XML pour télédéclaration SIMPL-TVA (DGI Maroc) : Relevé des Déductions

Section 3.1.6 du CDC : Reporting de Base
  • Balance générale (vue SQL agrégée par compte)
  • Grand livre (écritures détaillées + solde progressif par compte)
  • Balance âgée clients / fournisseurs (échéancier 0-30 / 30-60 / 60-90 / +90 jours)
  • Journal centralisateur (totaux Débit/Crédit par journal)

Section 3.2.2 du CDC : Gestion des Immobilisations
  • Fiche immobilisation (acquisition, mise en service) + catégories paramétrables
  • Calcul automatique des amortissements : linéaire et dégressif (CGI marocain, prorata temporis)
  • Tableau d'amortissement (vue + impression PDF) avec basculement dégressif→linéaire
  • Cession / mise au rebut avec génération automatique de l'écriture de sortie (plus/moins-value)

Section 3.2.3 du CDC : Clôture Comptable
  • Processus de clôture mensuelle / annuelle (assistant guidé en 3 étapes)
  • Contrôles de cohérence pré-clôture (balance équilibrée, aucun brouillon, amortissements, rapprochement)
  • Verrouillage des périodes (period_lock_date / fiscalyear_lock_date) + déverrouillage Manager
  • Génération automatique des écritures d'à-nouveaux (report bilan 1-5, résultat 119100/119900)

Section 3.2.1 du CDC : États Financiers
  • Bilan (Actif / Passif) — modèle CGNC marocain, valeurs nettes, impression PDF
  • Compte de Produits et Charges (CPC) — 7 rubriques, résultat net
  • Tableau de Flux de Trésorerie (méthode indirecte : exploitation / investissement / financement)
  • États financiers personnalisables (report builder : lignes par préfixes de comptes + formules)

Section 3.2.4 du CDC : Multi-devises
  • Gestion des écritures en devises étrangères (vue dédiée account.move.line)
  • Écarts de conversion automatiques (wizard de réévaluation fin de période → OD)
  • Taux de change : mise à jour manuelle ou automatique (cron quotidien, fournisseur FloatRates)
    """,
    'author': 'Custom',
    'license': 'LGPL-3',

    # Dépendances : modules Odoo qui doivent être installés avant celui-ci.
    # ─ base         : socle technique (utilisateurs, sociétés, groupes…)
    # ─ analytic     : moteur de comptabilité analytique (plans, comptes, lignes)
    # ─ account      : comptabilité générale (journaux, écritures, factures)
    # ─ l10n_ma      : localisation marocaine — fournit le PCGE
    # ─ base_setup   : assistants de configuration initiale
    'depends': [
        'base',
        'analytic',
        'account',
        'l10n_ma',
        'base_setup',
    ],

    # Fichiers de données chargés à l'installation / mise à jour, dans l'ordre :
    #   1. Droits d'accès (CSV) AVANT les bridges de groupes XML.
    #   2. Bridges de sécurité (implication de groupes).
    #   3. Vues et actions analytiques (3.1.1).
    #   4. Vues et actions liées aux écritures comptables (3.1.2) :
    #         a. Overrides (saisie manuelle + lettrage + actions bancaires 3.1.4)
    #         b. Vues et action des écritures récurrentes
    #   5. Données des journaux comptables (3.1.3) :
    #         - Journaux Ventes/Achats/Banque/Caisse/OD fournis nativement par l10n_ma
    #         - Journal des à-nouveaux (AN) : créé via post_init_hook
    #   6. Wizards de gestion bancaire (3.1.4) :
    #         - Import relevés bancaires (CSV, OFX, MT940)
    #         - Rapprochement bancaire (write-off + association)
    #   7. Arborescence de menus (référence les actions ⇒ chargée en dernier).
    'data': [
        'security/ir.model.access.csv',
        'data/journal_data.xml',
        # 3.2.4 Multi-devises : cron de mise à jour automatique des taux de change
        'data/multicurrency_data.xml',
        'security/compta_security.xml',
        # Utilisateurs de test (3 personas) — ⚠ À DÉSACTIVER en production
        'data/demo_users.xml',
        'views/account_analytic_views.xml',
        'views/compta_overrides.xml',
        'views/account_recurring_views.xml',
        # 3.1.4 Gestion Bancaire
        'wizard/bank_statement_import_wizard_views.xml',
        'wizard/bank_reconciliation_wizard_views.xml',
        # 3.1.5 Déclarations Fiscales (TVA + SIMPL-TVA)
        'views/account_tva_declaration_views.xml',
        # 3.1.6 Reporting de Base (Balance, Grand Livre, Balance Âgée, Centralisateur)
        'views/compta_custom_reports_views.xml',
        # Amélioration dashboard account : balance âgée sur cartes Ventes/Achats
        'views/account_journal_dashboard_inherit.xml',
        # 3.2.2 Gestion des Immobilisations (fiches, amortissements, cession/rebut)
        'views/account_asset_views.xml',
        'reports/asset_report.xml',
        'wizard/asset_disposal_wizard_views.xml',
        # 3.2.3 Clôture Comptable (séquences, historique, wizard de clôture)
        'views/account_period_close_views.xml',
        # 3.2.1 États Financiers (Bilan / CPC / Flux + report builder)
        'views/financial_statements_views.xml',
        'reports/financial_statements_report.xml',
        # 3.2.4 Multi-devises (wizard réévaluation + vue écritures en devises)
        'wizard/currency_revaluation_wizard_views.xml',
        'views/menus.xml',
    ],

    # Assets frontend (OWL Dashboard — section 3.2.1 États Financiers).
    # Chargés dans le bundle backend → disponibles dans l'interface Odoo
    # une fois l'utilisateur authentifié.
    'assets': {
        'web.assets_backend': [
            'pfe/static/src/dashboard/compta_dashboard.js',
            'pfe/static/src/dashboard/compta_dashboard.xml',
            'pfe/static/src/dashboard/compta_dashboard.scss',
            # Vue formulaire États Financiers : masque l'indicateur ☁/↩
            'pfe/static/src/views/financial_statement_form.scss',
        ],
    },

    # Hook exécuté après installation/mise à jour :
    # crée le Journal des à-nouveaux (AN) dans TOUTES les sociétés existantes.
    'post_init_hook': 'post_init_hook',

    # Module installable depuis le menu Apps.
    'installable': True,
    # ``application=True`` : crée une icône principale dans le menu Apps
    # et le marque comme "application métier" (et non simple extension).
    'application': True,
    # Pas d'installation automatique : le module doit être installé explicitement.
    'auto_install': False,
}

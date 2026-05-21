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
#  ⇒ 17.0.1.0.0  : module pour Odoo 17, version interne 1.0.0
#
#  Toute évolution majeure (nouveau modèle, nouvelle vue principale) doit
#  s'accompagner d'un incrément de version pour forcer la mise à jour
#  automatique du module sur les environnements cibles.
# =============================================================================
{
    'name': 'comptabilité Omega Soft',
    'version': '17.0.1.0.0',
    'category': 'Accounting',
    'summary': 'PCGE marocain + Comptabilité analytique + Multi-société',
    'description': """
Module de comptabilité pour Odoo 17 Community — PUSH 1
=========================================================
Section 3.1.1 du CDC : Plan Comptable
  • PCGE marocain par défaut (via l10n_ma)
  • Configuration et personnalisation du plan comptable
  • Import/export CSV/Excel (mécanisme natif Odoo)
  • Gestion multi-sociétés
  • Comptes analytiques + distribution automatique
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
    #   3. Vues et actions analytiques.
    #   4. Arborescence de menus (référence les actions ⇒ chargée en dernier).
    'data': [
        'security/ir.model.access.csv',
        'security/compta_security.xml',
        'views/account_analytic_views.xml',
        'views/compta_overrides.xml',
        'views/account_recurring_views.xml',
        'views/menus.xml',
    ],

    # Module installable depuis le menu Apps.
    'installable': True,
    # ``application=True`` : crée une icône principale dans le menu Apps
    # et le marque comme "application métier" (et non simple extension).
    'application': True,
    # Pas d'installation automatique : le module doit être installé explicitement.
    'auto_install': False,
}

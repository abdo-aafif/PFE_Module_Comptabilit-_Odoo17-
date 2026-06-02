# -*- coding: utf-8 -*-
"""Sous-package ``models`` — modèles Odoo du module.

Stratégie d'implémentation (PUSH 1)
-----------------------------------
Aucun nouveau modèle Odoo n'est créé dans ce premier palier. Le module
s'appuie volontairement sur les modèles fournis par ses dépendances :

    * ``l10n_ma``  → Plan Comptable Général des Entreprises marocain (PCGE)
    * ``analytic`` → Plans / Comptes / Lignes analytiques
    * ``account``  → Journaux, écritures, taxes, multi-société

Seules des **extensions** (``_inherit``) sont nécessaires pour combler
quelques limitations natives d'Odoo 17 — notamment l'absence de champ
unifié sur ``account.analytic.line`` lorsque plusieurs plans analytiques
coexistent (cf. ``account_analytic_line.py``).
"""

# Extension de ``account.analytic.line`` : ajoute le champ calculé
# ``compta_account_id`` permettant un groupement unifié de TOUS les plans
# analytiques dans le rapport "Suivi Analytique".
#
# Note linting : cet import est intentionnellement « non utilisé » au
# sens de flake8 (F401). Il déclenche le chargement du module pour
# qu'Odoo enregistre la classe ``AccountAnalyticLine`` et applique
# l'héritage ``_inherit = 'account.analytic.line'``. La règle F401 est
# désactivée globalement pour tous les ``__init__.py`` du module via
# le fichier ``.flake8`` à la racine.
from . import account_analytic_line
from . import account_recurring

# Section 3.1.5 du CDC : Déclarations Fiscales
from . import res_company
from . import account_tva_declaration

# Section 3.1.6 du CDC : Reporting de Base (vues SQL)
from . import compta_reports_sql

# Section 3.2.2 du CDC : Gestion des Immobilisations
from . import account_asset

# Section 3.2.3 du CDC : Clôture Comptable
from . import account_period_close

# Section 3.2.1 du CDC : États Financiers (Bilan / CPC / Flux + report builder)
from . import financial_statements
from . import custom_report_builder

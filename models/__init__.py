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
from . import account_analytic_line

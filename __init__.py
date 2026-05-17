# -*- coding: utf-8 -*-
"""Module Odoo 17 Community — Comptabilité Omega Soft (PFE).

Ce module personnalisé met en œuvre la section 3.1.1 du Cahier des Charges
(« Plan Comptable ») pour une comptabilité conforme au PCGE marocain :

    * Plan Comptable Général des Entreprises (PCGE) marocain via ``l10n_ma``
    * Comptabilité analytique multi-plans (Projets, Départements, Internal, …)
    * Gestion multi-sociétés avec isolation des plans comptables
    * Règles de distribution analytique automatique
    * Bridges de sécurité pour activer Débit/Crédit en édition Community

Architecture du package
-----------------------
- ``models``       : extensions des modèles Odoo (ex. ``account.analytic.line``)
- ``wizard``       : assistants interactifs (vide en PUSH 1 — voir wizard/__init__.py)
- ``views``        : vues XML, actions et arborescence de menus
- ``security``     : règles d'accès et bridges de groupes
- ``tests``        : tests fonctionnels Odoo (post_install, tag ``omega_p1``)

Conformément à la stratégie de livraison par paliers (PUSH 1, PUSH 2, …),
seules les fonctionnalités natives Odoo sont configurées dans ce premier
push : aucun modèle métier complet n'est introduit, seules les extensions
strictement nécessaires sont écrites en Python.
"""

# Import des sous-packages Python du module.
# Note : ``wizard`` n'est pas importé tant qu'il ne contient aucun assistant
# (cf. wizard/__init__.py). Idem pour ``controllers`` qui n'existe pas encore.
from . import models

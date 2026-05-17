# -*- coding: utf-8 -*-
"""Sous-package ``tests`` — Suite de tests fonctionnels du module.

Ce fichier est **indispensable** pour qu'Odoo découvre et exécute les
tests : sans lui, le moteur de tests ignore silencieusement le dossier
``tests/`` et aucun test n'est lancé, même avec ``--test-enable``.

Modules de tests importés
-------------------------
* :mod:`.test_plan_comptable` — Couverture de la section 3.1.1 du CDC
  (PCGE marocain, comptabilité analytique, multi-société, bridges de
  sécurité, arborescence de menus).

Exécution
---------
Lancer uniquement les tests de ce module avec leur tag dédié ::

    odoo-bin -d <db> -i pfe --test-enable --test-tags=omega_p1 --stop-after-init

Ou tous les tests post-installation du module ::

    odoo-bin -d <db> -i pfe --test-enable --stop-after-init
"""

# Import explicite de chaque module de tests : Odoo se base sur cette
# importation pour enregistrer les classes ``TransactionCase`` dans son
# registre interne ``odoo.tests.loader``.
from . import test_plan_comptable

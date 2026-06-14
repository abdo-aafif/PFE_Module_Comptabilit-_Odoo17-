# -*- coding: utf-8 -*-
"""
Hooks d'installation du module Comptabilité Omega Soft.

⚠️ Odoo n'appelle ``post_init_hook`` QU'À L'INSTALLATION du module
(state « to install ») — JAMAIS sur une simple mise à jour (``-u``).
Réf. odoo/modules/loading.py : le hook n'est exécuté que si ``new_install``.

Pour garantir le Journal des à-nouveaux (code AN) AUSSI lors des mises à jour,
la logique est centralisée dans la méthode idempotente
``res.company._ensure_journals_a_nouveau()``, appelée :
  * ici, par le post_init_hook (installation) ;
  * par une balise <function> dans data/journal_data.xml (installation + ``-u``).
"""


def post_init_hook(env):
    """Crée le Journal des à-nouveaux (AN) pour toutes les sociétés, à l'installation."""
    env["res.company"]._ensure_journals_a_nouveau()

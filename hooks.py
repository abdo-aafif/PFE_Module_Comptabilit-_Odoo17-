# -*- coding: utf-8 -*-
"""
Hooks d'installation du module Comptabilité Omega Soft.

post_init_hook : exécuté UNE SEULE FOIS après l'installation ou la mise à jour
du module. Utilisé ici pour créer le Journal des à-nouveaux (code AN) dans
TOUTES les sociétés existantes, et non uniquement la société active au moment
de l'installation.

Pourquoi un hook et non un enregistrement XML ?
-----------------------------------------------
Un <record> XML sans company_id explicite est rattaché à la société dont
l'ID est défini dans le contexte d'installation (généralement la société 1).
Dans un environnement multi-sociétés, les autres sociétés n'auraient pas le
journal AN — ce hook corrige ce comportement.
"""


def post_init_hook(env):
    """Crée le Journal des à-nouveaux (AN) pour chaque société qui n'en a pas.

    Ce hook est appelé automatiquement par Odoo après l'installation ou la
    mise à jour du module (déclaré dans __manifest__.py via 'post_init_hook').

    Args:
        env (odoo.api.Environment): environnement Odoo avec les droits SUPERUSER.
    """
    companies = env['res.company'].search([])

    for company in companies:
        # Vérifie si un journal avec le code 'AN' existe déjà pour cette société
        existing = env['account.journal'].search([
            ('code', '=', 'AN'),
            ('company_id', '=', company.id),
        ], limit=1)

        if not existing:
            env['account.journal'].create({
                'name': "Journal des à-nouveaux",
                'code': 'AN',
                'type': 'general',
                'show_on_dashboard': True,
                'company_id': company.id,
            })

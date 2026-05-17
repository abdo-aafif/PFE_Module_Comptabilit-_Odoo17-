# -*- coding: utf-8 -*-
"""Extension de ``account.analytic.line`` pour le Suivi Analytique multi-plans.

Contexte fonctionnel
--------------------
En Odoo 17, chaque **plan analytique** (Projets, Départements, Internal, …)
crée son propre champ ``Many2one`` dynamique sur ``account.analytic.line``.
Le champ standard ``account_id`` ne correspond qu'au plan principal
historique « Projects ».

Conséquence métier : les lignes analytiques dont la distribution porte
**uniquement** sur un autre plan (par exemple ``DEP-INFO`` du plan
« Départements ») ont ``account_id = False`` et apparaissent regroupées
sous la mention générique « Aucun » dans les vues groupées du Suivi
Analytique — ce qui rend le reporting illisible.

Solution mise en place
----------------------
Ce module ajoute le champ stocké et calculé ``compta_account_id`` qui
contient le compte analytique de **n'importe quel plan**, avec une
priorité donnée au plan principal. Il sert de pivot pour :

    * le groupement unifié dans la vue « Suivi Analytique »
    * la recherche multi-plans dans la barre de recherche enrichie
    * l'export et le reporting pivot/graph

Conformité au CDC : section 3.1.1 (Plan Comptable / Comptabilité analytique).
"""
from odoo import models, fields, api


class AccountAnalyticLine(models.Model):
    """Extension du modèle natif ``account.analytic.line``.

    N'introduit aucun stockage métier supplémentaire en base : seul un
    champ calculé (stocké pour permettre l'indexation et le tri SQL) est
    ajouté afin d'unifier la vision des comptes analytiques tous plans
    confondus.
    """

    _inherit = 'account.analytic.line'

    # -------------------------------------------------------------------------
    # Champs
    # -------------------------------------------------------------------------
    compta_account_id = fields.Many2one(
        'account.analytic.account',
        string='Compte Analytique',
        compute='_compute_compta_account_id',
        store=True,   # Stocké : requis pour le groupement SQL et le tri natif
        index=True,   # Indexé : accélère les filtres et group_by dans le reporting
        help="Compte analytique de la ligne, tous plans confondus "
             "(Projets, Départements, Internal, ...). Utilisé pour "
             "le groupement unifié dans le Suivi Analytique.",
    )

    # -------------------------------------------------------------------------
    # Méthodes calculées (@api.depends)
    # -------------------------------------------------------------------------
    @api.depends('account_id')
    def _compute_compta_account_id(self):
        """Calcule le compte analytique unifié, tous plans confondus.

        Règle métier :
            1. Si la ligne porte une distribution sur le plan principal
               (« Projects ») via ``account_id``, ce dernier est retenu en
               priorité — c'est l'axe d'analyse historique d'Odoo.
            2. Sinon, la méthode parcourt les autres plans dans l'ordre
               retourné par ``_get_all_plans()`` (ordre déterministe
               défini par Odoo : séquence puis identifiant) et retient le
               premier compte non-vide trouvé.
            3. Si aucun plan ne porte de valeur, le champ reste ``False``
               (la ligne ne sera pas regroupée par compte analytique).

        :return: Aucune valeur retournée — la méthode affecte directement
                 ``self.compta_account_id`` pour chaque enregistrement.

        Notes:
            - La dépendance ``@api.depends('account_id')`` suffit en
              pratique : lorsqu'Odoo enregistre une ligne analytique, le
              moteur recalcule la totalité du champ. Les champs dynamiques
              des autres plans ne sont pas connus à l'avance et sont
              résolus dynamiquement à l'exécution.
            - Le champ étant ``store=True``, ce calcul n'est exécuté que
              lors de la création/modification des lignes — pas à chaque
              lecture, ce qui garantit de bonnes performances.
        """
        # Récupère le plan principal (« Projects ») et la liste des autres plans
        # dans l'ordre déterministe défini par le module ``analytic``.
        project_plan, other_plans = self.env['account.analytic.plan']._get_all_plans()

        # Pré-calcule les noms de colonnes SQL associés à chaque plan
        # (ex. ``account_id``, ``x_plan2_dep_id``, …) afin d'éviter de
        # rappeler ``_column_name()`` à chaque itération sur ``self``.
        plan_columns = [p._column_name() for p in (project_plan + other_plans)]

        for line in self:
            account = False
            # Première colonne non-vide ⇒ priorité respectée par construction
            # (plan principal d'abord, puis autres plans).
            for col in plan_columns:
                # Vérifie que la colonne existe bien sur le modèle (sécurité
                # défensive : un plan peut être désactivé ou non instancié).
                if col in line._fields and line[col]:
                    account = line[col]
                    break
            line.compta_account_id = account

# -*- coding: utf-8 -*-
from odoo import models, fields
from dateutil.relativedelta import relativedelta


class AccountRecurring(models.Model):
    _name = "account.recurring"
    _description = "Écritures récurrentes (Abonnements)"

    name = fields.Char(string="Nom de l'abonnement", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Société",
        default=lambda self: self.env.company,
    )
    journal_id = fields.Many2one("account.journal", required=True)
    move_id = fields.Many2one(
        "account.move",
        string="Écriture modèle",
        required=True,
        help="L'écriture comptable existante qui servira de modèle " "à cloner pour chaque répétition",
    )

    date_start = fields.Date(string="Date de début", required=True, default=fields.Date.context_today)
    date_next = fields.Date(string="Prochaine date d'exécution", required=True, default=fields.Date.context_today)

    interval_number = fields.Integer(string="Intervalle", default=1, required=True)
    interval_type = fields.Selection(
        [
            ("days", "Jours"),
            ("weeks", "Semaines"),
            ("months", "Mois"),
            ("years", "Années"),
        ],
        string="Périodicité",
        default="months",
        required=True,
    )

    state = fields.Selection(
        [
            ("draft", "Brouillon"),
            ("running", "En cours"),
            ("done", "Terminé"),
        ],
        string="Statut",
        default="draft",
    )

    generated_move_ids = fields.One2many("account.move", "recurring_id", string="Écritures générées", readonly=True)

    def action_start(self):
        self.state = "running"

    def action_stop(self):
        self.state = "done"

    def action_generate_move(self):
        for rec in self:
            if rec.state == "running" and rec.move_id:
                rec.move_id.copy(
                    {
                        "date": rec.date_next,
                        "recurring_id": rec.id,
                        "ref": f"{rec.name} (Généré) - {rec.date_next}",
                        "auto_post": "no",  # La laisser en brouillon pour vérification
                    }
                )

                if rec.interval_type == "days":
                    rec.date_next = rec.date_next + relativedelta(days=rec.interval_number)
                elif rec.interval_type == "weeks":
                    rec.date_next = rec.date_next + relativedelta(weeks=rec.interval_number)
                elif rec.interval_type == "months":
                    rec.date_next = rec.date_next + relativedelta(months=rec.interval_number)
                elif rec.interval_type == "years":
                    rec.date_next = rec.date_next + relativedelta(years=rec.interval_number)


class AccountMove(models.Model):
    _inherit = "account.move"

    recurring_id = fields.Many2one("account.recurring", string="Généré par abonnement", readonly=True, copy=False)

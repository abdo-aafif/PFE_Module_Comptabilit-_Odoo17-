from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CurrencyRevaluationWizard(models.TransientModel):
    _name = "compta.currency.revaluation.wizard"
    _description = "Évaluation Multi-Devises (Écarts de conversion fin de période)"

    company_id = fields.Many2one("res.company", string="Société", default=lambda self: self.env.company)
    revaluation_date = fields.Date(string="Date d'évaluation", default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one(
        "account.journal", string="Journal des OD", domain=[("type", "=", "general")], required=True
    )

    income_account_id = fields.Many2one(
        "account.account",
        string="Compte Gain de Change (ex: 7331)",
        required=True,
        domain=[("account_type", "in", ("income", "income_other"))],
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Compte Perte de Change (ex: 6331)",
        required=True,
        domain=[("account_type", "in", ("expense", "expense_depreciation"))],
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company

        if "income_account_id" in fields_list and company.income_currency_exchange_account_id:
            res["income_account_id"] = company.income_currency_exchange_account_id.id
        if "expense_account_id" in fields_list and company.expense_currency_exchange_account_id:
            res["expense_account_id"] = company.expense_currency_exchange_account_id.id

        if "journal_id" in fields_list:
            journal = self.env["account.journal"].search(
                [("type", "=", "general"), ("company_id", "=", company.id)], limit=1
            )
            if journal:
                res["journal_id"] = journal.id

        return res

    def action_revaluate(self):
        self.ensure_one()

        company_currency = self.company_id.currency_id

        domain = [
            ("company_id", "=", self.company_id.id),
            ("move_type", "in", ("out_invoice", "in_invoice", "out_refund", "in_refund")),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
            ("currency_id", "!=", company_currency.id),
            ("date", "<=", self.revaluation_date),
        ]

        moves = self.env["account.move"].search(domain)
        if not moves:
            raise UserError(_("Aucune facture ouverte en devise étrangère trouvée à la date de fin de période."))

        move_lines_to_create = []

        for move in moves:
            partner_line = move.line_ids.filtered(
                lambda ml: ml.account_id.account_type in ("asset_receivable", "liability_payable")
            )
            if not partner_line:
                continue

            line = partner_line[0]
            amount_residual_currency = line.amount_residual_currency

            if amount_residual_currency == 0:
                continue

            historic_amount_company_curr = line.amount_residual

            new_amount_company_curr = move.currency_id._convert(
                amount_residual_currency,
                company_currency,
                self.company_id,
                self.revaluation_date,
            )

            diff = new_amount_company_curr - historic_amount_company_curr

            if company_currency.is_zero(diff):
                continue

            is_receivable = line.account_id.account_type == "asset_receivable"

            if is_receivable:
                is_gain = diff > 0
            else:
                # Pour les dettes, une diminution de dette (diff négative) est un gain
                is_gain = diff < 0

            move_lines_to_create.append(
                (
                    0,
                    0,
                    {
                        "name": _("Évaluation Écart Conversion: %s") % move.name,
                        "partner_id": move.partner_id.id,
                        "account_id": line.account_id.id,
                        "debit": diff if diff > 0 else 0.0,
                        "credit": -diff if diff < 0 else 0.0,
                        "currency_id": company_currency.id,
                    },
                )
            )

            exchange_account = self.income_account_id if is_gain else self.expense_account_id
            move_lines_to_create.append(
                (
                    0,
                    0,
                    {
                        "name": _("Écarts Conversion Contrepartie: %s") % move.name,
                        "account_id": exchange_account.id,
                        "debit": -diff if diff < 0 else 0.0,
                        "credit": diff if diff > 0 else 0.0,
                        "currency_id": company_currency.id,
                    },
                )
            )

        if not move_lines_to_create:
            raise UserError(_("Aucun écart de conversion significatif n'a été trouvé !"))

        reval_move = self.env["account.move"].create(
            {
                "journal_id": self.journal_id.id,
                "date": self.revaluation_date,
                "move_type": "entry",
                "ref": _("Évaluation Fin de Période (Devises)"),
                "line_ids": move_lines_to_create,
            }
        )

        reval_move.action_post()

        return {
            "name": _("Écritures d'écarts de conversion"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "account.move",
            "res_id": reval_move.id,
            "target": "current",
        }

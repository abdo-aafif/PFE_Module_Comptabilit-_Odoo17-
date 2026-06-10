from odoo import models


class AccountJournalPfe(models.Model):
    _inherit = "account.journal"

    def _fill_sale_purchase_dashboard_data(self, dashboard_data):
        """Inject balance âgée (échu / non-échu) into each sale/purchase kanban card."""
        super()._fill_sale_purchase_dashboard_data(dashboard_data)

        sale_purchase_journals = self.filtered(
            lambda j: j.type in ("sale", "purchase")
        )
        if not sale_purchase_journals:
            return

        for journal in sale_purchase_journals:
            account_type = (
                "asset_receivable" if journal.type == "sale" else "liability_payable"
            )
            currency = journal.currency_id or self.env["res.currency"].browse(
                journal.company_id.sudo().currency_id.id
            )

            balance_lines = self.env["compta.balance.agee"].search([
                ("account_type", "=", account_type),
                ("company_id", "=", journal.company_id.id),
            ])

            echu = sum(
                bal.jour_0_30 + bal.jour_30_60 + bal.jour_60_90 + bal.jour_plus_90
                for bal in balance_lines
            )
            non_echu = sum(bal.non_echu for bal in balance_lines)

            dashboard_data[journal.id].update({
                "pfe_echu_fmt": currency.format(echu) if echu else None,
                "pfe_non_echu_fmt": currency.format(non_echu) if non_echu else None,
            })

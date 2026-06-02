from odoo import models, fields, _
import logging

_logger = logging.getLogger(__name__)


class CustomFinancialReport(models.Model):
    """Report Builder – persistent report templates defined by users."""

    _name = "custom.financial.report"
    _description = "État Financier Personnalisé"
    _order = "name"

    name = fields.Char(string="Nom du rapport", required=True)
    code = fields.Char(string="Code", size=16)
    note = fields.Text(string="Description")
    line_ids = fields.One2many("custom.financial.report.line", "report_id", string="Lignes")

    def action_compute(self):
        """Open computation wizard pre-linked to this report."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Calculer – %s") % self.name,
            "res_model": "custom.report.result.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_report_id": self.id},
        }


class CustomFinancialReportLine(models.Model):
    """One line of a custom report template."""

    _name = "custom.financial.report.line"
    _description = "Ligne de rapport personnalisé"
    _order = "sequence, id"

    report_id = fields.Many2one("custom.financial.report", ondelete="cascade", required=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Désignation", required=True)
    code = fields.Char(string="Code ligne", size=16)

    line_type = fields.Selection(
        [
            ("account", "Comptes (par préfixe)"),
            ("formula", "Formule (codes de lignes)"),
            ("section", "En-tête de section"),
            ("spacer", "Séparateur"),
        ],
        string="Type",
        default="account",
        required=True,
    )

    account_prefixes = fields.Char(
        string="Préfixes de comptes",
        help="Séparés par des virgules, ex: 711,712,713",
    )
    sign = fields.Selection(
        [("1", "Normal (+débit−crédit)"), ("-1", "Inversé (crédit−débit)")],
        default="-1",
        string="Signe",
    )
    balance_type = fields.Selection(
        [
            ("cumul", "Solde cumulé (bilan)"),
            ("period", "Solde de période (résultat)"),
        ],
        string="Type de solde",
        default="period",
    )

    formula = fields.Char(
        string="Formule",
        help="Expression utilisant des codes de lignes, ex: PROD_EXPL - CH_EXPL",
    )
    level = fields.Integer(string="Niveau (indentation)", default=1)
    is_total = fields.Boolean(string="Ligne total")
    bold = fields.Boolean(string="Gras")

from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval
import logging

_logger = logging.getLogger(__name__)


class CustomReportResultWizard(models.TransientModel):
    """Transient wizard to run a custom financial report."""

    _name = "custom.report.result.wizard"
    _description = "Résultat rapport personnalisé"

    report_id = fields.Many2one("custom.financial.report", required=True, string="Rapport")
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    date_from = fields.Date(string="Date début")
    date_to = fields.Date(string="Date fin", default=fields.Date.context_today, required=True)
    result_ids = fields.One2many("custom.report.result.line", "wizard_id", "Résultats")

    @api.model
    def default_get(self, fields_list):
        from datetime import date as date_cls

        res = super().default_get(fields_list)
        today = date_cls.today()
        res.setdefault("date_from", date_cls(today.year, 1, 1))
        res.setdefault("date_to", date_cls(today.year, 12, 31))
        return res

    def action_compute(self):
        self.result_ids.unlink()
        lines = self._compute_lines()
        for ln in lines:
            ln["wizard_id"] = self.id
            self.env["custom.report.result.line"].create(ln)
        # Wizard is opened as a modal (target='new'); returning nothing would
        # close the dialog. Re-open the same record so computed result_ids are
        # visible to the user.
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_print(self):
        if not self.result_ids:
            self.action_compute()
        return self.env.ref(f"{self._module}.action_report_custom_financial").report_action(self)

    def _sql_balance(self, prefixes, sign, balance_type="period"):
        """Compute balance for given prefixes.

        balance_type:
          - 'cumul'  : cumulative balance from origin to date_to (Bilan accounts)
          - 'period' : period balance between date_from and date_to (P&L accounts)
        Falls back to 'cumul' if date_from is empty.
        """
        if not prefixes:
            return 0.0
        like_conds = " OR ".join(["a.code LIKE %s"] * len(prefixes))
        cid = self.company_id.id

        use_period = (balance_type == "period") and bool(self.date_from)
        if use_period:
            params = [cid, self.date_from, self.date_to] + [p + "%" for p in prefixes]
            where_date = "AND l.date >= %s AND l.date <= %s"
        else:
            params = [cid, self.date_to] + [p + "%" for p in prefixes]
            where_date = "AND l.date <= %s"

        self.env.cr.execute(
            f"""
            SELECT COALESCE(SUM(l.debit - l.credit), 0)
            FROM account_move_line l
            JOIN account_move    m ON l.move_id    = m.id
            JOIN account_account a ON l.account_id = a.id
            WHERE m.state = 'posted'
              AND l.company_id = %s
              {where_date}
              AND ({like_conds})
        """,
            params,
        )
        raw = self.env.cr.fetchone()[0] or 0.0
        return raw * int(sign)

    def _compute_lines(self):
        results = []
        seq = [0]
        computed = {}  # code → amount, exposed as locals to safe_eval

        for tpl_line in self.report_id.line_ids.sorted("sequence"):
            seq[0] += 1
            amount = 0.0
            has_amount = True

            if tpl_line.line_type == "account":
                prefixes = [p.strip() for p in (tpl_line.account_prefixes or "").split(",") if p.strip()]
                amount = self._sql_balance(prefixes, tpl_line.sign, tpl_line.balance_type or "period")

            elif tpl_line.line_type == "formula":
                # Codes are passed as local variables to safe_eval — no string
                # substitution (which collides on overlapping prefixes like A / AB)
                # and no raw eval (RCE via __subclasses__ even with empty builtins).
                formula = (tpl_line.formula or "").strip()
                if formula:
                    try:
                        amount = float(safe_eval(formula, {}, dict(computed)))
                    except Exception as e:
                        _logger.warning(
                            "Custom report '%s': formula '%s' failed: %s",
                            self.report_id.name,
                            formula,
                            e,
                        )
                        amount = 0.0

            else:
                # 'section' header or 'spacer' → no amount displayed
                has_amount = False

            if tpl_line.code and tpl_line.line_type in ("account", "formula"):
                computed[tpl_line.code] = amount

            results.append(
                dict(
                    name=tpl_line.name or "",
                    amount=amount,
                    level=tpl_line.level,
                    is_total=tpl_line.is_total,
                    bold=tpl_line.bold,
                    line_type=tpl_line.line_type,
                    has_amount=has_amount,
                    sequence=seq[0],
                    wizard_id=False,
                )
            )

        return results


class CustomReportResultLine(models.TransientModel):
    _name = "custom.report.result.line"
    _description = "Ligne résultat rapport personnalisé"
    _order = "sequence"

    wizard_id = fields.Many2one("custom.report.result.wizard", ondelete="cascade")
    sequence = fields.Integer()
    name = fields.Char(string="Désignation")
    amount = fields.Float(string="Montant", digits=(16, 2))
    level = fields.Integer()
    is_total = fields.Boolean()
    bold = fields.Boolean()
    line_type = fields.Char()
    has_amount = fields.Boolean(default=True)

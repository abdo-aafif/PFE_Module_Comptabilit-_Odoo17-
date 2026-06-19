import calendar
from datetime import date

from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError


class ComptaBalanceGenerale(models.Model):
    _name = "compta.balance.generale"
    _description = "Balance Générale (Vue SQL)"
    _auto = False

    account_id = fields.Many2one("account.account", string="Compte")
    company_id = fields.Many2one("res.company", string="Société")
    debit = fields.Monetary("Débit", currency_field="currency_id")
    credit = fields.Monetary("Crédit", currency_field="currency_id")
    balance = fields.Monetary("Solde", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    min(l.id) as id,
                    l.account_id,
                    l.company_id,
                    sum(l.debit) as debit,
                    sum(l.credit) as credit,
                    sum(l.balance) as balance,
                    l.company_currency_id as currency_id
                FROM account_move_line l
                JOIN account_move m ON l.move_id = m.id
                WHERE m.state = 'posted'
                GROUP BY l.account_id, l.company_id, l.company_currency_id
            )
        """ % (self._table,))


class ComptaGrandLivre(models.Model):
    _name = "compta.grand.livre"
    _description = "Grand Livre (Vue SQL)"
    _auto = False
    _order = "account_id, date, id"

    account_id = fields.Many2one("account.account", string="Compte")
    move_id = fields.Many2one("account.move", string="Pièce")
    move_name = fields.Char(string="N° Pièce")
    journal_id = fields.Many2one("account.journal", string="Journal")
    partner_id = fields.Many2one("res.partner", string="Partenaire")
    date = fields.Date(string="Date")
    label = fields.Char(string="Libellé")
    ref = fields.Char(string="Référence")
    company_id = fields.Many2one("res.company", string="Société")
    debit = fields.Monetary("Débit", currency_field="currency_id")
    credit = fields.Monetary("Crédit", currency_field="currency_id")
    balance = fields.Monetary("Solde Progressif", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    l.id as id,
                    l.account_id,
                    l.move_id,
                    m.name as move_name,
                    l.journal_id,
                    l.partner_id,
                    l.date,
                    l.name as label,
                    l.ref,
                    l.company_id,
                    l.debit,
                    l.credit,
                    SUM(l.debit - l.credit) OVER (
                        PARTITION BY l.account_id, l.company_id
                        ORDER BY l.date, l.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) as balance,
                    l.company_currency_id as currency_id
                FROM account_move_line l
                JOIN account_move m ON l.move_id = m.id
                WHERE m.state = 'posted'
            )
        """ % (self._table,))


class ComptaCentralisateur(models.TransientModel):  # pylint: disable=no-wizard-in-models
    """Journal Centralisateur périodique (Mois / Trimestre / Total cumulé).

    Contrairement à une simple vue SQL cumulée, ce modèle permet de
    centraliser les totaux Débit/Crédit par journal **sur une période
    choisie** (un mois ou un trimestre précis), tout en conservant un
    onglet « Total cumulé depuis l'origine ».
    """

    _name = "compta.centralisateur"
    _description = "Journal Centralisateur (rapport périodique)"

    _ANNEES = [(str(y), str(y)) for y in range(2020, 2035)]
    _MOIS = [
        ("01", "Janvier"), ("02", "Février"), ("03", "Mars"), ("04", "Avril"),
        ("05", "Mai"), ("06", "Juin"), ("07", "Juillet"), ("08", "Août"),
        ("09", "Septembre"), ("10", "Octobre"), ("11", "Novembre"), ("12", "Décembre"),
    ]
    _TRIMESTRES = [
        ("1", "1er Trimestre (Jan-Fév-Mars)"),
        ("2", "2ème Trimestre (Avr-Mai-Juin)"),
        ("3", "3ème Trimestre (Juil-Août-Sept)"),
        ("4", "4ème Trimestre (Oct-Nov-Déc)"),
    ]

    company_id = fields.Many2one(
        "res.company", string="Société", default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    # Sert uniquement au fil d'Ariane (display_name) — non affiché dans le formulaire.
    name = fields.Char(default="Journal Centralisateur", readonly=True)

    # ── Onglet « Par Mois » ──────────────────────────────────────────────────
    mois_annee = fields.Selection(
        _ANNEES, string="Année",
        default=lambda self: str(fields.Date.context_today(self).year),
    )
    mois_mois = fields.Selection(
        _MOIS, string="Mois",
        default=lambda self: str(fields.Date.context_today(self).month).zfill(2),
    )
    mois_line_ids = fields.One2many(
        "compta.centralisateur.line", "centralisateur_id",
        string="Centralisation mensuelle", domain=[("periode_type", "=", "mois")],
    )

    # ── Onglet « Par Trimestre » ─────────────────────────────────────────────
    trim_annee = fields.Selection(
        _ANNEES, string="Année",
        default=lambda self: str(fields.Date.context_today(self).year),
    )
    trim_trimestre = fields.Selection(
        _TRIMESTRES, string="Trimestre",
        default=lambda self: str((fields.Date.context_today(self).month - 1) // 3 + 1),
    )
    trim_line_ids = fields.One2many(
        "compta.centralisateur.line", "centralisateur_id",
        string="Centralisation trimestrielle", domain=[("periode_type", "=", "trim")],
    )

    # ── Onglet « Total cumulé » ──────────────────────────────────────────────
    total_line_ids = fields.One2many(
        "compta.centralisateur.line", "centralisateur_id",
        string="Total cumulé", domain=[("periode_type", "=", "total")],
    )

    # ── Calcul ───────────────────────────────────────────────────────────────
    def _recompute(self, periode_type, date_start, date_end):
        """Recalcule, par journal, les totaux Débit/Crédit des écritures
        comptabilisées sur la période (ou depuis l'origine si dates vides).

        Tous les journaux de la société sont listés — même ceux sans
        mouvement sur la période (affichés à 0/0), comme une vraie
        centralisation.
        """
        self.ensure_one()
        self.env["compta.centralisateur.line"].search([
            ("centralisateur_id", "=", self.id),
            ("periode_type", "=", periode_type),
        ]).unlink()

        domain = [
            ("parent_state", "=", "posted"),
            ("company_id", "=", self.company_id.id),
            ("journal_id", "!=", False),
        ]
        if date_start:
            domain.append(("date", ">=", date_start))
        if date_end:
            domain.append(("date", "<=", date_end))

        groups = self.env["account.move.line"].read_group(
            domain, fields=["debit:sum", "credit:sum"], groupby=["journal_id"]
        )
        totaux = {
            g["journal_id"][0]: (g["debit"] or 0.0, g["credit"] or 0.0)
            for g in groups if g.get("journal_id")
        }

        Line = self.env["compta.centralisateur.line"]
        journals = self.env["account.journal"].search(
            [("company_id", "=", self.company_id.id)]
        )
        for journal in journals:
            debit, credit = totaux.get(journal.id, (0.0, 0.0))
            Line.create({
                "centralisateur_id": self.id,
                "periode_type": periode_type,
                "journal_id": journal.id,
                "debit": debit,
                "credit": credit,
            })

    def action_calculer_mois(self):
        self.ensure_one()
        if not self.mois_annee or not self.mois_mois:
            raise UserError(_("Choisissez l'année et le mois avant de calculer."))
        year, month = int(self.mois_annee), int(self.mois_mois)
        date_start = date(year, month, 1)
        date_end = date(year, month, calendar.monthrange(year, month)[1])
        self._recompute("mois", date_start, date_end)

    def action_calculer_trimestre(self):
        self.ensure_one()
        if not self.trim_annee or not self.trim_trimestre:
            raise UserError(_("Choisissez l'année et le trimestre avant de calculer."))
        year, trimestre = int(self.trim_annee), int(self.trim_trimestre)
        start_month = (trimestre - 1) * 3 + 1
        end_month = start_month + 2
        date_start = date(year, start_month, 1)
        date_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        self._recompute("trim", date_start, date_end)

    @api.model
    def action_open(self):
        """Point d'entrée du menu : crée un rapport (transient) pour la session
        et calcule l'onglet « Total cumulé » avant affichage.

        TransientModel : l'enregistrement est éphémère (purgé automatiquement
        par le vacuum d'Odoo), donc aucun orphelin ne s'accumule en base.
        Les valeurs par défaut (société courante, libellé) sont posées à la
        création.
        """
        rec = self.create({})
        rec._recompute("total", False, False)
        return {
            "type": "ir.actions.act_window",
            "name": _("Journal Centralisateur"),
            "res_model": "compta.centralisateur",
            "view_mode": "form",
            "res_id": rec.id,
            "target": "current",
        }


class ComptaCentralisateurLine(models.TransientModel):  # pylint: disable=no-wizard-in-models
    _name = "compta.centralisateur.line"
    _description = "Ligne du Journal Centralisateur"
    _order = "journal_id"

    centralisateur_id = fields.Many2one(
        "compta.centralisateur", ondelete="cascade", index=True
    )
    periode_type = fields.Selection(
        [("mois", "Mois"), ("trim", "Trimestre"), ("total", "Total cumulé")],
        string="Type de période", required=True,
    )
    journal_id = fields.Many2one("account.journal", string="Journal")
    company_id = fields.Many2one(
        related="centralisateur_id.company_id", store=True, index=True
    )
    currency_id = fields.Many2one(related="centralisateur_id.currency_id")
    debit = fields.Monetary("Total Débit", currency_field="currency_id")
    credit = fields.Monetary("Total Crédit", currency_field="currency_id")


class ComptaBalanceAgee(models.Model):
    _name = "compta.balance.agee"
    _description = "Balance Agee (Vue SQL)"
    _auto = False

    partner_id = fields.Many2one("res.partner", string="Partenaire")
    account_type = fields.Selection(related="account_id.account_type", string="Type de Compte")
    account_id = fields.Many2one("account.account")
    company_id = fields.Many2one("res.company", string="Société")

    non_echu = fields.Monetary("Non échu", currency_field="currency_id")
    jour_0_30 = fields.Monetary("1-30 jours", currency_field="currency_id")
    jour_30_60 = fields.Monetary("31-60 jours", currency_field="currency_id")
    jour_60_90 = fields.Monetary("61-90 jours", currency_field="currency_id")
    jour_plus_90 = fields.Monetary("+90 jours", currency_field="currency_id")
    total = fields.Monetary("Total dû", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    min(l.id) as id,
                    l.partner_id,
                    l.account_id,
                    l.company_id,
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) <= 0  THEN ABS(l.amount_residual) ELSE 0 END) as non_echu,
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) > 0  AND (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) <= 30  THEN ABS(l.amount_residual) ELSE 0 END) as jour_0_30,
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) > 30 AND (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) <= 60  THEN ABS(l.amount_residual) ELSE 0 END) as jour_30_60,
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) > 60 AND (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) <= 90  THEN ABS(l.amount_residual) ELSE 0 END) as jour_60_90,
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) > 90 THEN ABS(l.amount_residual) ELSE 0 END) as jour_plus_90,
                    SUM(ABS(l.amount_residual)) as total,
                    l.company_currency_id as currency_id
                FROM account_move_line l
                JOIN account_move m ON l.move_id = m.id
                JOIN account_account a ON l.account_id = a.id
                WHERE m.state = 'posted'
                  AND m.move_type IN ('out_invoice', 'in_invoice')
                  AND l.reconciled = False
                  AND l.amount_residual != 0
                  AND a.account_type IN ('asset_receivable', 'liability_payable')
                  AND l.partner_id IS NOT NULL
                GROUP BY l.partner_id, l.account_id, l.company_id, l.company_currency_id
            )
        """ % (self._table,))

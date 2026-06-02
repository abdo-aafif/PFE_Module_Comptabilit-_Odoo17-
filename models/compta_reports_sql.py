from odoo import models, fields, tools


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


class ComptaJournalCentralisateur(models.Model):
    _name = "compta.journal.centralisateur"
    _description = "Journal Centralisateur (Vue SQL)"
    _auto = False

    journal_id = fields.Many2one("account.journal", string="Journal")
    company_id = fields.Many2one("res.company", string="Société")
    debit = fields.Monetary("Total Débit", currency_field="currency_id")
    credit = fields.Monetary("Total Crédit", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    j.id as id,
                    j.id as journal_id,
                    j.company_id,
                    COALESCE(stats.debit, 0) as debit,
                    COALESCE(stats.credit, 0) as credit,
                    rc.currency_id as currency_id
                FROM account_journal j
                LEFT JOIN res_company rc ON rc.id = j.company_id
                LEFT JOIN (
                    SELECT
                        l.journal_id,
                        l.company_id,
                        SUM(l.debit) as debit,
                        SUM(l.credit) as credit
                    FROM account_move_line l
                    JOIN account_move m ON l.move_id = m.id
                    WHERE m.state = 'posted'
                    GROUP BY l.journal_id, l.company_id
                ) stats ON stats.journal_id = j.id AND stats.company_id = j.company_id
            )
        """ % (self._table,))


class ComptaBalanceAgee(models.Model):
    _name = "compta.balance.agee"
    _description = "Balance Agee (Vue SQL)"
    _auto = False

    partner_id = fields.Many2one("res.partner", string="Partenaire")
    account_type = fields.Selection(related="account_id.account_type", string="Type de Compte")
    account_id = fields.Many2one("account.account")
    company_id = fields.Many2one("res.company", string="Société")

    jour_0_30 = fields.Monetary("0-30 jours", currency_field="currency_id")
    jour_30_60 = fields.Monetary("30-60 jours", currency_field="currency_id")
    jour_60_90 = fields.Monetary("60-90 jours", currency_field="currency_id")
    jour_plus_90 = fields.Monetary("+90 jours", currency_field="currency_id")
    total = fields.Monetary("Total", currency_field="currency_id")
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
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) <= 30 THEN ABS(l.amount_residual) ELSE 0 END) as jour_0_30,
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) > 30 AND (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) <= 60 THEN ABS(l.amount_residual) ELSE 0 END) as jour_30_60,
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) > 60 AND (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) <= 90 THEN ABS(l.amount_residual) ELSE 0 END) as jour_60_90,
                    SUM(CASE WHEN (CURRENT_DATE - COALESCE(l.date_maturity, l.date)) > 90 THEN ABS(l.amount_residual) ELSE 0 END) as jour_plus_90,
                    SUM(ABS(l.amount_residual)) as total,
                    l.company_currency_id as currency_id
                FROM account_move_line l
                JOIN account_move m ON l.move_id = m.id
                JOIN account_account a ON l.account_id = a.id
                WHERE m.state = 'posted'
                  AND l.reconciled = False
                  AND l.amount_residual != 0
                  AND a.account_type IN ('asset_receivable', 'liability_payable')
                  AND l.partner_id IS NOT NULL
                GROUP BY l.partner_id, l.account_id, l.company_id, l.company_currency_id
            )
        """ % (self._table,))

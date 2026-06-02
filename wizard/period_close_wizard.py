from odoo import models, fields, api, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta
from datetime import date
import logging

_logger = logging.getLogger(__name__)


class PeriodCloseWizard(models.TransientModel):
    """
    Wizard de clôture comptable mensuelle / annuelle.
    """
    _name = 'period.close.wizard'
    _description = 'Wizard Clôture Comptable'

    company_id = fields.Many2one(
        'res.company', string='Société',
        default=lambda s: s.env.company, required=True,
    )
    close_type = fields.Selection([
        ('monthly', 'Clôture Mensuelle'),
        ('annual',  'Clôture Annuelle'),
    ], string='Type de clôture', required=True, default='monthly')

    date_from = fields.Date(string='Début de période', required=True)
    date_to   = fields.Date(string='Fin de période',   required=True)

    # ── Résultats des contrôles ───────────────────────────────────────────────
    checks_done = fields.Boolean(default=False)

    check_balance      = fields.Boolean(readonly=True)
    check_no_draft     = fields.Boolean(readonly=True)
    check_depreciation = fields.Boolean(readonly=True)
    check_reconciled   = fields.Boolean(readonly=True)

    msg_balance      = fields.Char(readonly=True)
    msg_no_draft     = fields.Char(readonly=True)
    msg_depreciation = fields.Char(readonly=True)
    msg_reconciled   = fields.Char(readonly=True)

    # ── Détails des anomalies ─────────────────────────────────────────────────
    draft_move_ids = fields.Many2many(
        'account.move',
        'period_close_wiz_draft_rel',
        'wizard_id', 'move_id',
        string='Écritures en brouillon',
        readonly=True,
    )
    unreconciled_line_ids = fields.Many2many(
        'account.bank.statement.line',
        'period_close_wiz_unrec_rel',
        'wizard_id', 'line_id',
        string='Transactions non rapprochées',
        readonly=True,
    )
    unposted_dep_ids = fields.Many2many(
        'account.asset.depreciation.line',
        'period_close_wiz_dep_rel',
        'wizard_id', 'dep_id',
        string='Dotations non comptabilisées',
        readonly=True,
    )

    all_checks_ok = fields.Boolean(compute='_compute_all_checks_ok')

    # ── Options annuelles ─────────────────────────────────────────────────────
    generate_opening = fields.Boolean(
        string='Générer les écritures à-nouveaux', default=True,
    )
    opening_journal_id = fields.Many2one(
        'account.journal', string='Journal à-nouveaux',
        domain=[('type', '=', 'general')],
    )
    account_result_id = fields.Many2one(
        'account.account', string='Compte résultat (Bénéfice)',
        help="PCGE : 119100 – Résultat net solde créditeur (bénéfice)",
        domain=[('deprecated', '=', False)],
    )
    account_result_loss_id = fields.Many2one(
        'account.account', string='Compte résultat (Perte)',
        help="PCGE : 119900 – Résultat net solde débiteur (perte)",
        domain=[('deprecated', '=', False)],
    )

    # ── Defaults ─────────────────────────────────────────────────────────────

    def _set_default_opening_accounts(self):
        """Renseigne journal + comptes résultat à partir du PCGE marocain."""
        self.ensure_one()
        company_id = self.company_id.id or self.env.company.id

        if not self.opening_journal_id:
            # Cherche d'abord le journal dédié aux à-nouveaux (code AN),
            # puis tombe sur le premier journal général disponible (ex: OD).
            journal = self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('code', '=', 'AN'),
                ('company_id', '=', company_id),
            ], limit=1)
            if not journal:
                journal = self.env['account.journal'].search([
                    ('type', '=', 'general'),
                    ('company_id', '=', company_id),
                ], limit=1)
            if journal:
                self.opening_journal_id = journal.id

        if not self.account_result_id:
            account_benefit = self.env['account.account'].search([
                ('code', '=', '119100'),
                ('company_id', '=', company_id),
            ], limit=1)
            if not account_benefit:
                account_benefit = self.env['account.account'].search([
                    ('code', '=like', '1191%'),
                    ('company_id', '=', company_id),
                ], limit=1)
                if account_benefit:
                    _logger.warning(
                        "Clôture comptable : compte 119100 introuvable, fallback sur %s (%s). "
                        "Vérifiez le plan comptable PCGE.",
                        account_benefit.code, account_benefit.name,
                    )
            if account_benefit:
                self.account_result_id = account_benefit.id

        if not self.account_result_loss_id:
            account_loss = self.env['account.account'].search([
                ('code', '=', '119900'),
                ('company_id', '=', company_id),
            ], limit=1)
            if not account_loss:
                account_loss = self.env['account.account'].search([
                    ('code', '=like', '1199%'),
                    ('company_id', '=', company_id),
                ], limit=1)
                if account_loss:
                    _logger.warning(
                        "Clôture comptable : compte 119900 introuvable, fallback sur %s (%s). "
                        "Vérifiez le plan comptable PCGE.",
                        account_loss.code, account_loss.name,
                    )
            if account_loss:
                self.account_result_loss_id = account_loss.id

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = date.today()

        first_day_current = today.replace(day=1)
        last_month_end    = first_day_current - relativedelta(days=1)
        last_month_start  = last_month_end.replace(day=1)

        res.update({
            'date_from': last_month_start,
            'date_to':   last_month_end,
        })

        company_id = res.get('company_id') or self.env.company.id
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('code', '=', 'AN'),
            ('company_id', '=', company_id),
        ], limit=1)
        if not journal:
            journal = self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('company_id', '=', company_id),
            ], limit=1)
        if journal:
            res['opening_journal_id'] = journal.id

        account_benefit = self.env['account.account'].search([
            ('code', '=', '119100'),
            ('company_id', '=', company_id),
        ], limit=1)
        if not account_benefit:
            account_benefit = self.env['account.account'].search([
                ('code', '=like', '1191%'),
                ('company_id', '=', company_id),
            ], limit=1)
            if account_benefit:
                _logger.warning(
                    "Clôture comptable : compte 119100 introuvable, fallback sur %s (%s). "
                    "Vérifiez le plan comptable PCGE.",
                    account_benefit.code, account_benefit.name,
                )
        if account_benefit:
            res['account_result_id'] = account_benefit.id

        account_loss = self.env['account.account'].search([
            ('code', '=', '119900'),
            ('company_id', '=', company_id),
        ], limit=1)
        if not account_loss:
            account_loss = self.env['account.account'].search([
                ('code', '=like', '1199%'),
                ('company_id', '=', company_id),
            ], limit=1)
            if account_loss:
                _logger.warning(
                    "Clôture comptable : compte 119900 introuvable, fallback sur %s (%s). "
                    "Vérifiez le plan comptable PCGE.",
                    account_loss.code, account_loss.name,
                )
        if account_loss:
            res['account_result_loss_id'] = account_loss.id

        return res

    @api.depends('check_balance', 'check_no_draft', 'check_depreciation', 'check_reconciled', 'checks_done')
    def _compute_all_checks_ok(self):
        for wiz in self:
            wiz.all_checks_ok = (
                wiz.checks_done
                and wiz.check_balance
                and wiz.check_no_draft
                and wiz.check_depreciation
                and wiz.check_reconciled
            )

    @api.onchange('close_type')
    def _onchange_close_type(self):
        today = date.today()
        if self.close_type == 'monthly':
            first_day_current = today.replace(day=1)
            last_month_end    = first_day_current - relativedelta(days=1)
            self.date_from = last_month_end.replace(day=1)
            self.date_to   = last_month_end
        else:
            prev_year = today.year - 1
            self.date_from = date(prev_year, 1, 1)
            self.date_to   = date(prev_year, 12, 31)

    # ── ÉTAPE 1 : Contrôles pré-clôture ──────────────────────────────────────

    def action_run_checks(self):
        self.ensure_one()
        if not self.date_from or not self.date_to:
            raise UserError(_("Veuillez saisir la période avant de lancer les contrôles."))
        if self.date_from > self.date_to:
            raise UserError(_("La date de début doit être antérieure à la date de fin."))

        company = self.company_id

        # ── Contrôle 1 : Balance équilibrée ──────────────────────────────────
        self.env.cr.execute("""
            SELECT
                COALESCE(SUM(debit), 0),
                COALESCE(SUM(credit), 0)
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            WHERE am.company_id = %s
              AND am.state = 'posted'
              AND aml.date BETWEEN %s AND %s
        """, (company.id, self.date_from, self.date_to))
        total_debit, total_credit = self.env.cr.fetchone()
        diff = abs(total_debit - total_credit)
        if diff < 0.01:
            self.check_balance = True
            self.msg_balance   = _("Débit = Crédit = {:,.2f} MAD").format(total_debit)
        else:
            self.check_balance = False
            self.msg_balance   = _("Déséquilibre de {:,.2f} MAD  |  Débit: {:,.2f}  |  Crédit: {:,.2f}").format(
                diff, total_debit, total_credit)

        # ── Contrôle 2 : Aucune écriture brouillon ───────────────────────────
        draft_moves = self.env['account.move'].search([
            ('company_id', '=', company.id),
            ('state', '=', 'draft'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        self.draft_move_ids = [(6, 0, draft_moves.ids)]
        if not draft_moves:
            self.check_no_draft = True
            self.msg_no_draft   = _("Aucune écriture en brouillon")
        else:
            self.check_no_draft = False
            self.msg_no_draft   = _("{} écriture(s) en brouillon à comptabiliser ou supprimer").format(len(draft_moves))

        # ── Contrôle 3 : Amortissements comptabilisés ─────────────────────────
        unposted_dep = self.env['account.asset.depreciation.line'].search([
            ('asset_id.company_id', '=', company.id),
            ('state', '=', 'draft'),
            ('depreciation_date', '>=', self.date_from),
            ('depreciation_date', '<=', self.date_to),
        ])
        self.unposted_dep_ids = [(6, 0, unposted_dep.ids)]
        if not unposted_dep:
            self.check_depreciation = True
            self.msg_depreciation   = _("Toutes les dotations aux amortissements sont comptabilisées")
        else:
            self.check_depreciation = False
            self.msg_depreciation   = _("{} dotation(s) non comptabilisée(s)").format(len(unposted_dep))

        # ── Contrôle 4 : Transactions bancaires rapprochées ───────────────────
        unreconciled = self.env['account.bank.statement.line'].search([
            ('journal_id.company_id', '=', company.id),
            ('is_reconciled', '=', False),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        self.unreconciled_line_ids = [(6, 0, unreconciled.ids)]
        # Non bloquant : on stocke le résultat réel, le blocage est géré dans action_close_period
        self.check_reconciled = not unreconciled
        if not unreconciled:
            self.msg_reconciled = _("Toutes les transactions bancaires sont rapprochées")
        else:
            self.msg_reconciled = _("{} transaction(s) non rapprochée(s) (non bloquant)").format(len(unreconciled))

        self.checks_done = True

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'period.close.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ── ÉTAPE 2 : Verrouillage + à-nouveaux + historique ─────────────────────

    def action_close_period(self):
        self.ensure_one()

        if not self.checks_done:
            raise UserError(_("Veuillez d'abord lancer les contrôles pré-clôture."))
        if not self.check_balance:
            raise UserError(_("Impossible de clôturer : la balance n'est pas équilibrée."))
        if not self.check_no_draft:
            raise UserError(_("Impossible de clôturer : des écritures sont encore en brouillon."))
        if not self.check_depreciation:
            raise UserError(_("Impossible de clôturer : des amortissements ne sont pas comptabilisés."))

        company = self.company_id

        # ── Bug fix #2 : protection contre la double clôture ─────────────────
        existing = self.env['account.period.close'].search([
            ('company_id', '=', company.id),
            ('close_type', '=', self.close_type),
            ('date_from',  '=', self.date_from),
            ('date_to',    '=', self.date_to),
            ('state',      '=', 'done'),
        ], limit=1)
        if existing:
            raise UserError(_(
                "Une clôture %s existe déjà pour la période du %s au %s (réf : %s).\n"
                "Annulez-la via le bouton \"Déverrouiller\" avant d'en créer une nouvelle."
            ) % (
                dict(self._fields['close_type'].selection).get(self.close_type),
                self.date_from.strftime('%d/%m/%Y'),
                self.date_to.strftime('%d/%m/%Y'),
                existing.name,
            ))

        opening_move = False

        # ── Génération AVANT le verrouillage ────────────────────────────────
        # Si la génération échoue, la période n'est PAS verrouillée → rattrapable.
        if self.close_type == 'annual' and self.generate_opening:
            opening_move = self._generate_opening_entries()

        # ── Verrouillage de la période ──────────────────────────────────────
        # max() garantit que la date de verrou n'est jamais rétrogradée :
        # si une clôture mensuelle récente (ex: 31/03/2026) existe déjà,
        # une clôture annuelle antérieure (ex: 31/12/2024) ne l'écrasera pas.
        new_period_lock = max(company.period_lock_date or date.min, self.date_to)
        if self.close_type == 'monthly':
            company.sudo().write({'period_lock_date': new_period_lock})
        else:
            new_fiscal_lock = max(company.fiscalyear_lock_date or date.min, self.date_to)
            company.sudo().write({
                'fiscalyear_lock_date': new_fiscal_lock,
                'period_lock_date':     new_period_lock,
            })

        close_record = self.env['account.period.close'].create({
            'close_type':           self.close_type,
            'company_id':           company.id,
            'date_from':            self.date_from,
            'date_to':              self.date_to,
            'date_close':           fields.Date.context_today(self),
            'state':                'done',
            'check_balance':        self.check_balance,
            'check_no_draft':       self.check_no_draft,
            'check_depreciation':   self.check_depreciation,
            'check_reconciled':     self.check_reconciled,
            'opening_move_id':      opening_move.id if opening_move else False,
            'period_lock_date':     company.period_lock_date,
            'fiscalyear_lock_date': company.fiscalyear_lock_date,
        })

        label = _("Clôture mensuelle") if self.close_type == 'monthly' else _("Clôture annuelle")
        body = _("%s effectuée du %s au %s. Période verrouillée.") % (
            label,
            self.date_from.strftime('%d/%m/%Y'),
            self.date_to.strftime('%d/%m/%Y'),
        )
        if opening_move:
            body += _(
                "\nÉcriture à-nouveaux %s créée en BROUILLON (à comptabiliser après vérification)."
            ) % (opening_move.name or opening_move.ref or '')
        close_record.message_post(body=body)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Clôture effectuée'),
            'res_model': 'account.period.close',
            'res_id': close_record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Génération des à-nouveaux ─────────────────────────────────────────────

    def _generate_opening_entries(self):
        company = self.company_id

        if not self.opening_journal_id:
            raise UserError(_("Veuillez sélectionner un journal pour les écritures à-nouveaux."))
        if not self.account_result_id:
            raise UserError(_("Veuillez sélectionner le compte résultat bénéfice (119100)."))
        if not self.account_result_loss_id:
            raise UserError(_("Veuillez sélectionner le compte résultat perte (119900)."))

        opening_date = self.date_to + relativedelta(days=1)

        # Pré-contrôle : la période N+1 doit être accessible pour créer l'écriture.
        # Un verrou existant sur la société bloquerait la création avec un message générique ;
        # on préfère une UserError explicite avant d'entrer dans le savepoint.
        if company.period_lock_date and company.period_lock_date >= opening_date:
            raise UserError(_(
                "Impossible de créer l'écriture à-nouveaux au %s :\n"
                "la période est verrouillée jusqu'au %s sur la société « %s ».\n\n"
                "Déverrouillez la période (Comptabilité › Configuration › Paramètres) "
                "avant de relancer la clôture annuelle."
            ) % (
                opening_date.strftime('%d/%m/%Y'),
                company.period_lock_date.strftime('%d/%m/%Y'),
                company.name,
            ))
        if company.fiscalyear_lock_date and company.fiscalyear_lock_date >= opening_date:
            raise UserError(_(
                "Impossible de créer l'écriture à-nouveaux au %s :\n"
                "l'exercice fiscal est verrouillé jusqu'au %s sur la société « %s ».\n\n"
                "Déverrouillez l'exercice fiscal (Comptabilité › Configuration › Paramètres) "
                "avant de relancer la clôture annuelle."
            ) % (
                opening_date.strftime('%d/%m/%Y'),
                company.fiscalyear_lock_date.strftime('%d/%m/%Y'),
                company.name,
            ))

        # Bug fix #1 : ROUND au niveau SQL → soldes alignés sur 2 décimales,
        # exclusion uniquement des soldes strictement nuls après arrondi.
        self.env.cr.execute("""
            SELECT
                aml.account_id,
                aa.code,
                aa.name,
                ROUND(COALESCE(SUM(aml.debit - aml.credit), 0)::numeric, 2) AS balance
            FROM account_move_line aml
            JOIN account_account aa ON aa.id = aml.account_id
            JOIN account_move am    ON am.id = aml.move_id
            WHERE am.company_id = %s
              AND am.state = 'posted'
              AND aml.date <= %s
            GROUP BY aml.account_id, aa.code, aa.name
            HAVING ROUND(COALESCE(SUM(aml.debit - aml.credit), 0)::numeric, 2) != 0
            ORDER BY aa.code
        """, (company.id, self.date_to))

        rows = self.env.cr.fetchall()
        lines = []
        result_balance = 0.0

        for account_id, code, name, balance in rows:
            balance = float(balance)
            first_char = code[0] if code else '0'
            if first_char in ('6', '7'):
                result_balance += balance
            elif first_char in ('1', '2', '3', '4', '5'):
                if balance > 0:
                    lines.append((0, 0, {
                        'account_id': account_id,
                        'name': _("À-nouveau %s") % self.date_to.year,
                        'debit': round(balance, 2), 'credit': 0.0,
                    }))
                elif balance < 0:
                    lines.append((0, 0, {
                        'account_id': account_id,
                        'name': _("À-nouveau %s") % self.date_to.year,
                        'debit': 0.0, 'credit': round(abs(balance), 2),
                    }))

        result_balance = round(result_balance, 2)
        if abs(result_balance) > 0:
            # result_balance = SUM(débit - crédit) pour comptes 6 et 7
            # Bénéfice (produits > charges) → result_balance < 0 → Crédit 119100
            # Perte   (charges > produits) → result_balance > 0 → Débit  119900
            if result_balance < 0:
                result_account = self.account_result_id       # 119100 bénéfice
            else:
                result_account = self.account_result_loss_id  # 119900 perte

            lines.append((0, 0, {
                'account_id': result_account.id,
                'name': _("Résultat exercice %s") % self.date_to.year,
                'debit':  result_balance        if result_balance > 0 else 0.0,
                'credit': abs(result_balance)   if result_balance < 0 else 0.0,
            }))

        if not lines:
            return False

        # Bug fix #1 (suite) : ligne d'écart d'arrondi si le total débit ≠ crédit.
        total_debit  = round(sum(l[2]['debit']  for l in lines), 2)
        total_credit = round(sum(l[2]['credit'] for l in lines), 2)
        diff = round(total_debit - total_credit, 2)
        if diff != 0:
            ecart_account = self.account_result_loss_id if diff > 0 else self.account_result_id
            lines.append((0, 0, {
                'account_id': ecart_account.id,
                'name': _("Écart d'arrondi à-nouveaux %s") % self.date_to.year,
                'debit':  abs(diff) if diff < 0 else 0.0,
                'credit': abs(diff) if diff > 0 else 0.0,
            }))

        # Bug fix #1 (sécurité) : savepoint pour que toute exception de création
        # ou de validation ne laisse pas un état partiel dans la transaction.
        try:
            with self.env.cr.savepoint():
                move = self.env['account.move'].create({
                    'journal_id': self.opening_journal_id.id,
                    'date':       opening_date,
                    'ref':        _("À-nouveaux exercice %s → %s") % (self.date_to.year, self.date_to.year + 1),
                    'company_id': company.id,
                    'line_ids':   lines,
                })
        except Exception as e:
            _logger.exception("Échec de génération des à-nouveaux")
            raise UserError(_(
                "Échec de génération de l'écriture à-nouveaux :\n%s\n\n"
                "La période n'a PAS été verrouillée. Corrigez et relancez la clôture."
            ) % str(e))

        # UX 3 : on laisse l'écriture en BROUILLON pour révision.
        # L'utilisateur la comptabilise depuis le formulaire d'historique.
        return move

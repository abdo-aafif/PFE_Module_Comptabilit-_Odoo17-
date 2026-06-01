from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class BankReconciliationWizard(models.TransientModel):
    _name = 'bank.reconciliation.wizard'
    _description = 'Rapprochement Bancaire'

    statement_line_id = fields.Many2one(
        'account.bank.statement.line',
        string='Transaction Bancaire',
        required=True,
        readonly=True,
    )

    # ── Infos de la transaction (affichage) ──────────────────────────────────
    date = fields.Date(related='statement_line_id.date', readonly=True)
    payment_ref = fields.Char(related='statement_line_id.payment_ref', readonly=True)
    amount = fields.Monetary(related='statement_line_id.amount', readonly=True)
    currency_id = fields.Many2one(related='statement_line_id.currency_id', readonly=True)
    journal_id = fields.Many2one(related='statement_line_id.journal_id', readonly=True)
    is_reconciled = fields.Boolean(related='statement_line_id.is_reconciled', readonly=True)

    # ── Mode ─────────────────────────────────────────────────────────────────
    mode = fields.Selection([
        ('write_off', 'Imputation directe'),
        ('match', 'Associer à une écriture existante'),
    ], default='write_off', required=True)

    # ── Mode imputation directe ───────────────────────────────────────────────
    account_id = fields.Many2one(
        'account.account',
        string='Compte de contrepartie',
        domain=[('deprecated', '=', False)],
    )
    label = fields.Char(string="Libellé")

    INVOICE_TYPES = ['out_invoice', 'in_invoice', 'out_refund', 'in_refund']

    # ── Mode association ──────────────────────────────────────────────────────
    move_line_id = fields.Many2one(
        'account.move.line',
        string='Écriture à associer',
        domain=[
            ('reconciled', '=', False),
            ('parent_state', '=', 'posted'),
            ('account_id.reconcile', '=', True),
            ('move_id.move_type', 'in', ['out_invoice', 'in_invoice', 'out_refund', 'in_refund']),
        ],
    )

    # ── Candidats calculés (affichage informatif) ─────────────────────────────
    candidate_ids = fields.Many2many(
        'account.move.line',
        'bank_rec_wiz_candidate_rel',
        'wizard_id', 'line_id',
        string='Écritures candidates',
        compute='_compute_candidates',
    )

    @api.depends('statement_line_id')
    def _compute_candidates(self):
        for wiz in self:
            if not wiz.statement_line_id:
                wiz.candidate_ids = False
                continue
            amount = wiz.statement_line_id.amount
            domain = [
                ('reconciled', '=', False),
                ('parent_state', '=', 'posted'),
                ('account_id.reconcile', '=', True),
                ('move_id.move_type', 'in', ['out_invoice', 'in_invoice', 'out_refund', 'in_refund']),
            ]
            if amount > 0:
                domain.append(('balance', '>', 0))
            else:
                domain.append(('balance', '<', 0))
            wiz.candidate_ids = self.env['account.move.line'].search(domain, limit=50)

    # ── Action principale ─────────────────────────────────────────────────────

    def action_reconcile(self):
        self.ensure_one()
        line = self.statement_line_id

        if line.is_reconciled:
            raise UserError(_("Cette transaction est déjà rapprochée."))

        if self.mode == 'write_off':
            if not self.account_id:
                raise UserError(_("Veuillez sélectionner un compte de contrepartie."))
            self._do_write_off(line)
        else:
            if not self.move_line_id:
                raise UserError(_("Veuillez sélectionner une écriture à associer."))
            self._do_match(line)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Transactions Bancaires (à rapprocher)'),
            'res_model': 'account.bank.statement.line',
            'view_mode': 'list,form',
            'domain': [('is_reconciled', '=', False)],
            'context': {'create': False},
        }

    # ── Imputation directe ────────────────────────────────────────────────────

    def _do_write_off(self, line):
        """
        Remplace le compte suspens par le compte choisi et valide le mouvement.
        Utilisé pour les frais bancaires, revenus directs, etc.
        """
        move = line.move_id
        if not move:
            raise UserError(_("Aucun mouvement comptable associé à cette transaction."))

        # En Odoo 17 le mouvement importé est déjà validé — remettre en brouillon
        if move.state == 'posted':
            move.button_draft()

        suspense_lines = self._get_suspense_lines(line, move)
        suspense_lines.write({
            'account_id': self.account_id.id,
            'name': self.label or line.payment_ref or '/',
        })
        move.action_post()

    # ── Association à une écriture existante ──────────────────────────────────

    def _do_match(self, line):
        """
        Associe la transaction à une ligne d'écriture existante (facture payée, etc.)
        via réconciliation comptable.
        """
        move = line.move_id
        if not move:
            raise UserError(_("Aucun mouvement comptable associé à cette transaction."))

        target_line = self.move_line_id
        if not target_line.account_id.reconcile:
            raise UserError(_(
                'Le compte "%(account)s" n\'est pas réconciliable. '
                'Activez l\'option "Autoriser la réconciliation" sur ce compte '
                'dans Configuration > Plan Comptable.'
            ) % {'account': target_line.account_id.display_name})

        # En Odoo 17 le mouvement importé est déjà validé — remettre en brouillon
        if move.state == 'posted':
            move.button_draft()

        suspense_lines = self._get_suspense_lines(line, move)
        suspense_lines.write({
            'account_id': target_line.account_id.id,
            'name': line.payment_ref or '/',
        })
        move.action_post()

        # Réconcilier les deux lignes sur le même compte
        updated_line = move.line_ids.filtered(
            lambda ln: ln.account_id == target_line.account_id and not ln.reconciled
        )[:1]

        if updated_line and not target_line.reconciled:
            (updated_line | target_line).reconcile()
        else:
            _logger.warning(
                "Rapprochement partiel pour transaction %s : "
                "lignes déjà réconciliées ou introuvables.",
                line.id
            )

    # ── Utilitaire ────────────────────────────────────────────────────────────

    def _get_suspense_lines(self, line, move):
        """Retourne la (les) ligne(s) du compte suspens dans le mouvement."""
        suspense_account = line.journal_id.suspense_account_id
        if suspense_account:
            suspense_lines = move.line_ids.filtered(
                lambda ln: ln.account_id == suspense_account
            )
        else:
            # Fallback : ligne qui n'est pas le compte bancaire
            bank_account = line.journal_id.default_account_id
            suspense_lines = move.line_ids.filtered(
                lambda ln: ln.account_id != bank_account
            )

        if not suspense_lines:
            raise UserError(_(
                "Impossible de trouver la ligne de contrepartie (compte suspens) "
                "dans le mouvement %(move)s. "
                "Vérifiez que le journal bancaire a un compte suspens configuré."
            ) % {'move': move.name})

        return suspense_lines


class AccountFullReconcile(models.Model):
    _inherit = 'account.full.reconcile'

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = str(rec.id)

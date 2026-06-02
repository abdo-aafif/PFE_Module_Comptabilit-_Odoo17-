from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class AccountPeriodClose(models.Model):
    """
    Historique des clôtures comptables (mensuelles et annuelles).
    Chaque enregistrement représente une clôture effectuée.
    """

    _name = "account.period.close"
    _description = "Clôture Comptable"
    _order = "date_close desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        string="Référence",
        required=True,
        readonly=True,
        default="/",
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Société",
        default=lambda s: s.env.company,
        required=True,
        tracking=True,
    )
    close_type = fields.Selection(
        [
            ("monthly", "Clôture Mensuelle"),
            ("annual", "Clôture Annuelle"),
        ],
        string="Type",
        required=True,
        tracking=True,
    )

    date_from = fields.Date(string="Début de période", required=True, tracking=True)
    date_to = fields.Date(string="Fin de période", required=True, tracking=True)
    date_close = fields.Date(
        string="Date de clôture",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )

    state = fields.Selection(
        [
            ("draft", "Brouillon"),
            ("done", "Clôturée"),
            ("cancelled", "Annulée"),
        ],
        default="draft",
        string="État",
        tracking=True,
    )

    # Résultats des contrôles
    check_balance = fields.Boolean(string="Balance équilibrée", readonly=True)
    check_no_draft = fields.Boolean(string="Aucune écriture brouillon", readonly=True)
    check_depreciation = fields.Boolean(string="Amortissements comptabilisés", readonly=True)
    check_reconciled = fields.Boolean(string="Pas de transactions non rapprochées", readonly=True)

    # Écriture à-nouveaux générée
    opening_move_id = fields.Many2one(
        "account.move",
        string="Écriture à-nouveaux",
        readonly=True,
    )
    opening_move_state = fields.Selection(
        related="opening_move_id.state",
        string="État écriture",
        readonly=True,
    )

    # Verrous appliqués
    period_lock_date = fields.Date(string="Date verrou période", readonly=True)
    fiscalyear_lock_date = fields.Date(string="Date verrou exercice", readonly=True)

    note = fields.Text(string="Observations", tracking=True)

    @api.constrains("company_id", "close_type", "date_from", "date_to", "state")
    def _check_unique_done_closure(self):
        for rec in self:
            if rec.state != "done":
                continue
            duplicate = self.search(
                [
                    ("id", "!=", rec.id),
                    ("company_id", "=", rec.company_id.id),
                    ("close_type", "=", rec.close_type),
                    ("date_from", "=", rec.date_from),
                    ("date_to", "=", rec.date_to),
                    ("state", "=", "done"),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(_("Une clôture validée existe déjà pour cette période (%s).") % duplicate.name)

    @api.model
    def create(self, vals):
        if vals.get("name", "/") == "/":
            close_type = vals.get("close_type", "monthly")
            seq_code = "account.period.close.annual" if close_type == "annual" else "account.period.close.monthly"
            vals["name"] = self.env["ir.sequence"].next_by_code(seq_code) or "/"
        return super().create(vals)

    def unlink(self):
        for rec in self:
            if rec.state == "done":
                # pylint: disable=no-raise-unlink
                # Protection métier explicite : une clôture validée ne peut pas
                # être supprimée silencieusement (intégrité de l'historique).
                raise UserError(
                    _(
                        'Impossible de supprimer la clôture "%s" car elle est en état "Clôturée".\n'
                        'Annulez-la d\'abord via le bouton "Déverrouiller".'
                    )
                    % rec.name
                )
        return super().unlink()

    # ── Smart button : voir l'écriture à-nouveaux ────────────────────────────
    def action_view_opening_move(self):
        self.ensure_one()
        if not self.opening_move_id:
            raise UserError(_("Aucune écriture à-nouveaux n'est associée à cette clôture."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Écriture à-nouveaux"),
            "res_model": "account.move",
            "res_id": self.opening_move_id.id,
            "view_mode": "form",
            "target": "current",
        }

    # ── Confirmer (poster) l'écriture à-nouveaux ─────────────────────────────
    def action_post_opening_move(self):
        self.ensure_one()
        if not self.opening_move_id:
            raise UserError(_("Aucune écriture à-nouveaux à comptabiliser."))
        if self.opening_move_id.state == "posted":
            raise UserError(_("L'écriture à-nouveaux est déjà comptabilisée."))
        self.opening_move_id.action_post()
        self.message_post(
            body=_("Écriture à-nouveaux %s comptabilisée par %s.")
            % (self.opening_move_id.name or self.opening_move_id.ref, self.env.user.name)
        )
        return True

    # ── Annuler / supprimer l'écriture à-nouveaux (laisse la clôture) ─────────
    def action_cancel_opening_move(self):
        self.ensure_one()
        if not self.opening_move_id:
            raise UserError(_("Aucune écriture à-nouveaux à annuler."))
        if self.opening_move_id.state == "posted":
            self.opening_move_id.button_draft()
        move_ref = self.opening_move_id.name or self.opening_move_id.ref or ""
        self.opening_move_id.unlink()
        self.opening_move_id = False
        self.message_post(
            body=_("Écriture à-nouveaux %s supprimée par %s. Vous pouvez la régénérer.")
            % (move_ref, self.env.user.name)
        )
        return True

    # ── Régénérer une écriture à-nouveaux (annuel uniquement) ─────────────────
    def action_regenerate_opening_move(self):
        self.ensure_one()
        if self.close_type != "annual":
            raise UserError(_("La régénération des à-nouveaux n'est possible que pour une clôture annuelle."))
        if self.opening_move_id:
            raise UserError(_("Une écriture à-nouveaux existe déjà. Supprimez-la d'abord."))
        wizard = self.env["period.close.wizard"].new(
            {
                "company_id": self.company_id.id,
                "close_type": self.close_type,
                "date_from": self.date_from,
                "date_to": self.date_to,
            }
        )
        wizard._set_default_opening_accounts()
        if not wizard.opening_journal_id or not wizard.account_result_id or not wizard.account_result_loss_id:
            raise UserError(
                _(
                    "Impossible de régénérer automatiquement : configurez le journal et les comptes "
                    "résultat (119100 / 119900) avant de relancer."
                )
            )
        move = wizard._generate_opening_entries()
        if move:
            self.opening_move_id = move.id
            self.message_post(
                body=_("Écriture à-nouveaux régénérée par %s (en brouillon, à comptabiliser).") % self.env.user.name
            )
        return self.action_view_opening_move() if move else True

    # ── Déverrouiller (annuler la clôture) — réservé Manager Comptable ───────
    def action_unlock(self):
        self.ensure_one()
        if not self.env.user.has_group("account.group_account_manager"):
            raise UserError(_("Seul un Manager Comptable peut déverrouiller une clôture."))
        if self.state != "done":
            raise UserError(_("Seule une clôture en état 'Clôturée' peut être déverrouillée."))
        if not self.note or not self.note.strip():
            raise UserError(_('Veuillez saisir un motif dans le champ "Observations" avant de déverrouiller.'))

        company = self.company_id
        # Ne lever le verrou que s'il correspond toujours à cette clôture
        if self.close_type == "annual":
            if company.fiscalyear_lock_date == self.date_to:
                company.sudo().write({"fiscalyear_lock_date": False})
            if company.period_lock_date == self.date_to:
                company.sudo().write({"period_lock_date": False})
        else:
            if company.period_lock_date == self.date_to:
                company.sudo().write({"period_lock_date": False})

        # Si une écriture à-nouveaux existe et n'est pas postée → suppression
        if self.opening_move_id and self.opening_move_id.state != "posted":
            self.opening_move_id.unlink()
            self.opening_move_id = False

        self.state = "cancelled"
        self.message_post(body=_("Clôture déverrouillée par %s.\nMotif : %s") % (self.env.user.name, self.note))
        return True

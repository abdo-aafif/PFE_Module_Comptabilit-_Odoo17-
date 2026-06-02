from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AccountAssetDisposalWizard(models.TransientModel):
    """
    Wizard de cession ou de mise au rebut d'une immobilisation.

    Génère automatiquement l'écriture comptable de sortie :
      - Solde le compte d'immobilisation  (crédit 2xxx)
      - Solde les amortissements cumulés   (débit  28xx)
      - Comptabilise la plus/moins-value   (crédit 7512 / débit 6512)
      - Comptabilise le prix de cession    (débit  3481 Clients divers si vente)
    """

    _name = "account.asset.disposal.wizard"
    _description = "Wizard Cession / Mise au rebut"

    asset_id = fields.Many2one(
        "account.asset",
        string="Immobilisation",
        required=True,
        domain=[("state", "in", ("open", "close"))],
    )

    disposal_type = fields.Selection(
        [
            ("sale", "Cession (vente)"),
            ("rebut", "Mise au rebut"),
        ],
        string="Type",
        required=True,
        default="sale",
    )

    disposal_date = fields.Date(
        string="Date de cession/rebut",
        required=True,
        default=fields.Date.context_today,
    )

    # Valeurs calculées en lecture seule
    acquisition_value = fields.Monetary(
        string="Valeur d'acquisition",
        related="asset_id.acquisition_value",
        readonly=True,
    )
    value_depreciated = fields.Monetary(
        string="Amortissements cumulés (comptabilisés)",
        compute="_compute_vnc",
        readonly=True,
    )
    vnc = fields.Monetary(
        string="VNC à la date de cession",
        compute="_compute_vnc",
        readonly=True,
    )

    # Cession uniquement
    sale_price = fields.Monetary(
        string="Prix de cession HT",
        default=0.0,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Acheteur",
    )
    account_receivable_id = fields.Many2one(
        "account.account",
        string="Compte débiteur (acheteur)",
        help="Ex: 3481 – Clients divers (si vente hors partenaire habituel)",
    )

    # Résultat
    result_amount = fields.Monetary(
        string="Plus-value / Moins-value",
        compute="_compute_result",
        readonly=True,
    )
    result_type = fields.Selection(
        [
            ("gain", "Plus-value"),
            ("loss", "Moins-value"),
            ("zero", "Neutre"),
        ],
        compute="_compute_result",
        readonly=True,
    )

    currency_id = fields.Many2one(related="asset_id.currency_id")

    # ── Calculs ───────────────────────────────────────────────────────────────

    @api.depends("asset_id", "disposal_date")
    def _compute_vnc(self):
        for wiz in self:
            if not wiz.asset_id:
                wiz.value_depreciated = 0.0
                wiz.vnc = 0.0
                continue

            # Compter TOUTES les lignes déjà comptabilisées, quelle que soit leur date.
            # Une dotation comptabilisée a déjà été passée en charge → la VNC est réduite.
            dep = sum(
                wiz.asset_id.depreciation_line_ids.filtered(lambda ln: ln.state == "posted").mapped(
                    "depreciation_amount"
                )
            )

            wiz.value_depreciated = dep
            wiz.vnc = wiz.asset_id.acquisition_value - dep

    @api.depends("sale_price", "vnc", "disposal_type")
    def _compute_result(self):
        for wiz in self:
            if wiz.disposal_type == "rebut":
                result = -wiz.vnc  # perte = VNC entière
            else:
                result = (wiz.sale_price or 0.0) - wiz.vnc
            wiz.result_amount = result
            if result > 0.005:
                wiz.result_type = "gain"
            elif result < -0.005:
                wiz.result_type = "loss"
            else:
                wiz.result_type = "zero"

    # ── Validation ────────────────────────────────────────────────────────────

    def action_dispose(self):
        self.ensure_one()
        asset = self.asset_id

        if asset.state not in ("open", "close"):
            raise UserError(_("L'immobilisation doit être 'En service' ou 'Totalement amortie'."))

        # Comptabiliser les lignes non encore comptabilisées avant la date de cession
        unposted = asset.depreciation_line_ids.filtered(
            lambda ln: ln.state == "draft" and ln.depreciation_date <= self.disposal_date
        )
        if unposted:
            unposted.action_post()

        # Prorata temporis : Comptabiliser la dotation de l'année de sortie (jusqu'à la date de cession)
        next_draft = asset.depreciation_line_ids.filtered(
            lambda ln: ln.state == "draft" and ln.depreciation_date > self.disposal_date
        ).sorted("depreciation_date")

        if next_draft:
            line_to_prorate = next_draft[0]
            # Vérifier si c'est la même année
            if line_to_prorate.depreciation_date.year == self.disposal_date.year:
                months_prorata = self.disposal_date.month
                original_months = line_to_prorate.months or 12
                # Calculer la part de dotation jusqu'au mois de cession
                if months_prorata < original_months:
                    prorata_amount = round(line_to_prorate.depreciation_amount * (months_prorata / original_months), 2)
                    line_to_prorate.write(
                        {
                            "depreciation_amount": prorata_amount,
                            "depreciation_date": self.disposal_date,
                            "months": months_prorata,
                        }
                    )
                line_to_prorate.action_post()

            # Annuler les lignes restantes
            asset.depreciation_line_ids.filtered(lambda ln: ln.state == "draft").unlink()

        # Recalculer la VNC réelle après comptabilisation
        posted = asset.depreciation_line_ids.filtered(lambda ln: ln.state == "posted")
        total_depreciated = sum(posted.mapped("depreciation_amount"))
        vnc_real = asset.acquisition_value - total_depreciated

        # Vérification des comptes
        if not asset.account_asset_id:
            raise UserError(_("Compte d'immobilisation manquant sur la fiche."))
        if not asset.account_depreciation_id:
            raise UserError(_("Compte d'amortissement (Bilan) manquant sur la fiche."))
        if not asset.account_gain_id and self.disposal_type == "sale" and self.sale_price > 0:
            raise UserError(_("Compte produit de cession (751x) manquant sur la catégorie ou la fiche."))
        if not asset.account_loss_id and vnc_real > 0.005:
            raise UserError(
                _(
                    "Compte VNA cédée (651x) manquant sur la catégorie ou la fiche. "
                    "Ce compte est requis dès que la VNC est non nulle."
                )
            )
        if not asset.journal_id:
            raise UserError(_("Journal manquant sur la fiche."))

        lines = []

        if self.disposal_type == "sale" and self.sale_price > 0:
            receivable = self.account_receivable_id or asset.account_gain_id  # fallback
            # Débit : Créance client (3481)
            lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": receivable.id,
                        "name": _("Créance - Cession %s") % asset.name,
                        "debit": self.sale_price,
                        "credit": 0.0,
                        "partner_id": self.partner_id.id if self.partner_id else False,
                    },
                )
            )
            # Crédit : Produit de cession (751x)
            lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": asset.account_gain_id.id,
                        "name": _("Produit de cession - %s") % asset.name,
                        "debit": 0.0,
                        "credit": self.sale_price,
                        "partner_id": self.partner_id.id if self.partner_id else False,
                    },
                )
            )

        # ── 2) Écriture de sortie de l'actif (PCGE) ──
        # Débit : Amortissements cumulés (28xx)
        if total_depreciated > 0.005:
            lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": asset.account_depreciation_id.id,
                        "name": _("Amort. cumulés – sortie %s") % asset.name,
                        "debit": total_depreciated,
                        "credit": 0.0,
                    },
                )
            )

        # Débit : VNA cédée (651x)
        if vnc_real > 0.005:
            lines.append(
                (
                    0,
                    0,
                    {
                        "account_id": asset.account_loss_id.id,
                        "name": _("VNA des immo. cédées – %s") % asset.name,
                        "debit": vnc_real,
                        "credit": 0.0,
                    },
                )
            )

        # Crédit : Compte d'immobilisation (2xxx)
        lines.append(
            (
                0,
                0,
                {
                    "account_id": asset.account_asset_id.id,
                    "name": _("Sortie d'immobilisation – %s") % asset.name,
                    "debit": 0.0,
                    "credit": asset.acquisition_value,
                },
            )
        )

        # Création et validation de l'écriture
        label = (_("Cession") if self.disposal_type == "sale" else _("Mise au rebut")) + _(" – %s") % asset.name
        move = self.env["account.move"].create(
            {
                "journal_id": asset.journal_id.id,
                "date": self.disposal_date,
                "ref": label,
                "company_id": asset.company_id.id,
                "line_ids": lines,
            }
        )
        move.action_post()

        asset.write(
            {
                "state": "disposed",
                "disposal_date": self.disposal_date,
                "disposal_move_id": move.id,
            }
        )
        asset.message_post(
            body=_("%s comptabilisée le %s. Écriture : %s")
            % (
                _("Cession") if self.disposal_type == "sale" else _("Mise au rebut"),
                self.disposal_date.strftime("%d/%m/%Y"),
                move.name,
            )
        )

        # Retourner sur l'écriture générée
        return {
            "type": "ir.actions.act_window",
            "name": _("Écriture de cession"),
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
        }

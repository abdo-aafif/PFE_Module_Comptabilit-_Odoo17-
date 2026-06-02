from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import date as date_cls
import logging

_logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CATÉGORIE D'IMMOBILISATION
# ─────────────────────────────────────────────────────────────────────────────


class AccountAssetCategory(models.Model):
    _name = "account.asset.category"
    _description = "Catégorie d'immobilisation"
    _order = "name"

    name = fields.Char(string="Catégorie", required=True)
    code = fields.Char(string="Code", size=10)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company)
    active = fields.Boolean(default=True)

    # Comptes par défaut – PCGE Marocain
    account_asset_id = fields.Many2one(
        "account.account",
        string="Compte d'immobilisation",
        help="Classe 2 — ex: 2320 Matériel de bureau, 2340 Matériel de transport",
    )
    account_depreciation_id = fields.Many2one(
        "account.account",
        string="Compte d'amortissement (Bilan)",
        help="Classe 28 — ex: 2832 Amortissement matériel bureau",
    )
    account_expense_id = fields.Many2one(
        "account.account",
        string="Compte dotation aux amortissements (CPC)",
        help="Classe 619 — ex: 6193 Dotations aux amortissements des immo. corpo.",
    )
    account_gain_id = fields.Many2one(
        "account.account",
        string="Compte produit de cession",
        help="Compte 7512 — Produits de cession des immo. corporelles",
    )
    account_loss_id = fields.Many2one(
        "account.account",
        string="Compte VNC cédée (perte)",
        help="Compte 6512 — V.N.C. des immo. corporelles cédées",
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Journal",
        domain=[("type", "=", "general")],
    )

    # Paramètres d'amortissement par défaut
    method = fields.Selection(
        [
            ("linear", "Linéaire"),
            ("degressive", "Dégressif (CGI Marocain)"),
        ],
        string="Méthode par défaut",
        default="linear",
        required=True,
    )
    duration_years = fields.Integer(
        string="Durée par défaut (années)",
        default=5,
        required=True,
    )
    note = fields.Text(
        string="Notes",
        help="Taux CGI indicatifs : Constructions 4-5%, Matériel 10-15%, Véhicules 20-25%",
    )


# ─────────────────────────────────────────────────────────────────────────────
# IMMOBILISATION
# ─────────────────────────────────────────────────────────────────────────────


class AccountAsset(models.Model):
    _name = "account.asset"
    _description = "Immobilisation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "acquisition_date desc, name"

    # ── Identification ────────────────────────────────────────────────────────
    name = fields.Char(string="Désignation", required=True, tracking=True)
    ref = fields.Char(string="N° Inventaire")
    category_id = fields.Many2one(
        "account.asset.category",
        string="Catégorie",
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        default=lambda s: s.env.company,
        required=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id", store=True)
    note = fields.Text(string="Description")

    # ── Acquisition ───────────────────────────────────────────────────────────
    acquisition_date = fields.Date(
        string="Date d'acquisition",
        required=True,
        tracking=True,
    )
    commissioning_date = fields.Date(
        string="Date de mise en service",
        required=True,
        tracking=True,
    )
    acquisition_value = fields.Monetary(
        string="Valeur d'acquisition HT",
        required=True,
        tracking=True,
    )
    residual_value = fields.Monetary(
        string="Valeur résiduelle",
        default=0.0,
        help="Valeur de revente estimée en fin de vie (souvent 0 pour le fiscal marocain).",
    )
    purchase_move_id = fields.Many2one(
        "account.move",
        string="Écriture d'acquisition",
        readonly=True,
    )

    # ── Paramètres d'amortissement ────────────────────────────────────────────
    method = fields.Selection(
        [
            ("linear", "Linéaire"),
            ("degressive", "Dégressif (CGI Marocain)"),
        ],
        string="Méthode",
        default="linear",
        required=True,
        tracking=True,
    )
    duration_years = fields.Integer(
        string="Durée (années)",
        default=5,
        required=True,
        tracking=True,
    )

    # ── Comptes comptables ────────────────────────────────────────────────────
    account_asset_id = fields.Many2one(
        "account.account",
        string="Compte immobilisation",
    )
    account_depreciation_id = fields.Many2one(
        "account.account",
        string="Compte amortissement (Bilan)",
    )
    account_expense_id = fields.Many2one(
        "account.account",
        string="Compte dotation (CPC)",
    )
    account_gain_id = fields.Many2one(
        "account.account",
        string="Compte produit de cession",
    )
    account_loss_id = fields.Many2one(
        "account.account",
        string="Compte VNC cédée",
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Journal",
        domain=[("type", "=", "general")],
    )

    # ── État ──────────────────────────────────────────────────────────────────
    state = fields.Selection(
        [
            ("draft", "Brouillon"),
            ("open", "En service"),
            ("close", "Totalement amorti"),
            ("disposed", "Cédé / Mis au rebut"),
        ],
        default="draft",
        string="État",
        tracking=True,
        required=True,
    )

    disposal_date = fields.Date(string="Date de cession/rebut", readonly=True)
    disposal_move_id = fields.Many2one(
        "account.move",
        string="Écriture de cession/rebut",
        readonly=True,
    )

    # ── Lignes d'amortissement ────────────────────────────────────────────────
    depreciation_line_ids = fields.One2many(
        "account.asset.depreciation.line",
        "asset_id",
        string="Tableau d'amortissement",
    )

    # ── Calculés ──────────────────────────────────────────────────────────────
    value_depreciated = fields.Monetary(
        string="Amortissements cumulés",
        compute="_compute_values",
        store=True,
    )
    value_residual = fields.Monetary(
        string="Valeur nette comptable (VNC)",
        compute="_compute_values",
        store=True,
    )
    # Separate compute to avoid inconsistent store/compute_sudo warning (Odoo 17)
    depreciation_count = fields.Integer(
        compute="_compute_depreciation_count",
        string="Nb d'échéances",
    )

    @api.depends(
        "acquisition_value",
        "residual_value",
        "depreciation_line_ids.depreciation_amount",
        "depreciation_line_ids.state",
    )
    def _compute_values(self):
        for asset in self:
            posted = asset.depreciation_line_ids.filtered(lambda ln: ln.state == "posted")
            depreciated = sum(posted.mapped("depreciation_amount"))
            asset.value_depreciated = depreciated
            asset.value_residual = asset.acquisition_value - depreciated

    @api.depends("depreciation_line_ids")
    def _compute_depreciation_count(self):
        for asset in self:
            asset.depreciation_count = len(asset.depreciation_line_ids)

    # ── Onchange catégorie ────────────────────────────────────────────────────
    @api.onchange("category_id")
    def _onchange_category(self):
        if not self.category_id:
            return
        cat = self.category_id
        self.account_asset_id = cat.account_asset_id
        self.account_depreciation_id = cat.account_depreciation_id
        self.account_expense_id = cat.account_expense_id
        self.account_gain_id = cat.account_gain_id
        self.account_loss_id = cat.account_loss_id
        self.journal_id = cat.journal_id
        self.method = cat.method
        self.duration_years = cat.duration_years

    # ── Contraintes ───────────────────────────────────────────────────────────
    @api.constrains("acquisition_value", "residual_value")
    def _check_values(self):
        for a in self:
            if a.acquisition_value <= 0:
                raise ValidationError(_("La valeur d'acquisition doit être strictement positive."))
            if a.residual_value < 0:
                raise ValidationError(_("La valeur résiduelle ne peut pas être négative."))
            if a.residual_value >= a.acquisition_value:
                raise ValidationError(
                    _("La valeur résiduelle (%.2f) doit être inférieure à la valeur d'acquisition (%.2f).")
                    % (a.residual_value, a.acquisition_value)
                )

    @api.constrains("duration_years")
    def _check_duration(self):
        for a in self:
            if a.duration_years < 1:
                raise ValidationError(_("La durée d'amortissement doit être d'au moins 1 an."))

    @api.constrains("commissioning_date", "acquisition_date")
    def _check_dates(self):
        for a in self:
            if a.commissioning_date < a.acquisition_date:
                raise ValidationError(
                    _("La date de mise en service (%s) ne peut pas être antérieure " "à la date d'acquisition (%s).")
                    % (a.commissioning_date, a.acquisition_date)
                )

    # ── Workflow ──────────────────────────────────────────────────────────────

    def action_validate(self):
        """Valide l'immobilisation : (re-)calcule le tableau et passe en 'En service'."""
        for asset in self:
            if asset.state != "draft":
                raise UserError(_("Seule une immobilisation en brouillon peut être mise en service."))
            self._check_required_accounts(asset)
            # Toujours recalculer pour garantir la cohérence avec la méthode choisie
            asset.action_compute_depreciation()
            asset.write({"state": "open"})
            asset.message_post(body=_("Immobilisation mise en service."))

    def action_set_draft(self):
        for asset in self:
            if asset.state != "open":
                raise UserError(_("Seul un actif 'En service' peut être remis en brouillon."))
            posted = asset.depreciation_line_ids.filtered(lambda ln: ln.state == "posted")
            if posted:
                raise UserError(
                    _(
                        "Des écritures d'amortissement ont déjà été comptabilisées. "
                        "Annulez-les d'abord avant de revenir en brouillon."
                    )
                )
            asset.depreciation_line_ids.unlink()
            asset.write({"state": "draft"})

    def action_compute_depreciation(self):
        """(Re-)génère le tableau d'amortissement complet."""
        for asset in self:
            if asset.state not in ("draft", "open"):
                continue

            posted = asset.depreciation_line_ids.filtered(lambda ln: ln.state == "posted")
            if posted:
                raise UserError(
                    _(
                        "Impossible de recalculer le tableau d'amortissement car des écritures ont déjà été comptabilisées. "
                        "Veuillez annuler les écritures comptabilisées avant de relancer le calcul."
                    )
                )

            if asset.method == "degressive":
                lines_data = asset._compute_degressive_schedule()
            else:
                lines_data = asset._compute_linear_schedule()

            commands = [(5, 0, 0)]  # Vider les lignes brouillons (toutes puisqu'on a bloqué s'il y a des posted)

            for data in lines_data:
                commands.append((0, 0, data))

            asset.write({"depreciation_line_ids": commands})

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Tableau calculé"),
                "message": _("Le tableau d'amortissement a été (re-)généré avec succès."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_open_disposal_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Cession / Mise au rebut"),
            "res_model": "account.asset.disposal.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_asset_id": self.id},
        }

    def action_print_depreciation_table(self):
        return self.env.ref(f"{self._module}.action_report_asset_depreciation").report_action(self)

    # ── Algorithme Linéaire ───────────────────────────────────────────────────

    def _compute_linear_schedule(self):
        """Amortissement linéaire avec prorata temporis en mois (1ère et dernière année)."""
        duration = self.duration_years
        base = self.acquisition_value - self.residual_value
        annual_amt = base / duration

        com_date = self.commissioning_date
        first_months = 12 - com_date.month + 1  # mois restants dans l'année de mise en service

        lines = []
        remaining = round(base, 2)
        year = com_date.year
        seq = 1

        for i in range(duration + 1):  # +1 pour absorber le reste du prorata
            if remaining <= 0.005:
                break

            if i == 0:
                # 1ère année : prorata
                months = first_months
                amt = round(annual_amt * months / 12, 2)
            elif i == duration:
                # Dernière année complémentaire : on solde le reste pour éviter un écart d'arrondi
                months = 12 - first_months if first_months < 12 else 12
                amt = remaining
            else:
                months = 12
                amt = round(annual_amt, 2)

            amt = min(round(amt, 2), remaining)
            remaining = round(remaining - amt, 2)

            lines.append(
                self._build_line(
                    seq,
                    date_cls(year, 12, 31),
                    amt,
                    round(base - remaining, 2),
                    remaining + self.residual_value,
                    "linear",
                    months,
                    round(1 / duration * 100, 4),
                )
            )
            seq += 1
            year += 1

        return lines

    # ── Algorithme Dégressif (CGI Marocain) ───────────────────────────────────

    def _compute_degressive_schedule(self):
        """
        Amortissement dégressif CGI Marocain (Art. 7 CGI).

        Coefficients :
          3–4 ans → 1,5  |  5–6 ans → 2,0  |  > 6 ans → 3,0

        Taux dégressif = taux linéaire × coefficient
        Appliqué sur la VNC restante chaque année.
        Prorata temporis en mois sur la 1ère année.
        Basculement automatique au linéaire (VNC / années restantes)
        dès que la dotation linéaire dépasse la dotation dégressive.
        """
        n = self.duration_years
        base = self.acquisition_value - self.residual_value

        # Taux
        taux_lin = 1.0 / n
        if n <= 4:
            coeff = 1.5
        elif n <= 6:
            coeff = 2.0
        else:
            coeff = 3.0
        taux_deg = taux_lin * coeff

        # Prorata 1ère année : nombre de mois entre mise en service et fin d'année
        start_month = self.commissioning_date.month
        start_year = self.commissioning_date.year
        first_months = 13 - start_month  # ex: janv.=12, avr.=9, oct.=3

        lines = []
        vnc = round(base, 2)
        year = start_year

        for i in range(n + 2):  # +2 absorbe le prorata résiduel éventuel
            if vnc <= 0.005:
                break

            # Années restantes dans le plan en comptant l'année courante
            years_left = n - i

            if years_left <= 0:
                # Solde résiduel (arrondi ou prorata dernier exercice)
                amt = vnc
                method_flag = "linear_switch"
                months_used = 12
            else:
                dot_deg = vnc * taux_deg  # dotation dégressive sur VNC
                dot_lin = vnc / years_left  # dotation linéaire sur années restantes

                if i == 0:
                    # 1ère année : on applique le prorata temporis en mois
                    dot_deg = dot_deg * first_months / 12
                    dot_lin = dot_lin * first_months / 12
                    months_used = first_months
                else:
                    months_used = 12

                # Basculement : on prend le plus élevé des deux
                if dot_lin > dot_deg:
                    amt = dot_lin
                    method_flag = "linear_switch"
                else:
                    amt = dot_deg
                    method_flag = "degressive"

            amt = round(min(amt, vnc), 2)
            vnc = round(vnc - amt, 2)

            rate = round(taux_deg * 100, 4) if method_flag == "degressive" else round(taux_lin * 100, 4)

            lines.append(
                {
                    "sequence": i + 1,
                    "depreciation_date": date_cls(year, 12, 31),
                    "depreciation_amount": amt,
                    "cumulated_amount": round(base - vnc, 2),
                    "remaining_value": vnc + self.residual_value,
                    "method_used": method_flag,
                    "months": months_used,
                    "rate": rate,
                    "state": "draft",
                }
            )
            year += 1

        return lines

    # ── Utilitaires ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_line(seq, dep_date, amount, cumulated, vnc, method_used, months=12, rate=0.0):
        return {
            "sequence": seq,
            "depreciation_date": dep_date,
            "depreciation_amount": amount,
            "cumulated_amount": cumulated,
            "remaining_value": vnc,
            "method_used": method_used,
            "months": months,
            "rate": rate,
            "state": "draft",
        }

    @staticmethod
    def _check_required_accounts(asset):
        missing = []
        if not asset.account_asset_id:
            missing.append(_("Compte d'immobilisation"))
        if not asset.account_depreciation_id:
            missing.append(_("Compte d'amortissement (Bilan)"))
        if not asset.account_expense_id:
            missing.append(_("Compte de dotation (CPC)"))
        if not asset.journal_id:
            missing.append(_("Journal comptable"))
        if missing:
            raise UserError(_("Champs obligatoires manquants avant mise en service :\n• %s") % "\n• ".join(missing))


# ─────────────────────────────────────────────────────────────────────────────
# LIGNE D'AMORTISSEMENT
# ─────────────────────────────────────────────────────────────────────────────


class AccountAssetDepreciationLine(models.Model):
    _name = "account.asset.depreciation.line"
    _description = "Ligne d'amortissement"
    _order = "depreciation_date, sequence"

    asset_id = fields.Many2one(
        "account.asset",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="N°", default=1)

    depreciation_date = fields.Date(string="Date", required=True)
    depreciation_amount = fields.Monetary(string="Dotation", currency_field="currency_id")
    cumulated_amount = fields.Monetary(string="Amort. cumulés", currency_field="currency_id")
    remaining_value = fields.Monetary(string="VNC", currency_field="currency_id")

    method_used = fields.Selection(
        [
            ("linear", "Linéaire"),
            ("degressive", "Dégressif"),
            ("linear_switch", "Linéaire (basculement)"),
        ],
        string="Méthode",
        default="linear",
    )
    months = fields.Integer(string="Mois")
    rate = fields.Float(string="Taux (%)", digits=(6, 4))

    state = fields.Selection(
        [
            ("draft", "À comptabiliser"),
            ("posted", "Comptabilisé"),
        ],
        default="draft",
        string="État",
    )
    move_id = fields.Many2one(
        "account.move",
        string="Écriture",
        readonly=True,
    )
    currency_id = fields.Many2one(related="asset_id.currency_id", store=True)
    company_id = fields.Many2one(related="asset_id.company_id", store=True)

    # ── Comptabilisation ──────────────────────────────────────────────────────

    def action_post(self):
        """Génère et valide l'écriture comptable de dotation aux amortissements."""
        for line in self:
            if line.state == "posted":
                raise UserError(_("Cette ligne est déjà comptabilisée."))
            asset = line.asset_id
            AccountAsset._check_required_accounts(asset)

            libelle = _("Amortissement %s – Exercice %s") % (
                asset.name,
                line.depreciation_date.strftime("%Y"),
            )
            move_vals = {
                "journal_id": asset.journal_id.id,
                "date": line.depreciation_date,
                "ref": libelle,
                "company_id": asset.company_id.id,
                "line_ids": [
                    # Débit 619x – Dotation aux amortissements (charge)
                    (
                        0,
                        0,
                        {
                            "account_id": asset.account_expense_id.id,
                            "name": libelle,
                            "debit": line.depreciation_amount,
                            "credit": 0.0,
                        },
                    ),
                    # Crédit 28xx – Amortissements cumulés (bilan)
                    (
                        0,
                        0,
                        {
                            "account_id": asset.account_depreciation_id.id,
                            "name": libelle,
                            "debit": 0.0,
                            "credit": line.depreciation_amount,
                        },
                    ),
                ],
            }
            move = self.env["account.move"].create(move_vals)
            move.action_post()
            line.write({"move_id": move.id, "state": "posted"})

            # Clôturer l'immobilisation si toutes les lignes sont comptabilisées
            if all(ln.state == "posted" for ln in asset.depreciation_line_ids):
                asset.write({"state": "close"})
                asset.message_post(body=_("Immobilisation totalement amortie – état passé à 'Clôturé'."))

    def action_unpost(self):
        """Annule l'écriture de dotation et repasse la ligne en brouillon."""
        for line in self:
            if line.state != "posted":
                continue
            move = line.move_id
            if move and move.state == "posted":
                move.button_draft()
                move.button_cancel()
            line.write({"state": "draft", "move_id": False})
            if line.asset_id.state == "close":
                line.asset_id.write({"state": "open"})

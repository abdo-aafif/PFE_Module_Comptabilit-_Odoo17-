from odoo import models, fields, api, _
from odoo.exceptions import UserError

import requests
import logging

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    tva_regime = fields.Selection(
        [("mensuel", "Mensuel"), ("trimestriel", "Trimestriel")], string="Périodicité de TVA", default="mensuel"
    )

    # Multi-devises: Taux de change automatique
    auto_currency_update = fields.Boolean("Mise à jour automatique des taux (Devises)", default=False)
    currency_provider = fields.Selection(
        [
            ("floatrates", "FloatRates (Gratuit)"),
        ],
        string="Fournisseur de Taux",
        default="floatrates",
    )

    def action_update_currency_rates(self):
        """Fetch exchange rates from FloatRates for all active currencies."""
        for company in self:
            if company.currency_provider != "floatrates":
                continue

            base_currency = company.currency_id.name.lower()
            url = f"http://www.floatrates.com/daily/{base_currency}.json"

            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
            except requests.exceptions.ConnectionError:
                raise UserError(_(
                    "Impossible de contacter FloatRates. "
                    "Vérifiez la connexion Internet du serveur Odoo."
                ))
            except requests.exceptions.Timeout:
                raise UserError(_(
                    "La requête FloatRates a expiré (timeout 10 s). "
                    "Réessayez dans quelques instants."
                ))
            except requests.exceptions.HTTPError as exc:
                raise UserError(_(
                    "FloatRates a retourné une erreur HTTP : %(err)s", err=str(exc)
                ))

            data = response.json()
            today = fields.Date.context_today(self)
            active_currencies = self.env["res.currency"].search(
                [("active", "=", True), ("id", "!=", company.currency_id.id)]
            )

            # Odoo normalise : "Unité par MAD" affiché = rate_brut / rate_brut_MAD
            # Il faut donc multiplier l'api_rate par le rate brut du MAD
            # pour que le résultat affiché soit correct.
            mad_rate_obj = self.env["res.currency.rate"].search(
                [
                    ("currency_id", "=", company.currency_id.id),
                    ("company_id", "=", company.id),
                    ("name", "<=", today),
                ],
                order="name desc",
                limit=1,
            )
            mad_raw = mad_rate_obj.rate if mad_rate_obj else 1.0

            updated = 0

            for currency in active_currencies:
                curr_code = currency.name.lower()
                if curr_code not in data:
                    continue

                # FloatRates (base MAD) : 1 MAD = api_rate unités de devise étrangère
                # db_rate = api_rate * mad_raw  →  affiché = db_rate / mad_raw = api_rate ✓
                api_rate = float(data[curr_code]["rate"])
                db_rate = api_rate * mad_raw

                existing_rate = self.env["res.currency.rate"].search(
                    [
                        ("currency_id", "=", currency.id),
                        ("name", "=", today),
                        ("company_id", "=", company.id),
                    ],
                    limit=1,
                )
                if existing_rate:
                    existing_rate.write({"rate": db_rate})
                else:
                    self.env["res.currency.rate"].create({
                        "currency_id": currency.id,
                        "name": today,
                        "rate": db_rate,
                        "company_id": company.id,
                    })
                updated += 1
                _logger.info(
                    "Rate updated — %s: api=%.6f mad_raw=%.6f db=%.6f",
                    currency.name, api_rate, mad_raw, db_rate,
                )

            _logger.info(
                "FloatRates update done for %s: %d currencies updated.",
                company.name, updated,
            )

    @api.model
    def _cron_update_currency_rates(self):
        """Cron job to update Exchange rates daily"""
        companies = self.search([("auto_currency_update", "=", True)])
        companies.action_update_currency_rates()


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    tva_regime = fields.Selection(
        related="company_id.tva_regime", readonly=False, string="Périodicité de déclaration TVA"
    )

    auto_currency_update = fields.Boolean(related="company_id.auto_currency_update", readonly=False)
    currency_provider = fields.Selection(related="company_id.currency_provider", readonly=False)

    def action_update_currency_rates(self):
        self.ensure_one()
        # Appel de la méthode existante sur l'objet res.company
        self.company_id.action_update_currency_rates()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Mise à jour réussie",
                "message": "Les taux de change ont été mis à jour avec succès depuis FloatRates (pour les devises actives).",
                "type": "success",
                "sticky": False,
            },
        }

    # IMPORTANT: En Odoo 17, les méthodes appelées depuis des boutons dans res.config.settings
    # doivent être décorées avec api.model ou être liées explicitement pour contourner
    # les vérifications strictes de validation des vues. Parfois Odoo demande que l'attribut soit un model
    # L'erreur de vue est due au fait que "action_update_currency_rates" est considérée introuvable
    # au moment du parsing XML.

    def action_update_currency_rates_config(self):
        """Bouton manuel dans Configuration > Paramètres.
        Fonctionne même si auto_currency_update est désactivé.
        Propage les erreurs réseau à l'utilisateur via UserError.
        """
        self.ensure_one()
        # Forcer currency_provider pour que la méthode ne saute pas la société
        if not self.company_id.currency_provider:
            raise UserError(_("Aucun fournisseur de taux configuré."))
        self.company_id.action_update_currency_rates()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Taux mis à jour"),
                "message": _("Les taux FloatRates ont été mis à jour pour aujourd'hui."),
                "type": "success",
                "sticky": False,
            },
        }


class AccountFullReconcile(models.Model):
    _inherit = "account.full.reconcile"

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name if rec.name and not rec.name.startswith("account.") else str(rec.id)

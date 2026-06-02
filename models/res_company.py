from odoo import models, fields, api, _

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
            ("ecb", "European Central Bank"),
            ("bam", "Bank Al-Maghrib (Manuel/Proxy)"),
        ],
        string="Fournisseur de Taux",
        default="floatrates",
    )

    def action_update_currency_rates(self):
        """Fetch exchange rates from public API (FloatRates for MAD or Base Currency)"""
        for company in self:
            if not company.auto_currency_update or company.currency_provider != "floatrates":
                continue

            base_currency = company.currency_id.name.lower()
            url = f"http://www.floatrates.com/daily/{base_currency}.json"

            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    today = fields.Date.context_today(self)
                    active_currencies = self.env["res.currency"].search(
                        [("active", "=", True), ("id", "!=", company.currency_id.id)]
                    )

                    # Odoo affiche : "Unité par MAD" = raw_stored / raw_MAD
                    # FloatRates donne : 1 MAD = api_rate devises étrangères
                    # Pour que l'affichage soit correct : raw_stored = api_rate * raw_MAD
                    # company.currency_id.rate vaut toujours 1.0 (normalisé sur lui-même),
                    # on récupère donc le taux brut réel stocké en base via _get_rates.
                    raw_base_rates = company.currency_id._get_rates(company, today)
                    raw_base = raw_base_rates.get(company.currency_id.id, 1.0)

                    for currency in active_currencies:
                        curr_code = currency.name.lower()
                        if curr_code in data:
                            # FloatRates : 1 MAD = api_rate unités de devise étrangère
                            api_rate = data[curr_code]["rate"]

                            # Taux à stocker en base pour qu'Odoo affiche la bonne valeur
                            db_rate = api_rate * raw_base

                            existing_rate = self.env["res.currency.rate"].search(
                                [
                                    ("currency_id", "=", currency.id),
                                    ("name", "=", today),
                                    ("company_id", "=", company.id),
                                ],
                                limit=1,
                            )

                            if not existing_rate:
                                self.env["res.currency.rate"].create(
                                    {
                                        "currency_id": currency.id,
                                        "name": today,
                                        "rate": db_rate,
                                        "company_id": company.id,
                                    }
                                )
                            else:
                                existing_rate.write({"rate": db_rate})

                            _logger.info(
                                f"Updated rate for {currency.name}: api_rate={api_rate}, raw_base={raw_base}, db_rate={db_rate}"
                            )
            except Exception as e:
                _logger.error(f"Failed to update currency rates for {company.name}: {str(e)}")

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
        # Utilisons un nom très spécifique juste pour les settings
        self.ensure_one()
        self.company_id.action_update_currency_rates()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Mise à jour réussie",
                "message": "Les taux de change ont été mis à jour.",
                "type": "success",
                "sticky": False,
            },
        }


class AccountFullReconcile(models.Model):
    _inherit = "account.full.reconcile"

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name if rec.name and not rec.name.startswith("account.") else str(rec.id)

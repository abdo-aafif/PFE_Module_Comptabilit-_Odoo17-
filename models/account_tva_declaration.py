from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import calendar
import logging
import base64
from datetime import date
from xml.sax.saxutils import escape as xml_escape

_logger = logging.getLogger(__name__)

class AccountTvaDeclaration(models.Model):
    _name = 'account.tva.declaration'
    _description = 'Déclaration de TVA (Tableau de Bord et Historique)'
    _order = 'periode_annee desc, date_start desc'

    name = fields.Char(string='Titre de la déclaration', compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Société', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    
    tva_regime = fields.Selection([
        ('mensuel', 'Mensuel'),
        ('trimestriel', 'Trimestriel')
    ], string="Régime", default=lambda self: self.env.company.tva_regime or 'mensuel')
    
    periode_annee = fields.Selection(
        [(str(y), str(y)) for y in range(2020, 2035)], 
        string='Année', required=True, 
        default=lambda self: str(fields.Date.context_today(self).year)
    )
    
    periode_mois = fields.Selection([
        ('01', 'Janvier'), ('02', 'Février'), ('03', 'Mars'), ('04', 'Avril'),
        ('05', 'Mai'), ('06', 'Juin'), ('07', 'Juillet'), ('08', 'Août'),
        ('09', 'Septembre'), ('10', 'Octobre'), ('11', 'Novembre'), ('12', 'Décembre')
    ], string='Mois', default=lambda self: str(fields.Date.context_today(self).month).zfill(2))
    
    periode_trimestre = fields.Selection([
        ('1', '1er Trimestre (Jan-Fév-Mars)'),
        ('2', '2ème Trimestre (Avr-Mai-Juin)'),
        ('3', '3ème Trimestre (Juil-Août-Sept)'),
        ('4', '4ème Trimestre (Oct-Nov-Déc)'),
    ], string='Trimestre', default=lambda self: str((fields.Date.context_today(self).month - 1) // 3 + 1))
    
    date_start = fields.Date(string='Date de début', compute='_compute_dates', store=True)
    date_end = fields.Date(string='Date de fin', compute='_compute_dates', store=True)

    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('done', 'Validée')
    ], string='Statut', default='draft')

    # Synthèse financière
    tva_collectee = fields.Monetary(string='TVA Collectée (Ventes)', readonly=True)
    tva_deductible = fields.Monetary(string='TVA Déductible (Achats)', readonly=True)
    tva_a_payer = fields.Monetary(string='TVA à Payer', readonly=True)

    # Lignes de ventilation par taux
    line_ids = fields.One2many('account.tva.declaration.line', 'declaration_id', string='Ventilation des Montants')

    # Détail d'audit : une ligne par (facture, lettrage) pour traçabilité DGI
    detail_ids = fields.One2many('account.tva.declaration.detail', 'declaration_id', string='Détail des pièces')
    detail_count = fields.Integer(compute='_compute_detail_count')

    # Export XML pour télédéclaration (SIMPL-TVA DGI)
    edi_file_data = fields.Binary(string="Fichier XML SIMPL-TVA", readonly=True, attachment=True)
    edi_file_name = fields.Char(string="Nom du fichier XML", readonly=True)
    edi_generated_on = fields.Datetime(string="Généré le", readonly=True)

    @api.depends('detail_ids')
    def _compute_detail_count(self):
        for rec in self:
            rec.detail_count = len(rec.detail_ids)

    def action_view_details(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Détail du calcul TVA — %s') % self.name,
            'res_model': 'account.tva.declaration.detail',
            'view_mode': 'tree,form',
            'domain': [('declaration_id', '=', self.id)],
            'context': {'default_declaration_id': self.id},
        }

    @api.depends('periode_annee', 'periode_mois', 'periode_trimestre', 'tva_regime')
    def _compute_dates(self):
        for rec in self:
            if not rec.periode_annee:
                rec.date_start = False
                rec.date_end = False
                continue
                
            year = int(rec.periode_annee)
            
            if rec.tva_regime == 'mensuel' and rec.periode_mois:
                month = int(rec.periode_mois)
                rec.date_start = date(year, month, 1)
                last_day = calendar.monthrange(year, month)[1]
                rec.date_end = date(year, month, last_day)

            elif rec.tva_regime == 'trimestriel' and rec.periode_trimestre:
                trimestre = int(rec.periode_trimestre)
                start_month = (trimestre - 1) * 3 + 1
                end_month = start_month + 2
                rec.date_start = date(year, start_month, 1)
                last_day = calendar.monthrange(year, end_month)[1]
                rec.date_end = date(year, end_month, last_day)

            else:
                rec.date_start = False
                rec.date_end = False

    @api.depends('date_start', 'tva_regime', 'periode_annee', 'periode_mois', 'periode_trimestre')
    def _compute_name(self):
        for rec in self:
            if rec.tva_regime == 'trimestriel' and rec.periode_trimestre and rec.periode_annee:
                rec.name = f"TVA T{rec.periode_trimestre} - {rec.periode_annee}"
            elif rec.tva_regime == 'mensuel' and rec.periode_mois and rec.periode_annee:
                rec.name = f"TVA {dict(self._fields['periode_mois'].selection).get(rec.periode_mois)} {rec.periode_annee}"
            else:
                rec.name = "Nouvelle Déclaration"

    def action_validate(self):
        for rec in self:
            if not rec.date_start or not rec.date_end:
                raise UserError(_(
                    "Impossible de valider : la période n'est pas définie. "
                    "Choisissez l'année et le mois (ou trimestre) avant de valider."
                ))

            # Une autre déclaration validée chevauchant la même période
            overlap = self.search([
                ('id', '!=', rec.id),
                ('company_id', '=', rec.company_id.id),
                ('state', '=', 'done'),
                ('date_start', '<=', rec.date_end),
                ('date_end', '>=', rec.date_start),
            ], limit=1)
            if overlap:
                raise UserError(_(
                    "Impossible de valider « %(current)s » : la période "
                    "%(start)s → %(end)s chevauche la déclaration déjà validée "
                    "« %(other)s » (%(o_start)s → %(o_end)s).\n\n"
                    "Remettez d'abord l'autre déclaration en brouillon ou supprimez-la.",
                    current=rec.name, start=rec.date_start, end=rec.date_end,
                    other=overlap.name, o_start=overlap.date_start, o_end=overlap.date_end,
                ))

            rec.state = 'done'

    def action_draft(self):
        self.state = 'draft'

    @api.constrains('state', 'date_start', 'date_end', 'company_id')
    def _check_unique_validated_period(self):
        """Garde-fou : aucune écriture directe en base ne peut créer deux
        déclarations 'done' qui se chevauchent pour la même société.
        """
        for rec in self:
            if rec.state != 'done' or not rec.date_start or not rec.date_end:
                continue
            overlap = self.search([
                ('id', '!=', rec.id),
                ('company_id', '=', rec.company_id.id),
                ('state', '=', 'done'),
                ('date_start', '<=', rec.date_end),
                ('date_end', '>=', rec.date_start),
            ], limit=1)
            if overlap:
                raise ValidationError(_(
                    "Deux déclarations validées ne peuvent pas couvrir des "
                    "périodes qui se chevauchent : « %(a)s » et « %(b)s ».",
                    a=rec.name, b=overlap.name,
                ))

    def _get_tax_rate(self, t_line):
        """Bug 3 fix: extrait le taux réel d'une ligne de TVA, en gérant les taxes groupées.
        Pour une taxe simple : retourne tax_line_id.amount.
        Pour une taxe groupée (group): descend dans tax_repartition_line_id.tax_id
        ou dans children_tax_ids pour récupérer le taux réel.
        """
        rep = t_line.tax_repartition_line_id
        # Cas 1 : la repartition pointe vers une taxe non-groupée (cas standard Odoo)
        if rep and rep.tax_id and rep.tax_id.amount_type != 'group':
            return abs(rep.tax_id.amount)
        # Cas 2 : taxe groupée → on descend dans les enfants
        tax = t_line.tax_line_id
        if tax.amount_type == 'group':
            child = tax.children_tax_ids.filtered(lambda c: c.amount_type != 'group')[:1]
            return abs(child.amount) if child else 0.0
        # Cas 3 : taxe simple
        return abs(tax.amount)

    def _convert_to_company_currency(self, amount, from_currency, rate_date):
        """Bug 2 fix: convertit un montant vers la devise société de manière sûre."""
        company_currency = self.company_id.currency_id
        if not from_currency or from_currency == company_currency:
            return abs(amount)
        return abs(from_currency._convert(
            amount, company_currency, self.company_id,
            rate_date or fields.Date.context_today(self),
        ))

    def _expand_taxes(self, taxes):
        """Aplati les taxes groupées en sous-taxes percent applicables."""
        result = []
        for tax in taxes:
            if tax.amount_type == 'group':
                for child in tax.children_tax_ids:
                    if child.amount_type == 'percent':
                        result.append(child)
            elif tax.amount_type == 'percent':
                result.append(tax)
        return result

    def action_compute_tva(self):
        """
        Calcul TVA selon l'encaissement (Cash Basis), STRICTEMENT.

        Principe :
          - On part des paiements lettrés (`account.partial.reconcile`) dans la période.
          - Pour chaque facture liée à un paiement, on calcule la proportion payée.
          - On calcule la TVA à imputer = base HT × taux × proportion, signée
            selon le sens de la pièce (facture/avoir, vente/achat).

        Pourquoi calculer depuis la base HT et non depuis les lignes de TVA :
          - Pour les taxes en `on_payment` mal configurées (compte de transition
            non distinct), les lignes de TVA originales s'annulent dans la
            facture (debit/credit sur le même compte) → balance = 0.
          - Lire la balance des tax_lines donnerait 0.
          - Recalculer base × taux est robuste quel que soit le paramétrage.

        Correctifs intégrés :
          - Bug 1 : déduplication par (partial, ligne)
          - Bug 2 : tout en devise société pour la proportion
          - Bug 3 : taxes groupées dépliées via _expand_taxes()
          - Bug 5 : indépendance du mécanisme natif (on_payment/on_invoice)
          - Multi-société : with_company + check explicite
        """
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    "Impossible de recalculer une déclaration validée. "
                    "Remettez-la en brouillon avant de relancer le calcul."
                ))

            rec.line_ids.unlink()
            rec.detail_ids.unlink()

            total_collectee = 0.0
            total_deductible = 0.0
            ventilation = {}  # { ('collectee'|'deductible', taux): montant_tva }
            details_data = {}  # { (invoice_id, partial_id): {...} }
            processed = set()  # tracking (partial_id, ml_id)

            company = rec.company_id

            # Lettrages de la période, scoped à la société
            partials = self.env['account.partial.reconcile'].with_company(company).search([
                ('max_date', '>=', rec.date_start),
                ('max_date', '<=', rec.date_end),
                ('company_id', '=', company.id),
            ])

            for partial in partials:
                for ml in (partial.debit_move_id, partial.credit_move_id):
                    if not ml or not ml.move_id.is_invoice(include_receipts=True):
                        continue

                    pair_key = (partial.id, ml.id)
                    if pair_key in processed:
                        continue
                    processed.add(pair_key)

                    invoice = ml.move_id
                    if invoice.company_id != company:
                        continue
                    if invoice.state != 'posted' or not invoice.amount_total:
                        continue

                    paid_company = abs(partial.amount)
                    rate_date = invoice.invoice_date or invoice.date
                    invoice_total_company = rec._convert_to_company_currency(
                        invoice.amount_total, invoice.currency_id, rate_date,
                    )
                    if not invoice_total_company:
                        continue

                    proportion = paid_company / invoice_total_company

                    # Type TVA et signe
                    if invoice.move_type in ('out_invoice', 'out_receipt'):
                        type_tva, sign = 'collectee', 1.0
                    elif invoice.move_type == 'out_refund':
                        type_tva, sign = 'collectee', -1.0
                    elif invoice.move_type in ('in_invoice', 'in_receipt'):
                        type_tva, sign = 'deductible', 1.0
                    elif invoice.move_type == 'in_refund':
                        type_tva, sign = 'deductible', -1.0
                    else:
                        continue

                    # Calcul TVA depuis les lignes produit (HT) × taux
                    invoice_tva_total = 0.0
                    taux_principal = 0.0
                    tva_max_abs = 0.0

                    for line in invoice.invoice_line_ids:
                        # base_company en devise société (signé)
                        base_company = abs(line.balance)
                        if not base_company:
                            continue

                        for tax in rec._expand_taxes(line.tax_ids):
                            taux = abs(tax.amount)
                            if not taux:
                                continue

                            tva = sign * base_company * taux / 100.0 * proportion

                            if type_tva == 'collectee':
                                total_collectee += tva
                            else:
                                total_deductible += tva

                            key = (type_tva, taux)
                            ventilation[key] = ventilation.get(key, 0.0) + tva

                            invoice_tva_total += tva
                            if abs(tva) >= tva_max_abs:
                                tva_max_abs = abs(tva)
                                taux_principal = taux

                    # Détail d'audit
                    if invoice_tva_total:
                        details_data[(invoice.id, partial.id)] = {
                            'origin': invoice,
                            'partial': partial,
                            'tva': invoice_tva_total,
                            'taux': taux_principal,
                            'type_tva': type_tva,
                            'paid_company': paid_company,
                            'invoice_total_company': invoice_total_company,
                            'proportion': proportion,
                        }

            # Génération des lignes de détail
            details_to_create = []
            for (origin_id, partial_id), data in details_data.items():
                details_to_create.append({
                    'declaration_id': rec.id,
                    'invoice_id': data['origin'].id,
                    'partial_id': data['partial'].id,
                    'type_tva': data['type_tva'],
                    'amount_total_company': data['invoice_total_company'],
                    'amount_paid_period': data['paid_company'],
                    'proportion': data['proportion'],
                    'taux': data['taux'],
                    'tva_amount': data['tva'],
                })

            # Synthèse
            rec.tva_collectee = total_collectee
            rec.tva_deductible = total_deductible
            rec.tva_a_payer = total_collectee - total_deductible

            # Ventilation par taux
            rec.line_ids = [
                (0, 0, {'type_tva': type_tva, 'taux': taux, 'montant_tva': montant})
                for (type_tva, taux), montant in ventilation.items()
                if montant
            ]

            # Détails d'audit
            if details_to_create:
                self.env['account.tva.declaration.detail'].create(details_to_create)

            _logger.info(
                "Déclaration TVA %s [%s → %s] : %d lettrage(s) traité(s), "
                "%d détail(s), collectée=%.2f, déductible=%.2f",
                rec.name, rec.date_start, rec.date_end,
                len(partials), len(details_to_create),
                total_collectee, total_deductible,
            )

    def action_export_simpl_tva(self):
        """Génère le XML SIMPL-TVA (Relevé des Déductions) à partir des
        détails d'audit déjà calculés (cash basis) et le rend téléchargeable
        directement depuis la déclaration.
        """
        self.ensure_one()

        if self.state != 'done':
            raise UserError(_(
                "L'export pour télédéclaration n'est autorisé que sur une "
                "déclaration validée. Validez d'abord la déclaration."
            ))
        if not self.date_start or not self.date_end:
            raise UserError(_(
                "Impossible de générer le fichier : la période n'est pas définie."
            ))
        if not self.detail_ids:
            raise UserError(_(
                "Aucun détail à exporter. Lancez d'abord « Calculer la TVA » "
                "pour cette déclaration."
            ))

        company = self.company_id
        company_vat = company.vat or 'NON_DEFINI'

        # Régime DGI : 1 = mensuel, 2 = trimestriel
        regime_dgi = '2' if self.tva_regime == 'trimestriel' else '1'
        if self.tva_regime == 'trimestriel':
            periode_dgi = self.periode_trimestre or str(((self.date_start.month - 1) // 3) + 1)
        else:
            periode_dgi = self.periode_mois or str(self.date_start.month).zfill(2)

        # On ne garde que les lignes déductibles (achats) — Relevé des Déductions DGI
        deductibles = self.detail_ids.filtered(lambda d: d.type_tva == 'deductible')

        lignes_xml_parts = []
        for det in deductibles:
            inv = det.invoice_id
            if not inv:
                continue

            taux = det.taux or 0.0
            tva_amount = abs(det.tva_amount or 0.0)
            # Base HT correspondant au montant TVA imputé sur la période
            montant_ht = tva_amount / (taux / 100.0) if taux else 0.0

            ice_fournisseur = (inv.partner_id.vat or '000000000000000').strip()
            ref_facture = inv.ref or inv.name or 'SANS_REF'
            date_fact = inv.invoice_date.strftime('%Y-%m-%d') if inv.invoice_date else ''

            # Date de paiement : max_date du lettrage si dispo, sinon date_end
            date_paiement = ''
            if det.partial_id and det.partial_id.max_date:
                date_paiement = det.partial_id.max_date.strftime('%Y-%m-%d')
            else:
                date_paiement = self.date_end.strftime('%Y-%m-%d')

            designation = _("Achats %s") % (inv.partner_id.name or '')

            lignes_xml_parts.append(f"""
        <rdDeduction>
            <mpIdentifiant>{xml_escape(ice_fournisseur)}</mpIdentifiant>
            <designationBien>{xml_escape(designation)}</designationBien>
            <refFacture>{xml_escape(ref_facture)}</refFacture>
            <dateFacture>{date_fact}</dateFacture>
            <montantHT>{montant_ht:.2f}</montantHT>
            <tauxTva>{taux:.2f}</tauxTva>
            <montantTva>{tva_amount:.2f}</montantTva>
            <datePaiement>{date_paiement}</datePaiement>
        </rdDeduction>""")

        lignes_xml = ''.join(lignes_xml_parts) or "\n        <!-- Aucune deduction sur cette periode -->"

        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<DeclarationReleveDeduction>
    <identifiantFiscal>{xml_escape(company_vat)}</identifiantFiscal>
    <annee>{self.periode_annee}</annee>
    <periode>{periode_dgi}</periode>
    <regime>{regime_dgi}</regime>
    <releveDeductions>{lignes_xml}
    </releveDeductions>
</DeclarationReleveDeduction>"""

        if self.tva_regime == 'trimestriel':
            file_label = f"T{periode_dgi}_{self.periode_annee}"
        else:
            file_label = f"{self.periode_annee}_{periode_dgi}"

        self.write({
            'edi_file_data': base64.b64encode(xml_content.encode('utf-8')),
            'edi_file_name': f"SIMPL_TVA_{file_label}.xml",
            'edi_generated_on': fields.Datetime.now(),
        })

        _logger.info(
            "Export SIMPL-TVA %s : %d ligne(s) de déduction générée(s)",
            self.name, len(deductibles),
        )

        # Recharge le formulaire pour que le fichier XML apparaisse
        # immédiatement dans l'onglet « Export pour Télédéclaration ».
        return {
            'type': 'ir.actions.client',
            'tag': 'soft_reload',
        }


class AccountTvaDeclarationLine(models.Model):
    _name = 'account.tva.declaration.line'
    _description = 'Ligne de ventilation TVA'

    declaration_id = fields.Many2one('account.tva.declaration', ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id', store=True)
    
    type_tva = fields.Selection([
        ('collectee', 'TVA Collectée (Ventes)'),
        ('deductible', 'TVA Déductible (Achats)')
    ], string='Type')
    
    taux = fields.Float(string='Taux appliqué (%)')
    montant_tva = fields.Float(string='Montant TVA', digits=(16, 2))


class AccountTvaDeclarationDetail(models.Model):
    _name = 'account.tva.declaration.detail'
    _description = "Détail d'audit du calcul TVA (par facture/lettrage)"
    _order = 'invoice_date, id'

    declaration_id = fields.Many2one(
        'account.tva.declaration', ondelete='cascade', required=True, index=True,
    )
    company_id = fields.Many2one(related='declaration_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id', store=True)

    # Pièce d'origine
    invoice_id = fields.Many2one('account.move', string='Pièce', ondelete='restrict')
    invoice_date = fields.Date(related='invoice_id.invoice_date', store=True, string='Date facture')
    partner_id = fields.Many2one(related='invoice_id.partner_id', store=True, string='Partenaire')
    move_name = fields.Char(related='invoice_id.name', store=True, string='Référence')
    move_type = fields.Selection(related='invoice_id.move_type', store=True, string='Type pièce')

    # Lettrage qui a déclenché le calcul (peut être False si on évolue vers on_payment)
    partial_id = fields.Many2one('account.partial.reconcile', string='Lettrage', ondelete='set null')

    # Classification
    type_tva = fields.Selection([
        ('collectee', 'Collectée (Vente)'),
        ('deductible', 'Déductible (Achat)'),
    ], string='Type', required=True)
    taux = fields.Float(string='Taux principal (%)', digits=(5, 2))

    # Montants en devise société
    amount_total_company = fields.Float(string='Total facture (société)', digits=(16, 2))
    amount_paid_period = fields.Float(string='Encaissé période', digits=(16, 2))
    proportion = fields.Float(string='Proportion payée', digits=(8, 6))
    tva_amount = fields.Float(string='TVA imputée', digits=(16, 2))

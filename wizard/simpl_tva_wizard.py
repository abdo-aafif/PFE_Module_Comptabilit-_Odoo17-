from odoo import models, fields, api
import base64

class SimplTvaWizard(models.TransientModel):
    _name = 'simpl.tva.wizard'
    _description = 'Assistant Export EDI SIMPL-TVA'

    date_start = fields.Date(string='Date de début', required=True, default=fields.Date.context_today)
    date_end = fields.Date(string='Date de fin', required=True, default=fields.Date.context_today)
    state = fields.Selection([('draft', 'Brouillon'), ('done', 'Généré')], default='draft')
    
    file_data = fields.Binary('Fichier XML EDI', readonly=True)
    file_name = fields.Char('Nom du fichier', readonly=True)

    def generate_xml(self):
        company_vat = self.env.company.vat or 'NON_DEFINI'
        
        # 1. Recherche de toutes les factures d'achat validées dans la période (TVA Déductible)
        domain = [
            ('move_type', 'in', ['in_invoice', 'in_receipt']),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_start),
            ('invoice_date', '<=', self.date_end),
            ('company_id', '=', self.env.company.id)
        ]
        invoices = self.env['account.move'].search(domain)
        
        lignes_xml = ""
        
        # 2. Génération dynamique des lignes
        for inv in invoices:
            # Récupérer les lignes de taxes de la facture
            tax_lines = inv.line_ids.filtered(lambda l: l.tax_line_id)
            for t_line in tax_lines:
                taux = abs(t_line.tax_line_id.amount)
                montant_tva = abs(t_line.balance)
                
                # Récupérer la base HT correspondant à cette taxe
                base_lines = inv.line_ids.filtered(lambda l: t_line.tax_line_id.id in l.tax_ids.ids)
                montant_ht = sum(abs(b.balance) for b in base_lines)
                
                ice_fournisseur = inv.partner_id.vat or '000000000000000'
                ref_facture = inv.ref or inv.name or 'SANS_REF'
                date_fact = inv.invoice_date.strftime('%Y-%m-%d') if inv.invoice_date else ''
                
                lignes_xml += f"""
        <rdDeduction>
            <mpIdentifiant>{ice_fournisseur}</mpIdentifiant>
            <designationBien>Achats {inv.partner_id.name}</designationBien>
            <refFacture>{ref_facture}</refFacture>
            <dateFacture>{date_fact}</dateFacture>
            <montantHT>{montant_ht:.2f}</montantHT>
            <tauxTva>{taux}</tauxTva>
            <montantTva>{montant_tva:.2f}</montantTva>
            <datePaiement>{date_fact}</datePaiement>
        </rdDeduction>"""

        # S'il n'y a aucune facture, on met la balise d'exemple vide demandée par le DGI pour éviter les bugs
        if not lignes_xml:
            lignes_xml = "<!-- Aucune deduction sur cette periode -->"

        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<DeclarationReleveDeduction>
    <identifiantFiscal>{company_vat}</identifiantFiscal>
    <annee>{self.date_start.year}</annee>
    <periode>{self.date_start.month}</periode>
    <regime>1</regime>
    <releveDeductions>{lignes_xml}
    </releveDeductions>
</DeclarationReleveDeduction>"""

        self.write({
            'file_data': base64.b64encode(xml_content.encode('utf-8')),
            'file_name': f'SIMPL_TVA_{self.date_start.strftime("%Y_%m")}.xml',
            'state': 'done'
        })
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'simpl.tva.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

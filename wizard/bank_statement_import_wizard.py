import base64
import csv
import io
import re
import logging
from datetime import datetime

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BankStatementImportWizard(models.TransientModel):
    _name = 'bank.statement.import.wizard'
    _description = 'Import Relevé Bancaire (CSV / OFX / MT940)'

    journal_id = fields.Many2one(
        'account.journal',
        string='Journal Bancaire',
        domain=[('type', 'in', ['bank', 'cash'])],
        required=True,
    )
    import_file = fields.Binary(string='Fichier', required=True, attachment=False)
    filename = fields.Char(string='Nom du fichier')
    file_format = fields.Selection([
        ('csv', 'CSV'),
        ('ofx', 'OFX'),
        ('mt940', 'MT940'),
    ], string='Format', required=True, default='csv')

    # Options CSV
    csv_delimiter = fields.Char(string='Séparateur', default=';')
    csv_date_format = fields.Char(string='Format date', default='%d/%m/%Y')
    csv_col_date = fields.Integer(string='Colonne Date', default=1)
    csv_col_label = fields.Integer(string='Colonne Libellé', default=2)
    csv_col_amount = fields.Integer(string='Colonne Montant', default=3)
    csv_col_ref = fields.Integer(string='Colonne Référence', default=4)
    csv_skip_header = fields.Boolean(string='Ignorer en-tête', default=True)

    # ------------------------------------------------------------------ #
    #  ACTION PRINCIPALE                                                   #
    # ------------------------------------------------------------------ #

    def action_import(self):
        self.ensure_one()
        if not self.import_file:
            raise UserError(_('Veuillez sélectionner un fichier.'))

        if self.file_format == 'csv':
            created = self._import_csv()
        elif self.file_format == 'ofx':
            created = self._import_ofx()
        elif self.file_format == 'mt940':
            created = self._import_mt940()
        else:
            raise UserError(_('Format non supporté.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Lignes Importées (%(count)d)') % {'count': len(created)},
            'res_model': 'account.bank.statement.line',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', created.ids)],
            'context': {'create': False},
        }

    # ------------------------------------------------------------------ #
    #  CSV                                                                 #
    # ------------------------------------------------------------------ #

    def _import_csv(self):
        raw = base64.b64decode(self.import_file).decode('utf-8-sig', errors='replace')
        reader = csv.reader(io.StringIO(raw), delimiter=self.csv_delimiter or ';')
        rows = list(reader)

        if self.csv_skip_header and rows:
            rows = rows[1:]

        if not rows:
            raise UserError(_('Le fichier CSV est vide.'))

        parsed = []
        for i, row in enumerate(rows, start=2 if self.csv_skip_header else 1):
            if not any(r.strip() for r in row):
                continue
            vals = self._parse_csv_row(row, i)
            if vals:
                parsed.append(vals)

        return self._create_lines(parsed)

    def _parse_csv_row(self, row, line_no):
        def col(idx):
            try:
                return row[idx - 1].strip()
            except IndexError:
                return ''

        date_str = col(self.csv_col_date)
        label = col(self.csv_col_label)
        amount_str = col(self.csv_col_amount).replace(' ', '').replace(',', '.')
        ref = col(self.csv_col_ref)

        if not date_str or not amount_str:
            return None

        try:
            date = datetime.strptime(date_str, self.csv_date_format or '%d/%m/%Y').date()
        except ValueError:
            raise UserError(
                _('Ligne %(line)d — Format de date invalide : "%(date)s". Attendu : %(fmt)s')
                % {'line': line_no, 'date': date_str, 'fmt': self.csv_date_format}
            )
        try:
            amount = float(amount_str)
        except ValueError:
            raise UserError(
                _('Ligne %(line)d — Montant invalide : "%(amount)s"')
                % {'line': line_no, 'amount': amount_str}
            )

        return {
            'date': date,
            'payment_ref': label or ref or '/',
            'amount': amount,
            'narration': ref if ref != label else False,
        }

    # ------------------------------------------------------------------ #
    #  OFX  (SGML 1.x  et  XML 2.x)                                       #
    # ------------------------------------------------------------------ #

    def _import_ofx(self):
        raw = base64.b64decode(self.import_file).decode('utf-8-sig', errors='replace')

        # Détecter OFX 2.x (XML) vs OFX 1.x (SGML)
        if re.search(r'<\?xml', raw, re.IGNORECASE):
            parsed = self._parse_ofx_xml(raw)
        else:
            parsed = self._parse_ofx_sgml(raw)

        if not parsed:
            raise UserError(_('Aucune transaction trouvée dans le fichier OFX.'))

        return self._create_lines(parsed)

    def _parse_ofx_sgml(self, raw):
        """Parse OFX 1.x SGML : balises ouvrantes sans fermeture."""
        transactions = []
        # Isoler les blocs <STMTTRN>...</STMTTRN>
        blocks = re.findall(r'<STMTTRN>(.*?)</STMTTRN>', raw, re.DOTALL | re.IGNORECASE)

        for block in blocks:
            def tag(name):
                m = re.search(r'<' + name + r'>\s*([^\r\n<]+)', block, re.IGNORECASE)
                return m.group(1).strip() if m else ''

            date_raw = tag('DTPOSTED') or tag('DTUSER')
            amount_str = tag('TRNAMT')
            label = tag('MEMO') or tag('NAME')
            ref = tag('FITID') or tag('CHECKNUM')

            if not date_raw or not amount_str:
                continue

            # OFX date : YYYYMMDD[HHMMSS]
            try:
                date = datetime.strptime(date_raw[:8], '%Y%m%d').date()
            except ValueError:
                continue

            try:
                amount = float(amount_str.replace(',', '.'))
            except ValueError:
                continue

            transactions.append({
                'date': date,
                'payment_ref': label or ref or '/',
                'amount': amount,
                'narration': ref or False,
            })

        return transactions

    def _parse_ofx_xml(self, raw):
        """Parse OFX 2.x XML."""
        import xml.etree.ElementTree as ET

        try:
            # Supprimer le prologue OFX avant la balise XML
            xml_start = raw.find('<?xml')
            if xml_start == -1:
                xml_start = raw.find('<OFX')
            root = ET.fromstring(raw[xml_start:])
        except ET.ParseError as e:
            raise UserError(_('Fichier OFX XML invalide : %(error)s') % {'error': str(e)})

        # namespace not used — OFX 2.x uses bare element names
        transactions = []

        for stmttrn in root.iter('STMTTRN'):
            def tag(name):
                el = stmttrn.find(name)
                return el.text.strip() if el is not None and el.text else ''

            date_raw = tag('DTPOSTED') or tag('DTUSER')
            amount_str = tag('TRNAMT')
            label = tag('MEMO') or tag('NAME')
            ref = tag('FITID')

            if not date_raw or not amount_str:
                continue

            try:
                date = datetime.strptime(date_raw[:8], '%Y%m%d').date()
            except ValueError:
                continue
            try:
                amount = float(amount_str.replace(',', '.'))
            except ValueError:
                continue

            transactions.append({
                'date': date,
                'payment_ref': label or ref or '/',
                'amount': amount,
                'narration': ref or False,
            })

        return transactions

    # ------------------------------------------------------------------ #
    #  MT940  (SWIFT)                                                      #
    # ------------------------------------------------------------------ #

    def _import_mt940(self):
        raw = base64.b64decode(self.import_file).decode('latin-1', errors='replace')
        parsed = self._parse_mt940(raw)

        if not parsed:
            raise UserError(_('Aucune transaction trouvée dans le fichier MT940.'))

        return self._create_lines(parsed)

    def _parse_mt940(self, raw):
        """
        Parse MT940 SWIFT.
        Champ :61: — transaction
          Format : YYMMDD[MMDD]2S3[//ref][<CR><LF>:86:narrative]
          Exemple : 2601010101DR1275,00NTRFINV2026/00002
        Champ :86: — libellé libre (optionnel, suit :61:)
        """
        transactions = []

        # Séparer en blocs de transactions
        lines = raw.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith(':61:'):
                body = line[4:]
                # Récupérer continuation éventuelle
                while i + 1 < len(lines) and not lines[i + 1].startswith(':'):
                    i += 1
                    body += lines[i]

                # Lire le champ :86: suivant si présent
                narrative = ''
                if i + 1 < len(lines) and lines[i + 1].startswith(':86:'):
                    i += 1
                    narrative = lines[i][4:]
                    while i + 1 < len(lines) and not lines[i + 1].startswith(':'):
                        i += 1
                        narrative += ' ' + lines[i].strip()

                tx = self._parse_mt940_61(body, narrative)
                if tx:
                    transactions.append(tx)
            i += 1

        return transactions

    def _parse_mt940_61(self, body, narrative):
        """
        Décode un champ :61: MT940.
        Structure : YYMMDD[MMDD]<D/C>[<R>]<amount><type><ref>
        """
        # Regex : date valeur (6), date comptable optionnelle (4), D/C, [R], montant, code type (4), ref
        m = re.match(
            r'(\d{6})(\d{4})?([DC]R?)(\d+[,\.]\d{2})([A-Z]{4})(.{0,16})',
            body.strip()
        )
        if not m:
            return None

        date_str = m.group(1)
        dc = m.group(3)  # D = débit, C = crédit
        amount_str = m.group(4).replace(',', '.')
        ref = m.group(6).strip().rstrip('/')

        try:
            # YY MM DD → on suppose 2000+
            date = datetime.strptime('20' + date_str, '%Y%m%d').date()
        except ValueError:
            return None

        try:
            amount = float(amount_str)
        except ValueError:
            return None

        # Débit = montant négatif dans Odoo
        if dc.startswith('D'):
            amount = -amount

        label = narrative.strip() if narrative else (ref or '/')

        return {
            'date': date,
            'payment_ref': label or '/',
            'amount': amount,
            'narration': ref or False,
        }

    # ------------------------------------------------------------------ #
    #  CRÉATION DES LIGNES                                                 #
    # ------------------------------------------------------------------ #

    def _create_lines(self, parsed):
        if not parsed:
            raise UserError(_('Aucune ligne valide trouvée dans le fichier.'))

        StmtLine = self.env['account.bank.statement.line']
        created = StmtLine

        for vals in parsed:
            vals['journal_id'] = self.journal_id.id
            created |= StmtLine.create(vals)

        return created

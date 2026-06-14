import base64
import csv
import io
import re
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BankStatementImportWizard(models.TransientModel):
    _name = "bank.statement.import.wizard"
    _description = "Import Relevé Bancaire (CSV / OFX / MT940)"

    journal_id = fields.Many2one(
        "account.journal",
        string="Journal Bancaire",
        domain=[("type", "in", ["bank", "cash"])],
        required=True,
    )
    import_file = fields.Binary(string="Fichier", required=True, attachment=False)
    filename = fields.Char(string="Nom du fichier")
    file_format = fields.Selection(
        [
            ("csv", "CSV"),
            ("ofx", "OFX"),
            ("mt940", "MT940"),
        ],
        string="Format",
        required=True,
        default="csv",
    )

    statement_name = fields.Char(
        string="Nom du relevé",
        required=True,
        help="Sera utilisé comme référence du relevé bancaire créé : Import — [nom] — date",
    )

    # Options CSV
    csv_delimiter = fields.Char(string="Séparateur", default=";")
    csv_date_format = fields.Char(string="Format date", default="%d/%m/%Y")
    csv_col_date = fields.Integer(string="Colonne Date", default=1)
    csv_col_label = fields.Integer(string="Colonne Libellé", default=2)
    csv_col_amount = fields.Integer(string="Colonne Montant", default=3)
    csv_col_ref = fields.Integer(string="Colonne Référence", default=4)
    csv_col_partner = fields.Integer(
        string="Colonne Partenaire (optionnel)",
        default=0,
        help="Numéro de colonne contenant le nom du partenaire. "
             "Mettre 0 (défaut) pour ignorer — le partenaire sera alors "
             "déduit automatiquement depuis la facture lors du Perfect Match.",
    )
    csv_skip_header = fields.Boolean(string="Ignorer en-tête", default=True)

    # ------------------------------------------------------------------ #
    #  ACTION PRINCIPALE                                                   #
    # ------------------------------------------------------------------ #

    def action_import(self):
        self.ensure_one()
        if not self.import_file:
            raise UserError(_("Veuillez sélectionner un fichier."))

        if self.file_format == "csv":
            created = self._import_csv()
        elif self.file_format == "ofx":
            created = self._import_ofx()
        elif self.file_format == "mt940":
            created = self._import_mt940()
        else:
            raise UserError(_("Format non supporté."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Lignes Importées (%(count)d)", count=len(created)),
            "res_model": "account.bank.statement.line",
            "view_mode": "tree,form",
            "domain": [("id", "in", created.ids)],
            "context": {"create": False},
        }

    # ------------------------------------------------------------------ #
    #  CSV                                                                 #
    # ------------------------------------------------------------------ #

    def _import_csv(self):
        raw = base64.b64decode(self.import_file).decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(raw), delimiter=self.csv_delimiter or ";")
        rows = list(reader)

        if self.csv_skip_header and rows:
            rows = rows[1:]

        if not rows:
            raise UserError(_("Le fichier CSV est vide."))

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
                return ""

        date_str = col(self.csv_col_date)
        label = col(self.csv_col_label)
        amount_str = col(self.csv_col_amount).replace(" ", "").replace(",", ".")
        ref = col(self.csv_col_ref)
        # Colonne partenaire optionnelle (0 = désactivée)
        partner_name = col(self.csv_col_partner) if self.csv_col_partner else ""

        if not date_str or not amount_str:
            return None

        try:
            date = datetime.strptime(date_str, self.csv_date_format or "%d/%m/%Y").date()
        except ValueError as exc:
            raise UserError(
                _(
                    'Ligne %(line)d — Format de date invalide : "%(date)s". Attendu : %(fmt)s',
                    line=line_no,
                    date=date_str,
                    fmt=self.csv_date_format,
                )
            ) from exc
        try:
            amount = float(amount_str)
        except ValueError as exc:
            raise UserError(
                _(
                    'Ligne %(line)d — Montant invalide : "%(amount)s"',
                    line=line_no,
                    amount=amount_str,
                )
            ) from exc

        return {
            "date": date,
            "payment_ref": label or ref or "/",
            "amount": amount,
            "narration": ref if ref != label else False,
            "_partner_name": partner_name,  # champ temporaire résolu dans _create_lines
        }

    # ------------------------------------------------------------------ #
    #  OFX  (SGML 1.x  et  XML 2.x)                                       #
    # ------------------------------------------------------------------ #

    def _import_ofx(self):
        raw = base64.b64decode(self.import_file).decode("utf-8-sig", errors="replace")

        # Détecter OFX 2.x (XML) vs OFX 1.x (SGML)
        if re.search(r"<\?xml", raw, re.IGNORECASE):
            parsed = self._parse_ofx_xml(raw)
        else:
            parsed = self._parse_ofx_sgml(raw)

        if not parsed:
            raise UserError(_("Aucune transaction trouvée dans le fichier OFX."))

        return self._create_lines(parsed)

    @staticmethod
    def _sgml_tag(block, name):
        m = re.search(r"<" + name + r">\s*([^\r\n<]+)", block, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _parse_ofx_sgml(self, raw):
        """Parse OFX 1.x SGML : balises ouvrantes sans fermeture."""
        transactions = []
        # Isoler les blocs <STMTTRN>...</STMTTRN>
        blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", raw, re.DOTALL | re.IGNORECASE)

        for block in blocks:
            date_raw = self._sgml_tag(block, "DTPOSTED") or self._sgml_tag(block, "DTUSER")
            amount_str = self._sgml_tag(block, "TRNAMT")
            label = self._sgml_tag(block, "MEMO") or self._sgml_tag(block, "NAME")
            ref = self._sgml_tag(block, "FITID") or self._sgml_tag(block, "CHECKNUM")

            if not date_raw or not amount_str:
                continue

            # OFX date : YYYYMMDD[HHMMSS]
            try:
                date = datetime.strptime(date_raw[:8], "%Y%m%d").date()
            except ValueError:
                continue

            try:
                amount = float(amount_str.replace(",", "."))
            except ValueError:
                continue

            transactions.append(
                {
                    "date": date,
                    "payment_ref": label or ref or "/",
                    "amount": amount,
                    "narration": ref or False,
                }
            )

        return transactions

    @staticmethod
    def _xml_tag(stmttrn, name):
        el = stmttrn.find(name)
        return el.text.strip() if el is not None and el.text else ""

    def _parse_ofx_xml(self, raw):
        """Parse OFX 2.x XML."""
        try:
            # Supprimer le prologue OFX avant la balise XML
            xml_start = raw.find("<?xml")
            if xml_start == -1:
                xml_start = raw.find("<OFX")
            root = ET.fromstring(raw[xml_start:])
        except ET.ParseError as exc:
            raise UserError(_("Fichier OFX XML invalide : %(error)s", error=str(exc))) from exc

        # namespace not used — OFX 2.x uses bare element names
        transactions = []

        for stmttrn in root.iter("STMTTRN"):
            date_raw = self._xml_tag(stmttrn, "DTPOSTED") or self._xml_tag(stmttrn, "DTUSER")
            amount_str = self._xml_tag(stmttrn, "TRNAMT")
            label = self._xml_tag(stmttrn, "MEMO") or self._xml_tag(stmttrn, "NAME")
            ref = self._xml_tag(stmttrn, "FITID")

            if not date_raw or not amount_str:
                continue

            try:
                date = datetime.strptime(date_raw[:8], "%Y%m%d").date()
            except ValueError:
                continue
            try:
                amount = float(amount_str.replace(",", "."))
            except ValueError:
                continue

            transactions.append(
                {
                    "date": date,
                    "payment_ref": label or ref or "/",
                    "amount": amount,
                    "narration": ref or False,
                }
            )

        return transactions

    # ------------------------------------------------------------------ #
    #  MT940  (SWIFT)                                                      #
    # ------------------------------------------------------------------ #

    def _import_mt940(self):
        raw = base64.b64decode(self.import_file).decode("latin-1", errors="replace")
        parsed = self._parse_mt940(raw)

        if not parsed:
            raise UserError(_("Aucune transaction trouvée dans le fichier MT940."))

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

            if line.startswith(":61:"):
                body = line[4:]
                # Récupérer continuation éventuelle
                while i + 1 < len(lines) and not lines[i + 1].startswith(":"):
                    i += 1
                    body += lines[i]

                # Lire le champ :86: suivant si présent
                narrative = ""
                if i + 1 < len(lines) and lines[i + 1].startswith(":86:"):
                    i += 1
                    narrative = lines[i][4:]
                    while i + 1 < len(lines) and not lines[i + 1].startswith(":"):
                        i += 1
                        narrative += " " + lines[i].strip()

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
        m = re.match(r"(\d{6})(\d{4})?([DC]R?)(\d+[,\.]\d{2})([A-Z]{4})(.{0,16})", body.strip())
        if not m:
            return None

        date_str = m.group(1)
        dc = m.group(3)  # D = débit, C = crédit
        amount_str = m.group(4).replace(",", ".")
        ref = m.group(6).strip().rstrip("/")

        try:
            # YY MM DD → on suppose 2000+
            date = datetime.strptime("20" + date_str, "%Y%m%d").date()
        except ValueError:
            return None

        try:
            amount = float(amount_str)
        except ValueError:
            return None

        # Débit = montant négatif dans Odoo
        if dc.startswith("D"):
            amount = -amount

        label = narrative.strip() if narrative else (ref or "/")

        return {
            "date": date,
            "payment_ref": label or "/",
            "amount": amount,
            "narration": ref or False,
        }

    # ------------------------------------------------------------------ #
    #  CRÉATION DES LIGNES                                                 #
    # ------------------------------------------------------------------ #

    def _create_lines(self, parsed):
        if not parsed:
            raise UserError(_("Aucune ligne valide trouvée dans le fichier."))

        dates = [vals["date"] for vals in parsed]
        statement = self.env["account.bank.statement"].create({
            "name": _("Import — %(label)s — %(date)s",
                      label=self.statement_name,
                      date=fields.Date.today()),
            "journal_id": self.journal_id.id,
            "date": max(dates),
        })

        StmtLine = self.env["account.bank.statement.line"]
        created = StmtLine

        for vals in parsed:
            # Résoudre le partenaire depuis le nom (colonne optionnelle du CSV)
            partner_name = vals.pop("_partner_name", "")
            if partner_name:
                partner = self.env["res.partner"].search(
                    [("name", "ilike", partner_name), ("active", "=", True)],
                    limit=1,
                )
                if partner:
                    vals["partner_id"] = partner.id
            vals["journal_id"] = self.journal_id.id
            vals["statement_id"] = statement.id
            created |= StmtLine.create(vals)

        # Déclencher les modèles de rapprochement automatique (Perfect Match, etc.)
        # Les règles avec auto_reconcile=True sont appliquées immédiatement après l'import
        # sans attendre que l'utilisateur ouvre le widget de rapprochement bancaire.
        self._trigger_auto_reconciliation(created)

        return created

    def _trigger_auto_reconciliation(self, st_lines):
        """Perfect Match automatique après import.

        En Odoo 17 Community, les modèles de rapprochement sont appliqués par le
        widget JavaScript — il n'existe pas de méthode Python _apply_rules().
        On reproduit ici la logique de bank.reconciliation.wizard._do_match() :
        pour chaque ligne importée, on cherche une facture dont le montant ET la
        référence correspondent exactement, et on réconcilie automatiquement.
        Ne s'active que si au moins une règle invoice_matching avec auto_reconcile=True
        est configurée pour la société.
        """
        if not st_lines:
            return
        has_auto_rule = self.env["account.reconcile.model"].search_count([
            ("auto_reconcile", "=", True),
            ("rule_type", "=", "invoice_matching"),
            ("company_id", "=", self.journal_id.company_id.id),
        ])
        if not has_auto_rule:
            return
        for st_line in st_lines:
            if not st_line.is_reconciled:
                self._try_perfect_match(st_line)

    def _try_perfect_match(self, st_line):
        """Tente de réconcilier automatiquement une ligne de relevé avec une facture.

        Critères du Perfect Match :
          1. Montant résiduel identique (tolérance 0,01)
          2. payment_ref contient la référence ou le nom de la facture
        Si un seul candidat remplit les deux critères, la réconciliation est appliquée.
        """
        payment_ref = (st_line.payment_ref or "").strip()
        if not payment_ref:
            return

        amount = st_line.amount
        domain = [
            ("reconciled", "=", False),
            ("parent_state", "=", "posted"),
            ("account_id.reconcile", "=", True),
            ("move_id.move_type", "in", ["out_invoice", "in_invoice", "out_refund", "in_refund"]),
            ("company_id", "=", st_line.company_id.id),
        ]
        domain.append(("balance", ">", 0) if amount > 0 else ("balance", "<", 0))

        candidates = self.env["account.move.line"].search(domain, limit=200)

        # Filtre 1 : montant exact (résiduel)
        amount_abs = abs(amount)
        by_amount = candidates.filtered(
            lambda ln: abs(abs(ln.amount_residual) - amount_abs) < 0.01
        )
        if not by_amount:
            return

        # Filtre 2 : référence (payment_ref dans nom/ref de la facture, ou l'inverse)
        by_ref = by_amount.filtered(
            lambda ln: payment_ref in (ln.move_id.name or "")
            or payment_ref in (ln.move_id.payment_reference or "")
            or payment_ref in (ln.ref or "")
            or (ln.move_id.name or "") in payment_ref
        )
        if len(by_ref) != 1:
            # Ambiguïté ou pas de match → on laisse l'utilisateur décider
            return

        target_line = by_ref[0]

        try:
            # Si la ligne bancaire n'a pas de partenaire (CSV sans colonne Partenaire),
            # on le déduit depuis la facture matchée → satisfait "Partenaire est défini"
            if not st_line.partner_id and target_line.partner_id:
                st_line.partner_id = target_line.partner_id

            move = st_line.move_id
            if not move:
                return
            if move.state == "posted":
                move.button_draft()

            # Remplacer le compte suspens par le compte de la facture
            suspense_account = st_line.journal_id.suspense_account_id
            if suspense_account:
                suspense_lines = move.line_ids.filtered(
                    lambda ln: ln.account_id == suspense_account
                )
            else:
                bank_account = st_line.journal_id.default_account_id
                suspense_lines = move.line_ids.filtered(
                    lambda ln: ln.account_id != bank_account
                )

            if not suspense_lines:
                return

            suspense_lines.write({
                "account_id": target_line.account_id.id,
                "name": payment_ref or "/",
            })
            move.action_post()

            # Réconciliation des deux lignes sur le même compte
            updated = move.line_ids.filtered(
                lambda ln: ln.account_id == target_line.account_id and not ln.reconciled
            )[:1]
            if updated and not target_line.reconciled:
                (updated | target_line).reconcile()
                _logger.info(
                    "Perfect Match : transaction %s réconciliée automatiquement "
                    "avec la facture %s",
                    st_line.payment_ref,
                    target_line.move_id.name,
                )
        except Exception as exc:
            _logger.warning(
                "Perfect Match échoué pour la ligne '%s' : %s",
                st_line.payment_ref, exc
            )

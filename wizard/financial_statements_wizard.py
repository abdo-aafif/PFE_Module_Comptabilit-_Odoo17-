from odoo import models, fields, api
from datetime import date as date_cls, timedelta
import logging

_logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# TRANSIENT LINE MODELS
# ─────────────────────────────────────────────────────────────────────────────


class FinancialBilanLine(models.TransientModel):
    _name = "financial.bilan.line"
    _description = "Ligne Bilan"
    _order = "sequence"

    wizard_id = fields.Many2one("financial.statement.wizard", ondelete="cascade")
    sequence = fields.Integer()
    name = fields.Char(string="Désignation")
    amount = fields.Float(string="Montant", digits=(16, 2))
    level = fields.Integer(string="Niveau")
    is_total = fields.Boolean(string="Total")
    bold = fields.Boolean()
    section = fields.Selection([("actif", "Actif"), ("passif", "Passif")], default="actif")


class FinancialCpcLine(models.TransientModel):
    _name = "financial.cpc.line"
    _description = "Ligne CPC"
    _order = "sequence"

    wizard_id = fields.Many2one("financial.statement.wizard", ondelete="cascade")
    sequence = fields.Integer()
    name = fields.Char(string="Désignation")
    amount = fields.Float(string="Montant", digits=(16, 2))
    level = fields.Integer()
    is_total = fields.Boolean()
    bold = fields.Boolean()


class FinancialFluxLine(models.TransientModel):
    _name = "financial.flux.line"
    _description = "Ligne Flux de Trésorerie"
    _order = "sequence"

    wizard_id = fields.Many2one("financial.statement.wizard", ondelete="cascade")
    sequence = fields.Integer()
    name = fields.Char(string="Désignation")
    amount = fields.Float(string="Montant", digits=(16, 2))
    level = fields.Integer()
    is_total = fields.Boolean()
    bold = fields.Boolean()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN WIZARD
# ─────────────────────────────────────────────────────────────────────────────


class FinancialStatementWizard(models.TransientModel):
    _name = "financial.statement.wizard"
    _description = "États Financiers – Paramètres"

    company_id = fields.Many2one(
        "res.company",
        string="Société",
        required=True,
        default=lambda s: s.env.company,
    )
    date_from = fields.Date(string="Date début", required=True)
    date_to = fields.Date(string="Date fin", required=True, default=fields.Date.context_today)

    bilan_line_ids = fields.One2many("financial.bilan.line", "wizard_id", string="Bilan")
    cpc_line_ids = fields.One2many("financial.cpc.line", "wizard_id", string="CPC")
    flux_line_ids = fields.One2many("financial.flux.line", "wizard_id", string="Flux")

    # Champs filtrés par section pour la vue : Odoo 17 ne filtre pas
    # fiablement deux occurrences d'un même One2many avec ``domain``
    # déclaré au niveau XML — d'où ces deux miroirs côté Python.
    bilan_actif_line_ids = fields.One2many(
        "financial.bilan.line",
        "wizard_id",
        string="Actif",
        domain=[("section", "=", "actif")],
    )
    bilan_passif_line_ids = fields.One2many(
        "financial.bilan.line",
        "wizard_id",
        string="Passif",
        domain=[("section", "=", "passif")],
    )

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "États Financiers"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = date_cls.today()
        res.setdefault("date_from", date_cls(today.year, 1, 1))
        res.setdefault("date_to", date_cls(today.year, 12, 31))
        return res

    # ── SQL helpers ──────────────────────────────────────────────────────────

    def _balance_at(self, prefixes, at_date, company_id, sign=1):
        """Cumulative debit−credit balance for accounts matching any prefix, up to at_date."""
        if not prefixes:
            return 0.0
        like_conds = " OR ".join(["a.code LIKE %s"] * len(prefixes))
        params = [company_id, at_date] + [p + "%" for p in prefixes]
        self.env.cr.execute(
            f"""
            SELECT COALESCE(SUM(l.debit - l.credit), 0)
            FROM account_move_line l
            JOIN account_move    m ON l.move_id    = m.id
            JOIN account_account a ON l.account_id = a.id
            WHERE m.state = 'posted'
              AND l.company_id = %s
              AND l.date <= %s
              AND ({like_conds})
        """,
            params,
        )
        return (self.env.cr.fetchone()[0] or 0.0) * sign

    def _period_balance(self, prefixes, date_from, date_to, company_id, sign=1):
        """Period debit−credit balance for accounts matching any prefix."""
        if not prefixes:
            return 0.0
        like_conds = " OR ".join(["a.code LIKE %s"] * len(prefixes))
        params = [company_id, date_from, date_to] + [p + "%" for p in prefixes]
        self.env.cr.execute(
            f"""
            SELECT COALESCE(SUM(l.debit - l.credit), 0)
            FROM account_move_line l
            JOIN account_move    m ON l.move_id    = m.id
            JOIN account_account a ON l.account_id = a.id
            WHERE m.state = 'posted'
              AND l.company_id = %s
              AND l.date >= %s
              AND l.date <= %s
              AND ({like_conds})
        """,
            params,
        )
        return (self.env.cr.fetchone()[0] or 0.0) * sign

    def _period_debits(self, prefixes, date_from, date_to, company_id):
        """Sum of debit movements (gross) on accounts matching any prefix during the period."""
        if not prefixes:
            return 0.0
        like_conds = " OR ".join(["a.code LIKE %s"] * len(prefixes))
        params = [company_id, date_from, date_to] + [p + "%" for p in prefixes]
        self.env.cr.execute(
            f"""
            SELECT COALESCE(SUM(l.debit), 0)
            FROM account_move_line l
            JOIN account_move    m ON l.move_id    = m.id
            JOIN account_account a ON l.account_id = a.id
            WHERE m.state = 'posted'
              AND l.company_id = %s
              AND l.date >= %s
              AND l.date <= %s
              AND ({like_conds})
        """,
            params,
        )
        return self.env.cr.fetchone()[0] or 0.0

    def _compute_resultat_net(self, date_from, date_to, company_id):
        """Résultat net de la période = Produits − Charges (mêmes prefixes que le CPC)."""

        def P(p):
            return self._period_balance(p, date_from, date_to, company_id, sign=-1)

        def C(p):
            return self._period_balance(p, date_from, date_to, company_id, sign=1)

        produits = P(
            [
                "711",
                "712",
                "713",
                "714",
                "716",
                "718",
                "719",
                "732",
                "733",
                "738",
                "739",
                "751",
                "756",
                "757",
                "758",
                "759",
            ]
        )
        charges = C(
            [
                "611",
                "612",
                "613",
                "614",
                "616",
                "617",
                "618",
                "619",
                "631",
                "633",
                "638",
                "639",
                "651",
                "656",
                "658",
                "659",
                "670",
            ]
        )
        return produits - charges

    def _compute_cumulative_resultat(self, date_to, company_id):
        """Résultat cumulé des exercices NON clôturés jusqu'à date_to.

        Le résultat des exercices clôturés est déjà reporté dans 119100 / 119900
        par l'écriture à-nouveaux. Pour éviter un double comptage, on ne somme
        les classes 6/7 qu'à partir du jour suivant la dernière clôture annuelle
        validée pour la société."""
        last_close = self.env["account.period.close"].search(
            [
                ("company_id", "=", company_id),
                ("close_type", "=", "annual"),
                ("state", "=", "done"),
                ("date_to", "<=", date_to),
            ],
            order="date_to desc",
            limit=1,
        )

        if last_close:
            df = last_close.date_to + timedelta(days=1)
            if df > date_to:
                return 0.0

            def P(p):
                return self._period_balance(p, df, date_to, company_id, sign=-1)

            def C(p):
                return self._period_balance(p, df, date_to, company_id, sign=1)

        else:

            def P(p):
                return self._balance_at(p, date_to, company_id, sign=-1)

            def C(p):
                return self._balance_at(p, date_to, company_id, sign=1)

        produits = P(
            [
                "711",
                "712",
                "713",
                "714",
                "716",
                "718",
                "719",
                "732",
                "733",
                "738",
                "739",
                "751",
                "756",
                "757",
                "758",
                "759",
            ]
        )
        charges = C(
            [
                "611",
                "612",
                "613",
                "614",
                "616",
                "617",
                "618",
                "619",
                "631",
                "633",
                "638",
                "639",
                "651",
                "656",
                "658",
                "659",
                "670",
            ]
        )
        return produits - charges

    # ── BILAN ────────────────────────────────────────────────────────────────

    def action_compute_bilan(self):
        self.bilan_line_ids.unlink()
        for d in self._get_bilan_lines():
            d["wizard_id"] = self.id
            self.env["financial.bilan.line"].create(d)

    def action_print_bilan(self):
        if not self.bilan_line_ids:
            self.action_compute_bilan()
        return self.env.ref(f"{self._module}.action_report_bilan").report_action(self)

    def _get_bilan_lines(self):
        cid = self.company_id.id
        dt = self.date_to
        lines = []
        seq = [0]

        def L(name, amt, lvl=1, total=False, bold=False, section="actif"):
            seq[0] += 1
            return dict(
                name=name,
                amount=amt or 0.0,
                level=lvl,
                is_total=total,
                bold=bold,
                section=section,
                sequence=seq[0],
                wizard_id=False,
            )

        def bal(p):
            return self._balance_at(p, dt, cid, 1)

        def cbal(p):
            return self._balance_at(p, dt, cid, -1)

        # ── ACTIF ────────────────────────────────────────────────
        lines.append(L("ACTIF", 0, lvl=0, bold=True))

        # Valeurs nettes : amortissements (28X) et provisions (29X) ont des soldes
        # créditeurs → bal renvoie négatif → soustraction automatique
        immo_nv = bal(["211", "212", "213", "281"])
        immo_inc = bal(["221", "222", "223", "228", "282", "292"])
        immo_corp = bal(["231", "232", "233", "234", "235", "238", "239", "283", "293"])
        immo_fin = bal(["241", "248", "251", "258", "294", "295"])  # 271/272 retirés
        ecart_conv_actif_immo = bal(["271", "272"])  # Écarts conversion - Actif (immobilisé)
        t_immo = immo_nv + immo_inc + immo_corp + immo_fin + ecart_conv_actif_immo

        lines += [
            L("ACTIF IMMOBILISÉ", 0, lvl=1, bold=True),
            L("Immobilisations en non-valeurs (net)", immo_nv, lvl=2),
            L("Immobilisations incorporelles (net)", immo_inc, lvl=2),
            L("Immobilisations corporelles (net)", immo_corp, lvl=2),
            L("Immobilisations financières (net)", immo_fin, lvl=2),
            L("Écarts de conversion - Actif", ecart_conv_actif_immo, lvl=2),
            L("Total Actif Immobilisé", t_immo, lvl=1, total=True, bold=True),
        ]

        # Stocks : 311-315 + provisions 391
        stocks = bal(["311", "312", "313", "314", "315", "391"])
        # Créances : 341 (fournisseurs débiteurs), 342-349, provisions 394 (370 retiré)
        creances = bal(["341", "342", "343", "345", "346", "348", "349", "394"])
        # TVP : 350 + provisions 395
        tvp = bal(["350", "395"])
        # Écarts de conversion - Actif (éléments circulants)
        ecart_conv_actif_circ = bal(["370"])
        t_circ = stocks + creances + tvp + ecart_conv_actif_circ

        lines += [
            L("ACTIF CIRCULANT (hors trésorerie)", 0, lvl=1, bold=True),
            L("Stocks (net)", stocks, lvl=2),
            L("Créances de l'actif circulant (net)", creances, lvl=2),
            L("Titres et valeurs de placement (net)", tvp, lvl=2),
            L("Écarts de conversion - Actif (Circulant)", ecart_conv_actif_circ, lvl=2),
            L("Total Actif Circulant", t_circ, lvl=1, total=True, bold=True),
        ]

        # Trésorerie actif : 511, 514, 516 − provisions 590 (afficher la déduction)
        tres_cheq = bal(["511"])
        tres_banques = bal(["514"])
        tres_caisse = bal(["516"])
        tres_provs = bal(["590"])  # solde créditeur → négatif → déductif automatique
        t_tresor_a = tres_cheq + tres_banques + tres_caisse + tres_provs
        lines += [
            L("TRÉSORERIE - ACTIF", 0, lvl=1, bold=True),
            L("Chèques et valeurs à encaisser", tres_cheq, lvl=2),
            L("Banques, T.G. et C.C.P.", tres_banques, lvl=2),
            L("Caisses, régies d'avances et accréditifs", tres_caisse, lvl=2),
            L("(−) Provisions pour dépréciation", tres_provs, lvl=2),
            L("Total Trésorerie - Actif", t_tresor_a, lvl=1, total=True, bold=True),
        ]

        t_actif = t_immo + t_circ + t_tresor_a
        lines.append(L("TOTAL ACTIF", t_actif, lvl=0, total=True, bold=True))

        # ── PASSIF ───────────────────────────────────────────────
        lines.append(L("PASSIF", 0, lvl=0, bold=True, section="passif"))

        # Capitaux propres détaillés (CGNC : un poste par compte 111..119)
        capital = cbal(["111"])  # Capital social ou personnel
        primes = cbal(["112"])  # Primes d'émission, fusion, apport
        ecarts_reev = cbal(["113"])  # Écarts de réévaluation
        res_legale = cbal(["114"])  # Réserve légale
        autres_res = cbal(["115"])  # Autres réserves
        report_nv = cbal(["116"])  # Report à nouveau (±)
        res_inst = cbal(["118"])  # Résultats nets en instance d'affectation (±)
        # Résultat net de l'exercice = solde 119 (1191/1199 inclus via LIKE 119%)
        # + résultat des exercices NON clôturés (classes 6/7), via _compute_cumulative_resultat
        # qui filtre désormais par la dernière clôture annuelle pour éviter le double comptage.
        res_119 = cbal(["119"])
        res_cumule = self._compute_cumulative_resultat(dt, cid)
        res_net_ex = res_119 + res_cumule

        cap_prop = capital + primes + ecarts_reev + res_legale + autres_res + report_nv + res_inst + res_net_ex

        cap_assim = cbal(["131", "135"])
        dettes_fin = cbal(["141", "148"])
        prov_dur = cbal(["151", "155"])
        cpt_liaison = cbal(["160"])  # Comptes de liaison des établissements et succursales
        ecart_conv_passif_perm = cbal(["171", "172"])  # Écarts de conversion - Passif (Permanent)
        t_fin_perm = cap_prop + cap_assim + dettes_fin + prov_dur + cpt_liaison + ecart_conv_passif_perm

        lines += [
            L("FINANCEMENT PERMANENT", 0, lvl=1, bold=True, section="passif"),
            L("Capital social ou personnel", capital, lvl=2, section="passif"),
            L("Primes d'émission, de fusion, d'apport", primes, lvl=2, section="passif"),
            L("Écarts de réévaluation", ecarts_reev, lvl=2, section="passif"),
            L("Réserve légale", res_legale, lvl=2, section="passif"),
            L("Autres réserves", autres_res, lvl=2, section="passif"),
            L("Report à nouveau (±)", report_nv, lvl=2, section="passif"),
            L("Résultats nets en instance d'affectation (±)", res_inst, lvl=2, section="passif"),
            L("Résultat net de l'exercice (±)", res_net_ex, lvl=2, section="passif"),
            L("Total Capitaux propres", cap_prop, lvl=2, total=True, section="passif"),
            L("Capitaux propres assimilés", cap_assim, lvl=2, section="passif"),
            L("Dettes de financement", dettes_fin, lvl=2, section="passif"),
            L("Provisions durables pour risques et charges", prov_dur, lvl=2, section="passif"),
            L("Comptes de liaison", cpt_liaison, lvl=2, section="passif"),
            L("Écarts de conversion - Passif", ecart_conv_passif_perm, lvl=2, section="passif"),
            L("Total Financement Permanent", t_fin_perm, lvl=1, total=True, bold=True, section="passif"),
        ]

        # Passif circulant : 44X (dettes), 450 (provisions), 470 (écarts conv passif)
        dettes_circ = cbal(["441", "442", "443", "444", "445", "446", "448", "449"])
        prov_pc = cbal(["450"])
        ecart_pc = cbal(["470"])
        t_passif_circ = dettes_circ + prov_pc + ecart_pc
        lines += [
            L("PASSIF CIRCULANT (hors trésorerie)", 0, lvl=1, bold=True, section="passif"),
            L("Dettes du passif circulant", dettes_circ, lvl=2, section="passif"),
            L("Autres provisions pour risques et charges", prov_pc, lvl=2, section="passif"),
            L("Écarts de conversion - Passif (Éléments circulants)", ecart_pc, lvl=2, section="passif"),
            L("Total Passif Circulant", t_passif_circ, lvl=1, total=True, bold=True, section="passif"),
        ]

        # Trésorerie passif : 552, 553, 554
        t_tresor_p = cbal(["552", "553", "554"])
        lines += [
            L("TRÉSORERIE - PASSIF", 0, lvl=1, bold=True, section="passif"),
            L("Crédits d'escompte", cbal(["552"]), lvl=2, section="passif"),
            L("Crédits de trésorerie", cbal(["553"]), lvl=2, section="passif"),
            L("Banques (soldes créditeurs)", cbal(["554"]), lvl=2, section="passif"),
            L("Total Trésorerie - Passif", t_tresor_p, lvl=1, total=True, bold=True, section="passif"),
        ]

        t_passif = t_fin_perm + t_passif_circ + t_tresor_p
        lines.append(L("TOTAL PASSIF", t_passif, lvl=0, total=True, bold=True, section="passif"))

        return lines

    # ── CPC ──────────────────────────────────────────────────────────────────

    def action_compute_cpc(self):
        self.cpc_line_ids.unlink()
        for d in self._get_cpc_lines():
            d["wizard_id"] = self.id
            self.env["financial.cpc.line"].create(d)

    def action_print_cpc(self):
        if not self.cpc_line_ids:
            self.action_compute_cpc()
        return self.env.ref(f"{self._module}.action_report_cpc").report_action(self)

    def _get_cpc_lines(self):
        cid = self.company_id.id
        df = self.date_from
        dt = self.date_to
        lines = []
        seq = [0]

        def L(name, amt, lvl=1, total=False, bold=False):
            seq[0] += 1
            return dict(
                name=name, amount=amt or 0.0, level=lvl, is_total=total, bold=bold, sequence=seq[0], wizard_id=False
            )

        # produits → credit surplus → sign=-1 to get positive
        def P(p):
            return self._period_balance(p, df, dt, cid, sign=-1)

        # charges  → debit surplus → sign=+1
        def C(p):
            return self._period_balance(p, df, dt, cid, sign=1)

        # ── Produits d'exploitation ─────────────────────────────
        ventes = P(["711", "712"])
        var_stocks = P(["713"])
        immo_prod = P(["714"])  # 714 = Immobilisations produites pour soi-même
        sub_expl = P(["716"])
        autres_p = P(["718"])
        reprises_p = P(["719"])
        t_prod_expl = ventes + var_stocks + immo_prod + sub_expl + autres_p + reprises_p

        lines += [
            L("I.  PRODUITS D'EXPLOITATION", t_prod_expl, lvl=0, bold=True),
            L("Ventes de marchandises", P(["711"]), lvl=1),
            L("Ventes de biens et services produits", P(["712"]), lvl=1),
            L("Variation de stocks de produits", var_stocks, lvl=1),
            L("Immobilisations produites pour soi-même", immo_prod, lvl=1),
            L("Subventions d'exploitation", sub_expl, lvl=1),
            L("Autres produits d'exploitation", autres_p, lvl=1),
            L("Reprises d'exploitation; transferts de charges", reprises_p, lvl=1),
        ]

        # ── Charges d'exploitation ──────────────────────────────
        ach_march = C(["611"])
        ach_mat = C(["612"])
        ch_ext = C(["613", "614"])
        imp_taxes = C(["616"])
        ch_pers = C(["617"])
        autres_c = C(["618"])
        dot_expl = C(["619"])
        t_ch_expl = ach_march + ach_mat + ch_ext + imp_taxes + ch_pers + autres_c + dot_expl

        lines += [
            L("II.  CHARGES D'EXPLOITATION", t_ch_expl, lvl=0, bold=True),
            L("Achats revendus de marchandises", ach_march, lvl=1),
            L("Achats consommés de matières et fournitures", ach_mat, lvl=1),
            L("Autres charges externes", ch_ext, lvl=1),
            L("Impôts et taxes", imp_taxes, lvl=1),
            L("Charges de personnel", ch_pers, lvl=1),
            L("Autres charges d'exploitation", autres_c, lvl=1),
            L("Dotations d'exploitation", dot_expl, lvl=1),
        ]

        res_expl = t_prod_expl - t_ch_expl
        lines.append(L("RÉSULTAT D'EXPLOITATION  (I − II)", res_expl, lvl=0, total=True, bold=True))

        # ── Produits financiers ─────────────────────────────────
        rev_titres = P(["732"])
        gains_change = P(["733"])
        int_assim = P(["738"])
        reprises_fin = P(["739"])
        t_prod_fin = rev_titres + gains_change + int_assim + reprises_fin
        lines += [
            L("III.  PRODUITS FINANCIERS", t_prod_fin, lvl=0, bold=True),
            L("Produits des titres de participation", rev_titres, lvl=1),
            L("Gains de change", gains_change, lvl=1),
            L("Intérêts et autres produits financiers", int_assim, lvl=1),
            L("Reprises financières; transferts de charges", reprises_fin, lvl=1),
        ]

        # ── Charges financières ─────────────────────────────────
        ch_interets = C(["631"])
        pertes_change = C(["633"])
        autres_ch_fin = C(["638"])
        dot_fin = C(["639"])
        t_ch_fin = ch_interets + pertes_change + autres_ch_fin + dot_fin
        lines += [
            L("IV.  CHARGES FINANCIÈRES", t_ch_fin, lvl=0, bold=True),
            L("Charges d'intérêts", ch_interets, lvl=1),
            L("Pertes de change", pertes_change, lvl=1),
            L("Autres charges financières", autres_ch_fin, lvl=1),
            L("Dotations financières", dot_fin, lvl=1),
        ]

        res_fin = t_prod_fin - t_ch_fin
        res_courant = res_expl + res_fin
        lines.append(L("RÉSULTAT FINANCIER (III − IV)", res_fin, lvl=0, total=True, bold=True))
        lines.append(L("RÉSULTAT COURANT  (I+III − II−IV)", res_courant, lvl=0, total=True, bold=True))

        # ── Produits non courants ───────────────────────────────
        cessions_immo = P(["751"])
        sub_equilibre = P(["756"])
        reprises_sub_inv = P(["757"])
        autres_prod_nc = P(["758"])
        reprises_nc = P(["759"])
        t_prod_nc = cessions_immo + sub_equilibre + reprises_sub_inv + autres_prod_nc + reprises_nc
        lines += [
            L("V.  PRODUITS NON COURANTS", t_prod_nc, lvl=0, bold=True),
            L("Produits des cessions d'immobilisations", cessions_immo, lvl=1),
            L("Subventions d'équilibre", sub_equilibre, lvl=1),
            L("Reprises sur subventions d'investissement", reprises_sub_inv, lvl=1),
            L("Autres produits non courants", autres_prod_nc, lvl=1),
            L("Reprises non courantes; transferts", reprises_nc, lvl=1),
        ]

        # ── Charges non courantes ───────────────────────────────
        vnc_immo_cedees = C(["651"])
        sub_accordees = C(["656"])
        autres_ch_nc = C(["658"])
        dot_nc = C(["659"])
        t_ch_nc = vnc_immo_cedees + sub_accordees + autres_ch_nc + dot_nc
        lines += [
            L("VI.  CHARGES NON COURANTES", t_ch_nc, lvl=0, bold=True),
            L("V.N.C. des immobilisations cédées", vnc_immo_cedees, lvl=1),
            L("Subventions accordées", sub_accordees, lvl=1),
            L("Autres charges non courantes", autres_ch_nc, lvl=1),
            L("Dotations non courantes", dot_nc, lvl=1),
        ]

        res_nc = t_prod_nc - t_ch_nc
        res_avant_is = res_courant + res_nc
        is_amount = C(["670"])
        res_net = res_avant_is - is_amount

        lines += [
            L("RÉSULTAT NON COURANT (V − VI)", res_nc, lvl=0, total=True, bold=True),
            L("RÉSULTAT AVANT IMPÔTS", res_avant_is, lvl=0, total=True, bold=True),
            L("VII.  IMPÔTS SUR LES RÉSULTATS", is_amount, lvl=0, bold=True),
            L("RÉSULTAT NET DE L'EXERCICE", res_net, lvl=0, total=True, bold=True),
        ]
        return lines

    # ── FLUX DE TRÉSORERIE ───────────────────────────────────────────────────

    def action_compute_flux(self):
        self.flux_line_ids.unlink()
        for d in self._get_flux_lines():
            d["wizard_id"] = self.id
            self.env["financial.flux.line"].create(d)

    def action_print_flux(self):
        if not self.flux_line_ids:
            self.action_compute_flux()
        return self.env.ref(f"{self._module}.action_report_flux").report_action(self)

    # ── DASHBOARD OWL (JSON-RPC endpoint) ────────────────────────────────────

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, company_id=None):
        """Endpoint JSON-RPC pour le Dashboard OWL.

        Retourne KPIs + données structurées prêtes pour Chart.js :
          - 4 KPI cards (Actif, Passif, Résultat net, Trésorerie nette)
          - Donut Actif (Immobilisé / Circulant / Trésorerie)
          - Donut Passif (Fin. Permanent / Circulant / Trésorerie Passif)
          - Bar CPC (Produits Expl / Charges Expl / Résultat Expl)
          - Bar Flux (Exploitation / Investissement / Financement)
        """
        today = date_cls.today()
        company_id = company_id or self.env.company.id
        df = fields.Date.from_string(date_from) if date_from else date_cls(today.year, 1, 1)
        dt = fields.Date.from_string(date_to) if date_to else date_cls(today.year, 12, 31)

        wiz = self.new({"company_id": company_id, "date_from": df, "date_to": dt})

        # ---- Agrégats BILAN ----
        cid = company_id
        immo = wiz._balance_at(
            ["211", "212", "213", "281", "221", "222", "223", "228", "282", "292",
             "231", "232", "233", "234", "235", "238", "239", "283", "293",
             "241", "248", "251", "258", "294", "295", "271", "272"],
            dt, cid, 1,
        )
        circ = wiz._balance_at(
            ["311", "312", "313", "314", "315", "391",
             "341", "342", "343", "345", "346", "348", "349", "394",
             "350", "395", "370"],
            dt, cid, 1,
        )
        tresor_a = wiz._balance_at(["511", "514", "516", "590"], dt, cid, 1)
        total_actif = immo + circ + tresor_a

        fin_perm = wiz._balance_at(
            ["111", "112", "113", "114", "115", "116", "118", "119",
             "131", "135", "141", "148", "151", "155", "160", "171", "172"],
            dt, cid, -1,
        )
        # Ajouter résultat cumulé non clôturé
        fin_perm += wiz._compute_cumulative_resultat(dt, cid)
        pass_circ = wiz._balance_at(
            ["441", "442", "443", "444", "445", "446", "448", "449", "450", "470"],
            dt, cid, -1,
        )
        tresor_p = wiz._balance_at(["552", "553", "554"], dt, cid, -1)
        total_passif = fin_perm + pass_circ + tresor_p

        # ---- Agrégats CPC ----
        prod_expl = wiz._period_balance(
            ["711", "712", "713", "714", "716", "718", "719"], df, dt, cid, sign=-1
        )
        ch_expl = wiz._period_balance(
            ["611", "612", "613", "614", "616", "617", "618", "619"], df, dt, cid, sign=1
        )
        res_expl = prod_expl - ch_expl

        prod_fin = wiz._period_balance(["732", "733", "738", "739"], df, dt, cid, sign=-1)
        ch_fin = wiz._period_balance(["631", "633", "638", "639"], df, dt, cid, sign=1)
        prod_nc = wiz._period_balance(["751", "756", "757", "758", "759"], df, dt, cid, sign=-1)
        ch_nc = wiz._period_balance(["651", "656", "658", "659"], df, dt, cid, sign=1)
        impots = wiz._period_balance(["670"], df, dt, cid, sign=1)
        resultat_net = (prod_expl + prod_fin + prod_nc) - (ch_expl + ch_fin + ch_nc) - impots

        # ---- Agrégats FLUX ----
        flux_lines = wiz._get_flux_lines()
        flux_expl = next((ln["amount"] for ln in flux_lines if "FLUX NET D'EXPLOITATION" in ln["name"]), 0.0)
        flux_inv = next((ln["amount"] for ln in flux_lines if "FLUX NET D'INVESTISSEMENT" in ln["name"]), 0.0)
        flux_fin = next((ln["amount"] for ln in flux_lines if "FLUX NET DE FINANCEMENT" in ln["name"]), 0.0)
        tresor_nette = tresor_a - wiz._balance_at(["552", "553", "554"], dt, cid, 1)

        company = self.env["res.company"].browse(cid)
        currency = company.currency_id.symbol or "MAD"

        return {
            "company_name": company.name,
            "currency": currency,
            "date_from": fields.Date.to_string(df),
            "date_to": fields.Date.to_string(dt),
            "kpis": {
                "total_actif": round(total_actif, 2),
                "total_passif": round(total_passif, 2),
                "resultat_net": round(resultat_net, 2),
                "tresorerie_nette": round(tresor_nette, 2),
            },
            "actif_chart": {
                "labels": ["Actif Immobilisé", "Actif Circulant", "Trésorerie Actif"],
                "data": [round(immo, 2), round(circ, 2), round(tresor_a, 2)],
            },
            "passif_chart": {
                "labels": ["Financement Permanent", "Passif Circulant", "Trésorerie Passif"],
                "data": [round(fin_perm, 2), round(pass_circ, 2), round(tresor_p, 2)],
            },
            "cpc_chart": {
                "labels": ["Produits d'Exploitation", "Charges d'Exploitation", "Résultat d'Exploitation"],
                "data": [round(prod_expl, 2), round(ch_expl, 2), round(res_expl, 2)],
            },
            "flux_chart": {
                "labels": ["Exploitation", "Investissement", "Financement"],
                "data": [round(flux_expl, 2), round(flux_inv, 2), round(flux_fin, 2)],
            },
        }

    def _get_flux_lines(self):
        cid = self.company_id.id
        df = self.date_from
        dt = self.date_to
        dt0 = df - timedelta(days=1)  # day before period start
        lines = []
        seq = [0]

        def L(name, amt, lvl=1, total=False, bold=False):
            seq[0] += 1
            return dict(
                name=name, amount=amt or 0.0, level=lvl, is_total=total, bold=bold, sequence=seq[0], wizard_id=False
            )

        def bat(p):
            return self._balance_at(p, dt, cid)

        def bat0(p):
            return self._balance_at(p, dt0, cid)

        def delta(p):
            return bat(p) - bat0(p)

        def P(p):
            return self._period_balance(p, df, dt, cid, sign=-1)

        def C(p):
            return self._period_balance(p, df, dt, cid, sign=1)

        # ── A. Flux d'exploitation (méthode indirecte) ──────────
        # Résultat net cohérent avec le CPC (mêmes prefixes)
        res_net = self._compute_resultat_net(df, dt, cid)
        dotations = C(["619", "639", "659"])
        reprises = P(["719", "739", "759"])
        # Reclassement des cessions : la VNC (651) et le produit (751) sont dans
        # le résultat net mais leur cash réel passe en flux d'investissement.
        # On les neutralise donc dans l'opérationnel.
        vnc_cessions = C(["651"])
        prod_cessions = P(["751"])

        # BFR: increase in asset = use of cash → negate delta
        d_clients = -delta(["341", "342", "343", "345", "346", "348", "349"])
        d_stocks = -delta(["311", "312", "313", "314", "315"])
        d_fourn = -delta(["441", "442", "443", "444", "445", "446", "448", "449"])
        d_autres_bfr = -delta(["370", "394", "395", "450", "470"])
        bfr = d_clients + d_stocks + d_fourn + d_autres_bfr

        flux_expl = res_net + dotations - reprises + vnc_cessions - prod_cessions + bfr  # neutralisation cessions

        lines += [
            L("A.  FLUX DE TRÉSORERIE LIÉ À L'ACTIVITÉ", 0, lvl=0, bold=True),
            L("Résultat net de l'exercice", res_net, lvl=1),
            L("Dotations aux amortissements et provisions", dotations, lvl=1),
            L("Reprises sur provisions", -reprises, lvl=1),
            L("VNC des immobilisations cédées (réintégration)", vnc_cessions, lvl=1),
            L("Produits de cession (reclassés en invest.)", -prod_cessions, lvl=1),
            L("Variation des créances clients", d_clients, lvl=1),
            L("Variation des stocks", d_stocks, lvl=1),
            L("Variation des dettes fournisseurs", d_fourn, lvl=1),
            L("Variation des autres éléments du BFR", d_autres_bfr, lvl=1),
            L("FLUX NET D'EXPLOITATION  (A)", flux_expl, lvl=0, total=True, bold=True),
        ]

        # ── B. Flux d'investissement ─────────────────────────────
        # Acquisitions = mouvements DÉBITEURS sur immo brutes pendant la période
        # (évite de confondre avec les sorties d'immo brutes lors des cessions,
        #  qui sont des crédits sur ces mêmes comptes)
        immo_brut_prefixes = [
            "211",
            "212",
            "213",
            "221",
            "222",
            "223",
            "228",
            "231",
            "232",
            "233",
            "234",
            "235",
            "238",
            "239",
            "241",
            "248",
            "251",
            "258",
            "271",
            "272",
        ]
        acquisitions = self._period_debits(immo_brut_prefixes, df, dt, cid)
        # Cessions : cash reçu = produit de cession (compte 751)
        cessions_cash = P(["751"])
        flux_inv = cessions_cash - acquisitions

        lines += [
            L("B.  FLUX DE TRÉSORERIE LIÉ AUX INVESTISSEMENTS", 0, lvl=0, bold=True),
            L("Acquisitions d'immobilisations", -acquisitions, lvl=1),
            L("Produits de cession d'immobilisations", cessions_cash, lvl=1),
            L("FLUX NET D'INVESTISSEMENT  (B)", flux_inv, lvl=0, total=True, bold=True),
        ]

        # ── C. Flux de financement ───────────────────────────────
        # Capitaux propres hors résultat (119 déjà dans base A) et hors report à nouveau (116)
        d_cap = -delta(["111", "112", "113", "114", "115", "118"])
        # Subventions d'investissement reçues (131, 135) = flux d'encaissement entrant
        d_subv = -delta(["131", "135"])
        d_dettes = -delta(["141", "148"])
        # Dividendes payés = mouvements débiteurs de 4465 (paiements de dividendes)
        dividendes = self._period_debits(["4465"], df, dt, cid)
        flux_fin = d_cap + d_subv + d_dettes - dividendes

        lines += [
            L("C.  FLUX DE TRÉSORERIE LIÉ AU FINANCEMENT", 0, lvl=0, bold=True),
            L("Augmentations de capital", d_cap, lvl=1),
            L("Subventions d'investissement reçues", d_subv, lvl=1),
            L("Emprunts et dettes de financement", d_dettes, lvl=1),
            L("Dividendes versés", -dividendes, lvl=1),
            L("FLUX NET DE FINANCEMENT  (C)", flux_fin, lvl=0, total=True, bold=True),
        ]

        # ── Variation nette de trésorerie ────────────────────────
        var_tresor = flux_expl + flux_inv + flux_fin
        # Trésorerie nette = Actif (511, 514, 516) − Passif (552, 553, 554)
        # Les comptes de classe 55 ont des soldes créditeurs → bal renvoie négatif → soustraction auto
        tresor_debut = bat0(["511", "514", "516"]) + bat0(["552", "553", "554"])
        tresor_fin = tresor_debut + var_tresor

        lines += [
            L("VARIATION NETTE DE TRÉSORERIE  (A+B+C)", var_tresor, lvl=0, total=True, bold=True),
            L("Trésorerie nette – début de période", tresor_debut, lvl=1),
            L("Trésorerie nette – fin de période", tresor_fin, lvl=1, total=True, bold=True),
        ]
        return lines

# -*- coding: utf-8 -*-
"""Sous-package ``wizard`` — assistants interactifs Odoo.

Section 3.1.4 du CDC : Gestion Bancaire
  • bank_statement_import_wizard : Import de relevés bancaires (CSV, OFX, MT940)
  • bank_reconciliation_wizard   : Rapprochement bancaire (imputation directe + association)

Section 3.1.5 du CDC : Déclarations Fiscales
  • simpl_tva_wizard             : Export EDI XML SIMPL-TVA (DGI Maroc)
"""

from . import bank_statement_import_wizard
from . import bank_reconciliation_wizard
from . import simpl_tva_wizard

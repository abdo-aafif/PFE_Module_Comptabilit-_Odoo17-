# -*- coding: utf-8 -*-
"""Sous-package ``wizard`` — assistants interactifs Odoo.

Section 3.1.4 du CDC : Gestion Bancaire
  • bank_statement_import_wizard : Import de relevés bancaires (CSV, OFX, MT940)
  • bank_reconciliation_wizard   : Rapprochement bancaire (imputation directe + association)
"""
from . import bank_statement_import_wizard
from . import bank_reconciliation_wizard

# -*- coding: utf-8 -*-
"""Sous-package ``wizard`` — assistants interactifs Odoo.

Section 3.1.4 du CDC : Gestion Bancaire
  • bank_statement_import_wizard : Import de relevés bancaires (CSV, OFX, MT940)
  • bank_reconciliation_wizard   : Rapprochement bancaire (imputation directe + association)

Section 3.1.5 du CDC : Déclarations Fiscales
  • simpl_tva_wizard             : Export EDI XML SIMPL-TVA (DGI Maroc)

Section 3.2.2 du CDC : Gestion des Immobilisations
  • asset_disposal_wizard        : Cession / mise au rebut d'une immobilisation

Section 3.2.3 du CDC : Clôture Comptable
  • period_close_wizard          : Contrôles pré-clôture + verrouillage + génération à-nouveaux

Section 3.2.1 du CDC : États Financiers
  • financial_statements_wizard  : Wizard Bilan / CPC / Flux de Trésorerie (PCGE marocain)
  • custom_report_result_wizard  : Wizard d'exécution des rapports personnalisés

Section 3.2.4 du CDC : Multi-devises
  • currency_revaluation_wizard  : Écarts de conversion fin de période (OD automatique)
"""

from . import bank_statement_import_wizard
from . import bank_reconciliation_wizard
from . import simpl_tva_wizard
from . import asset_disposal_wizard
from . import period_close_wizard
from . import financial_statements_wizard
from . import custom_report_result_wizard
from . import currency_revaluation_wizard

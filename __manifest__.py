{
    'name': 'comptabilité Omega Soft',
    'version': '17.0.1.0.0',
    'category': 'Accounting',
    'summary': 'PCGE marocain + Comptabilité analytique + Multi-société',
    'description': """
Module de comptabilité pour Odoo 17 Community — PUSH 1
=========================================================
Section 3.1.1 du CDC : Plan Comptable
  • PCGE marocain par défaut (via l10n_ma)
  • Configuration et personnalisation du plan comptable
  • Import/export CSV/Excel (mécanisme natif Odoo)
  • Gestion multi-sociétés
  • Comptes analytiques + distribution automatique
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'analytic',
        'account',
        'l10n_ma',
        'base_setup',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/compta_security.xml',
        'views/account_analytic_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

# -*- coding: utf-8 -*-
{
    "name": "Pakistan Compliance",
    "summary": "FBR digital invoicing and PRA e-invoicing compliance for Pakistan",
    "description": """
Pakistan Compliance
====================
Submits Sales Invoices and Point of Sale invoices to Pakistan's FBR
(Federal Board of Revenue) digital invoicing API, and Sales Invoices to the
Punjab Revenue Authority (PRA) IMS, for tax compliance.

Ported from the ERPNext "Pak Compliance" app (fbr_e_invoicing).
""",
    "version": "18.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Deliverydevs",
    "website": "https://deliverydevs.com",
    "license": "LGPL-3",
    "depends": [
        "account",
        "l10n_pk",
        "point_of_sale",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/fbr_sale_type_data.xml",
        "data/ir_cron_data.xml",
        "data/pakistan_tax_data.xml",
        "views/res_company_views.xml",
        "views/res_partner_views.xml",
        "views/product_template_views.xml",
        "views/account_move_views.xml",
        "views/fbr_sale_type_views.xml",
        "views/fbr_queue_views.xml",
        "views/fbr_log_views.xml",
        "views/pra_pct_code_views.xml",
        "views/menu.xml",
        "report/pra_sales_invoice_report.xml",
        "report/fbr_sales_invoice_report.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
    "icon": "/pk_fbr_pra_e_invoicing/static/description/icon.png",
}

# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Correction vs the original porting plan: Odoo's own "hs_code" field
    # (product.template.hs_code) lives in the `stock_delivery` module, which
    # is about carrier customs declarations, not accounting. Pulling in that
    # whole module just to reuse one field isn't worth the dependency, so we
    # define our own here instead, used for FBR submissions.
    fbr_hs_code = fields.Char(
        string="HS Code",
        help="Pakistan Customs Tariff / HS classification code, used in FBR submissions "
        "(dotted format, e.g. 8471.3010 -- FBR's own API accepts this format).",
    )
    fbr_sale_type_id = fields.Many2one("fbr.sale.type", string="FBR Sale Type")
    pra_pct_code_id = fields.Many2one(
        "pra.pct.code",
        string="PRA PCT Code",
        help="Pakistan Customs Tariff code used specifically for PRA submissions. "
        "PRA requires a pure-digit code (no dots) -- kept as its own master-data "
        "list (synced from FBR's reference API) rather than reusing the HS Code "
        "field above, since PRA's own format/length checks are stricter.",
    )

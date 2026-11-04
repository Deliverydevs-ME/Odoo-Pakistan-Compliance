# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    fbr_hs_code = fields.Char(related="product_id.product_tmpl_id.fbr_hs_code", string="HS Code")
    fbr_sale_type_id = fields.Many2one(
        related="product_id.product_tmpl_id.fbr_sale_type_id", string="FBR Sale Type"
    )
    pra_pct_code_id = fields.Many2one(
        "pra.pct.code", related="product_id.product_tmpl_id.pra_pct_code_id", string="PRA PCT Code"
    )
    fbr_tax_rate = fields.Float(
        string="FBR Tax Rate (%)", compute="_compute_fbr_tax_rate_amount", store=True
    )
    fbr_tax_amount = fields.Monetary(
        string="FBR Tax Amount", compute="_compute_fbr_tax_rate_amount", store=True
    )

    @api.depends("tax_ids", "tax_ids.amount", "price_subtotal")
    def _compute_fbr_tax_rate_amount(self):
        # Mirrors calculate_fbr_custom_taxes: sum the percentage-type taxes on
        # the line and apply that rate to the line's net amount.
        for line in self:
            rate = sum(
                tax.amount
                for tax in line.tax_ids
                if tax.amount_type == "percent"
            )
            line.fbr_tax_rate = rate
            line.fbr_tax_amount = round(line.price_subtotal * rate / 100.0, 2)

    def _fbr_first_tax_rate(self):
        """Mirrors the source's "first Item Tax Template Detail row" lookup:
        the first percentage tax on the line, used for the payload's per-item
        tax_rate (as opposed to the combined fbr_tax_rate above)."""
        self.ensure_one()
        for tax in self.tax_ids:
            if tax.amount_type == "percent":
                return tax.amount
        return 0.0

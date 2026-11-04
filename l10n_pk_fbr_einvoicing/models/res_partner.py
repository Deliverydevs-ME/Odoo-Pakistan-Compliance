# -*- coding: utf-8 -*-
import re

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    fbr_customer_category = fields.Selection(
        [("bill_to", "Bill To"), ("ship_to", "Ship To")],
        string="FBR Customer Category",
    )
    fbr_province_id = fields.Many2one(
        "res.country.state",
        string="FBR/PRA Province",
        domain="[('country_id.code', '=', 'PK')]",
        help="Buyer province used for FBR/PRA tax-category resolution on invoices.",
    )
    fbr_ntn = fields.Char(string="NTN", help="National Tax Number.")
    fbr_stn = fields.Char(string="STN", help="Sales Tax Registration Number.")
    fbr_nic = fields.Char(
        string="NIC",
        help="National Identity Card number, used as buyer tax id when the "
        "customer is not NTN/STN-registered. Digits are normalised "
        "automatically when building submission payloads.",
    )
    fbr_contact_person = fields.Char(string="FBR Contact Person")

    def _fbr_resolve_tax_id(self):
        """Mirrors the source app's buyer-tax-id resolution order:
        NTN/STN > digit-stripped NIC."""
        self.ensure_one()
        if self.fbr_stn:
            return self.fbr_stn
        if self.fbr_ntn:
            return self.fbr_ntn
        if self.fbr_nic:
            digits = re.sub(r"\D", "", self.fbr_nic)
            return digits or False
        return False

    def _fbr_registration_type(self):
        return "Registered" if self._fbr_resolve_tax_id() else "Unregistered"

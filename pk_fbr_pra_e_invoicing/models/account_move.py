# -*- coding: utf-8 -*-
import logging
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Date

_logger = logging.getLogger(__name__)

PRA_PAYMENT_MODE_MAP = {
    "cash": 1,
    "card": 2,
    "gift_voucher": 3,
    "loyalty_card": 4,
    "mixed": 5,
    "cheque": 6,
}


def _format_fbr_rate(rate):
    if rate == int(rate):
        return f"{int(rate)}%"
    return f"{rate}%"


def _join_address(partner):
    parts = [
        partner.street,
        partner.street2,
        partner.city,
        partner.state_id.name if partner.state_id else False,
        partner.zip,
    ]
    return ", ".join(p for p in parts if p)


class AccountMove(models.Model):
    _inherit = "account.move"

    # ---- FBR ----
    fbr_invoice_number = fields.Char(string="FBR Invoice Number", readonly=True, copy=False)
    fbr_datetime = fields.Datetime(string="FBR Datetime", readonly=True, copy=False)
    fbr_status = fields.Char(string="FBR Status", readonly=True, copy=False)
    fbr_response = fields.Text(string="FBR Response", readonly=True, copy=False)
    fbr_submit_to_fbr = fields.Boolean(string="Submit to FBR", default=True)
    fbr_is_pos_origin = fields.Boolean(
        string="From POS", compute="_compute_fbr_is_pos_origin", store=True
    )

    # ---- PRA ----
    pra_invoice_number = fields.Char(string="PRA Invoice Number", readonly=True, copy=False)
    pra_datetime = fields.Datetime(string="PRA Datetime", readonly=True, copy=False)
    pra_status = fields.Char(string="PRA Status", readonly=True, copy=False)
    pra_response = fields.Text(string="PRA Response", readonly=True, copy=False)
    pra_payment_mode = fields.Selection(
        [
            ("cash", "Cash"),
            ("card", "Card"),
            ("gift_voucher", "Gift Voucher"),
            ("loyalty_card", "Loyalty Card"),
            ("mixed", "Mixed"),
            ("cheque", "Cheque"),
        ],
        string="PRA Payment Mode",
        default="cheque",
    )
    submit_to_pra = fields.Boolean(string="Submit to PRA", default=True)

    @api.depends("pos_order_ids")
    def _compute_fbr_is_pos_origin(self):
        for move in self:
            move.fbr_is_pos_origin = bool(move.pos_order_ids)

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    def _fbr_is_eligible(self):
        self.ensure_one()
        return (
            self.move_type in ("out_invoice", "out_refund")
            and self.company_id.fbr_enabled
            and self.fbr_submit_to_fbr
        )

    def _pra_is_eligible(self):
        self.ensure_one()
        if self.move_type not in ("out_invoice", "out_refund"):
            return False
        if not (self.company_id.pra_enabled and self.submit_to_pra):
            return False
        pra_province = self.company_id.pra_province_id
        buyer_province = self.partner_id.fbr_province_id
        return bool(pra_province) and buyer_province == pra_province

    # ------------------------------------------------------------------
    # Posting-time validation (mirrors validate_fbr_fields / validate_pra_fields
    # / force_today_posting_date from the source app)
    # ------------------------------------------------------------------
    def _post(self, soft=True):
        for move in self:
            if move.move_type in ("out_invoice", "out_refund") and move.state == "draft":
                errors = []
                if move._fbr_is_eligible():
                    errors += move._fbr_collect_validation_errors()
                if move._pra_is_eligible():
                    errors += move._pra_collect_validation_errors()
                if move._fbr_is_eligible() and move._pra_is_eligible():
                    errors.append(
                        "This invoice's buyer province qualifies for both FBR and "
                        "PRA submission on this company. Configure distinct "
                        "FBR/PRA provinces, or disable one of Submit to FBR / "
                        "Submit to PRA on this invoice."
                    )
                if errors:
                    raise ValidationError("\n".join(errors))
                if move._fbr_is_eligible() or move._pra_is_eligible():
                    today = Date.context_today(move)
                    move.invoice_date = today
                    move.date = today

        result = super()._post(soft=soft)

        # POS-originated invoices auto-submit to FBR immediately on posting
        # (mirrors submit_pos_invoice_on_submit); regular Customer Invoices
        # are never auto-queued -- manual "Post to FBR"/bulk action only.
        for move in self:
            if (
                move.move_type in ("out_invoice", "out_refund")
                and move.pos_order_ids
                and move._fbr_is_eligible()
            ):
                self.env["fbr.queue"]._add_to_queue(move, "fbr", force_immediate=True)

        return result

    def _fbr_collect_validation_errors(self):
        self.ensure_one()
        errors = []
        company = self.company_id
        if not company.fbr_api_endpoint:
            errors.append("FBR: API Endpoint is not configured on the company.")
        if not company.fbr_authorization_token:
            errors.append("FBR: Authorization Token is not configured on the company.")
        if company.fbr_mode not in ("sandbox", "production"):
            errors.append("FBR: Mode must be Sandbox Testing or Production.")
        if not company.fbr_province_id:
            errors.append("FBR: Seller Province is not configured on the company.")
        if not company.vat:
            errors.append("FBR: Company Tax ID (NTN) is required.")
        if not self.partner_id.fbr_province_id:
            errors.append("FBR: Buyer Province is required on the customer.")
        missing_hs, missing_tax, missing_sale_type = [], [], []
        for idx, line in enumerate(self.invoice_line_ids.filtered(lambda l: l.display_type == 'product'), start=1):
            if not line.fbr_hs_code:
                missing_hs.append(f"Row {idx} ({line.product_id.display_name})")
            if not line.tax_ids:
                missing_tax.append(f"Row {idx} ({line.product_id.display_name})")
            if not line.fbr_sale_type_id:
                missing_sale_type.append(f"Row {idx} ({line.product_id.display_name})")
        if missing_hs:
            errors.append("FBR: Missing HS Code on: " + ", ".join(missing_hs))
        if missing_tax:
            errors.append("FBR: Missing Tax on: " + ", ".join(missing_tax))
        if missing_sale_type:
            errors.append("FBR: Missing Sale Type on: " + ", ".join(missing_sale_type))
        return errors

    def _pra_collect_validation_errors(self):
        self.ensure_one()
        errors = []
        company = self.company_id
        if not company.pra_pos_id:
            errors.append("PRA: POS ID is not configured on the company.")
        if not company._get_pra_token():
            errors.append("PRA: Access Token is not configured on the company.")
        missing_pct = [
            f"Row {idx} ({line.product_id.display_name})"
            for idx, line in enumerate(
                self.invoice_line_ids.filtered(lambda l: l.display_type == 'product'), start=1
            )
            if not line.pra_pct_code_id
        ]
        if missing_pct:
            errors.append("PRA: Missing PCT Code on: " + ", ".join(missing_pct))
        return errors

    # ------------------------------------------------------------------
    # Cancel handling (block once FBR/PRA-valid, cleanup queue otherwise)
    # ------------------------------------------------------------------
    def button_draft(self):
        for move in self:
            if move.move_type in ("out_invoice", "out_refund"):
                if move.fbr_status and move.fbr_status.lower() == "valid" and move.fbr_invoice_number:
                    raise ValidationError(
                        "This invoice has already been successfully submitted to "
                        "FBR (%s) and cannot be reset to draft/cancelled."
                        % move.fbr_invoice_number
                    )
                if move.pra_status and move.pra_status.lower() == "success" and move.pra_invoice_number:
                    raise ValidationError(
                        "This invoice has already been successfully submitted to "
                        "PRA (%s) and cannot be reset to draft/cancelled."
                        % move.pra_invoice_number
                    )
        result = super().button_draft()
        Queue = self.env["fbr.queue"].sudo()
        Log = self.env["fbr.log"].sudo()
        for move in self:
            if move.move_type not in ("out_invoice", "out_refund"):
                continue
            stale = Queue.search(
                [
                    ("res_model", "=", "account.move"),
                    ("res_id", "=", move.id),
                    ("status", "in", ("pending", "failed")),
                ]
            )
            for authority in stale.mapped("authority"):
                Log.create(
                    {
                        "res_model": "account.move",
                        "res_id": move.id,
                        "authority": authority,
                        "status": "cancelled",
                        "submitted_at": fields.Datetime.now(),
                        "validation_errors": "Queue entries removed on cancel/reset-to-draft.",
                    }
                )
            stale.unlink()
        return result

    # ------------------------------------------------------------------
    # FBR payload builder
    # ------------------------------------------------------------------
    def _build_fbr_payload(self):
        self.ensure_one()
        company = self.company_id
        seller_partner = company.partner_id
        buyer_partner = self.partner_id

        payload = {
            "invoiceType": "Debit Note" if self.move_type == "out_refund" else "Sale Invoice",
            "invoiceDate": fields.Date.to_string(self.invoice_date),
            "sellerNTNCNIC": company.vat or "",
            "sellerBusinessName": company.name,
            "sellerProvince": company.fbr_province_id.name or "",
            "sellerAddress": _join_address(seller_partner),
            "buyerNTNCNIC": buyer_partner._fbr_resolve_tax_id() or "",
            "buyerBusinessName": buyer_partner.name,
            "buyerProvince": buyer_partner.fbr_province_id.name or "",
            "buyerAddress": _join_address(buyer_partner),
            "buyerRegistrationType": buyer_partner._fbr_registration_type(),
            "invoiceRefNo": "",
            "items": [],
        }

        lines = self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        if company.fbr_mode == "sandbox":
            first_sale_type = lines[:1].fbr_sale_type_id
            if not first_sale_type:
                raise ValidationError("FBR: cannot resolve a scenarioId for sandbox mode "
                                       "- the first invoice line has no FBR Sale Type.")
            payload["scenarioId"] = first_sale_type.scenario_id

        for line in lines:
            tax_rate = line._fbr_first_tax_rate()
            value_excl_st = line.price_subtotal
            sale_type_label = (
                line.fbr_sale_type_id._payload_sale_type_label()
                if line.fbr_sale_type_id
                else ""
            )
            payload["items"].append(
                {
                    "hsCode": line.fbr_hs_code or "",
                    "productDescription": line.name or line.product_id.display_name,
                    "rate": _format_fbr_rate(tax_rate),
                    "uoM": line.product_uom_id.name or "",
                    "quantity": line.quantity,
                    "valueSalesExcludingST": value_excl_st,
                    "salesTaxApplicable": round(tax_rate * value_excl_st / 100.0, 2),
                    "totalValues": 0.00,
                    "fixedNotifiedValueOrRetailPrice": 0.00,
                    "salesTaxWithheldAtSource": 0.00,
                    "extraTax": 0.00,
                    "furtherTax": 0.00,
                    "fedPayable": 0.00,
                    "sroScheduleNo": "",
                    "sroItemSerialNo": "",
                    "discount": 0.00,
                    "saleType": sale_type_label,
                }
            )
        return payload

    # ------------------------------------------------------------------
    # PRA payload builder
    # ------------------------------------------------------------------
    def _build_pra_payload(self):
        self.ensure_one()
        company = self.company_id
        buyer_partner = self.partner_id
        lines = self.invoice_line_ids.filtered(lambda l: l.display_type == 'product')

        payload = {
            "InvoiceNumber": "",
            "POSID": company.pra_pos_id or "",
            "USIN": self.name,
            "RefUSIN": self.reversed_entry_id.name if self.move_type == "out_refund" and self.reversed_entry_id else "",
            "DateTime": fields.Datetime.to_string(fields.Datetime.now()),
            "BuyerName": buyer_partner.name or "",
            "BuyerPNTN": buyer_partner._fbr_resolve_tax_id() or "",
            "BuyerCNIC": buyer_partner.fbr_nic or "",
            "BuyerPhoneNumber": buyer_partner.mobile or buyer_partner.phone or "",
            "TotalQuantity": sum(lines.mapped("quantity")),
            "TotalSaleValue": self.amount_untaxed,
            "TotalTaxCharged": self.amount_tax,
            "Discount": 0.00,
            "FurtherTax": 0.00,
            "TotalBillAmount": self.amount_total,
            "PaymentMode": PRA_PAYMENT_MODE_MAP.get(self.pra_payment_mode, 6),
            "InvoiceType": 3 if self.move_type == "out_refund" else 1,
            "Items": [],
        }
        for line in lines:
            payload["Items"].append(
                {
                    "ItemCode": line.product_id.default_code or str(line.product_id.id),
                    "ItemName": line.product_id.display_name,
                    # PRA requires a pure-digit PCT code (e.g. "84713010");
                    # the master data keeps FBR's canonical dotted format
                    # ("8471.3010") for display/lookup consistency, so strip
                    # non-digits only here, at the point of use for PRA.
                    "PCTCode": re.sub(r"\D", "", line.pra_pct_code_id.code_number or ""),
                    "Quantity": line.quantity,
                    "TaxRate": line.fbr_tax_rate,
                    "TaxCharged": line.fbr_tax_amount,
                    "SaleValue": line.price_subtotal,
                    "TotalAmount": round(line.price_subtotal + line.fbr_tax_amount, 2),
                    "Discount": 0.00,
                    "FurtherTax": 0.00,
                    "InvoiceType": payload["InvoiceType"],
                    "RefUSIN": payload["RefUSIN"],
                }
            )
        return payload

    # ------------------------------------------------------------------
    # Manual actions
    # ------------------------------------------------------------------
    def action_post_to_fbr(self):
        for move in self:
            self.env["fbr.queue"]._add_to_queue(move, "fbr", force_immediate=True)

    def action_post_to_pra(self):
        for move in self:
            self.env["fbr.queue"]._add_to_queue(move, "pra", force_immediate=True)

    def action_bulk_submit_to_fbr(self):
        return self._bulk_submit("fbr")

    def action_bulk_submit_to_pra(self):
        return self._bulk_submit("pra")

    def _bulk_submit(self, authority):
        queued = 0
        skipped = 0
        for move in self:
            if move.state != "posted":
                skipped += 1
                continue
            already = (
                (authority == "fbr" and move.fbr_status and move.fbr_status.lower() == "valid")
                or (authority == "pra" and move.pra_status and move.pra_status.lower() == "success")
            )
            if already:
                skipped += 1
                continue
            self.env["fbr.queue"]._add_to_queue(move, authority)
            queued += 1
        self.env["fbr.queue"]._process_queue(authority, limit=queued or 1)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Pakistan Compliance",
                "message": f"Queued {queued} invoice(s) for {authority.upper()}, skipped {skipped}.",
                "sticky": False,
            },
        }

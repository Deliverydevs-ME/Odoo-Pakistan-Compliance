# -*- coding: utf-8 -*-
import logging

import requests

from odoo import fields, models
from odoo.fields import Command

from ..pakistan_tax_reference import PROVINCES, SALES_PURCHASE_TAXES, WITHHOLDING_TAXES

_logger = logging.getLogger(__name__)

PRA_SANDBOX_URL = "https://ims.pral.com.pk/ims/sandbox/api/Live/PostData"
PRA_PRODUCTION_URL = "https://ims.pral.com.pk/ims/production/api/Live/PostData"
PRA_SANDBOX_TOKEN = "24d8fab3-f2e9-398f-ae17-b387125ec4a2"
FBR_PROVINCES_URL = "https://gw.fbr.gov.pk/pdi/v1/provinces"


class ResCompany(models.Model):
    _inherit = "res.company"

    # ---- FBR (federal) ----
    fbr_enabled = fields.Boolean(
        string="FBR Enabled",
        help="Turn this on to enforce FBR validations on Customer Invoice and "
        "POS Invoice submissions for this company.",
    )
    fbr_mode = fields.Selection(
        [("sandbox", "Sandbox Testing"), ("production", "Production")],
        string="FBR Mode",
        default="sandbox",
        help="Make sure the API endpoint matches the selected mode.",
    )
    fbr_api_endpoint = fields.Char(
        string="FBR API Endpoint",
        help="FBR API endpoint used when posting this company's invoices.",
    )
    fbr_authorization_token = fields.Char(
        string="FBR Authorization Token",
        groups="pk_fbr_pra_e_invoicing.group_pakistan_compliance_manager",
    )
    fbr_province_id = fields.Many2one(
        "res.country.state",
        string="FBR Seller Province",
        domain="[('country_id.code', '=', 'PK')]",
    )
    fbr_stats_html = fields.Html(string="FBR Stats", compute="_compute_fbr_stats_html")

    # ---- PRA (Punjab Revenue Authority) ----
    pra_enabled = fields.Boolean(
        string="PRA Enabled",
        help="Turn this on to enforce PRA validations and auto-report Customer "
        "Invoices for this company.",
    )
    pra_mode = fields.Selection(
        [("sandbox", "Sandbox Testing"), ("production", "Production")],
        string="PRA Mode",
        default="sandbox",
        help="Sandbox and Production both post to fixed PRA endpoints; only the "
        "POS ID/token differ.",
    )
    pra_pos_id = fields.Char(
        string="PRA POS ID", help="POS Registration Number given by PRA on registration."
    )
    pra_access_token = fields.Char(
        string="PRA Access Token",
        groups="pk_fbr_pra_e_invoicing.group_pakistan_compliance_manager",
        help="Bearer token for the PRA IMS API. Leave blank in Sandbox mode to use "
        "the shared sandbox token from PRA's manual; required in Production "
        "(unique per POS ID, found on the POS Details tab).",
    )
    pra_province_id = fields.Many2one(
        "res.country.state",
        string="PRA Tax Province",
        domain="[('country_id.code', '=', 'PK')]",
        help='"Post to PRA" only appears on invoices whose buyer province matches '
        "this value. Defaults to Punjab.",
    )

    def write(self, vals):
        result = super().write(vals)
        if {"account_fiscal_country_id", "fbr_enabled", "pra_enabled"} & set(vals):
            for company in self:
                company._setup_pakistan_tax_accounts_and_templates()
        return result

    def _compute_fbr_stats_html(self):
        Move = self.env["account.move"]
        for company in self:
            valid = Move.search_count(
                [
                    ("company_id", "=", company.id),
                    ("move_type", "=", "out_invoice"),
                    ("fbr_status", "=", "Valid"),
                ]
            )
            submitted = Move.search_count(
                [
                    ("company_id", "=", company.id),
                    ("move_type", "=", "out_invoice"),
                    ("state", "=", "posted"),
                    ("fbr_submit_to_fbr", "=", True),
                ]
            )
            company.fbr_stats_html = (
                f"<div><b>FBR Valid:</b> {valid} &nbsp; "
                f"<b>Submitted:</b> {submitted}</div>"
            )

    def action_check_fbr_api_status(self):
        self.ensure_one()
        try:
            resp = requests.get(FBR_PROVINCES_URL, timeout=(5, 10))
            message = f"HTTP {resp.status_code} in {resp.elapsed.total_seconds() * 1000:.0f}ms"
        except requests.RequestException as exc:
            message = f"Unreachable: {exc}"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": "FBR API Status", "message": message, "sticky": False},
        }

    def action_setup_pakistan_tax_accounts(self):
        for company in self:
            company._setup_pakistan_tax_accounts_and_templates()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Pakistan Compliance",
                "message": "Tax accounts, item tax templates, fiscal positions and "
                "withholding masters are up to date.",
                "sticky": False,
            },
        }

    def action_sync_pra_pct_codes(self):
        self.ensure_one()
        try:
            created = self.env["pra.pct.code"].sudo()._sync_from_fbr(self)
        except Exception as exc:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {"title": "PCT Code sync failed", "message": str(exc), "sticky": True},
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Pakistan Compliance",
                "message": f"PCT Code sync complete: {created} new code(s) added.",
                "sticky": False,
            },
        }

    def _get_pra_endpoint(self):
        self.ensure_one()
        return PRA_PRODUCTION_URL if self.pra_mode == "production" else PRA_SANDBOX_URL

    def _get_pra_token(self):
        self.ensure_one()
        if self.pra_access_token:
            return self.pra_access_token
        if self.pra_mode != "production":
            return PRA_SANDBOX_TOKEN
        return False


    # ------------------------------------------------------------------
    # Pakistan CoA / tax / withholding auto-setup
    #
    # Ported from coa_setup/overrides/company.py's
    # setup_pakistan_tax_accounts_and_item_templates, restructured for Odoo's
    # tax engine (see porting plan §7): instead of ERPNext's ~90-account tree
    # + "Item Tax Template" + "Sales/Purchase Taxes and Charges Template"
    # trio, this creates one GL account per province per sale/purchase side,
    # one account.tax per rate (all rates from the source data are kept --
    # see pakistan_tax_reference.py), and one account.fiscal.position per
    # province mapping no-tax to that province's standard rate.
    #
    # Idempotent/additive like the source: never deletes or renames existing
    # accounts/taxes, only creates what's missing. No year-stamping (plan
    # §7.6) -- one stable set of records, not recreated annually.
    # ------------------------------------------------------------------
    def _setup_pakistan_tax_accounts_and_templates(self):
        self.ensure_one()
        if (self.account_fiscal_country_id.code or "").upper() != "PK":
            return
        if not (self.account_sale_tax_id or self.chart_template or self._existing_accounts_ready()):
            # Mirrors _core_erpnext_accounts_ready: don't run before the
            # base l10n_pk Chart of Accounts has actually been installed.
            return

        province_accounts = self._ensure_province_tax_accounts()
        taxes_by_title = self._ensure_pakistan_taxes(province_accounts)
        self._ensure_province_fiscal_positions(taxes_by_title)
        self._ensure_withholding_taxes()

    def _existing_accounts_ready(self):
        self.ensure_one()
        Account = self.env["account.account"].with_company(self)
        return bool(
            Account.search_count(
                [("company_ids", "in", self.id), ("account_type", "=", "income")], limit=1
            )
        )

    def _get_or_create_account(self, code, name, account_type):
        self.ensure_one()
        Account = self.env["account.account"].with_company(self)
        existing = Account.search(
            [("name", "=", name), ("company_ids", "in", self.id)], limit=1
        )
        if existing:
            return existing
        return Account.create(
            {
                "code": code,
                "name": name,
                "account_type": account_type,
                "company_ids": [Command.link(self.id)],
            }
        )

    def _ensure_province_tax_accounts(self):
        """One liability (sales) + one asset (purchase) account per province,
        plus a generic pair for province-less rates. Returns {key: account}."""
        self.ensure_one()
        accounts = {}
        base_code = 220000
        for idx, (key, label) in enumerate([("GENERIC", "Pakistan")] + PROVINCES):
            sale_code = str(base_code + idx * 2)
            purchase_code = str(base_code + idx * 2 + 1)
            accounts[(key, "sale")] = self._get_or_create_account(
                sale_code, f"{label} Sales Tax Payable", "liability_current"
            )
            accounts[(key, "purchase")] = self._get_or_create_account(
                purchase_code, f"{label} Purchase Tax Receivable", "asset_current"
            )
        return accounts

    def _get_or_create_tax_group(self):
        self.ensure_one()
        TaxGroup = self.env["account.tax.group"].with_company(self)
        group = TaxGroup.search([("name", "=", "Pakistan Compliance"), ("company_id", "=", self.id)], limit=1)
        if not group:
            group = TaxGroup.create({"name": "Pakistan Compliance", "company_id": self.id})
        return group

    def _ensure_pakistan_taxes(self, province_accounts):
        self.ensure_one()
        Tax = self.env["account.tax"].with_company(self)
        tax_group = self._get_or_create_tax_group()
        by_title = {}
        for title, rate, type_tax_use, province_key, _is_standard in SALES_PURCHASE_TAXES:
            existing = Tax.search(
                [("name", "=", title), ("company_id", "=", self.id), ("type_tax_use", "=", type_tax_use)],
                limit=1,
            )
            if existing:
                by_title[(title, type_tax_use)] = existing
                continue
            account = province_accounts.get((province_key or "GENERIC", type_tax_use))
            tax = Tax.create(self._tax_create_vals(title, rate, type_tax_use, account, tax_group))
            by_title[(title, type_tax_use)] = tax
        return by_title

    def _tax_create_vals(self, title, rate, type_tax_use, account, tax_group):
        tax_line = {"factor_percent": 100, "repartition_type": "tax"}
        if account:
            tax_line["account_id"] = account.id
        return {
            "name": title,
            "amount": rate,
            "amount_type": "percent",
            "type_tax_use": type_tax_use,
            "company_id": self.id,
            "tax_group_id": tax_group.id,
            "invoice_repartition_line_ids": [
                Command.create({"factor_percent": 100, "repartition_type": "base"}),
                Command.create(tax_line),
            ],
            "refund_repartition_line_ids": [
                Command.create({"factor_percent": 100, "repartition_type": "base"}),
                Command.create(dict(tax_line)),
            ],
        }

    def _ensure_province_fiscal_positions(self, taxes_by_title):
        """One fiscal position per province, auto-applied via state_ids, that
        maps each province's standard-rate sale/purchase tax as the
        position's own tax -- lets Odoo auto-select the right province tax
        once the customer's state is set, without the user hunting through
        ~40 tax rates by hand."""
        self.ensure_one()
        FiscalPosition = self.env["account.fiscal.position"].with_company(self)
        standard_by_province = {
            (province_key, type_tax_use): taxes_by_title.get((title, type_tax_use))
            for title, rate, type_tax_use, province_key, is_standard in SALES_PURCHASE_TAXES
            if is_standard and province_key
        }
        # Generic (province-less) federal taxes act as the mapping *source* --
        # an account.fiscal.position.tax line swaps one tax for another, so it
        # needs both ends; these are the ones products are expected to carry
        # by default before a province-specific fiscal position remaps them.
        generic_source = {
            "sale": taxes_by_title.get(("FBR Standard GST 18%", "sale")),
            "purchase": taxes_by_title.get(("Standard Purchases Tax 18%", "purchase")),
        }
        for key, label in PROVINCES:
            state = self.env["res.country.state"].search(
                [("country_id.code", "=", "PK"), ("name", "=", label)], limit=1
            )
            if not state:
                continue
            existing = FiscalPosition.search(
                [("name", "=", f"{label} (FBR/PRA)"), ("company_id", "=", self.id)], limit=1
            )
            if existing:
                continue
            tax_ids_vals = []
            for type_tax_use in ("sale", "purchase"):
                province_tax = standard_by_province.get((key, type_tax_use))
                source_tax = generic_source.get(type_tax_use)
                if province_tax and source_tax and province_tax != source_tax:
                    tax_ids_vals.append(Command.create({
                        "tax_src_id": source_tax.id,
                        "tax_dest_id": province_tax.id,
                    }))
            FiscalPosition.create(
                {
                    "name": f"{label} (FBR/PRA)",
                    "company_id": self.id,
                    "country_id": self.env.ref("base.pk").id,
                    "state_ids": [Command.link(state.id)],
                    "auto_apply": True,
                    "tax_ids": tax_ids_vals,
                }
            )

    def _ensure_withholding_taxes(self):
        self.ensure_one()
        Tax = self.env["account.tax"].with_company(self)
        tax_group = self._get_or_create_tax_group()
        wh_payable = self._get_or_create_account(
            "220900", "Withholding Tax Payable (Sales)", "liability_current"
        )
        wh_receivable = self._get_or_create_account(
            "220901", "Withholding Tax Receivable (Purchases)", "asset_current"
        )
        for title, rate, type_tax_use in WITHHOLDING_TAXES:
            existing = Tax.search(
                [("name", "=", title), ("company_id", "=", self.id), ("type_tax_use", "=", type_tax_use)],
                limit=1,
            )
            if existing:
                continue
            account = wh_payable if type_tax_use == "sale" else wh_receivable
            Tax.create(self._tax_create_vals(title, rate, type_tax_use, account, tax_group))

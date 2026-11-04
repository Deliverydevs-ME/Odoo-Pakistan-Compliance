# -*- coding: utf-8 -*-
import logging

import requests

from odoo import fields, models

_logger = logging.getLogger(__name__)

FBR_ITEM_DESC_CODE_URL = "https://gw.fbr.gov.pk/pdi/v1/itemdesccode"


class PraPctCode(models.Model):
    _name = "pra.pct.code"
    _description = "PRA PCT Code (Pakistan Customs Tariff)"
    _order = "code_number"
    _rec_name = "display_name"

    code_number = fields.Char(required=True, index=True)
    description = fields.Text()
    display_name = fields.Char(compute="_compute_display_name", store=True)

    _sql_constraints = [
        ("code_number_uniq", "unique(code_number)", "PCT Code must be unique."),
    ]

    def _compute_display_name(self):
        for rec in self:
            desc = (rec.description or "")[:60]
            rec.display_name = f"{rec.code_number} - {desc}" if desc else rec.code_number

    def _sync_from_fbr(self, company=None):
        """Pulls the full PCT/HS code reference list from FBR's public master
        data API and idempotently creates whatever's missing (same endpoint
        FBR uses for its own HS Code master data -- PCT and HS are the same
        national classification scheme, per the source app's own comments).
        Never updates/deletes existing rows, only adds new ones."""
        company = company or self.env.company
        token = company.fbr_authorization_token
        if not token:
            raise ValueError("No FBR Authorization Token configured on this company -- "
                              "the PCT/HS code master data endpoint requires one.")

        resp = requests.get(
            FBR_ITEM_DESC_CODE_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=(10, 60),
        )
        resp.raise_for_status()
        entries = resp.json()

        existing_codes = set(self.search([]).mapped("code_number"))
        to_create = [
            {"code_number": e["hS_CODE"], "description": e.get("description")}
            for e in entries
            if e.get("hS_CODE") and e["hS_CODE"] not in existing_codes
        ]
        # de-dupe within the batch itself (the source list can repeat a code)
        seen = set()
        deduped = []
        for vals in to_create:
            if vals["code_number"] in seen:
                continue
            seen.add(vals["code_number"])
            deduped.append(vals)

        if deduped:
            self.create(deduped)
        _logger.info("PRA PCT Code sync: %s fetched, %s new created, %s already present",
                     len(entries), len(deduped), len(existing_codes))
        return len(deduped)

# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FbrLog(models.Model):
    _name = "fbr.log"
    _description = "FBR/PRA Submission Log"
    _order = "submitted_at desc, id desc"
    _rec_name = "display_name"

    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    authority = fields.Selection([("fbr", "FBR"), ("pra", "PRA")], required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    document_invoice_number = fields.Char(string="Authority Invoice Number")
    status = fields.Selection(
        [
            ("success", "Success"),
            ("invalid", "Invalid"),
            ("error", "Error"),
            ("timeout", "Timeout"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
    )
    submitted_at = fields.Datetime(required=True, default=fields.Datetime.now)
    processing_time_ms = fields.Float(string="Processing Time (ms)")
    request_payload = fields.Text()
    response_data = fields.Text()
    response_status_code = fields.Char(string="HTTP Status Code")
    validation_errors = fields.Text()
    api_version = fields.Char()
    retry_attempt = fields.Integer(default=0)

    display_name = fields.Char(compute="_compute_display_name")

    @api.depends("res_model", "res_id", "authority", "status")
    def _compute_display_name(self):
        for log in self:
            log.display_name = f"[{log.authority.upper()}] {log.res_model}#{log.res_id} - {log.status}"

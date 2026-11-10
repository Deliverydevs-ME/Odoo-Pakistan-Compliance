# -*- coding: utf-8 -*-
import json
import logging
import time

import requests
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 5
STUCK_PROCESSING_TIMEOUT_MINUTES = 30
RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429}
NON_RETRYABLE_HTTP_STATUS_CODES = {400, 422}
NON_RETRYABLE_FAILURE_TYPES = {"payload_error", "business_invalid", "http_validation_error"}


class FbrQueue(models.Model):
    _name = "fbr.queue"
    _description = "FBR/PRA Submission Queue"
    _order = "create_date asc, id asc"
    _rec_name = "display_name"

    res_model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    authority = fields.Selection([("fbr", "FBR"), ("pra", "PRA")], required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    status = fields.Selection(
        [("pending", "Pending"), ("processing", "Processing"), ("failed", "Failed")],
        default="pending",
        required=True,
        index=True,
    )
    retry_count = fields.Integer(default=0)
    remaining_retries = fields.Integer(default=DEFAULT_MAX_RETRIES)
    error_message = fields.Text()
    response_text = fields.Text()
    created_at = fields.Datetime(default=fields.Datetime.now)
    last_retry_at = fields.Datetime()
    completed_at = fields.Datetime()
    next_retry_at = fields.Datetime(default=fields.Datetime.now)

    display_name = fields.Char(compute="_compute_display_name")

    _sql_constraints = [
        (
            "unique_doc_authority",
            "unique(res_model, res_id, authority)",
            "A queue entry already exists for this document and authority.",
        ),
    ]

    @api.depends("res_model", "res_id", "authority", "status")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.authority.upper()}] {rec.res_model}#{rec.res_id} ({rec.status})"

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------
    def _add_to_queue(self, record, authority, force_immediate=False):
        """Mirrors add_to_queue: guards the record is postable/not already
        successful, creates or revives a queue row, then kicks processing.

        Runs the queue/log bookkeeping as sudo -- these are system-managed
        audit/retry records, not user data entry, so write access to them
        shouldn't depend on which user happened to click the button (mirrors
        the source app's own ignore_permissions=True on these writes)."""
        self = self.sudo()
        if record.state != "posted":
            raise UserError("Only posted invoices can be submitted.")

        existing = self.search(
            [
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
                ("authority", "=", authority),
            ],
            limit=1,
        )
        if existing:
            if existing.status == "failed":
                existing.write(
                    {
                        "status": "pending",
                        "next_retry_at": fields.Datetime.now(),
                        "error_message": False,
                    }
                )
            # pending/processing: leave as-is, just make sure the queue gets kicked
        else:
            self.create(
                {
                    "res_model": record._name,
                    "res_id": record.id,
                    "authority": authority,
                    "company_id": record.company_id.id,
                    "status": "pending",
                    "next_retry_at": fields.Datetime.now(),
                }
            )

        if force_immediate:
            # Process synchronously, in this same request/transaction. Simpler
            # and far more reliable than deferring to a post-commit callback
            # on a separate cursor -- this IS the "submit now" button, there's
            # nothing else in this transaction worth isolating it from.
            self._process_queue(authority, limit=50)

    # ------------------------------------------------------------------
    # Scheduled entry point
    # ------------------------------------------------------------------
    def _cron_process_queues(self):
        self = self.sudo()
        for authority in ("fbr", "pra"):
            self._recover_stuck_and_retryable(authority)
            self._process_queue(authority, limit=1)

    def _recover_stuck_and_retryable(self, authority):
        stuck_cutoff = fields.Datetime.now() - relativedelta(
            minutes=STUCK_PROCESSING_TIMEOUT_MINUTES
        )
        stuck = self.search(
            [
                ("authority", "=", authority),
                ("status", "=", "processing"),
                ("write_date", "<", stuck_cutoff),
            ]
        )
        for rec in stuck:
            rec._mark_retry_or_terminal(
                "Recovered from a stuck Processing state after "
                f"{STUCK_PROCESSING_TIMEOUT_MINUTES} minutes.",
                retryable=True,
            )

        now = fields.Datetime.now()
        due = self.search(
            [
                ("authority", "=", authority),
                ("status", "=", "failed"),
                ("next_retry_at", "!=", False),
                ("next_retry_at", "<=", now),
                ("retry_count", "<", DEFAULT_MAX_RETRIES),
            ]
        )
        due.write({"status": "pending"})

        terminal = self.search(
            [
                ("authority", "=", authority),
                ("status", "=", "failed"),
                ("retry_count", ">=", DEFAULT_MAX_RETRIES),
            ]
        )
        terminal.unlink()

    # ------------------------------------------------------------------
    # Single-flight sequential processing
    # ------------------------------------------------------------------
    def _has_processing(self, authority):
        return bool(self.search_count([("authority", "=", authority), ("status", "=", "processing")]))

    def _claim_next(self, authority):
        self.env.cr.execute(
            """
            SELECT id FROM fbr_queue
            WHERE authority = %s AND status = 'pending'
              AND (next_retry_at IS NULL OR next_retry_at <= now())
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (authority,),
        )
        row = self.env.cr.fetchone()
        if not row:
            return self.browse()
        rec = self.browse(row[0])
        rec.write({"status": "processing", "last_retry_at": fields.Datetime.now()})
        self.env.cr.commit()
        return rec

    def _process_queue(self, authority, limit=50):
        processed = 0
        while processed < limit:
            if self._has_processing(authority):
                break
            item = self._claim_next(authority)
            if not item:
                break
            item._process_item()
            processed += 1

    def _process_item(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists() or record.state != "posted":
            self.env["fbr.log"].create(
                {
                    "res_model": self.res_model,
                    "res_id": self.res_id,
                    "authority": self.authority,
                    "company_id": self.company_id.id,
                    "status": "error",
                    "validation_errors": "Document is no longer posted; submission skipped.",
                }
            )
            self.unlink()
            self.env.cr.commit()
            return

        start = time.monotonic()
        try:
            payload = (
                record._build_fbr_payload() if self.authority == "fbr" else record._build_pra_payload()
            )
        except Exception as exc:
            self._log_result(record, "invalid", message=str(exc))
            self._persist_failure_text(record, "Invalid", str(exc))
            self._post_chatter_message(record, "Invalid (could not build payload)", text=str(exc))
            self._mark_retry_or_terminal(str(exc), retryable=False, failure_type="payload_error")
            self.env.cr.commit()
            return

        outcome = self._submit(record, payload)
        processing_ms = (time.monotonic() - start) * 1000

        response_text = self._outcome_response_text(outcome)
        self._log_result(
            record,
            outcome["log_status"],
            payload=payload,
            response=outcome.get("response_json"),
            raw_text=outcome.get("raw_text"),
            http_status=outcome.get("http_status"),
            invoice_number=outcome.get("invoice_number"),
            message=outcome.get("message"),
            processing_ms=processing_ms,
        )

        if outcome["success"]:
            self._persist_success(record, outcome)
            self._post_chatter_message(
                record, "Valid" if self.authority == "fbr" else "Success",
                invoice_number=outcome.get("invoice_number"), text=response_text,
            )
            self.unlink()
        elif not outcome["retryable"] or outcome.get("failure_type") in NON_RETRYABLE_FAILURE_TYPES:
            self._persist_failure(record, outcome)
            self._post_chatter_message(record, "Invalid", text=response_text)
            self.unlink()
        else:
            self._persist_failure(record, outcome)
            self._post_chatter_message(record, "Error (will retry)", text=response_text)
            self._mark_retry_or_terminal(
                outcome.get("message"), retryable=True, failure_type=outcome.get("failure_type")
            )
        self.env.cr.commit()

    def _mark_retry_or_terminal(self, message, retryable=True, failure_type=None):
        self.ensure_one()
        retry_count = self.retry_count + 1
        remaining = max(0, DEFAULT_MAX_RETRIES - retry_count)
        if not retryable or remaining <= 0:
            self.unlink()
            return
        self.write(
            {
                "status": "failed",
                "retry_count": retry_count,
                "remaining_retries": remaining,
                "error_message": message,
                "next_retry_at": fields.Datetime.now(),
            }
        )

    # ------------------------------------------------------------------
    # HTTP submission + response classification
    # ------------------------------------------------------------------
    def _submit(self, record, payload):
        company = record.company_id
        if self.authority == "fbr":
            url = company.fbr_api_endpoint
            token = company.fbr_authorization_token
        else:
            url = company._get_pra_endpoint()
            token = company._get_pra_token()

        if not url or not token:
            return {
                "success": False,
                "retryable": True,
                "failure_type": "config_error",
                "log_status": "error",
                "message": "FBR/PRA endpoint or token is not configured.",
            }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Document-Model": self.res_model,
            "X-Document-Id": str(self.res_id),
            "X-Client": "Odoo Pakistan Compliance",
            "X-Retry": "1" if self.retry_count else "0",
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=(10, 30), verify=True)
        except requests.RequestException as exc:
            return {
                "success": False,
                "retryable": True,
                "failure_type": "network_error",
                "log_status": "error",
                "message": str(exc),
            }

        raw_text = resp.text
        try:
            resp_json = resp.json()
        except ValueError:
            resp_json = None

        if resp.status_code >= 400:
            failure_type = (
                "http_validation_error"
                if resp.status_code in NON_RETRYABLE_HTTP_STATUS_CODES
                else "http_error"
            )
            retryable = resp.status_code not in NON_RETRYABLE_HTTP_STATUS_CODES
            return {
                "success": False,
                "retryable": retryable,
                "failure_type": failure_type,
                "log_status": "invalid" if not retryable else "error",
                "message": f"HTTP {resp.status_code}: {raw_text[:500]}",
                "http_status": resp.status_code,
                "response_json": resp_json,
                "raw_text": raw_text,
            }

        if self.authority == "fbr":
            return self._classify_fbr_response(resp.status_code, resp_json, raw_text)
        return self._classify_pra_response(resp.status_code, resp_json, raw_text)

    def _classify_fbr_response(self, http_status, resp_json, raw_text=None):
        if resp_json is None:
            return {
                "success": False,
                "retryable": False,
                "failure_type": "business_invalid",
                "log_status": "invalid",
                "message": f"FBR returned a non-JSON response (HTTP {http_status}): "
                            f"{(raw_text or '')[:1000]}",
                "http_status": http_status,
                "response_json": None,
                "raw_text": raw_text,
            }
        validation = (resp_json or {}).get("validationResponse") or {}
        status = (validation.get("status") or "").lower()
        success = status == "valid"
        return {
            "success": success,
            "retryable": False,
            "failure_type": None if success else "business_invalid",
            "log_status": "success" if success else "invalid",
            "message": validation.get("error"),
            "invoice_number": (resp_json or {}).get("invoiceNumber") if success else None,
            "http_status": http_status,
            "response_json": resp_json,
            "raw_text": raw_text,
        }

    def _classify_pra_response(self, http_status, resp_json, raw_text=None):
        if resp_json is None:
            return {
                "success": False,
                "retryable": False,
                "failure_type": "business_invalid",
                "log_status": "invalid",
                "message": f"PRA returned a non-JSON response (HTTP {http_status}): "
                            f"{(raw_text or '')[:1000]}",
                "http_status": http_status,
                "response_json": None,
                "raw_text": raw_text,
            }
        code = str((resp_json or {}).get("Code"))
        success = code == "100"
        invoice_number = (resp_json or {}).get("InvoiceNumber") if success else None
        return {
            "success": success,
            "retryable": False,
            "failure_type": None if success else "business_invalid",
            "log_status": "success" if success else "invalid",
            "message": (resp_json or {}).get("Response") or (resp_json or {}).get("Errors"),
            "invoice_number": invoice_number,
            "http_status": http_status,
            "response_json": resp_json,
            "raw_text": raw_text,
        }

    # ------------------------------------------------------------------
    # Persisting results
    # ------------------------------------------------------------------
    def _outcome_response_text(self, outcome):
        """The single source of truth for 'what do we show as the response
        text' -- prefers parsed JSON, falls back to the raw response body
        when FBR/PRA didn't return valid JSON, falls back to the error
        message as a last resort (e.g. network errors have no body at all)."""
        if outcome.get("response_json"):
            return json.dumps(outcome["response_json"], indent=2)
        if outcome.get("raw_text"):
            return outcome["raw_text"]
        return outcome.get("message") or ""

    def _persist_success(self, record, outcome):
        now = fields.Datetime.now()
        response_text = self._outcome_response_text(outcome)
        if self.authority == "fbr":
            record.write(
                {
                    "fbr_invoice_number": outcome.get("invoice_number"),
                    "fbr_datetime": now,
                    "fbr_status": "Valid",
                    "fbr_response": response_text,
                }
            )
        else:
            record.write(
                {
                    "pra_invoice_number": outcome.get("invoice_number"),
                    "pra_datetime": now,
                    "pra_status": "Success",
                    "pra_response": response_text,
                }
            )

    def _persist_failure(self, record, outcome):
        response_text = self._outcome_response_text(outcome)
        self._persist_failure_text(
            record, "Invalid" if not outcome["retryable"] else "Error", response_text
        )
        self.write({"error_message": outcome.get("message"), "response_text": response_text})

    def _persist_failure_text(self, record, status_label, response_text):
        if self.authority == "fbr":
            record.write({"fbr_status": status_label, "fbr_response": response_text})
        else:
            record.write({"pra_status": status_label, "pra_response": response_text})

    def _post_chatter_message(self, record, status_label, invoice_number=None, text=None):
        import html as _html
        authority_label = self.authority.upper()
        parts = [f"<b>{authority_label} submission result:</b> {_html.escape(status_label)}"]
        if invoice_number:
            parts.append(f"<b>{authority_label} Invoice Number:</b> {_html.escape(str(invoice_number))}")
        if text:
            safe = _html.escape(text[:8000])
            parts.append(f"<pre style='white-space:pre-wrap'>{safe}</pre>")
        record.message_post(body="<br/>".join(parts), body_is_html=True)

    def _log_result(
        self,
        record,
        status,
        payload=None,
        response=None,
        raw_text=None,
        http_status=None,
        invoice_number=None,
        message=None,
        processing_ms=None,
    ):
        response_data = json.dumps(response, indent=2) if response else (raw_text or False)
        self.env["fbr.log"].create(
            {
                "res_model": self.res_model,
                "res_id": self.res_id,
                "authority": self.authority,
                "company_id": self.company_id.id,
                "document_invoice_number": invoice_number,
                "status": status,
                "submitted_at": fields.Datetime.now(),
                "processing_time_ms": processing_ms or 0.0,
                "request_payload": json.dumps(payload, indent=2) if payload else False,
                "response_data": response_data,
                "response_status_code": str(http_status) if http_status else False,
                "validation_errors": message,
                "retry_attempt": self.retry_count,
            }
        )

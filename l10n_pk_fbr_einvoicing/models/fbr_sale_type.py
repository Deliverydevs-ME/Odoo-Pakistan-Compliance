# -*- coding: utf-8 -*-
from odoo import fields, models

# Sale-type labels that FBR's sandbox scenario resolution remaps to a
# canonical string in the submission payload, keyed by scenario_id.
SCENARIO_LABEL_REMAP = {
    "SN001": "Goods at standard rate (default)",
    "SN002": "Goods at standard rate (default)",
    "SN026": "Goods at standard rate (default)",
    "SN005": "Goods at Reduced Rate",
    "SN028": "Goods at Reduced Rate",
    "SN008": "3rd Schedule Goods",
    "SN027": "3rd Schedule Goods",
}


class FbrSaleType(models.Model):
    _name = "fbr.sale.type"
    _description = "FBR Sale Type (scenario)"
    _order = "scenario_id"

    name = fields.Char(required=True)
    scenario_id = fields.Char(required=True, index=True)

    _sql_constraints = [
        ("scenario_id_uniq", "unique(scenario_id)", "Scenario ID must be unique."),
    ]

    def _payload_sale_type_label(self):
        self.ensure_one()
        return SCENARIO_LABEL_REMAP.get(self.scenario_id, self.name)

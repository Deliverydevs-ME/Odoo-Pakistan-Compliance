from . import models


def post_init_hook(env):
    """Run Pakistan CoA/tax/withholding setup for any Pakistani companies
    that already exist at install time (mirrors the source app's
    after_install / after_sync behaviour)."""
    companies = env["res.company"].search([("account_fiscal_country_id.code", "=", "PK")])
    for company in companies:
        company._setup_pakistan_tax_accounts_and_templates()

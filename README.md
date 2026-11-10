# Pakistan Compliance

Odoo 18 addon implementing Pakistan tax e-invoicing compliance:

- **FBR** (Federal Board of Revenue) digital invoicing — Customer Invoices and Point of Sale
- **PRA** (Punjab Revenue Authority) e-invoicing (IMS) — Customer Invoices

Ported from the ERPNext "Pak Compliance" app (`fbr_e_invoicing`), adapted to Odoo's
accounting/tax model rather than a line-by-line translation — see the module's own
code comments for where and why the Odoo implementation diverges from the ERPNext
source (e.g. a shared single-flight retry queue for both authorities, fiscal
positions instead of ERPNext's tax-charge templates, Odoo's native `res.country.state`
for provinces instead of a custom master list).

## What it does

- Per-company FBR/PRA configuration (sandbox/production mode, endpoint, token, province)
- Required-field validation before an invoice can be posted (seller/buyer province,
  company Tax ID, per-line HS Code, tax, and FBR Sale Type)
- Builds and submits the FBR/PRA JSON payload, classifies the response
  (HTTP success is not the same as business acceptance), and persists the result
  onto the invoice plus a full audit trail
- A sequential, single-flight retry queue (max 5 attempts, no backoff) shared by
  both FBR and PRA submissions
- Automatic Pakistan Chart-of-Accounts / tax-rate / fiscal-position / withholding-tax
  setup for Pakistani companies, built on top of Odoo's own `l10n_pk` base localization
- POS-originated invoices auto-submit to FBR on posting; regular Customer Invoices
  are submitted manually (single or bulk) — matching the source app's own behavior
- A PCT Code master-data model, synced from FBR's public reference API, used for
  PRA submissions (PRA requires a stricter pure-digit code format than FBR's HS Code)
- QR-code print reports for both FBR and PRA once an invoice is successfully submitted

## Installation

```bash
# Copy (or clone) this module into your Odoo addons path
cp -r pk_fbr_pra_e_invoicing /path/to/custom-addons/

# Install — depends on account, l10n_pk, and point_of_sale
odoo -d <your-database> -i pk_fbr_pra_e_invoicing --stop-after-init
```

After install, configure each Pakistani company under
**Settings → Users & Companies → Companies → (your company) → FBR / ePRA tabs**:
mode (sandbox/production), API endpoint, authorization token, and province.

## Compatibility

Targets Odoo 18.0 (Enterprise or Community — only standard `account`, `l10n_pk`,
and `point_of_sale` are required).

## License

LGPL-3. See [LICENSE](LICENSE).

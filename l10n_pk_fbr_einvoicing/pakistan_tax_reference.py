# -*- coding: utf-8 -*-
"""Reference data ported from the source ERPNext app's
data/item_tax_template_defaults.json and data/tax_withholding_defaults.json
(both branches agree on this data; only version-16 wires up the withholding
half). Kept as plain Python (not XML/CSV data files) because these records
must be created per-company by an idempotent "ensure" method, not loaded
once by the ORM's XML data loader -- mirrors the source's own create-only,
non-destructive ensure_* functions in coa_setup/overrides/company.py.
"""

# (key, label) -- matches the source's Tax Category / province naming.
PROVINCES = [
    ("PUNJAB", "Punjab"),
    ("SINDH", "Sindh"),
    ("KYBER PAKHTUNKHWA", "Khyber Pakhtunkhwa"),
    ("BALOCHISTAN", "Balochistan"),
    ("AZAD JAMMU AND KASHMIR", "Azad Jammu and Kashmir"),
    ("CAPITAL TERRITORY", "Islamabad Capital Territory"),
]

# (title, rate, type_tax_use, province_key or None, is_standard_rate)
# is_standard_rate marks the one rate per province that the province's
# fiscal position auto-maps a generic tax to.
SALES_PURCHASE_TAXES = [
    ("Standard Sales Service Tax Sindh 13%", 13.0, "sale", "SINDH", True),
    ("Standard Sales Service Tax Balochistan 15%", 15.0, "sale", "BALOCHISTAN", True),
    ("Standard Sales Service Tax Khyber Pakhtunkhwa 15%", 15.0, "sale", "KYBER PAKHTUNKHWA", True),
    ("Standard Sales Service Tax Azad Jammu and Kashmir 16%", 16.0, "sale", "AZAD JAMMU AND KASHMIR", True),
    ("Standard Sales Service Tax Islamabad Capital Territory 16%", 16.0, "sale", "CAPITAL TERRITORY", True),
    ("Standard Sales Service Tax Punjab 16%", 16.0, "sale", "PUNJAB", True),
    ("Sales Tax Telecommunication Services 19.5%", 19.5, "sale", None, False),
    ("Standard Sales Tax 17%", 17.0, "sale", None, False),
    ("Sales Service Tax 0% Sindh", 0.0, "sale", "SINDH", False),
    ("Sales Service Tax 1% Sindh", 1.0, "sale", "SINDH", False),
    ("Sales Service Tax 2% Sindh", 2.0, "sale", "SINDH", False),
    ("Sales Service Tax 3% Sindh", 3.0, "sale", "SINDH", False),
    ("Sales Service Tax 5% Sindh", 5.0, "sale", "SINDH", False),
    ("Sales Service Tax 8% Sindh", 8.0, "sale", "SINDH", False),
    ("Sales Service Tax 10% Sindh", 10.0, "sale", "SINDH", False),
    ("Sales Service Tax 13% Sindh", 13.0, "sale", "SINDH", False),
    ("Sales Service Tax 15% Sindh", 15.0, "sale", "SINDH", False),
    ("Sales Service Tax 16% Sindh", 16.0, "sale", "SINDH", False),
    ("Sales Service Tax 17% Sindh", 17.0, "sale", "SINDH", False),
    ("Standard Purchases Service Tax Azad Jammu and Kashmir 16%", 16.0, "purchase", "AZAD JAMMU AND KASHMIR", True),
    ("Standard Purchases Service Tax Balochistan 15%", 15.0, "purchase", "BALOCHISTAN", True),
    ("Standard Purchases Tax 17%", 17.0, "purchase", None, False),
    ("Purchases Tax Telecommunication Services 19.5%", 19.5, "purchase", None, False),
    ("Standard Purchases Service Tax Islamabad Capital Territory 16%", 16.0, "purchase", "CAPITAL TERRITORY", True),
    ("Standard Purchases Service Tax Khyber Pakhtunkhwa 15%", 15.0, "purchase", "KYBER PAKHTUNKHWA", True),
    ("Standard Purchases Service Tax Punjab 16%", 16.0, "purchase", "PUNJAB", True),
    ("Purchases Service Tax 0% Sindh", 0.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 1% Sindh", 1.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 2% Sindh", 2.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 3% Sindh", 3.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 5% Sindh", 5.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 8% Sindh", 8.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 10% Sindh", 10.0, "purchase", "SINDH", False),
    ("Standard Purchases Service Tax Sindh 13%", 13.0, "purchase", "SINDH", True),
    ("Purchases Service Tax 13% Sindh", 13.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 15% Sindh", 15.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 16% Sindh", 16.0, "purchase", "SINDH", False),
    ("Purchases Service Tax 17% Sindh", 17.0, "purchase", "SINDH", False),
    ("FBR Standard GST 18%", 18.0, "sale", None, False),
    ("Standard Purchases Tax 18%", 18.0, "purchase", None, False),
]

# (title, rate, type_tax_use) -- fixed FY2025-26 rate window in the source;
# ported as plain taxes on dedicated withholding accounts (see plan §7.4 --
# Odoo/l10n_pk has no first-class withholding-tax UI to hook into instead).
WITHHOLDING_TAXES = [
    ("WH TAX - 1% (Sales)", 1.0, "sale"),
    ("WH TAX - 1.5% (Sales)", 1.5, "sale"),
    ("WH TAX - 4% (Sales)", 4.0, "sale"),
    ("WH TAX - 5% (Sales)", 5.0, "sale"),
    ("WH TAX - 5.5% (Sales)", 5.5, "sale"),
    ("WH TAX - 7.5% (Sales)", 7.5, "sale"),
    ("WH TAX - 8% (Sales)", 8.0, "sale"),
    ("WH TAX - 9% (Sales)", 9.0, "sale"),
    ("WH TAX - 10% (Sales)", 10.0, "sale"),
    ("WH TAX - 11% (Sales)", 11.0, "sale"),
    ("Withholding Tax - 1% (Purchases)", 1.0, "purchase"),
    ("Withholding Tax - 1.5% (Purchases)", 1.5, "purchase"),
    ("Withholding Tax - 2% (Purchases)", 2.0, "purchase"),
    ("Withholding Tax - 3.5% (Purchases)", 3.5, "purchase"),
    ("Withholding Tax - 4% (Purchases)", 4.0, "purchase"),
    ("Withholding Tax - 5% (Purchases)", 5.0, "purchase"),
    ("Withholding Tax - 5.5% (Purchases)", 5.5, "purchase"),
    ("Withholding Tax - 6% (Purchases)", 6.0, "purchase"),
    ("Withholding Tax - 7.5% (Purchases)", 7.5, "purchase"),
    ("Withholding Tax - 8% (Purchases)", 8.0, "purchase"),
    ("Withholding Tax - 9% (Purchases)", 9.0, "purchase"),
    ("Withholding Tax - 10% (Purchases)", 10.0, "purchase"),
    ("Withholding Tax - 11% (Purchases)", 11.0, "purchase"),
]

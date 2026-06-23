"""
Insert a case that is fully rule-valid (→ Accepted) but structurally unlike
anything in the Arabic historical dataset, so the novelty detector flags it as
novel_pattern. Lets you see the recommendation generated for an
accepted-but-novel case.
"""
import sqlite3

con = sqlite3.connect("data/cases.db")
con.execute("""
    INSERT OR REPLACE INTO incoming_cases
    (case_id, document_type, owner_name, owner_id, property_id, property_type,
     area_sqm, address, city, notarized, owner_signature, liens_present,
     registration_date, status)
    VALUES
    ('NOVEL-001', 'lease_contract', 'NEOM Green Hydrogen Company', '1056789432',
     'PRP-SOLAR-7781', 'land', 4500000, 'Plot 12, Energy Sector 4', 'NEOM',
     1, 1, 0, '2024-03-10', 'pending')
""")
con.commit()
con.close()
print("Inserted NOVEL-001 (rule-valid utility-scale property — should flag as novel_pattern)")

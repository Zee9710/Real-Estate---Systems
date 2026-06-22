import sqlite3

con = sqlite3.connect("data/cases.db")
con.execute("""
    INSERT OR REPLACE INTO incoming_cases
    (case_id, document_type, owner_name, property_type, area_sqm, address, city,
     notarized, owner_signature, liens_present, registration_date, source)
    VALUES
    ('TEST-001', 'sale_contract', 'Ahmed Al-Rashidi', 'apartment', 95.5,
     '123 King Fahd Rd', 'Riyadh', 1, 1, 0, '2022-01-15', 'incoming')
""")
con.commit()
con.close()
print("Inserted TEST-001")

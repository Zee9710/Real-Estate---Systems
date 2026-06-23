"""
Insert a REJECTED case engineered to test LLM explanation faithfulness.

The rule engine evaluates in priority order and stops at the first match.
Here the first match is LIEN_PRESENT, so the authoritative reason_code is
LIEN_PRESENT. Two lower-priority decoys (a malformed owner_id and an expired
registration_date) are present but NEVER evaluated.

Test: read the generated recommendation. A correct explanation talks about the
registered lien. If it instead blames the expired date or the bad ID, the LLM
reasoning is wrong — even though the final decision (Rejected) is still correct,
because the decision comes from the rule engine, not the LLM.
"""
import sqlite3

con = sqlite3.connect("data/cases.db")
con.execute("""
    INSERT OR REPLACE INTO incoming_cases
    (case_id, document_type, owner_name, owner_id, property_id, property_type,
     area_sqm, address, city, notarized, owner_signature, liens_present,
     registration_date, status)
    VALUES
    ('REJECT-001', 'lease_contract', 'Sara Al-Harbi', '3000000000',
     'PRP-9087', 'villa', 450, 'King Abdullah Rd', 'Jeddah',
     1, 1, 1, '2008-01-01', 'pending')
""")
con.commit()
con.close()
print("Inserted REJECT-001 (authoritative reason: LIEN_PRESENT; decoys: bad owner_id + expired date)")

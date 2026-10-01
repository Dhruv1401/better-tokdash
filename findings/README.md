# Findings directory

Classification scheme (per audit instructions):

- `confirmed/` — reproduced, clearly incorrect
- `likely/` — strong evidence, incomplete repro
- `testing-gaps/` — important invariant untested (incl. surviving mutations)
- `security/` — concrete attack path or meaningful exposure
- `performance/` — measured or demonstrated scalability issue
- `leads/` — unconfirmed hypotheses worth future work

Each finding gets `finding.md`, plus `reproducer/` and `evidence/` subdirs when applicable.
IDs: F-### (finding), T-### (testing gap), S-### (security), P-### (performance), L-### (lead).

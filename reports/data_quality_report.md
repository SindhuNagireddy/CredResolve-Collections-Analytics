# Data Quality Report

## Scope and approach

The raw files are retained as supplied. Cleaning is performed in reproducible transformations; rejected records should be retained with stable reason codes and source-row lineage. Counts below are based on the provided synthetic extract and the independent Python audit.

| Dataset | Rule | Action | Raw rows | Affected rows | Quantified impact |
|---|---|---:|---:|---:|---:|
| payments | Duplicate `payment_id` | Reject later duplicate rows | 25,500 | 500 | ₹25,901,961.69 in repeated successful amount |
| calls | Duplicate `call_id` | Reject later duplicate rows | 91,350 | 1,350 | Not directly monetized |
| whatsapp_events | Duplicate event ID | Reject later duplicate rows | 60,600 | 600 | Not directly monetized |
| borrowers | Repeated borrower IDs/version history | Select latest valid version; preserve history | 30,600 | 19,585 later/repeated rows by ID | Requires version-aware entity resolution |
| agents | Repeated agent IDs/version history | Select latest valid version; preserve history | 30,000 | 29,000 repeated rows by ID | Requires identity graph review |
| sms_events | Duplicate event ID | Investigate | 45,000 | 0 | No duplicate IDs detected |

## Timestamp findings

- Calls audited: 91,350.
- Calendar-month classification changes after IST conversion: 310 (0.34%).
- Hour classification changes after IST conversion: 60,865 (66.63%).
- This makes timezone normalization material for calling-hour analysis, even though month-level impact is smaller.

## Payment definition

- Raw successful amount: approximately ₹134.15 Cr.
- Deduplicated successful amount: approximately ₹131.56 Cr.
- Repeated successful amount removed: approximately ₹2.59 Cr.
- Recovery metric includes only deduplicated `SUCCESS` payment events. Pending, failed, and reversed amounts are excluded. Production reporting should reconcile payment status to actual settlement and reversal events.

## Interpretation and caveats

Duplicate amounts are a data-quality correction, not genuine additional recovery. Repeated borrower/agent IDs indicate versioning or duplication but do not by themselves define a safe cross-ID identity merge. The current DPD and risk segment are account snapshots, so historical segment analysis is approximate. Attribution audits based on targeting events are sensitivity checks only; they do not prove a delivered touch or causal impact.

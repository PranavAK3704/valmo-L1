# Hardstop Loss — 10 Sub-Scenarios

## What is a Hardstop Loss?
A shipment marked hardstop when it stays at a hub for more than 5 days (120 hours) without being connected to the next node. Captains contest this via Kapture tickets.

## Resolution Steps (All Scenarios)
1. Verify AWBs are correctly entered by captain
2. Check Metabase loss attribution query — confirms if hardstop loss is actually marked
3. Check Log10 / Single AWB tracking for detailed scan history
4. Cross-reference Hardstop SOP
5. Apply scenario-specific logic below

---

## Scenario 1.1: Loss marked – Captain claims connection – Scans valid – Hardstop SOP followed
- Agent checks scan data on Log10 and verifies Hardstop SOP was followed
- Since scans show valid connection AND SOP was followed → **escalate to L2 for reversal**
- Reply to captain: loss marked against these shipments will be reversed

## Scenario 1.2: Loss marked – Captain claims connection – Scans valid – Hardstop SOP NOT followed
- Agent checks scan data on Log10 and verifies Hardstop SOP was NOT followed
- **Close ticket, no reversal** — reply stating reversal not applicable due to Hardstop SOP breach

## Scenario 2: Loss marked – Captain claims connection – Scans invalid (wrong destination)
- Agent checks scan data on Log10 — scans show wrong destination connection
- **Close ticket, no reversal** — reply stating reversal not applicable due to wrong connection

## Scenario 3: Loss marked – Captain claims wrong loss – Fails to connect after Customer Rejection
- Check scans on Single AWB tracking or Log10
- If scans do NOT show a forward connection within RTO connection timeline → **no reversal**
- Reply: reversal not applicable

## Scenario 4: Loss marked – Captain claims wrong loss – Fails to connect after Customer Unreachable
- Check scans on Log10
- If shipment not delivered within 7 days as per scans → **no reversal**
- Reply: reversal not applicable

## Scenario 5: Loss marked – Captain claims wrong loss – Customer denies cancellation OTP
- Check scans on Log10
- If scans do NOT show 3 delivery attempts within 7 days AND shipment not delivered within 7 days → **no reversal**
- Reply: reversal not applicable

## Scenario 6: Loss marked – Captain claims wrong loss – Customer wants shipment post 7 days
- Check scans on Log10
- If scans do NOT show 3 attempts within 7 days AND not delivered within 7 days → **no reversal**
- Reply: loss not applicable for reversal, delivery must be attempted 3 times per SOP

## Scenario 7: Loss marked – Captain claims wrong loss – Shipment delivered but couldn't be marked
- Direct captain to raise issue with tech team with relevant proof
- Reply: issue should be taken up directly with the tech team

## Scenario 8.1: Loss marked – Shipment not inscanned back to hub – Amount RECOVERED from FE
- Check Metabase query "LM FE Loss Marked" — verify amount corresponding to shipments was recovered from FE
- Since amount IS recovered → **escalate to L2 for reversal**
- Reply: loss marked against these shipments will be reversed

## Scenario 8.2: Loss marked – Shipment not inscanned back to hub – Amount NOT recovered from FE
- Check Metabase query "LM FE Loss Marked" — amount NOT recovered from FE
- Check Log10: last shipment status should show 'Consignment_Lost'
- If both conditions true → **escalate to L2 for reversal**
- Reply: loss marked against these shipments will be reversed

## Scenario 9.1: Loss marked – Awaited instruction – Seller Dependency SOP BREACHED
- Check Metabase query to verify day attempt instructions were sent
- Check Log10 to verify attempts per Seller Dependency SOP
- SOP was breached → **no reversal**
- Reply: no reversal due to SOP breach

## Scenario 9.2: Loss marked – Awaited instruction – Seller Dependency SOP FOLLOWED
- Check Metabase query to verify day attempt instructions were sent
- Check Log10 to verify attempts per Seller Dependency SOP
- SOP was followed → **escalate to L2 for reversal**
- Reply: loss marked against shipments will be reversed

## Scenario 10: Loss marked – Wrong shipment(s)/bag(s) received
- Check scans for mentioned AWBs or bag IDs in Log10
- For bags: use Bag ID tracking query (if unavailable, enter all AWBs in bag separately)
- Reply based on scan findings

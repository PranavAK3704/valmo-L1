# Valmo Knowledge Transfer — L1 Agent Reference

## What is Valmo?
Valmo (Value Mobility) is a third-party logistics player born inside Meesho. It does NOT get special treatment — whichever 3PL is cheapest in a region gets Meesho's volume. Valmo is a network of local third-party logistics partners forming a chain of nodes. Nothing is owned by Valmo — sort centers, gateways, trucks, delivery centers are all contracted to partners.

## Supply Chain Flow
Seller → (milk run pickup) → First Mile (FM) Hub → FM Sorting Center → National Line Haul → Last Mile (LM) Sorting Center → Delivery Center (DC) → Captain → Customer

- **FM Hub**: Picks up parcels from sellers, bags them, sends to FM Sort Center
- **FM Sort Center**: Sorts to LM Sort Centers (primary + secondary sort)
- **National Line Haul**: Truck movement from FM Sort Center to LM Sort Center
- **LM Sort Center**: Sorts packages for DC-level delivery
- **DC (Delivery Center)**: The last-mile node. Captains (delivery partners) operate from here.
- **Captain**: The delivery executive. Delivers forward shipments, picks up RTO/RVP.

## Valmo's Role
Valmo primarily operates on **last-mile (LM) stakeholders**. The DC-level operations and captain management is Valmo's core business.

## Three Types of Losses

### 1. Hardstop Loss
A shipment is at a particular hub for **more than 5 days (120 hours)** without being connected to the next node. The system marks it as hardstop loss. There are 10 sub-scenarios (see hardstop_scenarios.md).

### 2. Shortage Loss
Shipment is sent from Node A to Node B. Node B does not receive it. B marks it as shortage. Both nodes are asked for evidence (CCTV footage). Loss is attributed to one node based on evidence. If both seem right → trucker is asked. If trucker also seems right → loss attributed to Meesho.

### 3. In-Transit Loss
Shipment or bag is lost in transit from Node A to Node B. Simpler than shortage — no evidence process.

## COD (Cash on Delivery)
- ~75% of Valmo's orders are COD (tier 2/tier 3 cities, cash-based)
- Captain delivers parcel, collects cash from customer
- Captain deposits cash at the hub
- CMS (Cash Management System) vendors (e.g., Airtel, ~5 vendors total) collect cash from hubs and deposit to Meesho's bank account
- **COD Pendency**: If hub has outstanding cash not yet submitted to CMS, pendency builds up. E.g., hub owes ₹10,000 but only ₹9,000 submitted → ₹1,000 pendency.

## Systems Used

### Kapture CRM
- Ticket management system (CRM)
- Captains raise tickets via **self-serve portal** (separate website with pre-populated fields) which creates tickets in Kapture via webhook
- L1 agents work tickets from Kapture queue
- Fields: ticket_id, partner_id, queue, sub_queue, hub_code, AWBs, description, attachments

### Metabase
- Internal BI/analytics tool
- Contains queries for: loss attribution, AWB scan history, payment status, invoice status, COD pendency, hub performance, etc.
- L1 agents run queries here to validate captain claims

### Log10 (console.valmo.in)
- Ops tracking system
- Shows real-time shipment scan history
- Login: mobile number + OTP
- Used for: checking if shipment was scanned, connection timeline, RTO status, delivery attempts

### Captain Panel
- Captain-facing portal showing their stats: losses debited, parcels, general performance
- Captains see loss notifications here, then raise tickets via self-serve portal

## Ticket Queues Handled by L1
1. Losses & Debits
2. Payments
3. Orders & Planning
4. Line Haul
5. Last Mile Pendency
6. Cash Handover (COD)
7. (And others — ~8-10 queues total)

## How L1 Agents Work
- Agents have a shift covering as many tickets as possible
- When stuck → ask trainer on Google Chat (trainer responds same day)
- Night shift: flag uncertain tickets, hold them, answer in morning after trainer review
- For first month: all responses reviewed by trainer before sending (authorization mode)

## CRITICAL — "Delivered" Always Means Delivered to END CUSTOMER

In ALL loss/hardstop scenarios, "delivered" = the FE/driver physically handed the package to the end customer (the person who ordered the item). It does NOT mean the shipment arrived at a hub.

**Scenario 7 specifically**: "Shipment delivered but couldn't be marked" = FE went to the customer's address, gave them the package, but failed to tap "Mark Delivered" in the app. The loss is then wrongly marked on the hub. L1 checks: was it actually delivered to the customer? Resolution: captain should raise issue directly with tech team.

**Never apply Scenario 7** to tickets about missing items at the hub, wrong bags received, or products missing from a box. Those are completely different scenarios (shortage / misroute).

## Missing Item from Received Box at Hub

**Scenario**: A shipment (or bag) arrives at the hub but a product is missing from inside the box. Captain raises a ticket claiming "product missing" or "item not available from box". A loss is being marked.

**What L1 should do**:
1. Check if proof is provided in the ticket (photos, CCTV screenshots, weight discrepancy screenshots, or other attachments)
2. **If proof is shared** → action=escalate, escalation_queue=L2_LOSSES. Remark: "Captain has shared proof of missing item — please review for loss reversal."
3. **If no proof is mentioned or attached** → action=needs_info. Reply: "Dear Captain, To process your reversal request for the missing item, please share photographic/CCTV evidence and the box weight discrepancy report."

**Never use action=stuck for this scenario** — always either needs_info (no proof) or escalate (proof available). The hub cannot self-resolve a loss — it always needs L2 review once proof is shared.

## Waiver Eligibility (General Rule)
A captain qualifies for loss waiver ONLY if ALL conditions are true:
- Tenure < 60 days
- 0 prior waivers/reversals of this loss type
- At least 1 payment cycle invoice already generated
- Current pendency of this loss type = 0
- Not a GST defaulter or COD pendency defaulter (for shortage)

## CRITICAL — Seller Dependency / Meesho AM Scenarios

When a captain says **"no revert from Meesho AM"**, **"highlighted on time but no response from AM"**, **"awaited instruction"**, or any variation of waiting for the seller/Meesho Account Manager — this is **ALWAYS Hardstop Scenario 9 (Seller Dependency)**, NOT Scenarios 8.1/8.2.

- **Meesho AM** = Meesho Account Manager = the seller's point of contact at Meesho
- **Seller Dependency SOP**: For certain shipment situations (customer unreachable, special handling), the captain must await instructions from the seller via the AM. The SOP defines how many attempts to make and within what timeframe.
- If the captain flagged the issue and the AM/seller didn't respond → **Scenario 9.1** (SOP followed by captain, no response from seller = no fault of captain)
- If the captain also breached the SOP on their side → **Scenario 9.2** does NOT apply, stay on 9.1

**How to distinguish from Scenarios 8.1/8.2:**
- 8.1/8.2: Shipment was not inscanned BACK to hub. FE has the shipment or amount is recovered from FE.
- 9.1/9.2: Shipment situation where seller instructions were needed. Captain was waiting, AM didn't respond.
- The signal "Meesho AM", "AM not reverting", "no revert from AM", "highlighted on time" = **Scenario 9**, full stop.

## CRITICAL — When There Is No SOP: Always Ask, Never Guess

Valmo L1 has SOPs for approximately 22 defined scenarios across Shortage, Hardstop, Missing Item, Payments, Consumables, and Orders queues. **If a captain's ticket does not clearly map to one of these scenarios, the correct action is always `needs_info` — ask the captain for clarification.**

Never force-fit a vague ticket into the closest-sounding scenario. Getting the wrong scenario wrong is worse than asking.

### Vague Phrases That Always Require Clarification

| Captain says | What to ask |
|---|---|
| "suspicious shipment" | "Could you clarify what was suspicious — tampered packaging, suspected fraud, wrong contents, incorrect address, or something else?" |
| "issue with shipment" / "some problem" | "Could you describe exactly what the issue is — loss marked, item missing, cannot mark in system, or something else?" |
| "highlighted on time" | "What specifically did you highlight — the shipment status, a customer issue, or a delivery attempt problem?" |
| "wrong loss" (with no AWB or scan context) | Ask for AWB numbers first before any SOP check |
| "please check" / "please resolve" (with no detail) | Ask what specifically needs to be checked or resolved |

### What "Suspicious Shipment" Could Mean (Once Captain Clarifies)

Once the captain explains what "suspicious" means, map it:
- **Tampered/open packaging on arrival at hub** → Missing Item scenario (check proof, escalate L2_LOSSES)
- **Customer suspected of fraud / refuses delivery** → Seller Dependency scenario, check with AM
- **Wrong/unexpected contents in bag** → Shortage or Missing Item depending on context
- **Shipment seems misrouted or wrong AWB** → Hardstop misroute scenario (S10, S11.1, S11.2)
- **Consignment_Lost status on Log10** → Hardstop S8.1 or S8.2

**Do not attempt any of these until the captain confirms what "suspicious" actually means.**

## Key Terms
- **AWB**: Airway Bill — shipment tracking number (Valmo format: VL + 11-13 digits)
- **DC**: Delivery Center
- **Captain**: Delivery partner/executive
- **RTO**: Return to Origin
- **THC**: Truck Handover Confirmation scan
- **FE**: Field Executive (same as captain in some contexts)
- **CN Number**: Credit Note number (for debit-related tickets)
- **Payment Cycle**: Billing period (format: YYYY-WXX)
- **Enbolt ID**: Partner's system ID
- **Attribution**: Assignment of loss responsibility to a specific node/captain

"""
Scenario catalog — every SOP scenario as a structured entry.
Stage 2 of the comprehension pipeline: clean problem → exact scenario → precise SOP.
"""

SCENARIO_CATALOG = [

    # ══════════════════════════════════════════════════════════════
    # SHORTAGE LOSS  (W- LD)
    # ══════════════════════════════════════════════════════════════
    {
        "id": "shortage_s1",
        "queue": "W- LD",
        "category": "Shortage Loss",
        "title": "Evidence / reply emails NOT sent to one or all partners",
        "description": "Partner reports they never received the evidence submission email from Valmo — cannot submit CCTV or proof for the shortage loss marked on them.",
        "signals": [
            "not receiving evidence email", "evidence mail not sent", "mail not coming",
            "email not received", "cannot submit evidence", "registered email not receiving",
            "evidence submission mail missing", "not getting mail", "loss mail not received",
            "evidence email", "not receiving mail for evidence",
        ],
        "action": "escalate",
        "action_detail": "Direct L1 → L3 escalation on Kapture. Requeue evidence/reply emails to the partner(s).",
        "needs_data": False,
        "sop_reference": "Shortage Loss — Scenario 1",
    },
    {
        "id": "shortage_s2",
        "queue": "W- LD",
        "category": "Shortage Loss",
        "title": "Captain unable to mark shortage for shipment in system",
        "description": "Captain is trying to mark a shipment as shortage but the system won't let them. Need to check Shortage SOP timeline (24hr from vehicle arrival).",
        "signals": [
            "unable to mark shortage", "cannot mark shortage", "system not allowing shortage",
            "shortage option not available", "app not allowing shortage", "marking not possible",
        ],
        "action": "respond_or_tech",
        "action_detail": "Check Shortage Data Query for vehicle arrival time. If within 24hr + SOP followed → tech issue template. Else → SOP breach reply.",
        "needs_data": True,
        "sop_reference": "Shortage Loss — Scenario 2",
    },
    {
        "id": "shortage_s3",
        "queue": "W- LD",
        "category": "Shortage Loss",
        "title": "One partner shared evidence, other has not responded",
        "description": "In a shortage between two hubs, one submitted evidence and the other hasn't within SLA. Loss attributed to non-responding partner.",
        "signals": [
            "one partner submitted", "other partner not responded", "SLA breached",
            "evidence not submitted by other hub", "partner hasn't sent evidence",
        ],
        "action": "respond",
        "action_detail": "Loss attributed to partner with SLA BREACHED status. Respond with loss attribution reasoning.",
        "needs_data": True,
        "sop_reference": "Shortage Loss — Scenario 3",
    },
    {
        "id": "shortage_s4",
        "queue": "W- LD",
        "category": "Shortage Loss",
        "title": "Both partners shared evidence but loss marked on one — contesting",
        "description": "Both hubs submitted evidence for a shortage event but loss was attributed to one of them. That hub is contesting.",
        "signals": [
            "both submitted evidence", "loss wrongly marked", "contesting attribution",
            "we submitted evidence", "other partner's fault", "wrong attribution contesting",
        ],
        "action": "escalate",
        "action_detail": "Escalate to evidence validation team. If evidence valid → escalate with correct remark.",
        "needs_data": True,
        "sop_reference": "Shortage Loss — Scenario 4",
    },
    {
        "id": "shortage_s5",
        "queue": "W- LD",
        "category": "Shortage Loss",
        "title": "Captain claims wrong email ID was shared for evidence submission",
        "description": "Captain says the email ID registered for evidence submission is wrong/incorrect and wants it corrected.",
        "signals": [
            "wrong email id", "incorrect email shared", "wrong email registered",
            "email id is wrong", "email id incorrect", "wrong email used for evidence",
        ],
        "action": "respond",
        "action_detail": "Reply: 'You should have intimated this previously.' Use standard template.",
        "needs_data": False,
        "sop_reference": "Shortage Loss — Scenario 5",
    },

    # ══════════════════════════════════════════════════════════════
    # HARDSTOP LOSS  (W- LD)
    # ══════════════════════════════════════════════════════════════
    {
        "id": "hardstop_s1_1",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Claims wrong loss — valid connection scans — Hardstop SOP WAS followed",
        "description": "Loss marked (hardstop). Captain claims it's wrong. Scan data shows valid connection made within Hardstop SOP timelines. Reversal applicable.",
        "signals": [
            "wrong loss marked", "loss should be reversed", "shipment was connected",
            "valid connection", "scans show connection", "connected on time", "reversal request",
        ],
        "action": "escalate",
        "action_detail": "Verify scans on Log10. SOP followed → escalate L2 for reversal + reply reversal will be processed.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 1.1",
    },
    {
        "id": "hardstop_s1_2",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Claims wrong loss — valid scans — Hardstop SOP NOT followed",
        "description": "Loss marked (hardstop). Scans show connection but Hardstop SOP timelines were breached. Reversal NOT applicable.",
        "signals": [
            "wrong loss", "we connected the shipment", "scans available", "hardstop wrong",
        ],
        "action": "respond",
        "action_detail": "Verify scans on Log10. SOP breached → reply: reversal not applicable due to Hardstop SOP breach.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 1.2",
    },
    {
        "id": "hardstop_s2",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Claims wrong loss — scans show wrong destination / misrouted",
        "description": "Loss marked (hardstop). Captain claims wrong loss. Scans show shipment was sent to wrong destination (misrouted).",
        "signals": [
            "wrong connection", "sent to wrong hub", "misrouted", "wrong destination",
            "shipment went wrong place", "wrong sort",
        ],
        "action": "respond",
        "action_detail": "Verify scans on Log10. Wrong destination confirmed → reversal not applicable due to wrong connection.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 2",
    },
    {
        "id": "hardstop_s3",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Claims wrong loss — failed to connect after Customer Rejection (RTO)",
        "description": "Customer rejected the shipment (RTO). Captain failed to make forward connection within RTO connection timeline.",
        "signals": [
            "customer rejected", "rto", "return to origin", "customer refused",
            "customer cancelled", "rejection", "couldn't reconnect after rejection",
        ],
        "action": "respond",
        "action_detail": "Check scans. No forward connection within RTO timeline → reversal not applicable.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 3",
    },
    {
        "id": "hardstop_s4",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Claims wrong loss — Customer was Unreachable, shipment not delivered in 7 days",
        "description": "Customer was unreachable. Shipment not delivered within 7 days. Hardstop loss marked.",
        "signals": [
            "customer unreachable", "customer not picking up", "unable to reach customer",
            "customer not available", "no response from customer",
        ],
        "action": "respond",
        "action_detail": "Check Log10. Not delivered within 7 days → reversal not applicable.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 4",
    },
    {
        "id": "hardstop_s5",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Claims wrong loss — Customer denied Cancellation OTP",
        "description": "Customer denied giving cancellation OTP. Less than 3 delivery attempts made within 7 days.",
        "signals": [
            "customer denied otp", "otp not given", "customer denied cancellation",
            "cancellation otp", "otp refused",
        ],
        "action": "respond",
        "action_detail": "Check Log10. <3 attempts in 7 days AND not delivered → reversal not applicable.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 5",
    },
    {
        "id": "hardstop_s6",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Claims wrong loss — Customer wants shipment post 7 days",
        "description": "Customer didn't want shipment initially but now wants it after 7 days. Delivery attempts not made per SOP.",
        "signals": [
            "customer wants shipment after 7 days", "customer changed mind after 7 days",
            "post 7 days delivery", "customer now wants",
        ],
        "action": "respond",
        "action_detail": "Check Log10. <3 attempts in 7 days → loss not applicable for reversal.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 6",
    },
    {
        "id": "hardstop_s7",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Delivered to END CUSTOMER but FE couldn't mark it as delivered in app",
        "description": "FE physically delivered the shipment to the end customer at their address but couldn't mark it as delivered in the Valmo app. Loss wrongly marked on hub. NOTE: 'delivered' here means delivered to the customer, NOT to the hub.",
        "signals": [
            "delivered but not marked", "couldn't mark delivered", "app not working for marking",
            "delivery done but showing undelivered", "marked as lost but delivered to customer",
            "delivered to customer but not updated in system", "fe delivered but system shows loss",
            "delivered but marked as loss",
        ],
        "action": "respond",
        "action_detail": "Captain should raise directly with tech team with relevant proof (delivery photo, customer confirmation).",
        "needs_data": False,
        "sop_reference": "Hardstop — Scenario 7",
    },
    {
        "id": "hardstop_s8_1",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Shipment not inscanned back to hub — Amount RECOVERED from FE",
        "description": "Shipment was with an FE, never inscanned back to hub. Amount has been recovered from FE. Reversal applicable.",
        "signals": [
            "amount recovered from fe", "fe paid amount", "field executive recovered",
            "amount deducted from fe", "fe amount recovered", "recovered from delivery boy",
        ],
        "action": "escalate",
        "action_detail": "Check 'LM FE Loss Marked' Metabase query. Amount recovered → escalate L2 for reversal.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 8.1",
    },
    {
        "id": "hardstop_s8_2",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Shipment not inscanned back to hub — Amount NOT recovered from FE",
        "description": "Shipment was with FE, never inscanned back. Amount NOT recovered from FE. Need Log10 to check last status.",
        "signals": [
            "amount not recovered", "fe didn't pay", "field executive not recovered",
            "shipment with fe not returned", "not inscanned back to hub",
        ],
        "action": "escalate",
        "action_detail": "Check Metabase (amount not recovered) + Log10 (Consignment_Lost) → escalate L2 for reversal.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 8.2",
    },
    {
        "id": "hardstop_s9_1",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Awaited seller instruction — Seller Dependency SOP BREACHED",
        "description": "Captain was waiting for seller/Meesho AM instructions and the loss is now marked. Seller Dependency SOP was NOT correctly followed — either attempts weren't made per SOP or timelines were breached.",
        "signals": [
            "awaiting seller instruction", "seller instruction pending", "seller dependency",
            "waiting for seller", "seller not responding", "meesho am", "no revert from am",
            "meesho account manager", "no revert from meesho", "am not responding",
            "highlighted on time no response", "flagged but no reply", "raised on time no revert",
            "awaited instruction loss marked", "seller dependency sop breach",
        ],
        "action": "respond",
        "action_detail": "Check Metabase (when instruction was sent) + Log10 (attempts per SOP). SOP breached → no reversal. Reply with template.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 9.1",
    },
    {
        "id": "hardstop_s9_2",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Awaited seller instruction — Seller Dependency SOP FOLLOWED",
        "description": "Captain was waiting for seller/Meesho AM instructions, loss is marked, but captain followed the Seller Dependency SOP correctly. Reversal applicable.",
        "signals": [
            "awaiting seller instruction sop followed", "attempted per seller instructions",
            "seller dependency followed", "meesho am followed sop", "attempts made per seller sop",
            "seller dependency reversal",
        ],
        "action": "escalate",
        "action_detail": "Check Metabase + Log10. SOP followed → escalate L2 for reversal.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 9.2",
    },
    {
        "id": "hardstop_s10",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Wrong shipment(s) or bag(s) received at hub — misrouted",
        "description": "Captain claims they received wrong shipments or bags at their hub. A different hub's shipment was sent here.",
        "signals": [
            "wrong shipment received", "wrong bag received", "received wrong awb",
            "misrouted shipment", "wrong bag at hub", "shipment doesn't belong here",
            "wrong shipments in bag",
        ],
        "action": "respond",
        "action_detail": "Check scans for mentioned AWBs/bag IDs on Log10. Reply based on what scans show.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 10",
    },

    {
        "id": "hardstop_s11_1",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Loss marked — shipments correctly misrouted — MISROUTE scan within 2 days",
        "description": "Loss marked. Captain claims wrong loss. Shipment was misrouted but the MISROUTE scan on Log10 is within 2 days of the previous scan — this is a valid/correct misroute. Eligible for reversal.",
        "signals": [
            "misrouted shipment", "misroute scan", "wrong route", "incorrect routing",
            "shipment misrouted loss", "routed to wrong hub loss", "misrouted wrongly marked",
        ],
        "action": "escalate",
        "action_detail": "Check Log10 scans. If MISROUTE scan is within 2 days of previous scan → escalate to L2 for reversal.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 11.1",
    },
    {
        "id": "hardstop_s11_2",
        "queue": "W- LD",
        "category": "Hardstop Loss",
        "title": "Loss marked — shipments incorrectly misrouted — back-and-forth between hubs",
        "description": "Loss marked. Captain claims wrong loss. Shipment went back and forth between two hubs (misrouted incorrectly, can happen max twice). Loss is attributed to the original hub. No reversal.",
        "signals": [
            "misrouted back and forth", "shipment going back and forth", "misroute back to hub",
            "repeated misroute", "misrouted twice", "original hub loss", "back and forth hubs",
        ],
        "action": "respond",
        "action_detail": "Check Log10. Misroute happened incorrectly (back-and-forth, max twice). Reply: no reversal applicable. Loss on original hub.",
        "needs_data": True,
        "sop_reference": "Hardstop — Scenario 11.2",
    },

    # ══════════════════════════════════════════════════════════════
    # MISSING ITEM AT HUB
    # ══════════════════════════════════════════════════════════════
    {
        "id": "missing_item_s1",
        "queue": "W- LD",
        "category": "Missing Item at Hub",
        "title": "Product missing from inside received shipment box — proof provided",
        "description": "A shipment box arrived at the hub but a product is missing from inside. Captain has provided photographic/CCTV proof.",
        "signals": [
            "product missing from box proof", "item missing proof attached", "photo attached missing item",
            "cctv proof missing product", "evidence shared missing item",
        ],
        "action": "escalate",
        "action_detail": "Proof available → escalate L2_LOSSES with proof noted in remarks.",
        "needs_data": False,
        "sop_reference": "Missing Item at Hub — Proof Provided",
    },
    {
        "id": "missing_item_s2",
        "queue": "W- LD",
        "category": "Missing Item at Hub",
        "title": "Product missing from inside received shipment box — no proof",
        "description": "A shipment box arrived at the hub but a product is missing from inside. No proof/evidence provided.",
        "signals": [
            "product missing from box", "item missing in box", "shipment missing item",
            "box incomplete", "item not in box", "missing product received at hub",
            "combo incomplete", "qty less than ordered at hub", "order quantity wrong received",
        ],
        "action": "needs_info",
        "action_detail": "Request CCTV/photographic evidence and box weight discrepancy report.",
        "needs_data": False,
        "sop_reference": "Missing Item at Hub — No Proof",
    },

    # ══════════════════════════════════════════════════════════════
    # PAYMENTS
    # ══════════════════════════════════════════════════════════════
    {
        "id": "payment_s1",
        "queue": "Payments",
        "category": "Payments",
        "title": "Captain hasn't received payment for a payment cycle",
        "description": "Captain asking why payment not received for a cycle. Need to check Metabase payment status.",
        "signals": [
            "payment not received", "payment pending", "haven't received payment",
            "where is my payment", "payment not credited", "salary not received",
            "amount not received", "payment delayed", "payment cycle missing",
        ],
        "action": "respond",
        "action_detail": "Check Captain Payment Status Metabase query. Reply with status-specific template.",
        "needs_data": True,
        "sop_reference": "Payments — Scenario 1",
    },
    {
        "id": "payment_s2",
        "queue": "Payments",
        "category": "Payments",
        "title": "Payment status is Under Computation",
        "description": "Captain's payment is in 'Under Computation' status.",
        "signals": ["under computation", "payment being computed", "computation pending"],
        "action": "escalate",
        "action_detail": "Escalate to L2 who checks the payment tracker.",
        "needs_data": True,
        "sop_reference": "Payments — Under Computation",
    },

    # ══════════════════════════════════════════════════════════════
    # CONSUMABLES (C_V)
    # ══════════════════════════════════════════════════════════════
    {
        "id": "consumables_missing",
        "queue": "consumables",
        "category": "Consumables",
        "title": "Consumables missing / not received / order not dispatched",
        "description": "Captain ordered consumables (flyers, packaging, docket books, bags, polybags) but order was never dispatched, not received, or received incomplete.",
        "signals": [
            "consumables missing", "consumables not received", "didn't receive consumables",
            "consumable order incomplete", "combo order missing qty", "packing material not received",
            "docket book not received", "consumable not delivered", "qty less received",
            "2 qty ordered 1 received", "order ki thi mujhe 1 mili",
            "order not dispatched", "order not shipped", "flyer not available",
            "flyer order pending", "packaging not dispatched", "order not delivered yet",
            "placed order not received", "already ordered not dispatched", "high priority dispatch",
            "prin polymers", "online order not dispatched", "order raised not fulfilled",
        ],
        "action": "respond",
        "action_detail": "Check if AWB provided. If yes → check tracking via courier website. Reply with status.",
        "needs_data": True,
        "sop_reference": "Consumables — Missing in Order",
    },
    {
        "id": "consumables_wrong",
        "queue": "consumables",
        "category": "Consumables",
        "title": "Wrong consumables received",
        "description": "Captain received wrong type or quantity of consumables in their order.",
        "signals": [
            "wrong consumables", "received wrong items", "incorrect consumables received",
            "wrong type of consumable", "wrong consumable sent",
        ],
        "action": "respond",
        "action_detail": "Check order details. Respond with correction/replacement process.",
        "needs_data": True,
        "sop_reference": "Consumables — Wrong Item",
    },

    # ══════════════════════════════════════════════════════════════
    # ORDERS & PLANNING (M_V)
    # ══════════════════════════════════════════════════════════════
    {
        "id": "orders_planning",
        "queue": "orders",
        "category": "Orders & Planning",
        "title": "Order planning / route allocation / performance issue",
        "description": "Captain has issue with order planning, route allocation, or performance metrics.",
        "signals": [
            "order planning issue", "route not planned", "orders not allocated",
            "planning problem", "orders not showing", "route problem",
        ],
        "action": "respond",
        "action_detail": "Check Orders Planning View Metabase query. Respond based on data.",
        "needs_data": True,
        "sop_reference": "Orders & Planning",
    },

    # ══════════════════════════════════════════════════════════════
    # TECH ISSUES
    # ══════════════════════════════════════════════════════════════
    {
        "id": "tech_issue",
        "queue": "any",
        "category": "Tech Issue",
        "title": "App / system not working — tech team required",
        "description": "Captain facing technical issue with Valmo app or portal (can't login, can't mark deliveries, app crash).",
        "signals": [
            "app not working", "system error", "cannot login", "app crash",
            "not able to mark in app", "app issue", "technical problem", "portal not working",
            "app showing error", "system not working",
        ],
        "action": "respond",
        "action_detail": "Direct captain to raise issue with tech team with screenshots/proof.",
        "needs_data": False,
        "sop_reference": "Tech Issue",
    },
]

# Lookup helpers
SCENARIO_BY_ID = {s["id"]: s for s in SCENARIO_CATALOG}


def get_scenario(scenario_id: str) -> dict:
    return SCENARIO_BY_ID.get(scenario_id, {})


def get_catalog_for_queue(queue: str) -> list:
    """Return scenarios relevant to a given queue (+ universal ones)."""
    q = (queue or "").lower()
    return [
        s for s in SCENARIO_CATALOG
        if s["queue"] == "any"
        or s["queue"].lower() in q
        or q in s["queue"].lower()
    ]

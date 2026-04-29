# SOPs — Losses & Debits (Full Document with Links)


<!-- Source: Official Valmo L1 SOP Google Doc (includes hyperlinks to Metabase queries, SOPs, templates) -->


#### 2 .1. Losses &amp; Debits

L2 Problem Theme

Type

Scenario

Proposed Process - L1 Agents

Proposed Process - L2-L3

Guardrails

Design TAT as per new SOP

4.1.1. Wrong Loss is marked on me

This section currently includes SOPs for Shortage and Hard-stop cases. The SOP for in-transit loss is pending closure.

Shortage Loss (Shipment Shortage)

Captain claims shortage loss marked.

L1 agent checks if AWB Numbers have been rightly added by the Captain.   If not, L1 agent requests Captains for the right inputs.

L1 agent refers to this [Metabase query](https://metabase-main.bi.meeshogcp.in/question/177019-valmo-lost-data-2k24?end_date=2026-01-16&start_date=2026-01-01&date_grain=day&filter_date=lost)  to check the lost attribution against the AWB. The “Remarks” column in the query tells agents on whether lost attribution is pending or not.

For cross-validation, L1 agent will refer to the [Shortage SOP](https://docs.google.com/document/d/1VyAWTNAIaVFVsXtAj7FJcbW-yJ_-c3BtPeKTRYagMJQ/edit?tab=t.z1pojtefyn5d) . Additionally, L1 agents will also refer to Log 10 to check the detailed scans against the AWBs.

L1 agent will check the Shortage Data Query to re-verify if the mails are sent to the partner.   If they are not sent to BOTH partners, the mail needs to be triggered again to both or the respective hubs.

Basis steps 2-3 and the scenarios below, the L1 agent will abide by the following:

Scenario 1 - The Evidence and reply mails have not been sent to one or all partners

The mails need to be requeued to the partners ( through escalation).

This is a direct L1 to L3 escalation on kapture.

Scenario 2 - The captain is unable to mark shortage for shipment

The agent must check the vehicle arrival timestamp and then check if the ticket was raised within 24 hours after the timestamp (Shortage Data Query - marked_location_ticket_status  or assigned_location_ticket_status : if the status mentioned is CLOSED) is in accordance with the [Shortage SOP](https://docs.google.com/document/d/1VyAWTNAIaVFVsXtAj7FJcbW-yJ_-c3BtPeKTRYagMJQ/edit?tab=t.z1pojtefyn5d) .

If the SOP is followed, then the issue becomes a tech issue (Template).   (Font Size 10)

Else, reply with the following template:

Scenario 3 - One partner has shared the evidence and the other has not

In this case, the loss is directly attributed to the partner that hasn’t sent the evidence in the given timeframe in accordance with the Shortage SOP. (Font Size 10)

The L1 agent must check the marked_location_ticket_status  or assigned_location_ticket_status : if the status mentioned is SLA BREACHED it means that the partner has not shared the evidence.   (Not to be confused with the CLOSED status)

Scenario 4 - Both partners have shared the evidence but loss has been marked on one of the partners: Partner is contesting

This ticket must be escalated to the team who has been given the training to view and then validate the evidence.

Post validation of the evidence: If the evidence is valid: escalate the ticket and mention the correct remark for the escalation along with the evidence.   (Font Size 10)

Scenario 5 - Captain claims that wrong email ID was shared

&quot;You should have intimated this previously&quot; should be the response.

Follow this template:

L2 and L3 agents come into play when the tickets are escalated. L2 agents must validate the escalation remarks to verify if the escalation made is valid.

In case of escalation in the following scenarios, the L2 agents should follow these SOPs

L1 agent marks the ticket for reversal: L2 agent must check the reply and remarks added by the L1 agent and forward the corresponding shipments to the wrong losses sheet, filling in the appropriate columns – shared with the losses functional team.

The L1 agent is unable to access the information needed to resolve the ticket; the L2 agent must reverify it. If the information is available, then the agent must offer the best possible resolution according to the SOPs. If the information is not available, then the ticket must be worked out along with the functional teams.

NA

72 hours

Hardstop Loss

Captain received loss AWB details on email/ captain panel and  is contesting loss marked on him.

L1 agent checks if AWB Numbers have been rightly added by the Captain.   If not, L1 agent requests Captains for the right inputs.

L1 agent refers to this [Metabase query](https://metabase-main.bi.meeshogcp.in/question/177019-valmo-lost-data-2k24?end_date=2026-01-16&start_date=2026-01-01&date_grain=day&filter_date=lost)  to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not.

For cross-validation, L1 agent will refer to the [Hardstop SOP](https://sites.google.com/meesho.com/valmo-sop/hardstop-policy-lm-fm) . Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs.

While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB.

Parent AWB can be found by inputting the given AWB into this [single AWB tracking](https://di-prd-superset.meesho.com/superset/dashboard/3727/?native_filters_key=4TERMpi-_oM54ux85IWXDKr7-seaDqYbefav6P7ys1lEyXqtTP1ZWbpULQsf1js5)  with the AWB value as the filter.

Basis these scenarios, L1 agents will act in the following ways:

Scenario 1.1: Loss marked – Captains claim connection (Wrong loss marked) – Scans valid – Hardstop SOP followed

Agent checks the scan data on Log10 and also checks the Hardstop SOP

Hardstop rule: any shipment arriving to the hub should be connected forward within 5 days(reverse) or 7 days(forward).

Raises it for reversal to the respective L2.

Scenario 1.2: Loss marked – Captains claim connection (Wrong loss marked) – Scans valid – Hardstop SOP not followed

Agent checks the scan data on Log10 and also checks if the  Hardstop rule is valid.

Hardstop rule: any shipment arriving to the hub should be connected forward within 5 days(reverse) or 7 days(forward).

Replies to the partner stating that reversal is not applicable due to Hardstop SOP breach.

Scenario 2: Loss marked – Captains claim connection (Wrong loss marked) – Scans invalid (wrong destination)

Agent checks the scan data on Logx10.

Replies to the partner stating that reversal is not applicable due to wrong connection.

Follow this template.

Scenario 3: Loss marked – Captains claim wrong loss – Fails to connect after Customer Rejection

Agent checks the scan data on [Single AWB tracking](https://metabase-main.bi.meeshogcp.in/question/177020-single-awb-tracking?interval=90&awb=VL0083256975963)  or on log10.

If the scans don’t show a forward connection within the RTO connection timeline then the agent should reply to the captain stating that reversal is not applicable.

Follow this Template

Scenario 4: Loss marked – Captains claim wrong loss – Fails to connect after Customer Unreachable

Agent checks the scan data on log10.

If as per the scans, shipment is not delivered within 7 days, then the agent should reply to the captain stating that reversal is not applicable.

Follow this Template

Scenario 5: Loss marked – Captains claim wrong loss – Customer denies cancellation OTP

Agent checks the scan data on log10.

If the scans don’t show 3 attempts within 7 days and shipment is not delivered within 7 days then the agent should reply to the captain stating that reversal is not applicable.

Follow this Template

Scenario 6: Loss marked – Captains claim wrong loss – Customer wants shipment post 7 days

Agent checks the scan data on log10.

If the scans don’t show 3 attempts within 7 days and shipment is not delivered within 7 days, then the agent should reply to the captain stating that the loss is not applicable for reversal and delivery needs to be attempted 3 times in accordance with the SOP following this template.

Additionally the captain should be informed that they should inform the customer to cancel and reorder in this case.

Follow this Template

Scenario 7: Loss marked – Captains claim wrong loss – Shipment delivered but couldn’t be marked

In this case, the agent should reply to the partner stating that the issue should be directly taken up with the tech team with the relevant proof.

Follow this Template

Scenario 8.1: Loss marked – Captains claim wrong loss – Shipment not inscanned back to hub – amount recovered from FE

Agent inputs the AWBs mentioned in the query [LM FE Loss Marked](https://metabase-main.bi.meeshogcp.in/question/178546-lm-fe-loss-marked-awbs)  and should check if the amount corresponding to the shipments has been recovered from the FE.

Since it has in this case, the agent should escalate the corresponding ticket for reversal to the respective L2.

Agent should reply to the partner stating that any loss marked against the respective shipments will be reversed following this template.

Scenario 8.2: Loss marked – Captains claim wrong loss – Shipment not inscanned back to hub – amount not recovered from FE

Agent inputs the AWBs mentioned in the query [LM FE Loss Marked](https://metabase-main.bi.meeshogcp.in/question/178546-lm-fe-loss-marked-awbs)  and should check if the amount corresponding to the shipments has not been recovered from the FE.

Additionally, the agent should check log10 to check last shipment status should show ‘Consignment_Lost’.

If both conditions are true, the corresponding ticket should be escalated for reversal to the respective L2.

Agent should reply to the partner stating that any loss marked against the respective shipments will be reversed following this template.

Scenario 9.1: Loss marked – Captains claim wrong loss – Awaited instruction – Seller Dependency SOP breach

Agent should check the [Metabase query](https://metabase-main.bi.meeshogcp.in/question/177019-valmo-lost-data-2k24?end_date=2026-01-16&start_date=2026-01-01&date_grain=day&filter_date=lost)  to verify the day the attempt instructions were sent.

Agent should check Log10 to verify the attempts as per the [Seller Dependency SOP](https://docs.google.com/spreadsheets/d/1Y8QOhA-e0M3iuBzP3wD-Pn2vFlwqvw8dElLQzGKvJQw/edit?gid=336389956#gid=336389956) .

Since the SOP was breached, the agent should reply to the partner stating that no reversal will be done since the SOP was breached.

Scenario 9.2: Loss marked – Captains claim wrong loss – Awaited instruction – Seller Dependency SOP followed

Agent should check the [Metabase query](https://metabase-main.bi.meeshogcp.in/question/177019-valmo-lost-data-2k24?end_date=2026-01-16&start_date=2026-01-01&date_grain=day&filter_date=lost)  to verify the day the attempt instructions were sent.

Agent should check Log10 to verify the attempts as per the [Seller Dependency SOP](https://docs.google.com/spreadsheets/d/1Y8QOhA-e0M3iuBzP3wD-Pn2vFlwqvw8dElLQzGKvJQw/edit?gid=336389956#gid=336389956) .

Since the SOP was followed, the agent should reply to the partner stating that any loss marked against the shipments stated will be reversed.

The corresponding ticket should be escalated to the respective L2 following this template.

Scenario 10: Loss marked – Captains claim wrong loss – wrong shipment(s)/bag(s) received  (misrouted  – hardstop is marked )

Agent should check the scans for the mentioned AWBs or bag IDs in log10 for shipments and Bag ID tracking query for bags (since the bag ID tracking query isn&#39;t available right now all the AWBs in the bag must be entered in the query separately).

According to the misroute SOP the captain must route the shipments to the correct hub within 2 days of the shipment arriving to that hub.

Since the partner has missed the deadline in this scenario the hardstop is marked and no reversalis applicable.

Scenario 11.1: Loss marked – Captains claim wrong loss – Shipments correctly misrouted

Enter the shipments on log10 and check the scans.

Check if the MISROUTE scan is within 2 days of the previous scan (valid).

Escalate to L2 for reversal of the loss marked.

Scenario 11.2: Loss marked – Captains claim wrong loss – Shipments incorrectly misrouted

Enter the shipments on log10 and check the scans.

Check if the MISROUTE scan is within 2 days of the previous scan .

In this scenario the shipments have a chance to go back and forth between the 2 hubs, in this case the misroute can be done a maximum of twice and the loss will be marked on the original hub.

Reply to the partner stating that no reversal is applicable following this template.

Current Guardrail : Requests from AM on AWB level (Requested by agents to Captains in the ticket itself)

Proposed Guardrail:

Requests from AM

OR

Prior requests from Captains due to Tech Issues / Ops Issues

We have shared a new requirement with Kapture to add an additional field prompting captains to share any tech/ops ticket ID they might have created with regard to the issue for Agents to input in the ticket.

For Tech tickets, L1-L2 Agents need to be provided access to [Log10](https://log10-support.freshdesk.com/support/login)  (To-Do) to check whether a prior tech ticket has been raised in this regard.

For Ops tickets, once L1 agents can check the ticket in Kapture platform itself.

OR

Captain informs beforehand that he received a damaged shipment and could not process the shipment

In the short term, L1 agents will be provided access to the damage shipment tracker ( [link](https://docs.google.com/spreadsheets/d/1ucVLJ-5mAvnrybfwdlm_Bi8hLphaV1bV1222s4M1ECo/edit?gid=1875944891#gid=1875944891) ). These trackers are refreshed on a monthly level. Monthly data to be shared with Support lead ( Nandini Raj P S ) who will share it with recommended L1-L2 agents

In the long run, will try to have this within Kapture

OR

Hardstop Loss can be waived off under the following circumstances

Tenurity of the captain: &lt;60 days AND

0 hardstop reversals done in the past AND

Risk is above threshold (Open losses)

Risk is above threshold (COD + Shipment pendency + open losses)

Grocery Defaulter

GST above 20 Lakhs

DC under FnF Payout

Hold by ops.

4.3.5. Wrong debits are marked in my invoice

Debits have already been marked to the captain, and the credit note has been shared. The captain needs clarification on  why the debit is marked.

Hub Code*

In this case, L1 agent will reroute this ticket to L1 of losses and debits queue to get this issue resolved

As this is only a status enquiry, it can be handled by L1 and does not typically require L2 intervention. More complex scenarios may require L2 support, which will be evaluated and taken up on a case-by-case basis.

72 hours

4.3.6. Wrong debits are marked in my invoice

Debits have already been marked to the captain, and the credit note has been shared.  Captain is contesting the debit and asking for a reversal

Hub Code*

In this case, L1 agent will reroute this ticket to L1 of losses and debits queue to get this issue resolved

More complex scenarios may require L2 support, which will be evaluated and taken up on a case-by-case basis.

4.4.1. COD pendency reflecting in the system

Captain has deposited money but still it is reflecting in COD pendency for him

Source (CMS/Bank Account)*

Transaction ID*

Date of transaction

Attachment*

L1 agent will refer to this [query](https://metabase-main.bi.meeshogcp.in/question/179010-valmo-lmdc-cod-pendency)  to check the latest COD pendency of the hub

Next, L1 agent will use this [query](https://metabase-main.bi.meeshogcp.in/question/178927-cash-handover)  to check the transaction details by entering either the hub code/Transaction ID

If there is no COD pendency showing up, then agent can respond to the ticket using the following [template](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=1845677822#gid=1845677822)

Template:

Dear Partner,

The current COD pendency for your hub is reflecting as 0. The last deposit from your hub was received on [date] for an amount of Rs. XX.

We will be closing the ticket for now. You may reopen the ticket after 48 hours if the issue persists.

For any further assistance, feel free to reach out.

Thanks you,

Valmo Partner Support.

4.1.1. Wrong Loss is marked on me This section currently includes SOPs for Shortage and Hard-stop cases. The SOP for in-transit loss is pending closure. | Shortage Loss (Shipment Shortage) | Captain claims shortage loss marked. | - L1 agent checks if AWB Numbers have been rightly added by the Captain.   If not, L1 agent requests Captains for the right inputs.  - L1 agent refers to this [Metabase query](https://metabase-main.bi.meeshogcp.in/question/177019-valmo-lost-data-2k24?end_date=2026-01-16&start_date=2026-01-01&date_grain=day&filter_date=lost)  to check the lost attribution against the AWB. The “Remarks” column in the query tells agents on whether lost attribution is pending or not.  - For cross-validation, L1 agent will refer to the [Shortage SOP](https://docs.google.com/document/d/1VyAWTNAIaVFVsXtAj7FJcbW-yJ_-c3BtPeKTRYagMJQ/edit?tab=t.z1pojtefyn5d) . Additionally, L1 agents will also refer to Log 10 to check the detailed scans against the AWBs.  - L1 agent will check the Shortage Data Query to re-verify if the mails are sent to the partner.   If they are not sent to BOTH partners, the mail needs to be triggered again to both or the respective hubs.  - Basis steps 2-3 and the scenarios below, the L1 agent will abide by the following: Scenario 1 - The Evidence and reply mails have not been sent to one or all partners    - The mails need to be requeued to the partners ( through escalation).  - This is a direct L1 to L3 escalation on kapture.   Scenario 2 - The captain is unable to mark shortage for shipment    - The agent must check the vehicle arrival timestamp and then check if the ticket was raised within 24 hours after the timestamp (Shortage Data Query - marked_location_ticket_status  or assigned_location_ticket_status : if the status mentioned is CLOSED) is in accordance with the [Shortage SOP](https://docs.google.com/document/d/1VyAWTNAIaVFVsXtAj7FJcbW-yJ_-c3BtPeKTRYagMJQ/edit?tab=t.z1pojtefyn5d) .  - If the SOP is followed, then the issue becomes a tech issue (Template).   (Font Size 10)  - Else, reply with the following template: Scenario 3 - One partner has shared the evidence and the other has not    - In this case, the loss is directly attributed to the partner that hasn’t sent the evidence in the given timeframe in accordance with the Shortage SOP. (Font Size 10)  - The L1 agent must check the marked_location_ticket_status  or assigned_location_ticket_status : if the status mentioned is SLA BREACHED it means that the partner has not shared the evidence.   (Not to be confused with the CLOSED status) Scenario 4 - Both partners have shared the evidence but loss has been marked on one of the partners: Partner is contesting    - This ticket must be escalated to the team who has been given the training to view and then validate the evidence.    - Post validation of the evidence: If the evidence is valid: escalate the ticket and mention the correct remark for the escalation along with the evidence.   (Font Size 10) Scenario 5 - Captain claims that wrong email ID was shared    - &quot;You should have intimated this previously&quot; should be the response.    - Follow this template: | L2 and L3 agents come into play when the tickets are escalated. L2 agents must validate the escalation remarks to verify if the escalation made is valid. In case of escalation in the following scenarios, the L2 agents should follow these SOPs  - L1 agent marks the ticket for reversal: L2 agent must check the reply and remarks added by the L1 agent and forward the corresponding shipments to the wrong losses sheet, filling in the appropriate columns – shared with the losses functional team.  - The L1 agent is unable to access the information needed to resolve the ticket; the L2 agent must reverify it. If the information is available, then the agent must offer the best possible resolution according to the SOPs. If the information is not available, then the ticket must be worked out along with the functional teams. | NA | 72 hours

4.3.1. I have not received payment | Captain wants to know  why he has not received payment for a payment cycle | - Payment Cycle*  - Enbolt ID*  - Invoice Number*  - Hub code* | - L1 agent checks if mandatory fields ( Payment Cycle , Enbolt ID , Invoice Number ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs.  - For Step 2,  -  L1 agents will open the [Captain Payment Status and Amount](https://metabase-main.bi.meeshogcp.in/question/177461-captain-payment-status-amount?start_date=2026-03-10&end_date=2026-03-17&hub_code=pai)  query in the metabase.  - Once they open the query, L1 agent will search by the hub-code / invoice number / E nbolt  ID  - Once the query runs, L1 agents will refer to the column “Remarks” for the status of the payment for the hub and also look for the last updated date of the status.    - L1 agents will close the ticket using the appropriate status-specific message, as per the defined templates defined [here](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=0#gid=0) .  - Payment processed.  - Pending E-Sign.  - Hold Negative.  - GST Defaulter Hold.  - Risk is above threshold (COD pendency)  - Risk is above threshold (COD + Shipment pendency )  - Risk is above threshold (Open losses)  - Risk is above threshold (COD + Shipment pendency + open losses)  - Grocery Defaulter  - GST above 20 Lakhs  - DC under FnF Payout  - Hold by ops.  - Payment Failed. | For one of the statuses that is Under Computation,  tickets will be escalated to L2 where they will check the [payment tracker](https://docs.google.com/spreadsheets/d/1R9JKAaARaJNjxlgN7VPY6MgkSmGtUj5668a--X90F0s/edit?gid=2073316702#gid=2073316702)  for the status of that particular payment cycle and revert accordingly. | As this is only a status enquiry, it can be handled by L1 and L2 and does not typically require L3 intervention. More complex scenarios may require L3  support, which will be evaluated and taken up on a case-by-case basis. |  | 12 hours

4.3.5. Wrong debits are marked in my invoice | Debits have already been marked to the captain, and the credit note has been shared. The captain needs clarification on  why the debit is marked. | - Hub Code*  - Payment Cycle*  - Credit Note Number* OR  - Enbolt ID* OR  - AWBs  - Attachment of the credit note | In this case, L1 agent will reroute this ticket to L1 of losses and debits queue to get this issue resolved | As this is only a status enquiry, it can be handled by L1 and does not typically require L2 intervention. More complex scenarios may require L2 support, which will be evaluated and taken up on a case-by-case basis. |  |  | 72 hours

4.3.6. Wrong debits are marked in my invoice | Debits have already been marked to the captain, and the credit note has been shared.  Captain is contesting the debit and asking for a reversal | - Hub Code*  - Payment Cycle*  - Credit Note Number* OR  - Enbolt ID* OR  - AWBs  - Attachment of the credit note | In this case, L1 agent will reroute this ticket to L1 of losses and debits queue to get this issue resolved | More complex scenarios may require L2 support, which will be evaluated and taken up on a case-by-case basis. |  | 

4.4.1. COD pendency reflecting in the system | Captain has deposited money but still it is reflecting in COD pendency for him | - Source (CMS/Bank Account)*  - Transaction ID*  - Date of transaction  - Attachment* | - L1 agent will refer to this [query](https://metabase-main.bi.meeshogcp.in/question/179010-valmo-lmdc-cod-pendency)  to check the latest COD pendency of the hub  - Next, L1 agent will use this [query](https://metabase-main.bi.meeshogcp.in/question/178927-cash-handover)  to check the transaction details by entering either the hub code/Transaction ID  - If there is no COD pendency showing up, then agent can respond to the ticket using the following [template](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=1845677822#gid=1845677822) Template: Dear Partner, The current COD pendency for your hub is reflecting as 0. The last deposit from your hub was received on [date] for an amount of Rs. XX. We will be closing the ticket for now. You may reopen the ticket after 48 hours if the issue persists. For any further assistance, feel free to reach out. Thanks you, Valmo Partner Support. |  |  |  | 
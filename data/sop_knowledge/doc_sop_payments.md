# SOPs — Payments (Full Document with Links)


<!-- Source: Official Valmo L1 SOP Google Doc (includes hyperlinks to Metabase queries, SOPs, templates) -->


At least 1 payment cycle invoice generated AND

Current hardstop pendency = 0

Notes

The email templates for a few cases are a WIP. Will continue updating them.

*A threshold of ₹5,000 per payment cycle has been set as the approval limit for L2 agents to process waive-offs. This has been derived based on the average monthly payout for an LM captain being ~ ₹40,000, translating to a weekly payout of around ₹10,000. A 50% threshold of the weekly payout has therefore been considered as the guardrail per payment cycle.

#### 2 .3. Payments

L2 Problem Theme

Scenario

Proposed Process - Inputs needed from Partners

Proposed Process - L1 Agents

Proposed Process - L2

Proposed Process - L3

Guardrails / Exclusions

Design TAT as per new SOP

4.3.1. I have not received payment

Captain wants to know  why he has not received payment for a payment cycle

Payment Cycle*

Enbolt ID*

Invoice Number*

Hub code*

L1 agent checks if mandatory fields ( Payment Cycle , Enbolt ID , Invoice Number ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs.

For Step 2,

L1 agents will open the [Captain Payment Status and Amount](https://metabase-main.bi.meeshogcp.in/question/177461-captain-payment-status-amount?start_date=2026-03-10&end_date=2026-03-17&hub_code=pai)  query in the metabase.

Once they open the query, L1 agent will search by the hub-code / invoice number / E nbolt  ID

Once the query runs, L1 agents will refer to the column “Remarks” for the status of the payment for the hub and also look for the last updated date of the status.

L1 agents will close the ticket using the appropriate status-specific message, as per the defined templates defined [here](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=0#gid=0) .

Payment processed.

Pending E-Sign.

Hold Negative.

GST Defaulter Hold.

Risk is above threshold (COD pendency)

Risk is above threshold (COD + Shipment pendency )

Payment Failed.

For one of the statuses that is Under Computation,  tickets will be escalated to L2 where they will check the [payment tracker](https://docs.google.com/spreadsheets/d/1R9JKAaARaJNjxlgN7VPY6MgkSmGtUj5668a--X90F0s/edit?gid=2073316702#gid=2073316702)  for the status of that particular payment cycle and revert accordingly.

As this is only a status enquiry, it can be handled by L1 and L2 and does not typically require L3 intervention. More complex scenarios may require L3  support, which will be evaluated and taken up on a case-by-case basis.

12 hours

4.3.2. I want to have a full and final settlement

Captain wants to close his DC or wants FnF settlement

Payment Cycle

Enbolt ID*

Invoice Number

Hub Code*

Bank Transaction detail*

Bank Account statement/Cancel cheque Copy*

SD Deposit slip (only G Drive link applicable)

Vendor name (as per bank a/c)

L1 agent checks if mandatory fields (Hub Code, Enbolt ID ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs..

For Step 2,

L1 agent will refer to the [FnF Dashboard](https://docs.google.com/spreadsheets/d/1QgAWIzrtIK-tx3ZR9aoJzLZxSV7hHmokJVvMBwzz1gI/edit?gid=1510888552#gid=1510888552)    that will have the following input and output

Inputs

Hub Code* in the first cell of the FnF Details_1 column.

Output

AP Remarks

Cost ops sub header

Cost ops final remarks

Payment process date

Based on the AP Remarks, L1 agents will respond ➖

FnF done ( cases are picked every 15 days in a month)

GST issue (not paid by vendor)

Open Pendency

Deposit Consideration Issue

Signature Pending

SD details not available

Hold by ops

L1 agents will reply only when the remarks show  FnF done, GST issue  , Signature Pending and Open pendency using these [templates](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=844430580#gid=844430580) . For the rest of the cases, L1 will escalate the ticket to L2.

Steps to be followed by L2:-

Validate Enbolt ID 
       Check how many DCs are mapped to one Enbolt ID

If only one DC is mapped, check in the F&amp;F tracker to see if the hub has filed for FnF settlement
Search for the hub code in FnF Dashboard to check the reason for FnF hold

In case of Deposit consideration issue, first check for any COD hardstop status

If there is any hardstop, revert the ticket accordingly

In case of deposit consideration issues, held by ops and SD details not available, escalate to L3.

In the case of Deposit consideration and held by ops, instead of routing the tickets to AMs the tickets will be escalated to Christopher Benignus.

For SD deposit , escalate the tickets to Sachin yadav

Captain wants his  Security Deposit refunded

Payment Cycle

Enbolt ID*

Invoice Number

Hub Code*

Bank Transaction detail*

Bank Account statement/Cancel cheque Copy*

SD Deposit slip (only G Drive link applicable)

Vendor name (as per bank a/c)

L1 agent checks if mandatory fields (Hub Code, Enbolt ID ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs.

For Step 2, 
           L1 agent will refer to the [FnF Refund](https://docs.google.com/spreadsheets/d/16qBalPtdQyxaJ6aiLvdCpEns0HzoRc84pxi3PBD87Dk/edit?gid=571635645#gid=571635645)  tracker and check in the SD refund request       sheet the  Cost Ops remarks

Remarks by the Cost ops team:-

SD Refund Done

Pending from ops/Partner dependency

Details missing in sheet

Not eligible - need to move in FnF/ Multi - DC sheet
                                   Open pendency

Pending from cost ops
          Yet to pick(SD payments are picked up every week )
          Working under progress

L1 agents will reply only when the remarks show SD Refund Done  and Pending from cost ops with these [templates](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=844430580#gid=844430580) .  For Pending from ops/Partner dependency, L1 will escalate this ticket to L2

If the Cost ops remark says pending from ops/ partner dependency, this ticket will be escalated to L3 (sachin yadav) by L2 to connect with the particular AMs/CHs and get the missing Details filled in the sheet

L3 (Sachin Yadav) will connect to the AMs/CHs and get the details filled in the sheet to get picked up by the Cost Ops team.

4.3.3. I want to download/get  invoices of  my previous payment cycles

Captain wants to get all the invoices generated from (dd-mm-yyy) to (dd-mm-yyyy)

Hub Code*

Enbolt ID*

Invoice Number(s)

Payment Cycle(s)*

In this case, L1 agents need to directly escalate this ticket to L2

For this issue, L2 will send an email to soudeep@enbolt.com  providing the enbolt id and the period for which the invoices are required. 

After receiving the invoices, L2 will download the zip file and reply to the partner with this [message](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=1206155882#gid=1206155882) .

4.3.4. There is shipment count mismatch in my invoice

Captain says that the shipment count (FWD + RVP) is different as per captain and as per invoice

Hub Code*

Enbolt ID

Invoice Number*

Payment Cycle*

L1 agent checks if mandatory fields (Payment Cycle / Enbolt ID / Invoice Number) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs.

The L1 agent will refer to the [Captain Payment Status and Amount](https://metabase-main.bi.meeshogcp.in/question/177461-captain-payment-status-amount?start_date=2026-03-10&end_date=2026-03-17&hub_code=pai)  query to identify the delta between the shipment count considered in the invoice and the actual shipments delivered or picked up by the captain for the relevant payment cycle.

Inputs

Hub Code*

Payment Cycle*

Enbolt ID

Invoice Number

Output

#FWD Shipments delivered (as per the invoice)

#RVP Shipments picked (as per the invoice)

Total # Shipments (FWD + RVP as per invoice)

Base rate for FWD

Base rate for RVP

Total amount for FWD Shipments

Total amount for RVP Shipments

Incentives

Deductions

Net Amount Payable

Final Status of payment

Actual FWD Shipments delivered (captured real time)

Actual RVP Shipments picked (captured real time)

Delta in FWD Shipment (Actual - Invoice)

Delta in RVP Shipment (Actual - Invoice)

Basis the delta, agents will revert back to the partners with the following [templates.](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=1644211006#gid=1644211006)

Keep the ticket open with “awaiting user response” status for the partner to contest.

If the partner does not respond within 72 hours, the ticket will be auto-closed.

As this is only a status enquiry, it can be handled by L1 and does not typically require L2 intervention. More complex scenarios may require L2 support, which will be evaluated and taken up on a case-by-case basis.

As this is only a status enquiry, it can be handled by L1 and does not typically require L3 intervention. More complex scenarios may require L3  support, which will be evaluated and taken up on a case-by-case basis.

24 hours

Payment Cycle*

Credit Note Number*

OR

Enbolt ID*

OR

AWBs

Attachment of the credit note

Payment Cycle*

Credit Note Number*

OR

Enbolt ID*

OR

AWBs

Attachment of the credit note

4.3.7. Payment done on Razorpay (company QR) but same amount showing in captain’s COD pendency

Customer paid on Company QR (RazorPay) but showing in the COD pendency of Captain

Hub code*

Single AWB / Bulk AWB*

In this case, L1 agents need to directly escalate this ticket to L2

L2 will first check the AWB/AWBs in the [Razorpay Epay bulk awb check](https://metabase-main.bi.meeshogcp.in/question/170043-razorpay-epay-bulk-awb-check?awb_list=VL0082743800934)  query

If on entering the awb in the query, it shows the result then the awb is synced with razorpay

If the query does not show any results, revert with this [form](https://forms.gle/BiPJ5uRYRaQLXrAu8) .

4.3.8. My Pilot has not received the payment

FE has not received payment for the particular cycle chosen by him.

Partner ID*

FE  Phone number*

Hub code*

Payment cycle*

Date r

L1 agent checks if mandatory fields (Partner ID, FE phone number/ Hub code, Payment cycle) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs

For Step 2,

L1 agent will refer to the  LM Pilot Payout Raw query  that will have the following input and output

Inputs

Payment Cycle

Partner ID

Output
Once the query runs, L1 agents will refer to the column “Remarks” for the status of the payment for the hub and also look for the last updated date of the status.

L1 agents will close the ticket using the appropriate status-specific message, as per the defined templates defined [here](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=0#gid=0) .

Bts_open_ground

Bts_open_not_received

Dpt_not_created_bts_closed_after_14_days

Dpt_not_created_bts_received_after_14_days

Dpt_pending_created_later

FAILED

Failed_to_be_processed_next_cycle

Line_items_not_created

No_del_pick

Not_whitelisted

Pending_scheduled_for_later

Pending_others

Failed_pilot_name_mismatch

Failed_update_bank_account

Hold_blocked

Hold_others

Pending_non_payable_amount

Pending_scheduled_for_later_1_day_cycle

Pending_scheduled_for_later_14_days_cycle

Pending_scheduled_for_later_7_days_cycle

SUCCEEDED

Bts_open_others

RVP consumables invoice/payment not received. (till April)

Hub ID, Order ID, Billing cycle for which the payments have not been completed, CN/DN, Invoice number.

Agents must check if the required information is provided in the ticket and if the information is valid. If not then reply with the following template. Dispose with awaiting user input disposition.

Proactive steps that can be taken:

Input the hub code into the [captain payout query](https://metabase-main.bi.meeshogcp.in/question/177461-captain-payment-status-amount)  and check the payment cycles in which the payments have not been completed.

Note down these cycles and follow these steps to solve the following scenarios:

Scenario 1 – RVP consumables payment not received - Payment received for X out of Y consumables (X&lt;Y):

Agent must enter the hub ID  in the [captain payout query](https://metabase-main.bi.meeshogcp.in/question/177461-captain-payment-status-amount)  and check the mentioned payment cycles  by the partners or follow the proactive steps.

Scenario 2 – RVP consumables payment not received - Payment not received for any ordered consumables:

Agents must enter the hub ID  in the [captain payout query](https://metabase-main.bi.meeshogcp.in/question/177461-captain-payment-status-amount)  and check the mentioned payment cycles  by the partners or follow the proactive steps.

If the value in the count column for the mentioned payment cycles ~ 0 then this should be classified as an arrear and the payment for these cases will be done 2 weeks after the cycle in which the order was made.

The agent should reply to the partner following this template.

Scenario 3 – RVP consumables payment not received - manual entries post scan failure:

Since there is no actual way to figure out here what the partner is entering manually, the refunds for these follow the same pattern as the refunds given for Scenario 2.

The refund will be done in the payment cycle following the cycle in which the order was placed in April.

The agent must reply to the Partner following this template.

L2 Problem Theme | Type | Scenario | Proposed Process - L1 Agents | Proposed Process - L2-L3 | Guardrails | Design TAT as per new SOP

Hardstop Loss | Captain received loss AWB details on email/ captain panel and  is contesting loss marked on him. | - L1 agent checks if AWB Numbers have been rightly added by the Captain.   If not, L1 agent requests Captains for the right inputs.  - L1 agent refers to this [Metabase query](https://metabase-main.bi.meeshogcp.in/question/177019-valmo-lost-data-2k24?end_date=2026-01-16&start_date=2026-01-01&date_grain=day&filter_date=lost)  to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not.  - For cross-validation, L1 agent will refer to the [Hardstop SOP](https://sites.google.com/meesho.com/valmo-sop/hardstop-policy-lm-fm) . Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs.  - While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB.  - Parent AWB can be found by inputting the given AWB into this [single AWB tracking](https://di-prd-superset.meesho.com/superset/dashboard/3727/?native_filters_key=4TERMpi-_oM54ux85IWXDKr7-seaDqYbefav6P7ys1lEyXqtTP1ZWbpULQsf1js5)  with the AWB value as the filter.  - Basis these scenarios, L1 agents will act in the following ways: Scenario 1.1: Loss marked – Captains claim connection (Wrong loss marked) – Scans valid – Hardstop SOP followed  - Agent checks the scan data on Log10 and also checks the Hardstop SOP  - Hardstop rule: any shipment arriving to the hub should be connected forward within 5 days(reverse) or 7 days(forward).  - Raises it for reversal to the respective L2. Scenario 1.2: Loss marked – Captains claim connection (Wrong loss marked) – Scans valid – Hardstop SOP not followed  - Agent checks the scan data on Log10 and also checks if the  Hardstop rule is valid.  - Hardstop rule: any shipment arriving to the hub should be connected forward within 5 days(reverse) or 7 days(forward).  - Replies to the partner stating that reversal is not applicable due to Hardstop SOP breach. Scenario 2: Loss marked – Captains claim connection (Wrong loss marked) – Scans invalid (wrong destination)  - Agent checks the scan data on Logx10.  - Replies to the partner stating that reversal is not applicable due to wrong connection.  - Follow this template. Scenario 3: Loss marked – Captains claim wrong loss – Fails to connect after Customer Rejection  - Agent checks the scan data on [Single AWB tracking](https://metabase-main.bi.meeshogcp.in/question/177020-single-awb-tracking?interval=90&awb=VL0083256975963)  or on log10.  - If the scans don’t show a forward connection within the RTO connection timeline then the agent should reply to the captain stating that reversal is not applicable.  - Follow this Template Scenario 4: Loss marked – Captains claim wrong loss – Fails to connect after Customer Unreachable  - Agent checks the scan data on log10.  - If as per the scans, shipment is not delivered within 7 days, then the agent should reply to the captain stating that reversal is not applicable.  - Follow this Template Scenario 5: Loss marked – Captains claim wrong loss – Customer denies cancellation OTP  - Agent checks the scan data on log10.  - If the scans don’t show 3 attempts within 7 days and shipment is not delivered within 7 days then the agent should reply to the captain stating that reversal is not applicable.  - Follow this Template Scenario 6: Loss marked – Captains claim wrong loss – Customer wants shipment post 7 days  - Agent checks the scan data on log10.  - If the scans don’t show 3 attempts within 7 days and shipment is not delivered within 7 days, then the agent should reply to the captain stating that the loss is not applicable for reversal and delivery needs to be attempted 3 times in accordance with the SOP following this template.  - Additionally the captain should be informed that they should inform the customer to cancel and reorder in this case.  - Follow this Template Scenario 7: Loss marked – Captains claim wrong loss – Shipment delivered but couldn’t be marked  - In this case, the agent should reply to the partner stating that the issue should be directly taken up with the tech team with the relevant proof.  - Follow this Template Scenario 8.1: Loss marked – Captains claim wrong loss – Shipment not inscanned back to hub – amount recovered from FE  - Agent inputs the AWBs mentioned in the query [LM FE Loss Marked](https://metabase-main.bi.meeshogcp.in/question/178546-lm-fe-loss-marked-awbs)  and should check if the amount corresponding to the shipments has been recovered from the FE.  - Since it has in this case, the agent should escalate the corresponding ticket for reversal to the respective L2.  - Agent should reply to the partner stating that any loss marked against the respective shipments will be reversed following this template. Scenario 8.2: Loss marked – Captains claim wrong loss – Shipment not inscanned back to hub – amount not recovered from FE  - Agent inputs the AWBs mentioned in the query [LM FE Loss Marked](https://metabase-main.bi.meeshogcp.in/question/178546-lm-fe-loss-marked-awbs)  and should check if the amount corresponding to the shipments has not been recovered from the FE.  - Additionally, the agent should check log10 to check last shipment status should show ‘Consignment_Lost’.  - If both conditions are true, the corresponding ticket should be escalated for reversal to the respective L2.  - Agent should reply to the partner stating that any loss marked against the respective shipments will be reversed following this template. Scenario 9.1: Loss marked – Captains claim wrong loss – Awaited instruction – Seller Dependency SOP breach  - Agent should check the [Metabase query](https://metabase-main.bi.meeshogcp.in/question/177019-valmo-lost-data-2k24?end_date=2026-01-16&start_date=2026-01-01&date_grain=day&filter_date=lost)  to verify the day the attempt instructions were sent.  - Agent should check Log10 to verify the attempts as per the [Seller Dependency SOP](https://docs.google.com/spreadsheets/d/1Y8QOhA-e0M3iuBzP3wD-Pn2vFlwqvw8dElLQzGKvJQw/edit?gid=336389956#gid=336389956) .  - Since the SOP was breached, the agent should reply to the partner stating that no reversal will be done since the SOP was breached. Scenario 9.2: Loss marked – Captains claim wrong loss – Awaited instruction – Seller Dependency SOP followed  - Agent should check the [Metabase query](https://metabase-main.bi.meeshogcp.in/question/177019-valmo-lost-data-2k24?end_date=2026-01-16&start_date=2026-01-01&date_grain=day&filter_date=lost)  to verify the day the attempt instructions were sent.  - Agent should check Log10 to verify the attempts as per the [Seller Dependency SOP](https://docs.google.com/spreadsheets/d/1Y8QOhA-e0M3iuBzP3wD-Pn2vFlwqvw8dElLQzGKvJQw/edit?gid=336389956#gid=336389956) .  - Since the SOP was followed, the agent should reply to the partner stating that any loss marked against the shipments stated will be reversed.  - The corresponding ticket should be escalated to the respective L2 following this template. Scenario 10: Loss marked – Captains claim wrong loss – wrong shipment(s)/bag(s) received  (misrouted  – hardstop is marked )  - Agent should check the scans for the mentioned AWBs or bag IDs in log10 for shipments and Bag ID tracking query for bags (since the bag ID tracking query isn&#39;t available right now all the AWBs in the bag must be entered in the query separately).  - According to the misroute SOP the captain must route the shipments to the correct hub within 2 days of the shipment arriving to that hub.  - Since the partner has missed the deadline in this scenario the hardstop is marked and no reversalis applicable.  - Scenario 11.1: Loss marked – Captains claim wrong loss – Shipments correctly misrouted  - Enter the shipments on log10 and check the scans.  - Check if the MISROUTE scan is within 2 days of the previous scan (valid).  - Escalate to L2 for reversal of the loss marked. Scenario 11.2: Loss marked – Captains claim wrong loss – Shipments incorrectly misrouted  - Enter the shipments on log10 and check the scans.  - Check if the MISROUTE scan is within 2 days of the previous scan .  - In this scenario the shipments have a chance to go back and forth between the 2 hubs, in this case the misroute can be done a maximum of twice and the loss will be marked on the original hub.  - Reply to the partner stating that no reversal is applicable following this template. |  | Current Guardrail : Requests from AM on AWB level (Requested by agents to Captains in the ticket itself) Proposed Guardrail:  - Requests from AM OR  - Prior requests from Captains due to Tech Issues / Ops Issues  - We have shared a new requirement with Kapture to add an additional field prompting captains to share any tech/ops ticket ID they might have created with regard to the issue for Agents to input in the ticket.  - For Tech tickets, L1-L2 Agents need to be provided access to [Log10](https://log10-support.freshdesk.com/support/login)  (To-Do) to check whether a prior tech ticket has been raised in this regard.  - For Ops tickets, once L1 agents can check the ticket in Kapture platform itself. OR  - Captain informs beforehand that he received a damaged shipment and could not process the shipment  - In the short term, L1 agents will be provided access to the damage shipment tracker ( [link](https://docs.google.com/spreadsheets/d/1ucVLJ-5mAvnrybfwdlm_Bi8hLphaV1bV1222s4M1ECo/edit?gid=1875944891#gid=1875944891) ). These trackers are refreshed on a monthly level. Monthly data to be shared with Support lead ( Nandini Raj P S ) who will share it with recommended L1-L2 agents  - In the long run, will try to have this within Kapture OR  - Hardstop Loss can be waived off under the following circumstances  - Tenurity of the captain: &lt;60 days AND  - 0 hardstop reversals done in the past AND  - At least 1 payment cycle invoice generated AND  - Current hardstop pendency = 0

L2 Problem Theme | Type | Mandatory Inputs needed from Captain | Proposed Process - L1 Agents | Proposed Process - L2- L3 | Design TAT as per new SOP

4.3.2. I want to have a full and final settlement | Captain wants to close his DC or wants FnF settlement | - Payment Cycle  - Enbolt ID*  - Invoice Number  - Hub Code*  - Bank Transaction detail*  - Bank Account statement/Cancel cheque Copy*  - SD Deposit slip (only G Drive link applicable)  - Vendor name (as per bank a/c) | - L1 agent checks if mandatory fields (Hub Code, Enbolt ID ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs..  - For Step 2,  - L1 agent will refer to the [FnF Dashboard](https://docs.google.com/spreadsheets/d/1QgAWIzrtIK-tx3ZR9aoJzLZxSV7hHmokJVvMBwzz1gI/edit?gid=1510888552#gid=1510888552)    that will have the following input and output  - Inputs Hub Code* in the first cell of the FnF Details_1 column.  - Output AP Remarks Cost ops sub header Cost ops final remarks Payment process date  - Based on the AP Remarks, L1 agents will respond ➖  - FnF done ( cases are picked every 15 days in a month)  - GST issue (not paid by vendor)  - Open Pendency  - Deposit Consideration Issue  - Signature Pending  - SD details not available  - Hold by ops  - L1 agents will reply only when the remarks show  FnF done, GST issue  , Signature Pending and Open pendency using these [templates](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=844430580#gid=844430580) . For the rest of the cases, L1 will escalate the ticket to L2. | - Steps to be followed by L2:-  - Validate Enbolt ID         Check how many DCs are mapped to one Enbolt ID  -  If only one DC is mapped, check in the F&amp;F tracker to see if the hub has filed for FnF settlement Search for the hub code in FnF Dashboard to check the reason for FnF hold  - In case of Deposit consideration issue, first check for any COD hardstop status  -  If there is any hardstop, revert the ticket accordingly In case of deposit consideration issues, held by ops and SD details not available, escalate to L3. | - In the case of Deposit consideration and held by ops, instead of routing the tickets to AMs the tickets will be escalated to Christopher Benignus.  - For SD deposit , escalate the tickets to Sachin yadav |  | 

 | Captain wants his  Security Deposit refunded | - Payment Cycle  - Enbolt ID*  - Invoice Number  - Hub Code*  - Bank Transaction detail*  - Bank Account statement/Cancel cheque Copy*  - SD Deposit slip (only G Drive link applicable)  - Vendor name (as per bank a/c) | - L1 agent checks if mandatory fields (Hub Code, Enbolt ID ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs.  - For Step 2,             L1 agent will refer to the [FnF Refund](https://docs.google.com/spreadsheets/d/16qBalPtdQyxaJ6aiLvdCpEns0HzoRc84pxi3PBD87Dk/edit?gid=571635645#gid=571635645)  tracker and check in the SD refund request       sheet the  Cost Ops remarks   Remarks by the Cost ops team:-  -    SD Refund Done  -   Pending from ops/Partner dependency                                     Details missing in sheet                                     Not eligible - need to move in FnF/ Multi - DC sheet                                    Open pendency  -   Pending from cost ops           Yet to pick(SD payments are picked up every week )           Working under progress  - L1 agents will reply only when the remarks show SD Refund Done  and Pending from cost ops with these [templates](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=844430580#gid=844430580) .  For Pending from ops/Partner dependency, L1 will escalate this ticket to L2 | If the Cost ops remark says pending from ops/ partner dependency, this ticket will be escalated to L3 (sachin yadav) by L2 to connect with the particular AMs/CHs and get the missing Details filled in the sheet | - L3 (Sachin Yadav) will connect to the AMs/CHs and get the details filled in the sheet to get picked up by the Cost Ops team. |  | 

4.3.3. I want to download/get  invoices of  my previous payment cycles | Captain wants to get all the invoices generated from (dd-mm-yyy) to (dd-mm-yyyy) | - Hub Code*  - Enbolt ID*  - Invoice Number(s)  - Payment Cycle(s)* | In this case, L1 agents need to directly escalate this ticket to L2 | For this issue, L2 will send an email to soudeep@enbolt.com  providing the enbolt id and the period for which the invoices are required.   After receiving the invoices, L2 will download the zip file and reply to the partner with this [message](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=1206155882#gid=1206155882) . |  |  | 

4.3.4. There is shipment count mismatch in my invoice | Captain says that the shipment count (FWD + RVP) is different as per captain and as per invoice | - Hub Code*  - Enbolt ID  - Invoice Number*  - Payment Cycle* | - L1 agent checks if mandatory fields (Payment Cycle / Enbolt ID / Invoice Number) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs.  - The L1 agent will refer to the [Captain Payment Status and Amount](https://metabase-main.bi.meeshogcp.in/question/177461-captain-payment-status-amount?start_date=2026-03-10&end_date=2026-03-17&hub_code=pai)  query to identify the delta between the shipment count considered in the invoice and the actual shipments delivered or picked up by the captain for the relevant payment cycle. Inputs  - Hub Code*  - Payment Cycle*  - Enbolt ID  - Invoice Number Output  - #FWD Shipments delivered (as per the invoice)  -  #RVP Shipments picked (as per the invoice)  - Total # Shipments (FWD + RVP as per invoice)  - Base rate for FWD  - Base rate for RVP  - Total amount for FWD Shipments  - Total amount for RVP Shipments  - Incentives  - Deductions  - Net Amount Payable  - Final Status of payment  - Actual FWD Shipments delivered (captured real time)  - Actual RVP Shipments picked (captured real time)  - Delta in FWD Shipment (Actual - Invoice)  - Delta in RVP Shipment (Actual - Invoice)  - Basis the delta, agents will revert back to the partners with the following [templates.](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=1644211006#gid=1644211006)  - Keep the ticket open with “awaiting user response” status for the partner to contest.  - If the partner does not respond within 72 hours, the ticket will be auto-closed. | As this is only a status enquiry, it can be handled by L1 and does not typically require L2 intervention. More complex scenarios may require L2 support, which will be evaluated and taken up on a case-by-case basis. | As this is only a status enquiry, it can be handled by L1 and does not typically require L3 intervention. More complex scenarios may require L3  support, which will be evaluated and taken up on a case-by-case basis. |  | 24 hours

4.3.7. Payment done on Razorpay (company QR) but same amount showing in captain’s COD pendency | Customer paid on Company QR (RazorPay) but showing in the COD pendency of Captain | - Hub code*  - Single AWB / Bulk AWB* | In this case, L1 agents need to directly escalate this ticket to L2 | - L2 will first check the AWB/AWBs in the [Razorpay Epay bulk awb check](https://metabase-main.bi.meeshogcp.in/question/170043-razorpay-epay-bulk-awb-check?awb_list=VL0082743800934)  query  - If on entering the awb in the query, it shows the result then the awb is synced with razorpay  - If the query does not show any results, revert with this [form](https://forms.gle/BiPJ5uRYRaQLXrAu8) . |  |  | 

4.3.8. My Pilot has not received the payment | FE has not received payment for the particular cycle chosen by him. | - Partner ID*  - FE  Phone number*  - Hub code*  - Payment cycle*  - Date r | - L1 agent checks if mandatory fields (Partner ID, FE phone number/ Hub code, Payment cycle) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs  - For Step 2,  - L1 agent will refer to the  LM Pilot Payout Raw query  that will have the following input and output  - Inputs Payment Cycle Partner ID   - Output Once the query runs, L1 agents will refer to the column “Remarks” for the status of the payment for the hub and also look for the last updated date of the status.  - L1 agents will close the ticket using the appropriate status-specific message, as per the defined templates defined [here](https://docs.google.com/spreadsheets/d/1fah7eXHl6fHN_suMGaIF0DdDiGHrl-V-amOXrA320rc/edit?gid=0#gid=0) .  - Bts_open_ground  - Bts_open_not_received  - Dpt_not_created_bts_closed_after_14_days  - Dpt_not_created_bts_received_after_14_days  - Dpt_pending_created_later  - FAILED  - Failed_to_be_processed_next_cycle  - Line_items_not_created  - No_del_pick  - Not_whitelisted  - Pending_scheduled_for_later  - Pending_others  - Failed_pilot_name_mismatch  - Failed_update_bank_account  - Hold_blocked  - Hold_others  - Pending_non_payable_amount  - Pending_scheduled_for_later_1_day_cycle  - Pending_scheduled_for_later_14_days_cycle  - Pending_scheduled_for_later_7_days_cycle  - SUCCEEDED  - Bts_open_others |  |  |  | 

L2 Problem Theme | Scenario | Proposed Process - Inputs needed from Partners | Proposed Process - L1 Agents | Proposed Process - L2 | Proposed Process - L3 | Guardrails / Exclusions | Design TAT as per new SOP
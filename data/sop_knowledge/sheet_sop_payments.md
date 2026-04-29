# SOPs — Payments

## I have not received payment

**Category:** Payments
**TAT:** 12 hours
**Keywords:** payment|invoice|cod|pendency

### Scenario
L1 agent checks if mandatory fields (Payment Cycle , Enbolt ID , Invoice Number) have been rightly added by the Captain. If not, L1 agent requests Cap

### L1 Process (What agent must do)
L1 agent checks if mandatory fields (Payment Cycle , Enbolt ID , Invoice Number) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. For Step 2, L1 agents will open the Captain Payment Status and Amount query in the metabase. Once they open the query, L1 agent will search by the hub-code / invoice number / Enbolt ID Once the query runs, L1 agents will refer to the column “Remarks” for the status of the payment for the hub and also look for the last updated date of the status. L1 agents will close the ticket using the appropriate status-specific message, as per the defined templates defined here. Payment processed. Pending E-Sign. Hold Negative. GST Defaulter Hold. Risk is above threshold (COD pendency) Risk is above threshold (COD + Shipment pendency ) Risk is above threshold (Open losses) Risk is above threshold (COD + Shipment pendency + open losses) Grocery Defaulter GST above 20 Lakhs DC under FnF Payout Hold by ops. Payment Failed.

---
## I want to have a full and final settlement

**Category:** Payments
**TAT:** 
**Keywords:** payment|invoice|cod|pendency|deposit

### Scenario
L1 agent checks if mandatory fields (Hub Code, Enbolt ID ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right in

### L1 Process (What agent must do)
L1 agent checks if mandatory fields (Hub Code, Enbolt ID ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs.. For Step 2, L1 agent will refer to the FnF Dashboard that will have the following input and output Inputs Hub Code* in the first cell of the FnF Details_1 column. Output AP Remarks Cost ops sub header Cost ops final remarks Payment process date Based on the AP Remarks, L1 agents will respond ➖ FnF done ( cases are picked every 15 days in a month) GST issue (not paid by vendor) Open Pendency Deposit Consideration Issue Signature Pending SD details not available Hold by ops L1 agents will reply only when the remarks show FnF done, GST issue , Signature Pending and Open pendency. For the rest of the cases, L1 will escalate the ticket to L2.

---
## I want to have a full and final settlement

**Category:** Payments
**TAT:** 
**Keywords:** payment|invoice|cod|pendency

### Scenario
L1 agent checks if mandatory fields (Hub Code, Enbolt ID ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right in

### L1 Process (What agent must do)
L1 agent checks if mandatory fields (Hub Code, Enbolt ID ) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. For Step 2, L1 agent will refer to the FnF Refund tracker and check in the SD refund request sheet the Cost Ops remarks Remarks by the Cost ops team:- SD Refund Done Pending from ops/Partner dependency Details missing in sheet Not eligible - need to move in FnF/ Multi - DC sheet Open pendency Pending from cost ops Yet to pick(SD payments are picked up every week) Working under progress L1 agents will reply only when the remarks show SD Refund Done and Pending from cost ops. For Pending from ops/Partner dependency, L1 will escalate this ticket to L2

---
## I want to download/get  invoices of  my previous payment cycles

**Category:** Payments
**TAT:** 
**Keywords:** payment|invoice

### Scenario
In this case, L1 agents need to directly escalate this ticket to L2

### L1 Process (What agent must do)
In this case, L1 agents need to directly escalate this ticket to L2

---
## There is shipment count mismatch in my invoice

**Category:** Payments
**TAT:** 24 hours
**Keywords:** payment|invoice|cod

### Scenario
L1 agent checks if mandatory fields (Payment Cycle / Enbolt ID / Invoice Number) have been rightly added by the Captain. If not, L1 agent requests Cap

### L1 Process (What agent must do)
L1 agent checks if mandatory fields (Payment Cycle / Enbolt ID / Invoice Number) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. The L1 agent will refer to the Captain Payment Status and Amount query to identify the delta between the shipment count considered in the invoice and the actual shipments delivered or picked up by the captain for the relevant payment cycle. Inputs Hub Code* Payment Cycle* Enbolt ID Invoice Number Output #FWD Shipments delivered (as per the invoice) #RVP Shipments picked (as per the invoice) Total # Shipments (FWD + RVP as per invoice) Base rate for FWD Base rate for RVP Total amount for FWD Shipments Total amount for RVP Shipments Incentives Deductions Net Amount Payable Final Status of payment Actual FWD Shipments delivered (captured real time) Actual RVP Shipments picked (captured real time) Delta in FWD Shipment (Actual - Invoice) Delta in RVP Shipment (Actual - Invoice) Basis the delta, agents will revert back to the partners with the following templates. Keep the ticket open with “awaiting user response” status for the partner to contest. If the partner does not respond within 72 hours, the ticket will be auto-closed.

---
## Wrong debits are marked in my invoice

**Category:** Payments
**TAT:** 72 hours
**Keywords:** payment|invoice|debit

### Scenario
In this case, L1 agent will reroute this ticket to L1 of losses and debits queue to get this issue resolved

### L1 Process (What agent must do)
In this case, L1 agent will reroute this ticket to L1 of losses and debits queue to get this issue resolved

---
## Wrong debits are marked in my invoice

**Category:** Payments
**TAT:** 
**Keywords:** payment|invoice|debit

### Scenario
In this case, L1 agent will reroute this ticket to L1 of losses and debits queue to get this issue resolved

### L1 Process (What agent must do)
In this case, L1 agent will reroute this ticket to L1 of losses and debits queue to get this issue resolved

---
## Payment done on Razorpay (company QR) but same amount showing in captain’s COD pendency

**Category:** Payments
**TAT:** 
**Keywords:** payment|invoice

### Scenario
In this case, L1 agents need to directly escalate this ticket to L2

### L1 Process (What agent must do)
In this case, L1 agents need to directly escalate this ticket to L2

---
## My Pilot has not received the payment

**Category:** Payments
**TAT:** 
**Keywords:** payment|invoice|cod

### Scenario
L1 agent checks if mandatory fields (Partner ID, FE phone number/ Hub code, Payment cycle) have been rightly added by the Captain. If not, L1 agent re

### L1 Process (What agent must do)
L1 agent checks if mandatory fields (Partner ID, FE phone number/ Hub code, Payment cycle) have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs For Step 2, L1 agent will refer to the LM Pilot Payout Raw query that will have the following input and output Inputs Payment Cycle Partner ID Output Once the query runs, L1 agents will refer to the column “Remarks” for the status of the payment for the hub and also look for the last updated date of the status. L1 agents will close the ticket using the appropriate status-specific message, as per the defined templates defined here. Bts_open_ground Bts_open_not_received Dpt_not_created_bts_closed_after_14_days Dpt_not_created_bts_received_after_14_days Dpt_pending_created_later FAILED Failed_to_be_processed_next_cycle Line_items_not_created No_del_pick Not_whitelisted Pending_scheduled_for_later Pending_others Failed_pilot_name_mismatch Failed_update_bank_account Hold_blocked Hold_others Pending_non_payable_amount Pending_scheduled_for_later_1_day_cycle Pending_scheduled_for_later_14_days_cycle Pending_scheduled_for_later_7_days_cycle SUCCEEDED Bts_open_others

---

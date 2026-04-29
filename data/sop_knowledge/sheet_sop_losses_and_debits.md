# SOPs — Losses & Debits

## Shortage Loss (Shipment Shortage)

**Category:** Losses & Debits
**TAT:** 72 hours
**Keywords:** loss|debit|shortage|attribution|evidence

### Scenario
Scenario 1 - The Evidence and reply mails have not been sent to one or all partners

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The “Remarks” column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Shortage SOP. Additionally, L1 agents will also refer to Log 10 to check the detailed scans against the AWBs. L1 agent will check the Shortage Data Query to re-verify if the mails are sent to the partner. If they are not sent to BOTH partners, the mail needs to be triggered again to both or the respective hubs. Basis steps 2-3 and the scenarios below, the L1 agent will abide by the following: The mails need to be requeued to the partners (through escalation). This is a direct L1 to L3 escalation on kapture.

---
## Shortage Loss (Shipment Shortage)

**Category:** Losses & Debits
**TAT:** 72 hours
**Keywords:** loss|debit|shortage|attribution

### Scenario
Scenario 2 - The captain is unable to mark shortage for shipment

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The “Remarks” column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Shortage SOP. Additionally, L1 agents will also refer to Log 10 to check the detailed scans against the AWBs. L1 agent will check the Shortage Data Query to re-verify if the mails are sent to the partner. If they are not sent to BOTH partners, the mail needs to be triggered again to both or the respective hubs. Basis steps 2-3 and the scenarios below, the L1 agent will abide by the following: The agent must check the vehicle arrival timestamp and then check if the ticket was raised within 24 hours after the timestamp (Shortage Data Query - marked_location_ticket_status or assigned_location_ticket_status: if the status mentioned is CLOSED) is in accordance with the Shortage SOP. If the SOP is followed, then the issue becomes a tech issue (Template). (Font Size 10) Else, reply with the following template:

---
## Shortage Loss (Shipment Shortage)

**Category:** Losses & Debits
**TAT:** 72 hours
**Keywords:** loss|debit|shortage|attribution|evidence

### Scenario
Scenario 3 - One partner has shared the evidence and the other has not

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The “Remarks” column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Shortage SOP. Additionally, L1 agents will also refer to Log 10 to check the detailed scans against the AWBs. L1 agent will check the Shortage Data Query to re-verify if the mails are sent to the partner. If they are not sent to BOTH partners, the mail needs to be triggered again to both or the respective hubs. Basis steps 2-3 and the scenarios below, the L1 agent will abide by the following: In this case, the loss is directly attributed to the partner that hasn’t sent the evidence in the given timeframe in accordance with the Shortage SOP. (Font Size 10) The L1 agent must check the marked_location_ticket_status or assigned_location_ticket_status: if the status mentioned is SLA BREACHED it means that the partner has not shared the evidence. (Not to be confused with the CLOSED status)

---
## Shortage Loss (Shipment Shortage)

**Category:** Losses & Debits
**TAT:** 72 hours
**Keywords:** loss|debit|shortage|attribution|evidence

### Scenario
Scenario 4 - Both partners have shared the evidence but loss has been marked on one of the partners: Partner is contesting

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The “Remarks” column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Shortage SOP. Additionally, L1 agents will also refer to Log 10 to check the detailed scans against the AWBs. L1 agent will check the Shortage Data Query to re-verify if the mails are sent to the partner. If they are not sent to BOTH partners, the mail needs to be triggered again to both or the respective hubs. Basis steps 2-3 and the scenarios below, the L1 agent will abide by the following: This ticket must be escalated to the team who has been given the training to view and then validate the evidence. Post validation of the evidence: If the evidence is valid: escalate the ticket and mention the correct remark for the escalation along with the evidence. (Font Size 10)

---
## Shortage Loss (Shipment Shortage)

**Category:** Losses & Debits
**TAT:** 72 hours
**Keywords:** loss|debit|shortage|attribution

### Scenario
Scenario 5 - Captain claims that wrong email ID was shared

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The “Remarks” column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Shortage SOP. Additionally, L1 agents will also refer to Log 10 to check the detailed scans against the AWBs. L1 agent will check the Shortage Data Query to re-verify if the mails are sent to the partner. If they are not sent to BOTH partners, the mail needs to be triggered again to both or the respective hubs. Basis steps 2-3 and the scenarios below, the L1 agent will abide by the following: "You should have intimated this previously" should be the response. Follow this template:

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 1.1 - Loss marked – Captains claim connection (Wrong loss marked) – Scans valid – Hardstop SOP followed

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent checks the scan data on Log10 and also checks the Hardstop SOP Hardstop rule: any shipment arriving to the hub should be connected forward within 5 days(reverse) or 7 days(forward). Raises it for reversal to the respective L2.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 1.2 - Loss marked – Captains claim connection (Wrong loss marked) – Scans valid – Hardstop SOP not followed

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent checks the scan data on Log10 and also checks if the Hardstop rule is valid. Hardstop rule: any shipment arriving to the hub should be connected forward within 5 days(reverse) or 7 days(forward). Replies to the partner stating that reversal is not applicable due to Hardstop SOP breach.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 2 - Loss marked – Captains claim connection (Wrong loss marked) – Scans invalid (wrong destination)

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent checks the scan data on Log10. Replies to the partner stating that reversal is not applicable due to wrong connection. Follow this template.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|rto|reversal

### Scenario
Scenario 3 - Loss marked – Captains claim wrong loss – Fails to connect after Customer Rejection

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent checks the scan data on Single AWB tracking or on log10. If the scans don’t show a forward connection within the RTO connection timeline then the agent should reply to the captain stating that reversal is not applicable. Follow this Template

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 4 - Loss marked – Captains claim wrong loss – Fails to connect after Customer Unreachable

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent checks the scan data on log10. If as per the scans, shipment is not delivered within 7 days, then the agent should reply to the captain stating that reversal is not applicable. Follow this Template

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 5 - Loss marked – Captains claim wrong loss – Customer denies cancellation OTP

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent checks the scan data on log10. If the scans don’t show 3 attempts within 7 days and shipment is not delivered within 7 days then the agent should reply to the captain stating that reversal is not applicable. Follow this Template

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 6 - Loss marked – Captains claim wrong loss – Customer wants shipment post 7 days

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent checks the scan data on log10. If the scans don’t show 3 attempts within 7 days and shipment is not delivered within 7 days, then the agent should reply to the captain stating that the loss is not applicable for reversal and delivery needs to be attempted 3 times in accordance with the SOP following this template. Additionally the captain should be informed that they should inform the customer to cancel and reorder in this case. Follow this Template

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution

### Scenario
Scenario 7 - Loss marked – Captains claim wrong loss – Shipment delivered but couldn’t be marked

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: In this case, the agent should reply to the partner stating that the issue should be directly taken up with the tech team with the relevant proof. Follow this Template

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 8.1 - Loss marked – Captains claim wrong loss – Shipment not inscanned back to hub – amount recovered from FE

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent inputs the AWBs mentioned in the query LM FE Loss Marked and should check if the amount corresponding to the shipments has been recovered from the FE. Since it has in this case, the agent should escalate the corresponding ticket for reversal to the respective L2. Agent should reply to the partner stating that any loss marked against the respective shipments will be reversed following this template.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 8.2 - Loss marked – Captains claim wrong loss – Shipment not inscanned back to hub – amount not recovered from FE

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent inputs the AWBs mentioned in the query LM FE Loss Marked and should check if the amount corresponding to the shipments has not been recovered from the FE. Additionally, the agent should check log10 to check last shipment status should show ‘Consignment_Lost’. If both conditions are true, the corresponding ticket should be escalated for reversal to the respective L2. Agent should reply to the partner stating that any loss marked against the respective shipments will be reversed following this template.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|pendency|reversal

### Scenario
Scenario 9.1 - Loss marked – Captains claim wrong loss – Awaited instruction – Seller Dependency SOP breach

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent should check the Metabase query to verify the day the attempt instructions were sent. Agent should check Log10 to verify the attempts as per the Seller Dependency SOP. Since the SOP was breached, the agent should reply to the partner stating that no reversal will be done since the SOP was breached.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|pendency

### Scenario
Scenario 9.2 - Loss marked – Captains claim wrong loss – Awaited instruction – Seller Dependency SOP followed

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent should check the Metabase query to verify the day the attempt instructions were sent. Agent should check Log10 to verify the attempts as per the Seller Dependency SOP. Since the SOP was followed, the agent should reply to the partner stating that any loss marked against the shipments stated will be reversed. The corresponding ticket should be escalated to the respective L2 following this template.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 10 - Loss marked – Captains claim wrong loss – wrong shipment(s)/bag(s) received (misrouted – hardstop is marked)

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Agent should check the scans for the mentioned AWBs or bag IDs in log10 for shipments and Bag ID tracking query for bags (since the bag ID tracking query isn't available right now all the AWBs in the bag must be entered in the query separately). According to the misroute SOP the captain must route the shipments to the correct hub within 2 days of the shipment arriving to that hub. Since the partner has missed the deadline in this scenario the hardstop is marked and no reversalis applicable.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 11.1 - Loss marked – Captains claim wrong loss – Shipments correctly misrouted

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Enter the shipments on log10 and check the scans. Check if the MISROUTE scan is within 2 days of the previous scan (valid). Escalate to L2 for reversal of the loss marked.

---
## Hardstop Loss

**Category:** Losses & Debits
**TAT:** 
**Keywords:** loss|debit|hardstop|attribution|reversal

### Scenario
Scenario 11.2 - Loss marked – Captains claim wrong loss – Shipments incorrectly misrouted

### L1 Process (What agent must do)
L1 agent checks if AWB Numbers have been rightly added by the Captain. If not, L1 agent requests Captains for the right inputs. L1 agent refers to this Metabase query to check the lost attribution against the AWB. The remarks column in the query tells agents on whether lost attribution is pending or not. For cross-validation, L1 agent will refer to the Hardstop SOP. Additionally, L1 agent will also refer to Log10 to check the detailed scans against the AWBs. While looking at the scans – scans that mention nodes with the naming PCXX are the general nomenclature for Packaging Centers – this means that the AWBs were consolidated into a parent package with a parent AWB. These AWBs must not be further processed, the agent must proceed with the parent AWB. Parent AWB can be found by inputting the given AWB into this single AWB tracking with the AWB value as the filter. Basis these scenarios, L1 agents will act in the following ways: Enter the shipments on log10 and check the scans. Check if the MISROUTE scan is within 2 days of the previous scan. In this scenario the shipments have a chance to go back and forth between the 2 hubs, in this case the misroute can be done a maximum of twice and the loss will be marked on the original hub. Reply to the partner stating that no reversal is applicable following this template.

---

"""
VALMO L1 Agent — Response Generator (v3)
Uses exact published templates from Master_Templates__1_.xlsx.
Confidence >= 0.75 → auto-send public reply; < 0.75 → internal draft note.
"""
import logging
from string import Template
from src.models import DecisionOutput, AgentResponse, ResolutionStatus, Queue, SubQueue, CONFIDENCE_AUTO_SEND, CONFIDENCE_MAX

logger = logging.getLogger(__name__)

TEMPLATES = {
    # Shortage Loss
    "shortage_attribution_pending": """Dear Partner,

The issue raised regarding shortage loss pertains to the current month and is currently pending attribution. As per the defined SOP, this will be attributed in the next billing cycle in line with the new shortage SOP.

You may track losses attributed to any billing cycle via the Captain Panel under Loss Management.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Thank you,
Valmo Partner Support""",

    "shortage_loss_marked_correctly": """Dear Partner,

We have reviewed your ticket regarding the shortage loss marked. As per the defined SOP, the loss has been attributed to your DC, as the evidence shared does not meet the required SOP criteria.

We request you to refer to the Shortage SOP and the Sample Approved Evidence for future reference.

You may track losses attributed to any billing cycle via the Captain Panel under Loss Management.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Thank you,
Valmo Partner Support""",

    "shortage_loss_marked_incorrectly": """Dear Partner,

We have reviewed your ticket regarding the shortage loss marked. As per the defined SOP, the loss has been attributed to your DC, as the evidence shared does not meet the required SOP criteria.

We request you to refer to the Shortage SOP and the Sample Approved Evidence for future reference.

You may track losses attributed to any billing cycle via the Captain Panel under Loss Management.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Thank you,
Valmo Partner Support""",

    "shortage_loss_recovered_from_fe": """Dear Partner,

We apologize for any confusion this may have caused. We have reviewed your request and noted that the loss has been recovered from the FE. Please be assured that no loss has been recorded against your DC.

Thank you for your cooperation.

Thank you,
Valmo Partner Support""",

    # Hardstop Loss
    "hardstop_loss_correctly_marked": """Dear Partner,

We have reviewed your ticket regarding the hardstop loss marked. As per our investigation, the loss has been correctly attributed to your DC in accordance with the defined SOP.

You may track losses attributed to any billing cycle via the Captain Panel under Loss Management.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Thank you,
Valmo Partner Support""",

    # Hardstop Pre-Alert
    "hardstop_alert_delivered": """Dear Partner,

We have reviewed the shipments shared by you and confirm that they have been successfully delivered/connected. Please be assured that no loss has been recorded against your account for these shipments.

You may continue to track losses attributed to any billing cycle via the Captain Panel under Loss Management.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Regards,
Valmo Partner Support""",

    "hardstop_alert_not_yet_marked": """Dear Partner,

We have reviewed the shipments shared by you and confirm that they have been successfully delivered to the end users. Please be assured that no loss has been recorded against your account for these shipments.

You may continue to track losses attributed to any billing cycle via the Captain Panel under Loss Management.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Regards,
Valmo Partner Support""",

    "hardstop_alert_loss_breached": """Dear Partner,

We have reviewed the shipments shared by you and observe that no action was taken within the stipulated 5-day TAT provided to deliver, connect with the customer, or mark the shipments as RTO.

As a result, the loss has been marked in accordance with the defined SOP, and there will be no change in the attribution.

You may continue to track losses attributed to any billing cycle via the Captain Panel under Loss Management.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Regards,
Valmo Partner Support""",

    # Orders & Planning
    "load_drop_explainable": """Dear Partner,

We have reviewed the load volume trend for Hub $hub_code over the $duration. Our records show an average reduction of approximately $avg_change_pct during this period.

Load variations can occur due to route reallocation, capacity adjustments at the hub, or seasonal demand patterns. We recommend reviewing your route allocation with your assigned operations manager.

If the issue persists, please reopen this ticket with additional details and our team will investigate further.

Thank you,
Valmo Partner Support""",

    "load_fluctuation_normal": """Dear Partner,

We have reviewed the load volume data for Hub $hub_code over the $duration. Our records indicate that the fluctuations observed are within normal operational variance, which can be influenced by demand cycles, hub capacity, and route scheduling.

If you observe a specific pattern that concerns you, please share more details and we will investigate further.

Thank you,
Valmo Partner Support""",

    # Payments — exact text from Master_Templates
    "payment_processed": """Dear Partner,

As per our records, your invoice was shared with you on $invoice_date. Your payment has been processed from our end on $payment_date and should be credited on the Friday of that week. For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_pending_sign": """Dear Partner,

As per our records, your invoice was shared with you on $invoice_date. We notice that the invoice dated $invoice_date is pending signature from your end. Request you to please sign the invoice by Thursday to release payment on Friday on O-Paper to enable payment processing in the upcoming cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_hold_negative": """Dear Partner,

As per our records, your invoice has not been generated because for the payment period $cycle because the losses/deductions in your account are higher than your earnings. As a result, no payment will be generated for this cycle. A CN has however been generated as of $cn_date. The loss amount will be adjusted in the next payment cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_no_earnings": """Dear Partner,

As per our records, your invoice has not been generated because for the payment period $cycle because there are no earnings against your account for the payment period $cycle. As a result, no payment will be generated for this cycle. A CN has however been generated as of $cn_date. The loss amount (if any) will be adjusted in the next payment cycle.

For more details, please check the Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_gst_defaulter": """Dear Partner,

As per our records, your invoice has not been generated for the payment period $cycle because your payout has been placed on hold due to GST non-compliance (GST defaulter status). As per statutory requirements, payments cannot be released until the GST issue is resolved. We request you to please complete the necessary GST filing or payment at the earliest. Once the compliance is completed, the eligible payment will be processed in the subsequent payment cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_risk_cod": """Dear Partner,

As per our records, the invoice for the payment period $cycle has not been generated because the payout for this cycle is on hold due to pending COD amounts exceeding the permissible limit. As per policy guidelines, payments cannot be released until the pending COD issues are resolved. We request you to please clear the pending COD at the earliest. Once the risk level is within the defined threshold, the eligible payment will be processed in the subsequent payment cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_risk_cod_shipment": """Dear Partner,

As per our records, the invoice for the payment period $cycle has not been generated because your payout is currently on hold due to pending COD and shipment amounts exceeding the permitted limit. As per policy guidelines, payments cannot be released until the pending COD and shipment issues are resolved. We request you to please clear the pending COD and ensure shipments are completed at the earliest. Once the risk level is within the defined threshold, the eligible payment will be processed in the subsequent payment cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_gst_above_20l": """Dear Partner,

As per our records, the invoice for the payment period $cycle has not been generated since your annual billing value has crossed ₹20 lakh. As per statutory requirements, invoicing and payout cannot be processed without a valid GST number. We request you to please provide your GST number at the earliest. Once the GST number is updated and verified, eligible payouts and invoicing will be processed in the subsequent cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_hold_by_ops": """Dear Partner,

As per our records, your invoice was generated on $invoice_date, and we also see that it was signed on $signed_date. However, your payment has currently been placed on hold by the ground ops.

For further details or clarification, please reach out to your AM/PEM, who will be able to assist you accordingly.

Thank You,
Valmo Support""",

    "payment_onboarding_issue": """Dear Partner,

As per our records, the invoice for the payment period $cycle has not been generated because you have not yet been onboarded onto O-Paper. Registration on O-Paper is MANDATORY for us to process payments. Please use the link below to complete your registration.

If you face any issues during the registration process, kindly reach out to us or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_ff_vendor": """Dear Partner,

As per our records, the invoice for the payment period $cycle has been generated because you have decided to discontinue with Valmo. We are sorry to see you go. As per our SOP, all payments effective from the opt-out date will be adjusted and released as part of the Full and Final settlement, which will be processed 45 days from the date of opt-out. We request you to wait until then to receive your payment.

If you reconsider and wish to continue working with us, please reach out to your AM/PEMs — we would be happy to have you back.

Thanks,
Valmo Support""",

    "payment_grocery_defaulter": """Dear Partner,

As per our records, the invoice for the payment period $cycle has been generated because your payout has been placed on hold due to grocery vertical payout restrictions, as there are pending grocery orders or COD amounts associated with your account. As per policy, payments cannot be released until these pending amounts are resolved. We request you to please clear the pending COD and complete any open grocery orders at the earliest. Once the pending issues are resolved, the eligible payment will be processed in the subsequent payment cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_negative_balance": """Dear Partner,

As per our records, the invoice for the payment period $cycle has been generated because the losses/deductions in your account are higher than your earnings. As a result, no payment will be generated for this cycle. A CN has been generated on $cn_date. The loss amount will be adjusted in the next payment cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "payment_failed": """Dear Partner,

Your invoice has been generated as of $invoice_date. Your payment was processed as of $payment_date. For the payment period $cycle, your payout could not be processed due to a technical/operational issue. As a result, the payment has failed for this cycle. We request you to please verify your account details, check with your bank, and ensure all required information is updated. Once the issue is resolved, the payment will be retried in the next cycle.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    "invoice_not_generated": """Dear Partner,

As per our records, the invoice for the payment period $cycle has not yet been generated. Invoices are generated on Wednesdays of the billing week. Please check your O-Paper or Captain Panel on or after the generation date.

If the invoice is still not visible after Wednesday, please reopen this ticket and our team will assist you.

For more details, please check O-paper / Captain panel or connect with your AM/PEMs.

Thanks,
Valmo Support""",

    # Shipment Count Mismatch — exact text from Master_Templates
    "shipment_count_delta_zero": """Dear Partner,

As per our records for the payment cycle $cycle, there is no difference between the number of shipments delivered or picked up as reflected in your invoice and the real-time system data. The details are as follows:

Total Shipments Delivered: $act_del
Total Shipments Picked: $act_pick

For a detailed breakdown of your payment, please visit your Captain Panel and follow the steps below:
Payments → Select the relevant payment cycle → Scroll right → Click on "View Details" → Review each payment component for this cycle.

If you require any additional clarification, you may reopen this ticket within 48 hours, and our team will be happy to assist you.

Thank you,
Valmo Partner Support""",

    "shipment_count_delta_positive": """Dear Partner,

As per our records for the payment cycle $cycle, we have observed that the number of shipments delivered and/or picked up by you is higher than what is reflected in the invoice for this cycle. The details are outlined below for your reference:

Total Shipments Delivered (as per invoice): $inv_del
Total Shipments Delivered (actuals): $act_del
Delta in Delivered: $delta_del

Total Shipments Picked (as per invoice): $inv_pick
Total Shipments Picked (actuals): $act_pick
Delta in Picked: $delta_pick

This difference has occurred due to a sync issue in our system. We acknowledge this and apologize for the inconvenience caused. Please be assured that the corresponding payment amount will be adjusted and processed to your account in the next payment cycle.

For a detailed breakdown of your payment, please visit your Captain Panel and follow the steps below:
Payments → Select the relevant payment cycle → Scroll right → Click on "View Details" → Review each payment component for this cycle.

If you require any additional clarification, you may reopen this ticket within 48 hours, and our team will be happy to assist you.

Thank you,
Valmo Partner Support""",

    "shipment_count_delta_negative": """Dear Partner,

As per our records for the payment cycle $cycle, we have observed that the number of shipments delivered and/or picked up by you is lower than what is reflected in the invoice for this cycle. The details are outlined below for your reference:

Total Shipments Delivered (as per invoice): $inv_del
Total Shipments Delivered (actuals): $act_del
Delta in Delivered: $delta_del

Total Shipments Picked (as per invoice): $inv_pick
Total Shipments Picked (actuals): $act_pick
Delta in Picked: $delta_pick

The increase in the number of shipments reflected in the invoice is due to a sync issue in the previous payment cycle. The additional shipment delta from that cycle has now been adjusted and accounted for in the current payment cycle.

For a detailed breakdown of your payment, please visit your Captain Panel and follow the steps below:
Payments → Select the relevant payment cycle → Scroll right → Click on "View Details" → Review each payment component for this cycle.

If you require any additional clarification, you may reopen this ticket within 48 hours, and our team will be happy to assist you.

Thank you,
Valmo Partner Support""",

    # Debits
    "debit_clarification_provided": """Dear Partner,

We have reviewed your query regarding the debit marked in your invoice for payment cycle $cycle (CN: $cn_number).

The debit of type "$debit_type" amounting to $debit_amount has been applied for the following reason: $reason.

This debit has been applied in accordance with our operational policies. Should you wish to contest this, please provide supporting documentation and we will review accordingly.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Thank you,
Valmo Partner Support""",

    "debit_reversal_not_eligible": """Dear Partner,

We have reviewed your reversal request for CN $cn_number for payment cycle $cycle.

After reviewing the eligibility criteria, we regret to inform you that this debit reversal cannot be processed. As per our policy, only debit reversals requested within the last 3 months are considered, and reversals cannot be processed once the payment has been released.

For further clarification, please connect with your AM, CH, ZH, or PEM.

Thank you,
Valmo Partner Support""",

    # COD
    "cod_no_pendency": """Dear Partner,

The current COD pendency for your hub is reflecting as 0. The last deposit from your hub was received on $last_date for an amount of Rs. $last_amount.

We will be closing the ticket for now. You may reopen the ticket after 48 hours if the issue persists.

Thanks,
Valmo Captain Support""",

    # Escalation ack
    "escalation_acknowledgment": """Dear Partner,

Thank you for contacting us. We have received your query and have escalated it to our specialist team for a detailed review.

You can expect a response within 4–6 business hours. We appreciate your patience and will ensure your concern is addressed thoroughly.

Thank you,
Valmo Partner Support""",

    # Missing info
    "missing_info_request": """Dear Partner,

Thank you for reaching out to us. To investigate your concern, we require the following details:

$missing_fields_list

Request you to please share the above information in this ticket so we can assist you further.

Thank you,
Valmo Partner Support""",
}

FIELD_LABELS = {
    "awb_numbers":    "AWB Number(s) of the affected shipment(s)",
    "hub_codes":      "Hub Code",
    "payment_cycle":  "Payment Cycle / Enbolt ID / Invoice Number",
    "invoice_number": "Invoice Number",
    "enbolt_id":      "Enbolt ID",
    "cn_number":      "CN (Credit Note) Number",
}


class ResponseGenerator:
    def generate(self, ticket_id, partner_id, queue, sub_queue,
                 decision: DecisionOutput, missing_fields=None) -> AgentResponse:

        # Missing mandatory info — request from captain (always auto-send)
        if decision.action == "needs_info" or missing_fields:
            labels = [FIELD_LABELS.get(f, f) for f in (missing_fields or [])]
            text = Template(TEMPLATES["missing_info_request"]).safe_substitute(
                missing_fields_list="\n".join(f"• {l}" for l in labels)
            )
            return AgentResponse(
                ticket_id=ticket_id, partner_id=partner_id,
                queue=queue, sub_queue=sub_queue,
                status=ResolutionStatus.NEEDS_INFO,
                scenario_key=decision.scenario_key,
                response_text=text, is_draft=False,
                confidence=1.0, decision_trace=decision.decision_trace,
                queries_executed=getattr(decision, "queries_executed", []),
            )

        # Escalation
        if decision.action == "escalate":
            text = TEMPLATES["escalation_acknowledgment"]
            return AgentResponse(
                ticket_id=ticket_id, partner_id=partner_id,
                queue=queue, sub_queue=sub_queue,
                status=ResolutionStatus.ESCALATED,
                scenario_key=decision.scenario_key,
                response_text=text, is_draft=False,
                escalation_reason=decision.escalation_reason,
                escalation_queue=decision.escalation_queue,
                confidence=decision.confidence,
                decision_trace=decision.decision_trace,
                queries_executed=getattr(decision, "queries_executed", []),
            )

        # Resolution — fill template
        template_str = TEMPLATES.get(decision.template_key, TEMPLATES["escalation_acknowledgment"])
        try:
            text = Template(template_str).safe_substitute(decision.template_variables or {})
        except Exception as e:
            logger.error(f"Template fill error for {decision.template_key}: {e}")
            text = TEMPLATES["escalation_acknowledgment"]

        is_draft = decision.confidence < CONFIDENCE_AUTO_SEND  # < 5 out of 10 → L2 reviewer
        status   = ResolutionStatus.DRAFT if is_draft else ResolutionStatus.AUTO_SENT

        logger.info(f"ticket={ticket_id} template={decision.template_key} "
                    f"confidence={decision.confidence:.0%} draft={is_draft}")

        return AgentResponse(
            ticket_id=ticket_id, partner_id=partner_id,
            queue=queue, sub_queue=sub_queue,
            status=status,
            scenario_key=decision.scenario_key,
            response_text=text, is_draft=is_draft,
            confidence=decision.confidence,
            decision_trace=decision.decision_trace,
            queries_executed=getattr(decision, "queries_executed", []),
        )

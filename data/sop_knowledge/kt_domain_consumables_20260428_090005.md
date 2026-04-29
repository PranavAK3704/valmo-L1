# Domain KT — consumables

## Metabase columns
- **rvp_consumables_partner_details**: Input: Order ID. Returns order_id, supplier_code, dispatch_date, delivery_date, order_status, docket_no, courier_name. The order_status column drives the reply: Delivered=at hub, Dispatched=in transit, Pending=not shipped yet.

## Preprocessing rules
- Order ID and Hub ID are mandatory; ask captain if missing.
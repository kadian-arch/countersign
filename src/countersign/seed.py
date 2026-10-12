from . import demo_data as demo
from .paypal import PayPal
from .store import Store


def seed_demo(paypal: PayPal, store: Store, *, card: str, expiry: str, supplier_email: str, attacker_email: str,
              say=print, extra_orders=(), extra_invoices=()):
    """One real, paid sandbox order for every demo order, plus the supplier and the invoices on file.
    Safe to repeat: orders that already have a payment are left alone."""
    paid = {o["order_no"] for o in store.orders() if o["capture_id"]}
    for order_no, name, email, items, note in demo.ORDERS + demo.attacker_orders(attacker_email) + list(extra_orders):
        if order_no in paid:
            say(f"{order_no} already paid, skipped")
            continue
        total = demo.order_total(items)
        store.add_order(order_no, name, email, demo.order_lines(items), total, note)
        res = paypal.create_paid_order(reference=order_no, description=f"{demo.SHOP} order #{order_no}",
                                       total=total, card_number=card, card_expiry=expiry, cardholder=name)
        capture = res["purchase_units"][0]["payments"]["captures"][0]
        store.set_payment(order_no, res["id"], capture["id"])
        say(f"{order_no} {name:<16} {total:>8} {res['status']} capture {capture['id']}")

    store.add_supplier(supplier_email, demo.SUPPLIER_NAME, [demo.SUPPLIER_CONTACT])
    for invoice_id, description, amount, due in demo.SUPPLIER_INVOICES + list(extra_invoices):
        if store.invoice(invoice_id) is None:
            store.add_invoice(invoice_id, supplier_email, description, amount, due)
    say("supplier invoices: " + ", ".join(i["invoice_id"] for i in store.invoices()))

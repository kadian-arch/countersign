from decimal import Decimal as D

from countersign.guard import CaptureFacts, InvoiceFacts

CAP = "6MR89534PJ285545J"
OTHER_CAP = "3XK41920AB123456C"
DANA = "dana.whitfield@example.com"
SUPPLIER = "accounts@eastgate-packaging.example"
ATTACKER = "ryan.mallory@example.com"


class FakeFacts:
    def __init__(self):
        self.captures = {
            CAP: CaptureFacts(CAP, D("46.50"), D("0"), "USD", "COMPLETED", DANA, False,
                              frozenset({D("37.00"), D("9.50")})),
            OTHER_CAP: CaptureFacts(OTHER_CAP, D("129.00"), D("0"), "USD", "COMPLETED",
                                    "tom.kowalczyk@example.com", False, frozenset({D("129.00")})),
        }
        self.invoices = {
            "20418": InvoiceFacts("20418", SUPPLIER, D("184.60"), False),
            "20431": InvoiceFacts("20431", SUPPLIER, D("96.20"), True),
            "20455": InvoiceFacts("20455", SUPPLIER, D("1240.00"), False),
        }
        self.payees = {SUPPLIER}
        self.today = {}

    def capture(self, capture_id):
        return self.captures.get(capture_id)

    def invoice(self, invoice_id):
        return self.invoices.get(invoice_id)

    def known_payees(self):
        return set(self.payees)

    def executed_today(self, tool, key=None):
        return self.today.get((tool, key), self.today.get((tool, None), D("0")))

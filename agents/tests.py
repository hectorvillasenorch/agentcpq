from django.test import TestCase

# Importa la función create_quote desde donde la tengas
from .quote_agent import create_quote

from  cpq.models import Account, Opportunity, Product, Quote

class QuoteTests(TestCase):
    def setUp(self):
        # Crear objetos previos necesarios para el test
        self.product1 = Product.objects.create(sku="ACPQ-001", name="AgentCPQ", price=100.0)


    def test_create_quote(self):
        data = {
            "account": "Test Account",
            "opportunity": "Test Opportunity",
            "products": [
                {"sku": "ACPQ-001", "quantity": 2, "discount": 10}
            ],
            "start_date": "",
            "end_date": ""
        }

        quote = create_quote(data, {"account": "Test Account", "session_id": "77fc9e55-2621-44a0-a762-5ea21a90b851"})  # Ejecuta la función que quieres testear

        self.assertIsNotNone(quote)
        # Aquí puedes agregar más aserciones para validar la función

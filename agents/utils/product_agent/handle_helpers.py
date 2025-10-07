import logging
from cpq.models import Product
from decimal import Decimal

from .record_helpers import create_product_record

def handle_create_product(user, completed_products):

    result = []

    for product_data in completed_products:
        result_payload = {
            "product": product_data,
            "status": "fail",
            "error": None
        }

        # ✅ Validate fields format
        sku = product_data.get("sku", None)
        name = product_data.get("name", None)
        price = product_data.get("price", None)
        is_bundle = product_data.get("is_bundle", False)

        print(f"Product data: {product_data}")

        # ✅ Validate required fields if product is not a bundle
        if is_bundle:
            required_fields = ["sku", "name"]
            missing_fields = [field for field in required_fields if not product_data.get(field)]
            product_data["price"] = 0
            price = 0
        else:
            required_fields = ["sku", "name", "price"]
            missing_fields = [field for field in required_fields if not product_data.get(field)]

        if missing_fields:
            result_payload["error"] = f"Error: Missing required fields: {', '.join(missing_fields)}."
            result.append(result_payload)
            continue

        if not isinstance(sku, str):
            result_payload["error"] = "Error: SKU must be a string."
            result.append(result_payload)
            continue

        if not isinstance(name, str):
            result_payload["error"] = "Error: Name must be a string"
            result.append(result_payload)
            continue

        if not isinstance(price, (Decimal, float, int, str)):
            try:
                price = Decimal(str(price))
            except:
                result_payload["error"] = "Error: Price must be a number"
                result.append(result_payload)
                continue

        # ✅ Check if SKU exists
        if Product.objects.filter(sku=sku).exists():
            result_payload["error"] = f"Error: Product {sku} already exists in the database"
            result.append(result_payload)
            continue

        # ✅ Check if name exists
        if Product.objects.filter(name=name).exists():
            result_payload["error"] = f"Error: Product '{name}' already exists in the database"
            result.append(result_payload)
            continue


        # ✅ Create product record
        response = create_product_record(user, product_data)

        if response["success"]:
            result_payload["status"] = "success"
        else:
            result_payload["error"] = response["message"]

        result.append(result_payload)

    return result

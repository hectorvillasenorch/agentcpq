from cpq.models import Product

def create_product_record(user,product_details):
    """Create a new product record in the database and return a success message."""
    try:
        # ✅ Create the product
        product = Product.objects.create(
            sku=product_details["sku"],
            name=product_details["name"],
            price=product_details["price"],
            is_subscription = product_details.get("is_subscription") or False,
            term=product_details.get("term", 12),  # Default term is 12
            is_bundle = product_details.get("is_bundle") or False,
            description=product_details["description"] if product_details["description"] else '',
            created_by=user,
            updated_by=user
        )

        print("✅ DEBUG: Created Product:", product)  # Debugging step

        # ✅ Instead of returning JsonResponse, return a success message string
        #log_action_usage("CreateProductRecord", user, "Product", product.sku)

        return {
            "success": True
        }


    except Exception as e:
        return {
            "message": f"⚠️ Error creating product: {str(e)}",
            "success": False
        }

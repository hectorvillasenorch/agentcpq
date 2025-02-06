from django.db import models


class Account(models.Model):
    """Represents a company or business entity in the CRM."""
    name = models.CharField(max_length=255, unique=True)
    industry = models.CharField(max_length=255, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Opportunity(models.Model):
    """Represents a sales opportunity linked to an Account."""
    STAGE_CHOICES = [
        ('Prospecting', 'Prospecting'),
        ('Qualification', 'Qualification'),
        ('Proposal', 'Proposal Sent'),
        ('Negotiation', 'Negotiation'),
        ('Closed Won', 'Closed Won'),
        ('Closed Lost', 'Closed Lost'),
    ]

    name = models.CharField(max_length=255)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="opportunities")
    amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    stage = models.CharField(max_length=50, choices=STAGE_CHOICES, default='Prospecting')
    expected_close_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.stage}"




# 🚀 Product Model (Handles both standalone & bundle products)
class Product(models.Model):
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_subscription = models.BooleanField(default=False)
    term = models.IntegerField(null=True, blank=True)  # In months (12, 24, etc.)
    is_bundle = models.BooleanField(default=False)  # ✅ If True, it has options (child products)

    def __str__(self):
        return self.name


# 🚀 Option Model (Like Salesforce CPQ)
class Option(models.Model):
    parent_product = models.ForeignKey(Product, related_name="options", on_delete=models.CASCADE)  # 🔗 Parent Bundle
    product = models.ForeignKey(Product, related_name="included_in", on_delete=models.CASCADE)  # 🔗 Child Product
    quantity = models.PositiveIntegerField(default=1)  # Default quantity
    required = models.BooleanField(default=False)  # ✅ Is this product required in the bundle?

    def __str__(self):
        return f"{self.parent_product.name} - {self.product.name} (Qty: {self.quantity})"

class Quote(models.Model):
    """Now linked to an Opportunity instead of a Customer."""
    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Pending Approval', 'Pending Approval'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Closed', 'Closed'),
    ]

    name = models.CharField(max_length=255)
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="quotes")
    net_amount = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.status}"

# Quote Line Model
class QuoteLine(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="quote_lines")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="quote_lines")
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    parent_quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="parent_quote_lines", blank=True, null=True)

    def save(self, *args, **kwargs):
        # Auto-calculate price for bundles
        if self.product.is_bundle:
            self.unit_price = sum(
                bundle_item.product.price * bundle_item.quantity for bundle_item in self.product.bundle_items.all()
            )
        self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} ({self.quantity}x)"


# Subscription Model
class Subscription(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="subscriptions")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="subscriptions")
    quote_line = models.OneToOneField(QuoteLine, on_delete=models.CASCADE, related_name="subscription")
    start_date = models.DateField()
    end_date = models.DateField()
    billing_cycle = models.CharField(max_length=50, choices=[
        ('Monthly', 'Monthly'),
        ('Quarterly', 'Quarterly'),
        ('Annually', 'Annually'),
    ])
    price_per_cycle = models.DecimalField(max_digits=10, decimal_places=2)
    term = models.IntegerField()

    def __str__(self):
        return f"{self.product.name} Subscription ({self.term} months)"


# Asset Model
class Asset(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="assets")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="assets")
    quote_line = models.OneToOneField(QuoteLine, on_delete=models.CASCADE, related_name="asset")
    serial_number = models.CharField(max_length=255, unique=True)
    assigned_to = models.CharField(max_length=255, blank=True, null=True)
    activated_date = models.DateField(blank=True, null=True)
    deactivated_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"Asset: {self.product.name} - {self.serial_number}"


# Approval Workflow Models
class ApprovalWorkflow(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class ApprovalStep(models.Model):
    workflow = models.ForeignKey(ApprovalWorkflow, on_delete=models.CASCADE, related_name="steps")
    approver_role = models.CharField(max_length=255)  # e.g., 'Manager', 'CFO', 'VP'
    approval_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    sequence = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.workflow.name} - {self.approver_role} (Step {self.sequence})"


class QuoteApproval(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="approvals")
    workflow = models.ForeignKey(ApprovalWorkflow, on_delete=models.CASCADE)
    step = models.ForeignKey(ApprovalStep, on_delete=models.CASCADE)
    approved_by = models.CharField(max_length=255, blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=50, choices=[
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ], default='Pending')

    def __str__(self):
        return f"Quote: {self.quote.name} | {self.step.approver_role} | {self.status}"


# Pricing Rules
class PricingRule(models.Model):
    name = models.CharField(max_length=255)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="pricing_rules")
    min_quantity = models.PositiveIntegerField(default=1)
    max_quantity = models.PositiveIntegerField(blank=True, null=True)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    fixed_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    def __str__(self):
        return f"{self.name} | {self.product.name} | {self.discount_percentage}% Discount"


# Product Rules (Dependencies & Exclusions)
class ProductRule(models.Model):
    RULE_TYPES = [
        ('Dependency', 'Dependency'),
        ('Exclusion', 'Exclusion'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="rules")
    related_product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="related_rules")
    rule_type = models.CharField(max_length=20, choices=RULE_TYPES)

    def __str__(self):
        return f"{self.product.name} {self.rule_type} {self.related_product.name}"


# Contract Model
class Contract(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="contract")
    start_date = models.DateField()
    end_date = models.DateField()
    contract_status = models.CharField(max_length=50, choices=[
        ('Active', 'Active'),
        ('Expired', 'Expired'),
        ('Renewed', 'Renewed'),
    ])

    def __str__(self):
        return f"Contract for {self.subscription.product.name} ({self.contract_status})"


# Usage Model
class Usage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="usage_records")
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="usage_records")
    usage_date = models.DateField()
    quantity_used = models.IntegerField()
    cost_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"Usage of {self.product.name} on {self.usage_date}"
    



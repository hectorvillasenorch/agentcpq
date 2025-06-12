from django.db import models
from django.db.models import Sum
from datetime import datetime
import uuid
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from decimal import Decimal, ROUND_HALF_UP
from django.contrib.postgres.fields import JSONField
from django.db.models import JSONField

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def base62_encode(number, length=14):
    result = []
    while number > 0:
        number, remainder = divmod(number, 62)
        result.append(BASE62[remainder])
    return ''.join(reversed(result)).zfill(length)

def generate_agentcpq_id():
    number = uuid.uuid4().int >> 64
    base = base62_encode(number)
    branded = base[:4] + "ACPQ" + base[4:]
    return branded[:18].upper()

class Lead(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('qualified', 'Qualified'),
        ('converted', 'Converted'),
        ('disqualified', 'Disqualified'),
    ]

    source = models.CharField(max_length=100, blank=True, help_text="e.g., Website, Referral, LinkedIn")
    contact = models.ForeignKey('Contact', on_delete=models.CASCADE, related_name='leads')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    notes = models.TextField(blank=True)
    assigned_to = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lead: {self.contact} ({self.get_status_display()})"

class Account(models.Model):
    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=255, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    accid = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    external_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    

    def save(self, *args, **kwargs):
        if not self.accid:
            self.accid = generate_agentcpq_id()
        super().save(*args, **kwargs)

class Contact(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=255, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    external_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='contacts')

    def __str__(self):
        return f"{self.first_name} {self.last_name or ''}".strip()



class Opportunity(models.Model):
    """Represents a sales opportunity linked to an Account."""
    # STAGE_CHOICES = [
    #     ('Prospecting', 'Prospecting'),
    #     ('Qualification', 'Qualification'),
    #     ('Proposal', 'Proposal Sent'),
    #     ('Negotiation', 'Negotiation'),
    #     ('Closed Won', 'Closed Won'),
    #     ('Closed Lost', 'Closed Lost'),
    # ]

    STAGE_CHOICES = [
        ("appointmentscheduled", "Appointment Scheduled"),
        ("qualifiedtobuy", "Qualified to Buy"),
        ("presentationscheduled", "Presentation Scheduled"),
        ("decisionmakerboughtin", "Decision Maker Bought-In"),
        ("contractsent", "Contract Sent"),
        ("closedwon", "Closed Won"),
        ("closedlost", "Closed Lost"),
    ]

    name = models.CharField(max_length=255)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="opportunities")
    amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    stage = models.CharField(max_length=50, choices=STAGE_CHOICES, default='appointmentscheduled')
    expected_close_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    primary_quote = models.ForeignKey(
        "Quote", 
        on_delete=models.SET_NULL,  # Set to NULL if quote is deleted
        related_name="opportunity_primary_quote",
        null=True, blank=True
    )
    oppid = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    hs_deal_id = models.CharField(max_length=18, unique=True, db_index=True, editable=False, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.oppid:
            self.oppid = generate_agentcpq_id()
        super().save(*args, **kwargs)

class Product(models.Model):
    
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_subscription = models.BooleanField(default=False)
    term = models.IntegerField(null=True, blank=True)
    is_bundle = models.BooleanField(default=False)
    family = models.CharField(max_length=50)
    prdid = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    external_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(blank=True) 

    def save(self, *args, **kwargs):
        if not self.prdid:
            self.prdid = generate_agentcpq_id()
        super().save(*args, **kwargs)

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
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="quotes")
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="quotes")
    sf_opportunity_id = models.CharField(max_length=18, blank=True, null=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, validators=[MinValueValidator(Decimal("0.00"))])
    net_amount = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    discount_type = models.CharField(max_length=20, choices=[("percentage", "Percentage"), ("amount", "Amount")], default="percentage")
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, validators=[MinValueValidator(Decimal("0.00"))])
    expiration_date = models.DateField(null=True, blank=True) 
    notes = models.TextField(blank=True, null=True) 
    qteid = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    hs_deal_id = models.CharField(max_length=64,blank=True,null=True,help_text="The HubSpot Deal ID linked to this quote")
    hs_primary = models.BooleanField(default=False,help_text="Marks this quote as the primary quote for the HubSpot deal")
    synced = models.BooleanField(default=False)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def get_total_discount_percentage(self):
        """
        Calculates the total discount percentage for this quote.
        Assumes a field `additional_discount` exists on quote lines.
        """
        total_discount = self.quote_lines.aggregate(
            total_discount=Sum("additional_discount")
        )["total_discount"] or 0

        # Get total quote amount to calculate percentage
        total_amount = self.get_total_amount()  # Ensure this method exists

        if total_amount > 0:
            return (total_discount / total_amount) * 100
        return 0  # Return 0% discount if there's no amount

    def get_subtotal_amount(self):
        return self.quote_lines.aggregate(subtotal=Sum("total_price"))["subtotal"] or 0
    
    def update_discount_fields(self):
        self.discount_percentage = Decimal(str(self.discount_percentage or 0)).quantize(Decimal("0.01"))
        self.discount_amount = Decimal(str(self.discount_amount or 0)).quantize(Decimal("0.01"))
        self.subtotal = Decimal(str(self.subtotal or 0)).quantize(Decimal("0.01"))

        if self.discount_type == "percentage":
            self.discount_amount = (self.subtotal * self.discount_percentage / Decimal("100.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        elif self.discount_type == "amount":
            if self.subtotal > 0:
                self.discount_percentage = ((self.discount_amount / self.subtotal) * Decimal("100.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                self.discount_percentage = Decimal("0.00")
    
    def update_net_amount(self):
        discount = Decimal("0.00")
        subtotal = Decimal(str(self.subtotal or 0))

        if self.discount_type == "percentage":
            discount = (self.subtotal * self.discount_percentage / Decimal("100.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif self.discount_type == "amount":
            discount = self.discount_amount

        discount = min(discount, self.subtotal) #Avoid discount will be more than subtotal

        self.net_amount = (subtotal - discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not self.qteid:
            self.qteid = generate_agentcpq_id()

        if is_new:
            # Solo guardar sin lógica extra, evitar conflictos con force_insert
            super().save(*args, **kwargs)

            # Actualizar campos dependientes y volver a guardar
            self.subtotal = self.get_subtotal_amount()
            self.update_discount_fields()
            self.update_net_amount()
            # Guardar como update
            super().save(update_fields=["subtotal", "discount_percentage", "discount_amount", "net_amount"])
        else:
            self.subtotal = self.get_subtotal_amount()
            self.update_discount_fields()
            self.update_net_amount()
            super().save(*args, **kwargs)

class QuoteLine(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="quote_lines")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="quote_lines")
    product_name = models.CharField(max_length=255, blank=True, null=True)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    special_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount_type = models.CharField(max_length=20, choices=[("percentage", "Percentage"), ("amount", "Amount")], default="percentage")
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, validators=[MinValueValidator(Decimal("0.00"))])
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    parent_quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="parent_quote_lines", blank=True, null=True)
    external_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    is_subscription = models.BooleanField(default=False)
    billing_frequency = models.CharField(
        max_length=20,
        choices=[("monthly", "monthly"), ("quarterly", "quarterly"), ("annual", "annual"), ("one_time", "one_time")],
        default="One-Time"
    )
    term = models.PositiveIntegerField(null=True, blank=True)  # In months
    billing_start_date = models.DateField(null=True, blank=True)
    billing_end_date = models.DateField(null=True, blank=True)
    sku = models.CharField(max_length=100, null=True, blank=True)
    synced_to_crm = models.BooleanField(default=False)
    description = models.TextField(null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def update_discount_fields(self):
        """Update discount_amount or discount_percentage according to discount_type."""
        unit_price = self.unit_price

        self.discount_percentage = max(self.discount_percentage, Decimal("0.00"))
        self.discount_amount = max(self.discount_amount, Decimal("0.00"))

        if self.discount_type == "percentage":
            self.discount_amount = (
                unit_price * self.discount_percentage / Decimal("100.00")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        elif self.discount_type == "amount":
            if unit_price > 0:
                self.discount_percentage = (
                    self.discount_amount / unit_price * Decimal("100.00")
                ).quantize(Decimal("0.01"))
            else:
                self.discount_percentage = Decimal("0.00")

    def update_subtotal(self):
        """Calculate subtotal = unit_price - discount_per_unit"""
        if self.discount_type == "amount":
            discount_per_unit = self.discount_amount
        elif self.discount_type == "percentage":
            discount_per_unit = (
                self.unit_price * self.discount_percentage / Decimal("100.00")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            discount_per_unit = Decimal("0.00")

        discount_per_unit = min(discount_per_unit, self.unit_price)

        self.subtotal = (self.unit_price - discount_per_unit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def update_total_price(self):
        """Calculate total_price = quantity * unit_price - discount according to discount_type"""

        if self.discount_type == "amount":
            discount_per_unit = self.discount_amount
        elif self.discount_type == "percentage":
            discount_per_unit = (
                self.unit_price * self.discount_percentage / Decimal("100.00")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            discount_per_unit = Decimal("0.00")

        discount_per_unit = min(discount_per_unit, self.unit_price)  # Evitar que el descuento sea mayor al unit price

        unit_net_price = self.unit_price - discount_per_unit
        base_price = unit_net_price * self.quantity

        if self.is_subscription:
            term = self.term if self.term else 1 
            self.total_price = (base_price * term).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            self.total_price = base_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


    def save(self, *args, **kwargs):
        # Auto-calculate price for bundles
        if self.product.is_bundle:
            self.unit_price = sum(
                bundle_item.product.price * bundle_item.quantity for bundle_item in self.product.bundle_items.all()
            )
        elif self.unit_price is None:
            self.unit_price = self.product.price

        # Auto-fill product name and SKU
        if self.product and not self.product_name:
            self.product_name = self.product.name
        if self.product and not self.sku:
            self.sku = self.product.sku

        #Update discount fields
        self.update_discount_fields()
        #Update subtotal
        self.update_subtotal()
        #Update total price
        self.update_total_price()
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} ({self.quantity}x)"

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

class ApprovalWorkflow(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class ApprovalRule(models.Model):
    workflow = models.ForeignKey(
        'ApprovalWorkflow',
        on_delete=models.CASCADE,
        related_name='rules'
    )
    name = models.CharField(max_length=255)
    priority = models.IntegerField(
        default=0,
        help_text="Higher priority rules are evaluated first."
    )
    # This can be extended in the future with other fields or flags

    def __str__(self):
        return f"{self.name} (Priority: {self.priority})"

    def matches_quote(self, quote):
        """
        Evaluates all conditions related to this rule against the given quote.
        By default, we use AND logic: all conditions must match to return True.
        """
        conditions = self.conditions.all()
        if not conditions.exists():
            # If there are no conditions, assume it always matches
            return True

        # Evaluate each condition
        for condition in conditions:
            if not condition.matches(quote):
                return False
        return True

class RuleCondition(models.Model):
    OPERATORS = [
        ('>=', 'Greater Than or Equal'),
        ('<=', 'Less Than or Equal'),
        ('==', 'Equal'),
        ('>', 'Greater Than'),
        ('<', 'Less Than'),
        ('!=', 'Not Equal'),
    ]

    rule = models.ForeignKey(
        'ApprovalRule',
        on_delete=models.CASCADE,
        null=True, 
        related_name='conditions'
    )
    field_name = models.CharField(max_length=255)  # e.g. "discount_percentage"
    operator = models.CharField(max_length=2, choices=OPERATORS)
    value = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.rule.name} condition: {self.field_name} {self.operator} {self.value}"

    def matches(self, quote):
        """
        Evaluates this condition against the quote.
        For example, if field_name == "discount_percentage":
          1. we compute quote's discount
          2. compare with 'value' using 'operator'.
        """
        # 1. Retrieve the field's current value (example: discount_percentage)
        field_value = self._get_quote_field_value(quote, self.field_name)

        # 2. Convert to Decimal as needed:
        from decimal import Decimal
        compare_value = Decimal(str(self.value))
        current_value = Decimal(str(field_value))

        # 3. Apply operator logic
        if self.operator == '>=':
            return current_value >= compare_value
        elif self.operator == '<=':
            return current_value <= compare_value
        elif self.operator == '==':
            return current_value == compare_value
        elif self.operator == '>':
            return current_value > compare_value
        elif self.operator == '<':
            return current_value < compare_value
        elif self.operator == '!=':
            return current_value != compare_value
        return False

    def _get_quote_field_value(self, quote, field_name):
        """
        Here you map `field_name` to the actual attribute or computed value on the quote.
        For example, if `field_name` == "discount_percentage", you might do:
          return quote.get_total_discount_percentage()
        If `field_name` == "total_amount", you might do:
          return quote.get_total_amount()
        """
        # As a simple example, if we store discount in a "discount_percentage" field:
        if field_name == "discount_percentage":
            return quote.get_total_discount_percentage()
        elif field_name == "total_amount":
            return quote.get_total_amount()
        
        # Fallback or dynamic attribute retrieval:
        return getattr(quote, field_name, 0)

class ApprovalStep(models.Model):
    rule = models.ForeignKey(
        'ApprovalRule',
        on_delete=models.CASCADE,
        null=True,
        related_name='steps'
    )
    sequence = models.PositiveIntegerField(default=1)
    approver_role = models.CharField(max_length=255, help_text="Role required to approve this step")

    def __str__(self):
        return f"{self.rule.name} (Step {self.sequence} - {self.approver_role})"

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

class PricingRule(models.Model):
    name = models.CharField(max_length=255)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="pricing_rules")
    min_quantity = models.PositiveIntegerField(default=1)
    max_quantity = models.PositiveIntegerField(blank=True, null=True)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    fixed_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    def __str__(self):
        return f"{self.name} | {self.product.name} | {self.discount_percentage}% Discount"

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

class Usage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="usage_records")
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="usage_records")
    usage_date = models.DateField()
    quantity_used = models.IntegerField()
    cost_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"Usage of {self.product.name} on {self.usage_date}"

class SystemFieldMapping(models.Model):
    """Stores manual field mappings between local CPQ fields and CRM fields."""

    CRM_CHOICES = [
        ('AgentCPQ', 'AgentCPQ'),
        ('Salesforce', 'Salesforce'),
        ('HubSpot', 'HubSpot'),
        ('Dynamics', 'Microsoft Dynamics'),
        ('Custom', 'Custom CRM'),
    ]

    FIELD_TYPE_CHOICES = [
        ('Opportunity', 'Opportunity Field'),
        ('Quote', 'Quote Field'),
        ('LineItem', 'Line Item Field'),
    ]

    crm = models.CharField(max_length=50, choices=CRM_CHOICES)
    field_type = models.CharField(max_length=50, choices=FIELD_TYPE_CHOICES, default="Quote")
    local_field = models.CharField(max_length=255)  # ✅ Field name in CPQ
    crm_field = models.CharField(max_length=255)  # ✅ Field name in the CRM

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('crm', 'field_type', 'local_field', 'crm_field') 

    def __str__(self):
        return f"{self.crm} - {self.field_type} - {self.local_field} → {self.crm_field}"

class Pricebook(models.Model):
    """Represents a Salesforce Pricebook (e.g., Standard Pricebook, Custom Pricebooks)."""
    name = models.CharField(max_length=255)
    salesforce_id = models.CharField(max_length=18, unique=True, blank=True, null=True)  # ✅ SF Pricebook ID

    def __str__(self):
        return self.name


class PricebookEntry(models.Model):
    """Represents a Pricebook Entry linked to a Product and Pricebook."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="pricebook_entries")
    pricebook = models.ForeignKey(Pricebook, on_delete=models.CASCADE, related_name="entries")
    salesforce_id = models.CharField(max_length=18, unique=True, blank=True, null=True)  # ✅ SF PricebookEntry ID
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product.name} in {self.pricebook.name} - ${self.unit_price}"


class Tenant(models.Model):
    PLAN_CHOICES = [
        ('solo', 'Solo'),
        ('team', 'Team'),
        ('pro', 'Pro'),
        ('business', 'Business'),
        ('enterprise', 'Enterprise'),
    ]
    tenant_id = models.CharField(max_length=20, unique=True, blank=True)
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=50, blank=True, null=True)
    street_address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    version = models.CharField(max_length=50, default='1.0.0')
    logo = models.ImageField(upload_to='tenant_logos/', blank=True, null=True)
    billing_contact = models.EmailField(blank=True, null=True)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='solo')
    actions_limit = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    primary_color = models.CharField(max_length=7, blank=True, null=True)
    secondary_color = models.CharField(max_length=7, blank=True, null=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)  # Save first to get auto-incremented ID
        if not self.tenant_id:
            self.tenant_id = generate_agentcpq_id()
            super().save(update_fields=['tenant_id'])  # Only update the tenant_id

    def __str__(self):
        return self.name
    
class QuoteDocument(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='documents')
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    content = models.TextField(blank=True, null=True, help_text="Optional HTML/text content of the document")
    file = models.FileField(upload_to='quote_documents/', blank=True, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.CharField(max_length=255, blank=True, null=True, help_text="Who generated this version (e.g., system, user email)")

    class Meta:
        unique_together = ('quote', 'version')
        ordering = ['-version']  # Most recent version first

    def save(self, *args, **kwargs):
        if not self.pk:
            last_version = QuoteDocument.objects.filter(quote=self.quote).aggregate(
                max_version=models.Max('version')
            )['max_version'] or 0
            self.version = last_version + 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quote.name} - v{self.version}"

#dummy model for all custom objects
class CustomRecord(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

class CustomObject(models.Model):
    name = models.CharField(max_length=255, unique=True)
    label = models.CharField(max_length=255)              
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label or self.name


class CustomField(models.Model):
    label = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=100)  # Local field name
    crm = models.CharField(max_length=50)
    object_type = models.CharField(max_length=50)
    data_type = models.CharField(max_length=50)  # text, number, date, etc.
    required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    custom_object = models.ForeignKey(CustomObject, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.crm}.{self.object_type}.{self.field_name}"


class CustomFieldValue(models.Model):
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="values")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)  # Generic relation
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    value = models.TextField()

    def __str__(self):
        return f"{self.content_object} - {self.field.field_name}: {self.value}"
    
    
class QuoteDocumentSettings(models.Model):
    DESIGN_CHOICES = [
        ('classic', 'Classic'),
        ('modern', 'Modern'),
    ]
    
    def default_rendered_fields():
        return ['Product And SKU', 'Description', 'Quantity', 'Unit Price', 'Total Price']

    def default_omitted_fields():
        return ['Product', 'SKU', 'Discount Percentage', 'Discount Amount']
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="pdf_settings")

    # Company information
    show_company_name = models.BooleanField(default=True)
    show_company_address = models.BooleanField(default=True)
    show_company_phone = models.BooleanField(default=False)
    show_company_email = models.BooleanField(default=True)
    show_company_domain = models.BooleanField(default=False)
    show_company_logo = models.BooleanField(default=True)

    # Account information
    show_account_name = models.BooleanField(default=True)
    show_account_website = models.BooleanField(default=False)
    show_account_phone = models.BooleanField(default=False)

    # Quote information
    show_quote_opportunity = models.BooleanField(default=True)
    show_quote_status = models.BooleanField(default=True)
    show_quote_created_at = models.BooleanField(default=True)
    show_quote_expires_at = models.BooleanField(default=True)
    show_quote_notes = models.BooleanField(default=True)

    # Quote Line Items
    show_line_discount_percentage = models.BooleanField(default=False)
    show_line_discount_amount = models.BooleanField(default=False)
    show_line_discount = models.BooleanField(default=True)
    rendered_fields = JSONField(default=default_rendered_fields, blank=True)
    omitted_fields = JSONField(default=default_omitted_fields, blank=True)

    # Quote Line Items - Subscriptions
    show_subscription_term = models.BooleanField(default=True)

    # General PDF
    show_sign = models.BooleanField(default=True)
    template_style = models.CharField(
        max_length=20,
        choices=DESIGN_CHOICES,
        default='modern',
        help_text="Select the design style of the PDF template"
    )

    # Terms and conditions
    terms_and_conditions = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        accid = self.account.accid if self.account else "General"
        return f"PDF Settings for Tenant {self.tenant.name} - Account {accid}"

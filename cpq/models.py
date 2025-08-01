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
from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import User
from django.conf import settings
import os , uuid
import secrets


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

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    leadId = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    source = models.CharField(max_length=100, blank=True, help_text="e.g., Website, Referral, LinkedIn")
    contact = models.ForeignKey('Contact', on_delete=models.SET_NULL, null=True, blank=True, related_name='leads')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    notes = models.TextField(blank=True)
    assigned_to = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_leads')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_leads')
    def save(self, *args, **kwargs):
        if not self.leadId:
            self.leadId = generate_agentcpq_id()
        super().save(*args, **kwargs)

    def convert_to_contact(self):
        if not self.contact:
            contact = Contact.objects.create(
                first_name=self.first_name,
                last_name=self.last_name,
                phone=self.phone,
                email=self.email,
            )
            self.contact = contact
            self.status = 'converted'
            self.save()
        return self.contact
    def __str__(self):
        return self.first_name + ' ' + self.last_name
    

class Account(models.Model):
    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=255, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    accid = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    external_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='accounts')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_accounts')
     # Address fields
    street = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    zip_code = models.CharField(max_length=20, blank=True, null=True)
    tenant_id = models.CharField(max_length=30, unique=False,null=True)
    # country = models.CharField(max_length=100, blank=True, null=True)
    

    def save(self, *args, **kwargs):
        if not self.accid:
            self.accid = generate_agentcpq_id()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name

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
    contactId = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_contacts')
    is_primary = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.contactId:
            self.contactId = generate_agentcpq_id()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name or ''}".strip()



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

    ### UNCOMENT FOR HUBSPOT INTEGRATION ###
    # STAGE_CHOICES = [
    #     ("appointmentscheduled", "Appointment Scheduled"),
    #     ("qualifiedtobuy", "Qualified to Buy"),
    #     ("presentationscheduled", "Presentation Scheduled"),
    #     ("decisionmakerboughtin", "Decision Maker Bought-In"),
    #     ("contractsent", "Contract Sent"),
    #     ("closedwon", "Closed Won"),
    #     ("closedlost", "Closed Lost"),
    # ]

    name = models.CharField(max_length=255)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="opportunities")
    amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    stage = models.CharField(max_length=50, choices=STAGE_CHOICES, default='Prospecting')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_opportunities')
    expected_close_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_opportunities')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_opportunities')
    primary_quote = models.ForeignKey(
        "Quote", 
        on_delete=models.SET_NULL,  # Set to NULL if quote is deleted
        related_name="opportunity_primary_quote",
        null=True, blank=True
    )
    oppid = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    hs_deal_id = models.CharField(max_length=18, unique=True, db_index=True, editable=False, null=True, blank=True)
    class Meta:
        verbose_name = "Opportunity"
        verbose_name_plural = "Opportunities"

    def save(self, *args, **kwargs):
        if not self.oppid:
            self.oppid = generate_agentcpq_id()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name

class Activity(models.Model):
    ACTIVITY_TYPE_CHOICES = [
        ('call', 'Call'),
        ('email', 'Email'),
        ('meeting', 'Meeting'),
        ('task', 'Task'),
    ]

    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('deferred', 'Deferred'),
    ]

    subject = models.CharField(max_length=255)
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPE_CHOICES)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='not_started')
    due_date = models.DateField(null=True, blank=True)
    lead = models.ForeignKey('Lead', on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    opportunity = models.ForeignKey('Opportunity', on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    contact = models.ForeignKey('Contact', on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_activities')
    activityid = models.CharField(max_length=18, unique=True, db_index=True, editable=False)

    class Meta:
        verbose_name = "Activity"
        verbose_name_plural = "Activities"

    def save(self, *args, **kwargs):
        if not self.activityid:
            self.activityid = generate_agentcpq_id()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.subject} ({self.get_activity_type_display()})"

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
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_products')
    description = models.TextField(blank=True)

    def get_custom_fields(self):
        return CustomField.objects.filter(object_type="Product")

    def get_custom_fields_values(self):
        content_type = ContentType.objects.get_for_model(Product)
        return CustomFieldValue.objects.filter(content_type=content_type, object_id=self.id)

    def save(self, *args, **kwargs):
        if not self.prdid:
            self.prdid = generate_agentcpq_id()

        if self.is_bundle and self.pk:
            total_price = 0
            for option in self.options.all():
                if option.product_option:
                    total_price += option.quantity * option.product_option.price
            self.price = total_price
        super().save(*args, **kwargs)
    def __str__(self):
        bundle_tag = " - BUNDLE" if self.is_bundle else ""
        return f"{self.name} ({self.sku}){bundle_tag}"

class Option(models.Model):
    parent_product = models.ForeignKey(Product, related_name="options", on_delete=models.CASCADE)  # 🔗 Parent Bundle
    product_option = models.ForeignKey(Product, related_name="included_in", on_delete=models.CASCADE)  # 🔗 Child Product
    quantity = models.PositiveIntegerField(default=1)  # Default quantity
    is_required = models.BooleanField(default=False)
    min_quantity = models.PositiveIntegerField(default=1)
    max_quantity = models.PositiveIntegerField(default=10)
    default_selected = models.BooleanField(default=True)
    group_name = models.CharField(max_length=255, blank=True, null=True)  # Optional grouping (for dynamic)

    def __str__(self):
        return f"{self.parent_product.name}"

class Quote(models.Model):
    """Now linked to an Opportunity instead of a Customer."""
    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Pending Approval', 'Pending Approval'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Closed', 'Closed'),
    ]

    def default_expiration_date():
        return timezone.now().date() + relativedelta(months=1)

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
    expiration_date = models.DateTimeField(default=default_expiration_date, blank=True, null=True)
    notes = models.TextField(blank=True, null=True) 
    qteid = models.CharField(max_length=18, unique=True, db_index=True, editable=False)
    hs_deal_id = models.CharField(max_length=64,blank=True,null=True,help_text="The HubSpot Deal ID linked to this quote")
    hs_primary = models.BooleanField(default=False,help_text="Marks this quote as the primary quote for the HubSpot deal")
    synced = models.BooleanField(default=False)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_quotes')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_quotes')


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
        return self.quote_lines.filter(is_bundle_child=False).aggregate(subtotal=Sum("total_price"))["subtotal"] or 0
    
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
    discount_type = models.CharField(max_length=20, choices=[("percentage", "Percentage"), ("amount", "Amount")], default="percentage", null=True, blank=True)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, validators=[MinValueValidator(Decimal("0.00"))])
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    parent_quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="parent_quote_lines", blank=True, null=True)
    external_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    is_subscription = models.BooleanField(default=False)
    is_bundle_parent = models.BooleanField(default=False)
    is_bundle_child = models.BooleanField(default=False)
    is_bundle_component_selected = models.BooleanField(default=False)
    parent_line = models.ForeignKey('self', null=True, blank=True, related_name="child_lines", on_delete=models.CASCADE)  # for nesting
    product_option = models.ForeignKey("Option", null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_quote_lines')
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

    def check_term_is_not_null_for_subscriptions(self):
        if self.product.is_subscription and self.term is None:
            self.term = 1

    def update_unit_price_bundle_post_created(self):
        total = sum(
            (child.total_price or Decimal("0.00"))
            for child in self.child_lines.filter(is_bundle_component_selected=True)
        )
        self.unit_price = total
    
    def check_if_is_bundle_component_deselected(self):
        if self.is_bundle_child and self.is_bundle_component_selected == False:
            self.total_price = Decimal("0.00")
        

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new:
        # Auto-calculate price for bundles
            if self.product.is_bundle:
                self.unit_price = sum(
                    Decimal(option.product_option.price) * Decimal(option.quantity)
                    for option in self.product.options.all()
                    if option.product_option and option.default_selected
                ) or Decimal("0.00")
            elif self.unit_price is None:
                self.unit_price = self.product.price
        else:
            if self.product.is_bundle:
                print(f"{self.product_name} is a bundle")
                self.update_unit_price_bundle_post_created()
                print(f"Unit Price before update: {self.unit_price}")
            else:
                self.unit_price = self.product.price

        # Auto-fill product name and SKU
        if self.product and not self.product_name:
            self.product_name = self.product.name
        if self.product and not self.sku:
            self.sku = self.product.sku

        #Chech term for subscriptions:
        self.check_term_is_not_null_for_subscriptions()

        #Update discount fields
        self.update_discount_fields()
        #Update subtotal
        self.update_subtotal()
        #Update total price
        self.update_total_price()

        # Set total price to 0 if is a bundle component deselected
        if self.is_bundle_child:
            self.check_if_is_bundle_component_deselected()
        
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
    
class BusinessRule(models.Model):
    RULE_TYPES = [
        ("validation", "Validation"),
        ("inclusion", "Inclusion"),
        ("exclusion", "Exclusion")
    ]

    TARGET_TYPES = [
        ("quote", "Quote"),
        ("quote_line", "Quote Line"),
        ("product", "Product"),
    ]

    name = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255)
    rule_type = models.CharField(max_length=20, choices=RULE_TYPES, default="validation")
    target_type = models.CharField(max_length=20, choices=TARGET_TYPES, default="quote_line")
    priority = models.IntegerField(default=0, help_text="Higher priority rules run first.")
    error_message = models.TextField(blank=True, help_text="Message shown when the rule is triggered.")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    conditions = models.JSONField(default=list, blank=True, help_text="List of conditions for the rule.")

    def __str__(self):
        return f"{self.name} ({self.rule_type}, Priority {self.priority})"
    
class RuleCondition(models.Model):
    OPERATORS = [
        ('>=', 'Greater Than or Equal'),
        ('<=', 'Less Than or Equal'),
        ('==', 'Equal'),
        ('>', 'Greater Than'),
        ('<', 'Less Than'),
        ('!=', 'Not Equal'),
    ]

    #rule = models.ForeignKey(
    #    'ApprovalRule',
    #    on_delete=models.CASCADE,
    #    null=True, 
    #    related_name='conditions'
    #)
    rule = models.ForeignKey(BusinessRule, on_delete=models.CASCADE)
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


def temp_logo_path(instance, filename):
    ext = os.path.splitext(filename)[1]
    random_name = f"{uuid.uuid4().hex}{ext}"
    tenant_id = instance.tenant_id or "unsaved"
    return f"tenant_{tenant_id}/logos/{random_name}"


def gen_api_key():
    # 32 bytes → ~43 URL-safe chars; trim or base-64 as you like
    return secrets.token_urlsafe(32)


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
    logo = models.ImageField(upload_to=temp_logo_path, blank=True, null=True)
    billing_contact = models.EmailField(blank=True, null=True)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='solo')
    actions_limit = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    primary_color = models.CharField(max_length=7, blank=True, null=True)
    secondary_color = models.CharField(max_length=7, blank=True, null=True)
    api_key = models.CharField(max_length=43,null=True,editable=False,default=gen_api_key,help_text="Public API key, auto-generated")
    api_secret = models.CharField(max_length=43,null=True,editable=False,default=gen_api_key,help_text="Private key used for request signing")

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if not self.tenant_id:
            self.tenant_id = generate_agentcpq_id()
            super().save(update_fields=['tenant_id'])

        if self.logo and self.logo.name.startswith('temp/logos/'):
            # move logo to new path
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile

            old_logo = self.logo
            logo_content = old_logo.read()
            old_logo.close()

            new_path = f"tenant_{self.tenant_id}/logos/{os.path.basename(old_logo.name)}"
            saved_path = default_storage.save(new_path, ContentFile(logo_content))
            self.logo.name = saved_path
            self.save(update_fields=["logo"])
    
def temp_file_path(instance, filename):
    return f"temp/quotes/{filename}"
    
class QuoteDocument(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='documents')
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    content = models.TextField(blank=True, null=True, help_text="Optional HTML/text content of the document")
    file = models.FileField(upload_to=temp_file_path, blank=True, null=True)
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


class CustomObject(models.Model):
    name = models.CharField(max_length=255, unique=True)
    label = models.CharField(max_length=255)              
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_custom_objects')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_custom_objects')

    def __str__(self):
        return self.label or self.name
    
    class Meta:
        verbose_name = "Custom Object"
        verbose_name_plural = "Custom Objects"
        
#dummy model for all custom objects
class CustomRecord(models.Model):
    object_type = models.ForeignKey(CustomObject, on_delete=models.CASCADE)
    # record_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    record_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        label = f"{self.object_type.name} record"
        try:
            from .models import CustomFieldValue
            values = CustomFieldValue.objects.filter(record=self).select_related("field")[:4]
            value_parts = [
                f"{v.field.label}: {v.value}" for v in values if v.field and v.value
            ]
            return f"{label} — {' | '.join(value_parts)}" if value_parts else label
        except Exception:
            return label


class CustomField(models.Model):
    label = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=100)  # Local field name
    crm = models.CharField(max_length=50)
    object_type = models.CharField(max_length=50)
    data_type = models.CharField(max_length=50)  # text, number, date, etc.
    required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='creted_custom_fields')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_custom_fields')
    custom_object = models.ForeignKey(CustomObject, on_delete=models.SET_NULL, null=True, blank=True)
    lookup_model = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Format: 'app_label.ModelName' (e.g., 'cpq.Account')"
    )
    class Meta:
        verbose_name = "Custom Field"
        verbose_name_plural = "Custom Fields"

    def __str__(self):
        return f"{self.crm}.{self.object_type}.{self.name}"
    

class CustomFieldValue(models.Model):
    field = models.ForeignKey(CustomField, on_delete=models.CASCADE, related_name="values")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)  # Generic relation
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")
    value = models.TextField()
    record = models.ForeignKey(CustomRecord, null=True, blank=True, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.content_object} - {self.field.label}: {self.value}"
    
    

class QuoteDocumentSettings(models.Model):
    DESIGN_CHOICES = [
        ('classic', 'Classic'),
        ('modern', 'Modern'),
    ]

    DESCRIPTION_DETAIL_CHOICES = [
        ('short', 'Short'),
        ('long', 'Modern'),
    ]
    
    def default_rendered_fields():
        return ['Product And SKU', 'Description', 'Quantity', 'Unit Price', 'Total Price']

    def default_omitted_fields():
        return ['Product', 'SKU', 'Discount']
    

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

    #Quote Line Description
    line_description_detail_level = models.CharField(
        max_length=20,
        choices=DESCRIPTION_DETAIL_CHOICES,
        default='short',
        help_text="Select the quote line description detail level."
    )

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
        return f"PDF Settings"
    
class QuoteUIRender(models.Model):

    def default_rendered_fields():
        return ['sku_product', 'quantity', 'unit_price', 'discount_percentage', 'discount_amount', 'subscription', 'term', 'total_price']

    def default_omitted_fields():
        return []

    # Quote information
    show_quote_account = models.BooleanField(default=True)
    show_quote_opportunity = models.BooleanField(default=True)
    show_quote_created_at = models.BooleanField(default=True)
    show_quote_expires_at = models.BooleanField(default=True)
    show_quote_discount = models.BooleanField(default=True)

    # Line items information
    rendered_fields = JSONField(default=default_rendered_fields, blank=True)
    omitted_fields = JSONField(default=default_omitted_fields, blank=True)

    # Subtotal and net amount information
    show_quote_subtotal = models.BooleanField(default=True)
    show_quote_net_amount = models.BooleanField(default=True)

    def __str__(self):
        return f"QuoteUI Settings"

class ActionUsage(models.Model):
    action = models.CharField(max_length=100)  # e.g., "CreateQuote", "UpdateQuoteLine"
    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="action_usages"
    )
    related_object_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Type of object this action is related to (e.g., Quote, Product, Approval)"
    )
    related_object_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="ID of the related object (e.g., Q-0001, PROD-001)"
    )

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.action} by {self.user or 'System'} on {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

class TenantUsageReport(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="usage_reports"
    )
    tenant_long_id = models.CharField(max_length=100, blank=True, null=True)
    # Use the first day of the month to represent a billing period
    billing_period = models.DateField(
        help_text="First day of the month this report covers"
    )
    total_actions = models.PositiveBigIntegerField(
        default=0,
        help_text="Total number of actions performed by this tenant in the period"
    )
    overflow_actions = models.PositiveBigIntegerField(
        default=0,
        help_text="Number of actions beyond the tenant’s plan limit"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this report row was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this report row was last updated"
    )

    class Meta:
        unique_together = ("tenant", "billing_period")
        ordering = ["-billing_period"]
        indexes = [
            models.Index(fields=["tenant", "billing_period"]),
        ]

    def __str__(self):
        return f"{self.tenant.tenant_id} – {self.billing_period:%Y-%m}"
    
class TenantUsageLog(models.Model):
    tenant_id = models.CharField(max_length=50, db_index=True)
    billing_period = models.DateField()
    
    status = models.CharField(max_length=20, choices=[
        ("success", "Success"),
        ("failure", "Failure")
    ])
    
    http_status = models.IntegerField(null=True, blank=True)
    message = models.TextField(blank=True, help_text="Response body or error message")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant_id", "billing_period", "status"]),
        ]

    def __str__(self):
        return f"{self.tenant_id} ({self.billing_period}) – {self.status}"
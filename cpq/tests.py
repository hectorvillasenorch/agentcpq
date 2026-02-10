from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from cpq.models import Account, AccessPolicy, RecordAccessGrant
from cpq.permissions import apply_partner_access_filter, partner_can_access_record


class RecordAccessPolicyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="test123")
        self.viewer = User.objects.create_user(username="viewer", password="test123")
        self.group = Group.objects.create(name="sales-team")
        self.viewer.groups.add(self.group)

        self.account = Account.objects.create(
            name="Acme Corp",
            owner=self.owner,
            created_by=self.owner,
        )

        AccessPolicy.objects.all().update(is_active=False)
        AccessPolicy.objects.create(
            key="test-policy",
            label="Global Policy",
            strategy=AccessPolicy.STRATEGY_CREATOR_OR_GROUP,
            is_active=True,
            allow_superuser=True,
            allow_staff=True,
            include_partner_scope=False,
            allow_unassigned_records=False,
            use_record_grants=True,
        )

    def test_creator_can_view_record(self):
        visible = apply_partner_access_filter(self.owner, "Account", Account.objects.all(), permission="view")
        self.assertEqual(list(visible.values_list("id", flat=True)), [self.account.id])

    def test_non_creator_cannot_view_without_grant(self):
        visible = apply_partner_access_filter(self.viewer, "Account", Account.objects.all(), permission="view")
        self.assertFalse(visible.filter(id=self.account.id).exists())

    def test_group_grant_allows_view(self):
        content_type = ContentType.objects.get_for_model(Account)
        RecordAccessGrant.objects.create(
            content_type=content_type,
            object_id=self.account.id,
            group=self.group,
            can_view=True,
            can_change=False,
            can_delete=False,
            created_by=self.owner,
        )

        visible = apply_partner_access_filter(self.viewer, "Account", Account.objects.all(), permission="view")
        self.assertTrue(visible.filter(id=self.account.id).exists())

    def test_change_requires_change_permission(self):
        content_type = ContentType.objects.get_for_model(Account)
        RecordAccessGrant.objects.create(
            content_type=content_type,
            object_id=self.account.id,
            group=self.group,
            can_view=True,
            can_change=False,
            can_delete=False,
            created_by=self.owner,
        )
        self.assertFalse(
            partner_can_access_record(self.viewer, "Account", self.account, permission="change")
        )

        grant = RecordAccessGrant.objects.get(group=self.group, object_id=self.account.id)
        grant.can_change = True
        grant.save(update_fields=["can_change"])

        self.assertTrue(
            partner_can_access_record(self.viewer, "Account", self.account, permission="change")
        )

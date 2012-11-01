"""
Portfoliyo network models.

"""
import base64
import time
from hashlib import sha1
from django.contrib.auth import models as auth_models
from django.db import models, transaction, IntegrityError
from django.db.models import signals
from django.utils import timezone

from model_utils import Choices

from .. import events


# monkeypatch Django's User.email to be sufficiently long and unique/nullable
email_field = auth_models.User._meta.get_field("email")
email_field._unique = True
email_field.null = True
email_field.max_length = 255

# monkeypatch User's __unicode__ method to be friendlier for no-username
auth_models.User.__unicode__ = lambda self: (
    self.email or self.profile.name or self.profile.phone or u'<unknown>')



class School(models.Model):
    name = models.CharField(max_length=200)
    postcode = models.CharField(max_length=20)
    # True if this School is autogenerated for a user with no affiliation
    auto = models.BooleanField(default=False)


    def __unicode__(self):
        return self.name


    class Meta:
        unique_together = [('name', 'postcode')]



class Profile(models.Model):
    """A Portfoliyo user profile."""
    user = models.OneToOneField(auth_models.User)
    school = models.ForeignKey(School)
    # fields from User we use: username, password, email
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True, null=True, unique=True)
    # e.g. "Math Teacher", "Father", "Principal", etc
    # serves as default fall-back for the relationship-description field
    role = models.CharField(max_length=200)
    school_staff = models.BooleanField(default=False)
    # code for parent-initiated signups
    code = models.CharField(max_length=20, blank=True, null=True, unique=True)
    # signup status (for text-based multi-step signup); what are we awaiting?
    STATE = Choices('kidname', 'relationship', 'name', 'done')
    state = models.CharField(max_length=20, choices=STATE, default=STATE.done)
    # does this user want to receive email notifications?
    email_notifications = models.BooleanField(default=True)
    # who invited this user to the site?
    invited_by = models.ForeignKey('self', blank=True, null=True)
    # what group was this user initially invited to?
    invited_in_group = models.ForeignKey('Group', blank=True, null=True)
    declined = models.BooleanField(default=False)


    def __unicode__(self):
        return (
            self.name or
            self.user.email or
            getattr(self, 'role_in_context', None) or
            self.role or
            self.phone or
            u'<unknown>'
            )


    def save(self, *a, **kw):
        """Make site staff always school staff, too."""
        if self.user.is_staff:
            self.school_staff = True
        return super(Profile, self).save(*a, **kw)


    @classmethod
    def create_with_user(cls, school,
                         name='', email=None, phone=None, password=None,
                         role='', school_staff=False, is_active=False,
                         state=None, invited_by=None, invited_in_group=None,
                         email_notifications=True):
        """
        Create a Profile and associated User and return the new Profile.

        Generates a unique username to satisfy the User model by hashing as
        much user data as we're given, plus a timestamp.

        """
        to_hash = u"-".join(
            [email or u'', phone or u'', name, u'%f' % time.time()])
        username = base64.b64encode(sha1(to_hash.encode('utf-8')).digest())
        now = timezone.now()
        user = auth_models.User(
            username=username,
            email=email,
            is_staff=False,
            is_active=is_active,
            is_superuser=False,
            date_joined=now,
            )
        user.set_password(password)
        user.save()
        code = generate_code(username, 6) if school_staff else None
        profile = cls(
            school=school,
            name=name,
            phone=phone,
            user=user,
            role=role,
            school_staff=school_staff,
            state=state or cls.STATE.done,
            invited_by=invited_by,
            invited_in_group=invited_in_group,
            code=code,
            email_notifications=email_notifications,
            )

        # try a few times to generate a unique code, if we keep failing give up
        # and raise the error
        for i in range(5):
            sid = transaction.savepoint()
            try:
                profile.save()
            except IntegrityError:
                if code is not None:
                    transaction.savepoint_rollback(sid)
                    profile.code = generate_code(u'%s%s' % (username, i), 6)
                else:
                    raise
            else:
                break
        else:
            # give up and try one last save without catching errors
            profile.save()

        return profile


    @property
    def name_or_role(self):
        return self.name or self.role


    @property
    def elder_relationships(self):
        return self.relationships_to.filter(
            kind=Relationship.KIND.elder).order_by(
            'from_profile__name').select_related("from_profile")


    @property
    def elders(self):
        return contextualized_elders(self.elder_relationships)


    @property
    def student_relationships(self):
        return self.relationships_from.filter(
            kind=Relationship.KIND.elder).order_by(
            'to_profile__name').select_related("to_profile")


    @property
    def students(self):
        return [rel.to_profile for rel in self.student_relationships]



class GroupBase(object):
    """Common methods between Group and AllStudentsGroup."""
    def __unicode__(self):
        return self.name


    @property
    def all_elders(self):
        """Return queryset of all elders of all students in group."""
        return Profile.objects.order_by('name').distinct().filter(
            relationships_from__to_profile__in=self.students.all(),
            ).select_related('user')



class Group(GroupBase, models.Model):
    """A group of students and elders, set up by a particular teacher."""
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(Profile, related_name='owned_groups')
    students = models.ManyToManyField(
        Profile, related_name='student_in_groups', blank=True)
    elders = models.ManyToManyField(
        Profile, related_name='elder_in_groups', blank=True)
    # code for parent-initiated signups
    code = models.CharField(max_length=20, unique=True)


    def save(self, *args, **kwargs):
        """Set code for all new groups."""
        if self.code:
            return super(Group, self).save(*args, **kwargs)
        # try a few times to generate a unique code, then give up and error out
        for i in range(3):
            # teacher codes are length 6, group length 7
            self.code = generate_code(
                '%s-%f' % (self.owner_id, time.time()), 7)
            sid = transaction.savepoint()
            try:
                return super(Group, self).save(*args, **kwargs)
            except IntegrityError:
                transaction.savepoint_rollback(sid)

        # couldn't save, try one last time without catching errors
        return super(Group, self).save(*args, **kwargs)


    is_all = False


    @property
    def elder_relationships(self):
        """Return queryset of all relationships for students in group."""
        return Relationship.objects.filter(
            kind=Relationship.KIND.elder,
            to_profile__in=self.students.all(),
            ).select_related('from_profile')



class AllStudentsGroup(GroupBase):
    """Stand-in for a Group instance for all-students."""
    name = 'All Students'
    is_all = True

    def __init__(self, owner):
        self.owner = owner


    @property
    def id(self):
        return 'all%s' % self.owner.id
    pk = id


    @property
    def elder_relationships(self):
        """Return queryset of all relationships for students in group."""
        return Relationship.objects.select_related('from_profile').filter(
            kind=Relationship.KIND.elder, to_profile__in=self.owner.students)


    @property
    def students(self):
        """Return queryset of all students in group."""
        return Profile.objects.filter(
            relationships_to__from_profile=self.owner,
            ).distinct()



def group_deleted(sender, instance, **kwargs):
    events.group_removed(instance)



def group_saved(sender, instance, created, **kwargs):
    if created:
        events.group_added(instance)



signals.post_save.connect(group_saved, sender=Group)
signals.post_delete.connect(group_deleted, sender=Group)



def update_group_relationships(
        sender, instance, action, reverse, pk_set, **kwargs):
    """Create/remove relationships based on group membership changes."""
    if sender is Group.students.through:
        # group-elder memberships being modified
        sender_attr = 'to_profile'
        other_attr = 'from_profile'
        for_each = 'elders'
    else:
        # group-student memberships being modified
        sender_attr = 'from_profile'
        other_attr = 'to_profile'
        for_each = 'students'

    check_for_orphan_relationships = False

    if reverse:
        # instance is a student/elder; pk_set are group PKs
        if action == 'post_clear':
            Relationship.objects.filter(
                **{
                    sender_attr: instance,
                    'direct': False,
                    }
                  ).delete()
        elif action == 'post_add':
            for group in Group.objects.filter(pk__in=pk_set):
                for profile in getattr(group, for_each).all():
                    rel, created = Relationship.objects.get_or_create(
                        **{
                            other_attr: profile,
                            sender_attr: instance,
                            'defaults': {
                                'direct': False,
                                }
                            }
                          )
                    rel.groups.add(group)
        elif action == 'post_remove':
            Relationship.groups.through.objects.filter(
                **{
                    'relationship__%s' % sender_attr: instance,
                    'group__in': pk_set,
                    }
                  ).delete()
            check_for_orphan_relationships = True

    else:
        # instance is a group, pk_set are student/elder PKs
        if action == 'post_clear':
            Relationship.groups.through.objects.filter(group=instance).delete()
            check_for_orphan_relationships = True
        elif action == 'post_add':
            for pk in pk_set:
                for profile in getattr(instance, for_each).all():
                    rel, created = Relationship.objects.get_or_create(
                        **{
                            other_attr: profile,
                            '%s_id' % sender_attr: pk,
                            'defaults': {
                                'direct': False,
                                }
                            }
                          )
                    rel.groups.add(instance)
        elif action == 'post_remove':
            Relationship.groups.through.objects.filter(
                **{
                    'relationship__%s__in' % sender_attr: pk_set,
                    'group': instance,
                    }
                  ).delete()
            check_for_orphan_relationships = True

    if check_for_orphan_relationships:
        Relationship.objects.delete_orphans()


signals.m2m_changed.connect(
    update_group_relationships, sender=Group.students.through)
signals.m2m_changed.connect(
    update_group_relationships, sender=Group.elders.through)


def send_student_group_event(
        sender, instance, action, reverse, pk_set, **kwargs):
    """Fire events based on group student membership changes."""
    # don't do unnecessary work
    if action not in {'pre_clear', 'pre_add', 'pre_remove'}:
        return
    if reverse:
        # instance is a student, pk_set are group PKs
        if action == 'pre_clear':
            groups = instance.student_in_groups.order_by('owner')
        else:
            groups = Group.objects.filter(pk__in=pk_set).order_by('owner')
        groups_by_owner = {}
        for group in groups:
            groups_by_owner.setdefault(group.owner, []).append(group)
        students = [instance]
    else:
        # instance is a group, pk_set are student PKs
        groups_by_owner = {instance.owner: [instance]}
        if action == 'pre_clear':
            students = instance.students.all()
        else:
            students = Profile.objects.filter(pk__in=pk_set)

    if action in {'pre_clear', 'pre_remove'}:
        event = events.student_removed_from_group
    else:
        event = events.student_added_to_group

    for owner, groups in groups_by_owner.items():
        event(owner, list(students), list(groups))



signals.m2m_changed.connect(
    send_student_group_event, sender=Group.students.through)



class RelationshipManager(models.Manager):
    def delete_orphans(self):
        """Delete all relationships that are not direct and have no groups."""
        self.get_query_set().annotate(
            group_count=models.Count('groups')
            ).filter(direct=False, group_count=0).delete()



class Relationship(models.Model):
    """A relationship between two Portfoliyo users."""
    KIND = Choices("elder")
    LEVEL = Choices("normal", "owner")

    from_profile = models.ForeignKey(
        Profile, related_name="relationships_from")
    to_profile = models.ForeignKey(
        Profile, related_name="relationships_to")
    kind = models.CharField(max_length=20, choices=KIND, default=KIND.elder)
    level = models.CharField(max_length=20, choices=LEVEL, default=LEVEL.normal)
    description = models.CharField(max_length=200, blank=True)
    # is this a direct relationship (not a result of group membership)?
    direct = models.BooleanField(default=True)
    # what groups would cause this relationship to exist?
    groups = models.ManyToManyField(
        Group, blank=True, related_name='relationships')


    objects = RelationshipManager()


    def __unicode__(self):
        return u"%s is %s%s to %s" % (
            self.from_profile,
            self.kind,
            ((u" (%s)" % self.description_or_role)
             if self.description_or_role else u""),
            self.to_profile,
            )


    class Meta:
        unique_together = [("from_profile", "to_profile", "kind")]


    @property
    def description_or_role(self):
        """If the description is empty, fall back to from_profile role."""
        return self.description or self.from_profile.role


    @property
    def name_or_role(self):
        return self.from_profile.name or self.description_or_role


    # Add a couple clearer aliases for working with elder relationships
    @property
    def elder(self):
        return self.from_profile


    @property
    def student(self):
        return self.to_profile



def relationship_saved(sender, instance, created, **kwargs):
    if created:
        events.student_added(instance.student, instance.elder)


def relationship_deleted(sender, instance, **kwargs):
    events.student_removed(instance.student, instance.elder)
    for group in instance.elder.owned_groups.all():
        group.students.remove(instance.student)


signals.post_save.connect(relationship_saved, sender=Relationship)
signals.post_delete.connect(relationship_deleted, sender=Relationship)



def contextualized_elders(queryset):
    """
    Given QS of elders/relationships, return contextualized elder queryset.

    A contextualized elder has an added ``role_in_context`` attribute, which is
    the relationship description if in context of a relationship, or simply the
    elder's profile role otherwise.

    """
    if queryset.model is Relationship:
        return EldersForRelationships(queryset)
    elif queryset.model is Profile:
        return EldersInContext(queryset)
    else:
        raise ValueError(
            "Only Profile or Relationship querysets can be contextualized.")


class QuerySetWrapper(object):
    """Simple QuerySet wrapper that can pass-through filter/exclude/order_by."""
    def __init__(self, queryset):
        self.queryset = queryset


    def _mangle_fieldname(self, name):
        return name


    def _mangle_fieldname_kwargs(self, kwargs):
        return {self._mangle_fieldname(k): v for k, v in kwargs.items()}


    def filter(self, *args, **kwargs):
        return self._filter_or_exclude(False, *args, **kwargs)


    def exclude(self, *args, **kwargs):
        return self._filter_or_exclude(True, *args, **kwargs)


    def _filter_or_exclude(self, negate, *args, **kwargs):
        kwargs = self._mangle_fieldname_kwargs(kwargs)
        return self.__class__(
            self.queryset._filter_or_exclude(negate, *args, **kwargs))


    def order_by(self, *args):
        args = [self._mangle_fieldname(fn) for fn in args]
        return self.__class__(self.queryset.order_by(*args))




class EldersInContext(QuerySetWrapper):
    """Elders queryset that tacks on ``role_in_context`` attr when iterated."""
    def __iter__(self):
        for elder in self.queryset:
            elder.role_in_context = elder.role
            yield elder



class EldersForRelationships(QuerySetWrapper):
    """Relationship queryset wrapper; emulates QS of contextualized elders."""
    def __iter__(self):
        for rel in self.queryset.select_related('from_profile'):
            rel.elder.role_in_context = rel.description_or_role
            yield rel.elder


    def _mangle_fieldname(self, name):
        return 'from_profile__%s' % name



# 1 and 0 already eliminated by base32 encoding
AMBIGUOUS = ['L', 'I', 'O', 'S', '5']


def generate_code(seed, length):
    """Generate a probably-unique code given a unique seed."""
    full = base64.b32encode(sha1(seed).digest())
    for char in AMBIGUOUS:
        full = full.replace(char, '')
    return full[:length]

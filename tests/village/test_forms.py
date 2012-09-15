"""Tests for village forms."""
from django.core import mail
import mock

from portfoliyo.village import forms

from tests.users import factories



class TestInviteElderForm(object):
    """Tests for InviteElderForm."""
    def data(self, **kwargs):
        """Utility method to get default form data, with override option."""
        defaults = {
            'contact': 'foo@example.com',
            'relationship': 'mentor',
            'school_staff': False,
            }
        defaults.update(kwargs)
        return defaults


    def test_phone_contact(self, sms):
        """If contact field is phone, it's normalized and saved to profile."""
        form = forms.InviteElderForm(self.data(contact='(321)456-7890'))
        assert form.is_valid()
        request = mock.Mock()
        request.get_host.return_value = 'portfoliyo.org'
        request.is_secure.return_value = False
        request.user = factories.ProfileFactory().user
        profile = form.save(request, factories.ProfileFactory())

        assert profile.phone == u'+13214567890'
        assert len(sms.outbox) == 1
        assert sms.outbox[0].to == u'+13214567890'


    def test_email_contact(self):
        """If contact field is email, invite email is sent."""
        form = forms.InviteElderForm(self.data(contact='bar@EXAMPLE.com'))
        assert form.is_valid()
        request = mock.Mock()
        request.get_host.return_value = 'portfoliyo.org'
        request.is_secure.return_value = False
        request.user = factories.ProfileFactory().user
        profile = form.save(request, factories.ProfileFactory())

        assert profile.user.email == u'bar@example.com'
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [u'bar@example.com']


    def test_user_inactive(self):
        """User created is inactive (so we don't send them emails)."""
        form = forms.InviteElderForm(self.data())
        assert form.is_valid()
        profile = form.save(mock.Mock(), factories.ProfileFactory())

        assert not profile.user.is_active


    def test_bad_contact(self):
        """If contact field is unparseable, validation error is raised."""
        form = forms.InviteElderForm(self.data(contact='baz'))

        assert not form.is_valid()
        assert form.errors['contact'] == [
            u"Please supply a valid email address or US mobile number."]


    def test_user_with_email_exists(self):
        """If a user with given email already exists, no new user is created."""
        elder = factories.ProfileFactory(user__email='foo@example.com')
        form = forms.InviteElderForm(self.data(contact='foo@example.COM'))
        assert form.is_valid()
        profile = form.save(None, factories.ProfileFactory())

        assert elder == profile


    def test_user_with_phone_exists(self):
        """If a user with given phone already exists, no new user is created."""
        elder = factories.ProfileFactory(phone='+13214567890')
        form = forms.InviteElderForm(self.data(contact='321.456.7890'))
        assert form.is_valid()
        profile = form.save(None, factories.ProfileFactory())

        assert elder == profile


    def test_update_existing_elder_to_staff(self):
        """If a non-staff is added as staff elder, they gain staff status."""
        elder = factories.ProfileFactory(school_staff=False)
        form = forms.InviteElderForm(
            self.data(contact=elder.phone, school_staff=True))
        assert form.is_valid()
        profile = form.save(None, factories.ProfileFactory())

        assert elder == profile
        assert profile.school_staff


    def test_update_existing_elder_role(self):
        """If existing elder has no role, update from new relationship."""
        elder = factories.ProfileFactory(role='')
        form = forms.InviteElderForm(
            self.data(contact=elder.phone, relationship='foo'))
        assert form.is_valid()
        profile = form.save(None, factories.ProfileFactory())

        assert elder == profile
        assert profile.role == u'foo'


    def test_relationship_exists(self):
        """If existing elder is already elder for student, no error."""
        rel = factories.RelationshipFactory()
        form = forms.InviteElderForm(self.data(contact=rel.elder.phone))
        assert form.is_valid()
        profile = form.save(None, rel.student)

        assert rel.elder == profile
        assert len(profile.students) == 1



class TestAddStudentForm(object):
    """Tests for AddStudentForm."""
    def test_add_student(self):
        """Saves a student, given just name."""
        form = forms.AddStudentForm({'name': "Some Student"})
        assert form.is_valid()
        profile = form.save()

        assert profile.name == u"Some Student"


    def test_add_two_students_same_name(self):
        """Adding two students with same name causes no username trouble."""
        form = forms.AddStudentForm({'name': "Some Student"})
        assert form.is_valid()
        profile1 = form.save()

        form = forms.AddStudentForm({'name': "Some Student"})
        assert form.is_valid()
        profile2 = form.save()

        assert profile1 != profile2


    def test_student_added_by_staff(self):
        """If profile is passed to save(), relationship is created."""
        elder = factories.ProfileFactory()
        form = forms.AddStudentForm({'name': "Some Student"})
        assert form.is_valid()
        profile = form.save(elder)

        assert profile.elders == [elder]



class TestAddStudentAndInviteEldersForm(object):
    """Tests for AddStudentAndInviteEldersForm."""
    def data(self, elders=1, **kwargs):
        """
        Get default form data, with option to specify number of elders.

        Override elder data defaults by specifying kwargs like::

            elder0={'contact':'foo@example.com'}

        """
        defaults = {
            'name': "Some student",
            'elders-TOTAL_FORMS': str(elders),
            'elders-INITIAL_FORMS': '0',
            }
        for i in range(elders):
            defaults.update(self.elder_data(i, **kwargs.pop('elder%s' % i, {})))
        defaults.update(kwargs)
        return defaults


    def elder_data(self, index=0, **kwargs):
        """Get formset form data for an elder with given index."""
        defaults = {
            'contact': 'foo@example.com',
            'relationship': 'mentor',
            'school_staff': False,
            }
        defaults.update(kwargs)
        return dict(('elders-%s-%s' % (index, k), v) for k, v in defaults.items())



    def test_add_student_and_invite_elders(self):
        """Can add a student and invite some elders."""
        form = forms.AddStudentAndInviteEldersForm(
            self.data(
                2,
                elder0={'contact': '321-456-7890'},
                elder1={'contact': '321-654-0987'},
                )
            )
        assert form.is_valid()
        student, elders = form.save(mock.Mock())

        assert set(e.phone for e in elders) == set(
            ['+13214567890', '+13216540987'])
        assert all(e.students == [student] for e in elders)


    def test_elder_form_optional(self):
        """Elder forms can be empty."""
        form = forms.AddStudentAndInviteEldersForm(
            self.data(1, elder0={'contact': '', 'relationship': ''}))

        assert form.is_valid()
        student, elders = form.save(None)

        assert len(elders) == 0
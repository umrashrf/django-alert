import time
from uuid import uuid1
from datetime import datetime

from threading import Thread

from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from django.core import management, mail
from django.conf import settings
from django.db.models.signals import post_save

from alert.utils import BaseAlert, ALERT_TYPES, BaseAlertBackend, ALERT_BACKENDS
from alert.exceptions import AlertIDAlreadyInUse, AlertBackendIDAlreadyInUse, CouldNotSendError
from alert.models import Alert
from django.core.mail import send_mail
from alert.forms import AlertPreferenceForm, UnsubscribeForm


class SubclassTestingAlert(BaseAlert):
    """
    This will never send any alerts - it's just a check to make sure that
    subclassing alerts doesn't explode
    """
    title = 'Welcome new users'
    description = 'When a new user signs up, send them a welcome email'

    signal = post_save
    sender = User
    
    default = True
    
    def before(self, **kwargs):
        return False
    
    def get_applicable_users(self, instance, **kwargs):
        return [instance]


class WelcomeAlert(SubclassTestingAlert):
    """
    everything is inherited from SubclassTestingAlert
    
    only change is that alerts will actually be sent
    """

    def before(self, created, **kwargs):
        return created


class DummyBackend(BaseAlertBackend):
    title = "Dummy"

    def send(self, alert):
        pass



class EpicFailBackend(BaseAlertBackend):
    """
    Backend that fails to send on the first try for every alert
    """
    id = "EpicFail"
    title = "Epic Fail"

    def send(self, alert):
        if not alert.failed:
            raise CouldNotSendError
        

class SlowBackend(BaseAlertBackend):
    """
    Backend that takes a full second to send an alert
    """
    title = "Slow backend"
    
    def send(self, alert):
        time.sleep(1)
        send_mail("asdf", 'woot', 'fake@gmail.com', ['superfake@gmail.com'])




#################################################
###                 Tests                     ###
#################################################

class AlertTests(TestCase):        

    def setUp(self):
        pass
    
    
    def test_alert_creation(self):
        username = str(uuid1().hex)[:16]
        email = "%s@example.com" % username
        
        user = User.objects.create(username=username, email=email)
        
        alerts = Alert.objects.filter(user=user)
        self.assertEqual(len(alerts), len(ALERT_BACKENDS))
        for alert in alerts:
            self.assertEqual(alert.alert_type, "WelcomeAlert")
            if alert.backend == 'EmailBackend':
                self.assertEqual(alert.title, "email subject")
                self.assertEqual(alert.body, "email body")
            else:
                self.assertEqual(alert.title, "default title")
                self.assertEqual(alert.body, "default body")
    
    
    def test_alert_registration_only_happens_once(self):
        self.assertTrue(isinstance(ALERT_TYPES["WelcomeAlert"], WelcomeAlert))
        self.assertEquals(len(ALERT_TYPES), 2)
        
        def define_again():
            class WelcomeAlert(BaseAlert):
                title = 'Welcome new users'
                signal = post_save
        
        self.assertRaises(AlertIDAlreadyInUse, define_again)
        
        

class AlertBackendTests(TestCase):

    def setUp(self):
        username = str(uuid1().hex)[:16]
        email = "%s@example.com" % username
        
        self.user = User.objects.create(username=username, email=email)
    
    
    def test_backend_creation(self):
        self.assertTrue(isinstance(ALERT_BACKENDS["DummyBackend"], DummyBackend))
        
    
    def test_backends_use_supplied_id(self):
        self.assertTrue(isinstance(ALERT_BACKENDS["EpicFail"], EpicFailBackend))
    
    def test_pending_manager(self):
        self.assertEqual(Alert.pending.all().count(), len(ALERT_BACKENDS))
        management.call_command("send_alerts")
        self.assertEqual(Alert.pending.all().count(), 1)
    
    def test_backend_registration_only_happens_once(self):
        self.assertEquals(len(ALERT_BACKENDS), 4)
        
        def define_again():
            class DummyBackend(BaseAlertBackend):
                title = 'dummy'
        
        self.assertRaises(AlertBackendIDAlreadyInUse, define_again)
        
        
    def test_backend_fails_to_send(self):        
        alert_that_should_fail = Alert.objects.filter(backend='EpicFail')[0]
        
        before_send = datetime.now()
        alert_that_should_fail.send()
        after_send = datetime.now()
        
        self.assertTrue(alert_that_should_fail.failed)
        self.assertFalse(alert_that_should_fail.is_sent)
        self.assertTrue(alert_that_should_fail.last_attempt is not None)
        
        self.assertTrue(alert_that_should_fail.last_attempt > before_send)
        self.assertTrue(alert_that_should_fail.last_attempt < after_send)
        
        # and now retry
        before_send = datetime.now()
        alert_that_should_fail.send()
        after_send = datetime.now()
        
        self.assertFalse(alert_that_should_fail.failed)
        self.assertTrue(alert_that_should_fail.is_sent)
        self.assertTrue(alert_that_should_fail.last_attempt is not None)
        
        self.assertTrue(alert_that_should_fail.last_attempt > before_send)
        self.assertTrue(alert_that_should_fail.last_attempt < after_send)

        

class ConcurrencyTests(TransactionTestCase):
    
    def setUp(self):
        username = str(uuid1().hex)[:16]
        email = "%s@example.com" % username
        
        self.user = User.objects.create(username=username, email=email)
        
        
    def testMultipleSimultaneousSendScripts(self):    
        self.assertFalse("sqlite" in settings.DATABASES['default']['ENGINE'],
            """Sqlite uses an in-memory database, which does not work with the concurrency tests.
                Please change the test database to another database (such as MySql).
                
                Note that the alert django app will work fine with Sqlite. It's only the 
                concurrency *tests* that do not work with sqlite.""")
        
        self.assertEqual(len(mail.outbox), 0)
            
        threads = [Thread(target=management.call_command, args=('send_alerts',)) for i in range(100)]
        
        for t in threads:
            t.start()
            
            # space them out a little tiny bit
            time.sleep(0.001)
        
        [t.join() for t in threads]
        
        self.assertEqual(len(mail.outbox), 2)


class EmailBackendTests(TestCase):
    
    def setUp(self):
        pass


class FormTests(TestCase):
    
    def setUp(self):
        self.user = User.objects.create(username='wootz', email='wootz@woot.com')
    
    def testNoArgs(self):
        pref_form = self.assertRaises(TypeError, AlertPreferenceForm)
        unsubscribe_form = self.assertRaises(TypeError, UnsubscribeForm)
        
    def simpleCase(self):
        pref_form = AlertPreferenceForm(self.user)
        unsubscribe_form = UnsubscribeForm(self.user)
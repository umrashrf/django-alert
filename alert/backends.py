from datetime import datetime
from django.core.mail import send_mail
from django.conf import settings

from alert.utils import BaseAlertBackend
from alert.exceptions import CouldNotSendError

class EmailBackend(BaseAlertBackend):
    title = "Email"
    
    def notify(self, alerts):
        try:
            [self.send(n) for n in alerts]
        except TypeError:
            self.send(alerts)
        
    def send(self, alert):
        recipient = alert.user.email
        if not recipient: raise CouldNotSendError
        
        send_mail(alert.title, alert.body, settings.DEFAULT_FROM_EMAIL, [recipient])
        
    
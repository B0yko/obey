from django.db import models


class Order(models.Model):
    status = models.CharField(max_length=20, default="open")

import datetime


ACTIVATION_DATE = datetime.date(2026, 3, 31)
EXPIRY_DAYS = 180
EXPIRY_WARNING_DAYS = 30


def get_expiry_date():
    return ACTIVATION_DATE + datetime.timedelta(days=EXPIRY_DAYS)


def is_expired():
    return datetime.date.today() > get_expiry_date()


def is_expiring_soon():
    expiry = get_expiry_date()
    warning_start = expiry - datetime.timedelta(days=EXPIRY_WARNING_DAYS)
    return warning_start <= datetime.date.today() <= expiry


def days_until_expiry():
    delta = get_expiry_date() - datetime.date.today()
    return max(0, delta.days)

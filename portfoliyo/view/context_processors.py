from django.conf import settings

def services(request):
    return {
        'GOOGLE_ANALYTICS_ID': getattr(settings, 'GOOGLE_ANALYTICS_ID', ''),
        'USERVOICE_ID': getattr(settings, 'USERVOICE_ID', ''),
        'SNAPENGAGE_ID': getattr(settings, 'SNAPENGAGE_ID', ''),
        'MIXPANEL_ID': getattr(settings, 'MIXPANEL_ID', ''),
        'CRAZYEGG_ID': getattr(settings, 'CRAZYEGG_ID', ''),
        'INTERCOM_ID': getattr(settings, 'INTERCOM_ID', ''),
        'PUSHER_KEY': getattr(settings, 'PUSHER_KEY', ''),
        }

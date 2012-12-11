(function ($) {

    'use strict';

    var serverEvents = function (sel, dataAttr) {
        // Look for and record events the server recorded in a JSON structure
        // in the given data attribute of the element named by the given
        // selector. Expect a list of events, where each element in the list is
        // itself a length-two list, where the first element is the event name
        // and the second a properties object.
        var events = $(sel).data(dataAttr);
        if (events) {
            $.each(events, function (index, value) {
                mixpanel.track(value[0], value[1]);
                // If the user just registered, tell mixpanel that we'll be
                // identifying them by user ID from now on, but they should
                // still be considered the same person who previously viewed
                // the landing and register pages anonymously. If we don't do
                // this, then we can't track users' progression from landing to
                // register to use of the site.
                if (value[0] === 'registered' && value[1].user_id) {
                    mixpanel.alias(value[1].user_id);
                }
            });
        }
    };

    var existence = function (sel, eventName) {
        // Fire given event name if the given selector exists on the page.
        if ($(sel).length) {
            mixpanel.track(eventName);
        }
    };

    var ajaxClick = function (sel, eventName) {
        // This function is only safe to use on clicks that don't reload the
        // page (otherwise the page will reload before this has time to
        // actually send the event off to mixpanel).  For normal links, use
        // mixpanel.track_click (or better, do it on the target page or on the
        // server).
        $('body').on('click', sel, function () {
            mixpanel.track(eventName);
        });
    };

    var identifyUser = function (sel) {
        // Identify the current user to MixPanel, based on data attributes
        // found on the element named by the given selector.
        var elem = $(sel);
        if (elem.length) {
            var userId = elem.data('user-id');
            var userEmail = elem.data('user-email');
            if (userId) {
                mixpanel.identify(userId);
                if (userEmail) {
                    mixpanel.name_tag(userEmail);
                    mixpanel.people.set({
                        $email: userEmail
                    });
                }
            }
        }
    };

    var ajaxPageViews = function () {
        var History = window.History;
        if (History.enabled) {
            $(window).on('statechange', function () {
                // by the time we get here, the URL is already changed, so
                // mixpanel gets the right URL automatically.
                mixpanel.track_pageview();
            });
        }
    };

    $(function () {
        existence('article.landing', 'viewed landing');
        existence('article.register', 'viewed register');
        existence('article.awaiting-activation', 'registered');
        existence('.login .activated.success', 'activated');

        ajaxClick('.action-post', 'posted');
        ajaxClick('.group-posts', 'mass texted');

        serverEvents('.meta', 'user-events');

        ajaxPageViews();

        // this should come last, to make sure that on registration we call
        // mixpanel.alias() with their user id (handled in serverEvents) before
        // we try to identify the user using their user-id.
        identifyUser('.meta .settingslink');
    });

}(jQuery));

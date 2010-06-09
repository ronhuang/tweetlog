#!/usr/bin/env python
#
# Copyright (c) 2010 Ron Huang
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.


from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
import os
from google.appengine.ext.webapp import template
import tweepy
from tweepy import Cursor
from configs import CONSUMER_KEY, CONSUMER_SECRET, CALLBACK
from models import OAuthToken, User
from utils import Cookies


COOKIE_LIFE = 7 * 24 * 60 * 60 # 1 week


def get_user_status(cookies):
    user = None
    screen_name = None

    if "ulg" in cookies and "auau" in cookies:
        token_key = cookies["ulg"]
        token_secret = cookies["auau"]

        user = User.gql("WHERE token_key=:key AND token_secret=:secret",
                        key=token_key, secret=token_secret).get()

    if user:
        screen_name = user.screen_name

    return user, screen_name


class MainHandler(webapp.RequestHandler):
    def get(self):
        cookies = Cookies(self, max_age = COOKIE_LIFE)
        user, screen_name = get_user_status(cookies)
        data = {
            'signed_in': user and True,
            'screen_name': screen_name,
            }
        path = os.path.join(os.path.dirname(__file__), 'view', 'about.html')
        self.response.out.write(template.render(path, data))


class CallbackHandler(webapp.RequestHandler):
    def get(self):
        oauth_token = self.request.get("oauth_token", None)
        oauth_verifier = self.request.get("oauth_verifier", None)

        if oauth_token is None:
            # Invalid request!
            msg = {'message': 'Missing required parameters!'}
            path = os.path.join(os.path.dirname(__file__), 'view', 'error.html')
            self.response.out.write(template.render(path, msg))
            return

        # lookup the request token
        request_token = OAuthToken.gql("WHERE token_key=:key", key=oauth_token).get()
        if request_token is None:
            # We do not seem to have this request token, show an error.
            msg = {'message': 'Invalid token!'}
            path = os.path.join(os.path.dirname(__file__), 'view', 'error.html')
            self.response.out.write(template.render(path, msg))
            return

        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_request_token(request_token.token_key, request_token.token_secret)
        request_token.delete() # FIXME: better use session.

        # fetch the access token
        try:
            auth.get_access_token(oauth_verifier)
        except tweepy.TweepError, e:
            # Failed to get access token
            msg = {'message': e}
            path = os.path.join(os.path.dirname(__file__), 'view', 'error.html')
            self.response.out.write(template.render(path, msg))
            return

        # remember on the user browser
        cookies = Cookies(self, max_age = COOKIE_LIFE)
        token_key = cookies["ulg"] = auth.access_token.key
        token_secret = cookies["auau"] = auth.access_token.secret

        # save to datastore if not already
        user = User.gql("WHERE token_key=:key AND token_secret=:secret",
                        key=token_key, secret=token_secret).get()
        if user is None:
            api = tweepy.API(auth)
            twitter_user = api.me()
            user = User(
                screen_name = twitter_user.screen_name,
                token_key = auth.access_token.key,
                token_secret = auth.access_token.secret
                )
            user.put()

        self.redirect("/manage")


class SignInHandler(webapp.RequestHandler):
    def get(self):
        cookies = Cookies(self, max_age = COOKIE_LIFE)
        token_key = None
        token_secret = None

        if "ulg" in cookies:
            token_key = cookies["ulg"]
        if "auau" in cookies:
            token_secret = cookies["auau"]

        if token_key is not None and token_secret is not None:
            self.redirect("/manage")
            return

        # OAuth dance
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET, CALLBACK)
        try:
            url = auth.get_authorization_url()
        except tweepy.TweepError, e:
            # Failed to get a request token
            msg = {'message': e}
            path = os.path.join(os.path.dirname(__file__), 'view', 'error.html')
            self.response.out.write(template.render(path, msg))
            return

        # store the request token for later use in the callback page.
        # FIXME: better use session.
        request_token = OAuthToken(
            token_key = auth.request_token.key,
            token_secret = auth.request_token.secret
            )
        request_token.put()

        self.redirect(url)


class SignOutHandler(webapp.RequestHandler):
    def get(self):
        cookies = Cookies(self, max_age = COOKIE_LIFE)
        del cookies["ulg"]
        del cookies["auau"]

        self.redirect("/")


class ManageHandler(webapp.RequestHandler):
    def get(self):
        cookies = Cookies(self, max_age = COOKIE_LIFE)
        user, screen_name = get_user_status(cookies)
        lists = []

        if user:
            auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
            auth.set_access_token(user.token_key, user.token_secret)
            api = tweepy.API(auth)

            #me = api.me()
            #for l in me.lists()[0]:
            #    lists.append(l.full_name)

            for l in Cursor(api.lists).items():
                lists.append(l)

        data = {
            'signed_in': user and True,
            'screen_name': screen_name,
            'lists': lists,
            }
        path = os.path.join(os.path.dirname(__file__), 'view', 'manage.html')
        self.response.out.write(template.render(path, data))


def main():
    actions = [
        ('/', MainHandler),
        ('/callback', CallbackHandler),
        ('/sign_in', SignInHandler),
        ('/sign_out', SignOutHandler),
        ('/manage', ManageHandler),
        ]
    application = webapp.WSGIApplication(actions, debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()

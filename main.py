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
import re
import logging
from google.appengine.ext.webapp import template
from google.appengine.api.labs import taskqueue
import tweepy
from tweepy import Cursor
from configs import CONSUMER_KEY, CONSUMER_SECRET, CALLBACK
from models import OAuthToken, User, Criterion
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
        request_token.delete()

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
            user = User.gql("WHERE token_key=:key AND token_secret=:secret",
                            key=token_key, secret=token_secret).get()
            if user is not None:
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
        oauth_token = auth.request_token.key
        oauth_secret = auth.request_token.secret
        request_token = OAuthToken.gql("WHERE token_key=:key AND secret=:secret",
                                       key=oauth_token, secret=oauth_secret).get()
        if request_token is not None:
            request_token.delete()
        request_token = OAuthToken(
            token_key = oauth_token,
            token_secret = oauth_secret
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
        lists = []
        term = ""
        list_id = 0

        cookies = Cookies(self, max_age = COOKIE_LIFE)
        user, screen_name = get_user_status(cookies)

        if user:
            auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
            auth.set_access_token(user.token_key, user.token_secret)
            api = tweepy.API(auth)

            for l in Cursor(api.lists).items():
                lists.append(l)

        c = Criterion.gql("WHERE screen_name=:name", name=screen_name).get()
        if c:
            term = c.term
            list_id = int(c.list_id or 0)

        data = {
            'signed_in': user and True,
            'screen_name': screen_name,
            'lists': lists,
            'term': term,
            'list_id': list_id,
            }
        path = os.path.join(os.path.dirname(__file__), 'view', 'manage.html')
        self.response.out.write(template.render(path, data))


class PreviewHandler(webapp.RequestHandler):
    def get(self):
        cookies = Cookies(self, max_age = COOKIE_LIFE)
        user, screen_name = get_user_status(cookies)
        if user is None:
            self.response.out.write("")
            return

        term = self.request.get("term")
        list_id = self.request.get("list_id")
        if len(term) == 0 or len(list_id) == 0:
            self.response.out.write("")
            return

        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_access_token(user.token_key, user.token_secret)
        api = tweepy.API(auth)

        prog = re.compile(term, re.IGNORECASE)
        total_count = 100
        effective_count = 10
        result = []

        try:
            for status in Cursor(api.list_timeline, owner=user.screen_name, slug=list_id).items():
                if prog.search(status.text):
                    result.append("<pre>")
                    result.append(status.user.screen_name)
                    result.append(": ")
                    result.append(status.text)
                    result.append("</pre>")
                    effective_count -= 1

                total_count -= 1

                if effective_count <= 0 or total_count <= 0:
                    # enough for preview?
                    break
        except tweepy.TweepError, e:
            self.response.out.write("")
            return

        self.response.out.write("".join(result))


class SaveHandler(webapp.RequestHandler):
    def post(self):
        cookies = Cookies(self, max_age = COOKIE_LIFE)
        user, screen_name = get_user_status(cookies)
        if user is None:
            self.response.out.write("fail")
            return

        term = self.request.get("term")
        list_id = self.request.get("list_id")

        # delete the criterion if both are empty.
        if len(term) == 0 and len(list_id) == 0:
            c = Criterion.gql("WHERE screen_name=:name",
                              name=screen_name).get()
            if c is not None:
                c.delete()
            self.response.out.write("success")
            return

        # return fail if some fields are empty.
        if len(term) == 0 or len(list_id) == 0:
            self.response.out.write("fail")
            return

        # create or update criterion
        c = Criterion.gql("WHERE screen_name=:name",
                          name=user.screen_name).get()
        if c is not None:
            c.term = term
            c.list_id = list_id
        else:
            c = Criterion(
                screen_name = user.screen_name,
                term = term,
                list_id = list_id)
        c.put()

        self.response.out.write("success")


class TriggerHandler(webapp.RequestHandler):
    def get(self):
        for c in Criterion.all():
            params = {
                "screen_name": c.screen_name,
                "term": c.term,
                "list_id": c.list_id,
                }
            taskqueue.add(url = "/collect", params = params)


class CollectHandler(webapp.RequestHandler):
    def post(self):
        screen_name = self.request.get("screen_name")
        term = self.request.get("term")
        list_id = self.request.get("list_id")

        u = User.gql("WHERE screen_name = :name", name = screen_name).get()
        if u is None:
            logging.error("Could not find screen name: %s.", screen_name)
            return
        since_id = u.since_id
        token_key = u.token_key
        token_secret = u.token_secret

        # prepare Twitter API.
        auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
        auth.set_access_token(token_key, token_secret)
        api = tweepy.API(auth)

        # if it's the first time this user is using this service,
        # check all the existing tweets.
        existing_tweets = set()
        if since_id is None:
            try:
                for t in Cursor(api.retweeted_by_me).items():
                    existing_tweets.add(t.retweeted_status.id)
            except tweepy.TweepError, e:
                logging.error(e)
                return

        # retweet
        prog = re.compile(term, re.IGNORECASE)
        max_id = 1
        try:
            for t in Cursor(api.list_timeline, owner=screen_name, slug=list_id, since_id=since_id or 1).items():
                if prog.search(t.text) and (t.id not in existing_tweets):
                    logging.info("%s RT %d", screen_name, t.id)
                    api.retweet(t.id)
                # keep max tweet id as the next since_id
                if max_id < t.id:
                    max_id = t.id
        except tweepy.TweepError, e:
            logging.error(e)
            return

        # update since_id
        if u.since_id < max_id:
            u.since_id = max_id
            u.put()


def main():
    actions = [
        ('/', MainHandler),
        ('/callback', CallbackHandler),
        ('/sign_in', SignInHandler),
        ('/sign_out', SignOutHandler),
        ('/manage', ManageHandler),
        ('/preview', PreviewHandler),
        ('/save', SaveHandler),
        ('/trigger', TriggerHandler),
        ('/collect', CollectHandler),
        ]
    application = webapp.WSGIApplication(actions, debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()

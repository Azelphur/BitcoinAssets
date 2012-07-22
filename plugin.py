# -*- coding: utf-8 -*-
###
# Copyright (c) 2012, Alfie "Azelphur" Day
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import supybot.irclib as irclib
import supybot.schedule as schedule
from supybot.i18n import PluginInternationalization, internationalizeDocstring
import tweetstream
import threading
import time
import socket
import supybot.ircmsgs as ircmsgs
import urllib2
import json
from decimal import *

_ = PluginInternationalization('BitcoinAssets')
getcontext().prec = 8

def zeroTrunc(num):
    num = str(num)
    if "." in num:
        return str(num).rstrip('0')
    else:
        return num

def getURLSafe(callback, url, retries, data=()):
    print url, retries, data
    t1 = HTTPQuery(callback, url, retries, data)
    t1.start()

class HTTPQuery(threading.Thread):
    def __init__(self, target, *args):
        self._target = target
        self._args = args
        threading.Thread.__init__(self)
 
    def run(self):
        if self._args[1] == 0:
            while True:
                try:
                    u = urllib2.urlopen(self._args[0])
                    data = u.read()
                except:
                    continue
                self._target(data, self._args[2])
                return
        else:
            for i in range(0, self._args[1]):
                try:
                    u = urllib2.urlopen(self._args[0])
                    data = u.read()
                except:
                    continue
                self._target(data, self._args[2])
                return
            self._target(None, self._args[2])

class TweetProcessor( ):
    def __init__(self):
        self.networks = []
        self.last = {}
        self.last['GLBSE'] = {}
        self.last['MPEX'] = {}

    def _addIrc(self, irc):
        # We need to keep a directory of IRC objects for each network to send arbitrary messages through.
        if irc not in self.networks:
            self.networks.append(irc)

    def processTrade(self, exchange, asset, quantity, price):
        symbol = "TRADE"
        last = self.last[exchange].get(asset, None)
        if last != None:
            if last < Decimal(price):
                symbol = u'^\x0303TRADE\x03'
            elif last > Decimal(price):
                symbol = u'v\x0304TRADE\x03'
            else:
                symbol = u'~\x0314TRADE\x03'
        
        self.last[exchange][asset] = Decimal(price)
        try:
            if quantity == 1:
                return u'[ %s ] [ %s ] [ %s ] [ %d @ %s ]' % (exchange, symbol, asset, quantity, price)

            return u'[ %s ] [ %s ] [ %s ] [ %d @ %s = %s ]' % (exchange, symbol, asset, quantity, price, zeroTrunc(quantity * Decimal(price)))
        except:
            print exchange, symbol, asset, quantity, price, zeroTrunc(quantity * Decimal(price))
            print u'[ %s ] [ %s ] [ %s ] [ %d @ %s = %s ]'

    def process(self, tweet):
        user = tweet["user"]["screen_name"].lower()
        message = tweet["text"]
        print 'Processing', user, message
        if user == 'glbse':
            split = message.split(':')
            quantity, price = split[1].split('@')
            message = self.processTrade('GLBSE', split[2], int(quantity), price)
        elif user == 'mpex1':
            split = message.split()
            message = self.processTrade('MPEX', split[1], int(split[0].replace('`', '')), split[3].replace('BTC', ''))
        else:
            message = "%s %s" % (user, message)

        # Send the tweet where it's supposed to go
        for irc in self.networks:
            if irc.network == 'Freenode':
                irc.queueMsg(ircmsgs.privmsg('#bitcoin-shares', message))


class TweetStream( threading.Thread ):
    def __init__(self, processor):
        super(TweetStream, self).__init__()
        self.stop = False
        self.tweetprocessor = processor

    def die(self):
        print 'Killing the thread'
        self.stop = True
        self.stream.close()

    def run(self):
        socket.setdefaulttimeout(None) # supybot sets a global timeout elsewhere :/
        socket._fileobject.default_bufsize = 0 # http://blog.persistent.info/2009/08/twitter-streaming-api-from-python.html
        while True:
            print 'connecting to twitter'
            self.stream = tweetstream.FilterStream("TWITTERUSER", "TWITTERPASS", follow=[278613296, 552245625])
            while True:
                self.tweetprocessor.process(self.stream.next())
                if self.stop:
                    return
            self.stop = False


@internationalizeDocstring
class BitcoinAssets(callbacks.Plugin):
    """Add the help for "@plugin help BitcoinAssets" here
    This should describe *how* to use this plugin."""
    threaded = True
    def __init__(self, irc):
        super(BitcoinAssets, self).__init__(irc)

        getcontext().prec = 8

        self.ircstates = {}

        self.tweetprocessor = TweetProcessor()

        self.tweetstream = TweetStream(self.tweetprocessor)
        self.tweetstream.start()

    def __call__(self, irc, msg):
        irc = self._getRealIrc(irc)
        if irc not in self.ircstates:
            self.tweetprocessor._addIrc(irc)

    def _getRealIrc(self, irc):
        if isinstance(irc, irclib.Irc):
            return irc
        else:
            return irc.getRealIrc()

    def die(self):
        self.tweetstream.die()

    def ticker(self, irc, msg, args):
        request = args[0].upper()
        u = urllib2.urlopen("https://glbse.com/api/asset/%s" % request)
        data = u.read()
        if data == '':
            irc.reply( "Couldn't find %s on GLBSE" % (request) )
            return
        data = json.loads(data)
        bid = Decimal(data['bid'])/100000000
        ask = Decimal(data['ask'])/100000000
        spread = ask-bid
        last = Decimal(data['latest_trade'])/100000000
        volume = Decimal(data['t24hvol'])/100000000
        irc.reply( "[ GLBSE ] [ TICKER ] [ %s ] [ BID: %s ] [ ASK: %s ] [ SPREAD : %s ] [ LAST TRADE: %s ] [ 24h VOLUME : %s BTC ]" % ( request, bid, ask, spread, last, volume ) )


Class = BitcoinAssets


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:

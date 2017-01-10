#!/usr/bin/python2
'''
Hello?
'''

# The MIT License (MIT)
#
# Copyright (c) 2017 Wizcorp
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

ANSIBLE_METADATA = {'status': ['stableinterface'],
                    'supported_by': 'committer',
                    'version': '1.0'}

DOCUMENTATION = '''
---
module: swarm
short_description: control the swarm configuration of a docker node
'''

EXAMPLES = '''
- name: init a new swarm (both addrs are optional), force will force init a new swarm every provisioning
  swarm: action=init listen_addr=10.0.0.5 advertise_addr=10.0.0.5 force=false
- name: join a swarm
  swarm: action=join type=worker remote_addrs="node1:2377,node2:2377" listen_addr=10.0.0.6 advertise_addr=10.0.0.6
- name: leave a swarm
  swarm: action=leave
'''

DEFAULT_UNIX_SOCKET = 'unix://%2Fvar%2Frun%2Fdocker.sock'

from ansible.module_utils.six import iteritems

from ansible.module_utils.basic import *
from ansible.module_utils.urls import *

from urllib2 import AbstractHTTPHandler, build_opener, install_opener, urlopen, addinfourl, Request
from urllib import unquote
from httplib import HTTPConnection

import json
import socket

# HELPERS

class UHTTPConnection(HTTPConnection):
    """Subclass of Python library HTTPConnection that
        uses a unix-domain socket.
    """

    def __init__(self, path, **kwargs):
        HTTPConnection.__init__(self, 'localhost')
        self.path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.path)
        self.sock = sock

class UnixHandler(AbstractHTTPHandler):
    """This is a simple handler that allows us to call
       urlopen on unix sockets using the following url format:
       unix://%2Fvar%2Frun%2whatver.sock/path/to/resource
    """

    def unix_open(self, req):
        h = UHTTPConnection(unquote(req.get_host()))

        headers = dict(req.headers)
        headers.update(req.unredirected_hdrs)

        # We want to make an HTTP/1.1 request, but the addinfourl
        # class isn't prepared to deal with a persistent connection.
        # It will try to read all remaining data from the socket,
        # which will block while the server waits for the next request.
        # So make sure the connection gets closed after the (only)
        # request.
        headers["Connection"] = "close"
        headers = dict(
            (name.title(), val) for name, val in headers.items())
        try:
            h.request(req.get_method(), req.get_selector(), req.data, headers)
            try:
                r = h.getresponse(buffering=True)
            except TypeError: #buffering kw not supported
                r = h.getresponse()
        except socket.error, err: # XXX what error?
            raise URLError(err)

        r.recv = r.read
        fp = socket._fileobject(r, close=True)

        resp = addinfourl(fp, r.msg, req.get_full_url())
        resp.code = r.status
        resp.msg = r.reason
        return resp

def build_url(args, path):
    """Build the URL to Docker based on kwargs and path"""
    url = DEFAULT_UNIX_SOCKET
    if 'url' in args and args['url'] != None:
        url = args['url']

    # TODO: should we read from the environment the DOCKER_HOST?

    if '://' not in url:
        url = 'http://' + url

    return url + path

def fetch_url(url, data=None):
    """Try to fetch the given URL, return an empty dict on failure"""


    try:
        req = None
        if data != None:
            req = Request(url, json.dumps(data), {'Content-Type': 'application/json'})
        else:
            req = Request(url)

        f = urlopen(req)
        res = json.loads(f.read())
        code = f.getcode()
        f.close()
        return code, res
    except:
        return 500, dict()

# ACTUAL DOCKER METHODS

def init(listen_addr=None, advertise_addr=None, force=False, **kwargs):
    """Init a swarm cluster"""
    post_data = dict(
        ListenAddr=listen_addr,
        ForceNewCluster=force
    )

    if advertise_addr != None and advertise_addr != "":
        post_data['AdvertiseAddr'] = advertise_addr

    code, res = fetch_url(build_url(kwargs, '/swarm/init'), post_data)

    # already in a swarm
    if code == 406:
        return False, res

    if code == 200:
        return True, res

    raise Exception('Invalid answer from docker: %s' % (res['message']))

def main():
    install_opener(build_opener(UnixHandler()))

    #argument_spec = url_argument_spec()
    argument_spec = dict(
        url = dict(required=False),
        action = dict(required=True, choices=['init', 'join', 'leave']),
        listen_addr = dict(required=True),
        advertise_addr = dict(required=False),
        force = dict(required=False, type='bool'),
        remote_addrs = dict(required=False),
    )

    module = AnsibleModule(argument_spec = argument_spec)

    action = module.params['action']

    try:
        res = None
        if action == 'init':
            changed, res = init(**module.params)

        module.exit_json(changed=changed, result=res)
    except Exception as e:
        module.exit_json(failed=True, msg=str(e))

if __name__ == '__main__':
    main()
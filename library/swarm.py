#!/usr/bin/python2
'''
Allows one to manipulate a Swarm cluster through ansible directives
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
import urlparse

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

    parsed_url = urlparse.urlparse(url)
    if parsed_url.scheme[0:4] == 'http' and parsed_url.port == None:
        parsed_url = parsed_url._replace(netloc=parsed_url.netloc + ':2376')

    parsed_url = parsed_url._replace(path=path)

    return parsed_url.geturl()

def fetch_url(url, data=None):
    """Try to fetch the given URL, if data is provided it is json encoded and POSTed"""
    req = None
    if data != None:
        req = Request(url, json.dumps(data), {'Content-Type': 'application/json'})
    else:
        req = Request(url)

    f = urlopen(req)
    res = f.read()
    code = f.getcode()
    f.close()

    if len(res) > 0:
        res = json.loads(res)

    return code, res

def get_info(**kwargs):
    code, info = fetch_url(build_url(kwargs, '/info'))

    if code != 200:
        raise Exception('Could not retrieve node information')

    return info

def get_swarm_addrs(node_addr):
    info = get_info(url=node_addr)

    if 'Swarm' not in info or 'RemoteManagers' not in info['Swarm']:
        return None

    return [manager['Addr'] for manager in info['Swarm']['RemoteManagers']]

def get_join_token(node_addrs, node_type):
    """Get the join tokens and the swarm addr from the first answering node in a list of remote nodes"""
    for node_addr in node_addrs:
        code, info = fetch_url(build_url(dict(url=node_addr), '/swarm'))

        if code != 200:
            continue

        if 'JoinTokens' not in info:
            continue

        return info['JoinTokens'][node_type.capitalize()], get_swarm_addrs(node_addr)

    return None, None

# ACTUAL DOCKER METHODS

def init(listen_addr, advertise_addr=None, force=False, **kwargs):
    """Init a swarm cluster"""
    post_data = dict(
        ListenAddr=listen_addr,
        ForceNewCluster=force
    )

    if advertise_addr != None and advertise_addr != "":
        post_data['AdvertiseAddr'] = advertise_addr

    code, res = fetch_url(build_url(kwargs, '/swarm/init'), post_data)

    # already in a swarm
    if code == 406 or code == 503:
        return False, res

    if code == 200:
        return True, res

    raise Exception('Invalid answer from docker [%d]: %s' % (code, res['message']))

def join(type, remote_addrs, listen_addr, advertise_addr=None, **kwargs):
    if type not in ['worker', 'manager']:
        raise Exception("value of type must be one of: worker,manager, got: %s" % (type))

    # find the join token
    token, swarm_addrs = get_join_token(remote_addrs, type)

    if token == None or len(swarm_addrs) == 0:
        raise Exception('Could not load swarm information from any of the remote nodes')

    post_data = dict(
        ListenAddr=listen_addr,
        RemoteAddrs=swarm_addrs,
        JoinToken=token
    )

    if advertise_addr != None and advertise_addr != "":
        post_data['AdvertiseAddr'] = advertise_addr

    code, res = fetch_url(build_url(kwargs, '/swarm/join'), post_data)

    # already in a swarm
    if code == 406 or code == 503:
        return False, res

    if code == 200:
        return True, res

    raise Exception('Invalid answer from docker [%d]: %s' % (code, res['message']))

def availability(type, **kwargs):
    if type not in ['active', 'pause', 'drain']:
        raise Exception("value of type must be one of: active,pause,drain, got: %s" % (type))

    # retrieve the node id
    info = get_info(**kwargs)

    if 'Swarm' not in info or 'NodeID' not in info['Swarm']:
        raise Exception('This node is not part of a swarm')

    node_id = info['Swarm']['NodeID']

    code, node_info = fetch_url(build_url(kwargs, '/nodes/%s' % (node_id)))

    if code != 200 or 'Spec' not in node_info:
        raise Exception('Could not retrieve node information')

    current_type = node_info['Spec']['Availability']
    current_version = node_info['Version']['Index']

    if type == current_type:
        return False, None

    post_data = node_info['Spec']
    post_data['Availability'] = type

    code, res = fetch_url(build_url(kwargs, '/nodes/%s/update?version=%d' % (node_id, current_version)), post_data)

    if code == 200:
        return True, res

    raise Exception('Invalid answer from docker: %s' % (res['message']))

def main():
    install_opener(build_opener(UnixHandler()))

    #argument_spec = url_argument_spec()
    argument_spec = dict(
        url = dict(required=False),
        action = dict(required=True, choices=['init', 'join', 'availability']),
        listen_addr = dict(required=False),
        advertise_addr = dict(required=False),
        force = dict(required=False, type='bool'),
        remote_addrs = dict(required=False, type='list'),
        type = dict(required=False)
    )

    module = AnsibleModule(argument_spec = argument_spec)

    action = module.params['action']

    try:
        res = None
        if action == 'init':
            changed, res = init(**module.params)
        elif action == 'join':
            changed, res = join(**module.params)
        elif action == 'availability':
            changed, res = availability(**module.params)

        module.exit_json(changed=changed, result=res)
    except Exception as e:
        module.exit_json(failed=True, msg=str(e))

if __name__ == '__main__':
    main()
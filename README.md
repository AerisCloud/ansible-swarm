Swarm
=====

Library and tasks for creating a swarm docker 1.12+

When using the tasks you should make sure that either your managers are already setup or that the leader nodes are
processed before/at the same time as the managers otherwise the manager join will fail due to the cluster not existing.

Requirements
------------

Docker must be available on the node itself.

Role Variables
--------------

```yaml
# this is the url to the docker instance we want to manipulate, default to the unix socket
swarm_docker_url: ""

# whether we should create a cluster on this node?
swarm_leader: false

# use to join a cluster as a manager
swarm_manager: false

# use to join a cluster as a worker
swarm_worker: false

# when joining a cluster, this should contain a list of nodes with docker available through HTTP (port defaults to 2376
# if not specified)
swarm_remote_addrs: []

# on which (address|interface)[:port] the swarm should be listening
swarm_listen_addr: 0.0.0.0

# advertise address, docker will try to find a decent default
swarm_advertise_addr: ""

# when set, updates the node availability to match this value, can be either "active", "pause", "drain"
swarm_availability: "drain"
```

Dependencies
------------

None

Example Playbook
----------------

Including an example of how to use your role (for instance, with variables passed in as parameters) is always nice for users too:

```yaml
- hosts: swarm
  gather_facts: true
  become: true
  roles:
  - AerisCloud.swarm
```

License
-------

MIT

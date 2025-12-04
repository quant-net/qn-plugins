QUANT-NET Control Plane Plugins
===============================

Controller plugins extend the built-in functionality of the Quant-Net
Control Plane (QNCP). There are currently four plugin types (Routing, 
Scheduling, Monitoring, and Protocol), each representing common classes
of functions involved in quantum networking experiments. This repository
is expected to primarily contain plugins of type ``Protocol``.

Each plugin defines both client and server commands for RPC calls, along
with the corresponding handlers that the controller must process.
Additionally, plugins can define message commands to handle non-RPC
messages. When the controller starts, it loads and initializes these
plugins, registering the provided commands in its RPC server and client
and message server.

The ``ControllerContextManager`` provides the running context of the
controller to a plugin. The ``context`` object includes the current
controller configuration, the RPC server/client, and the Message
server/client.

An example of how to use plugins to implement message handling can be
found in the QNCP documentation.


Installation and Usage
----------------------

Plugins should be referenced by QNCP Controllers and Agents by setting
the appropriate paths in their respective configuration files. Both
Controller and Agent configuration files contain plugin and schema path
entries.

This plugin repository does not require any independent installation or
configuration beyond making the contents accessible to the Controller and
Agent processes.

Plugin Layout
-------------

The typical filesystem layout for a Protocol Plugin is as follows:

 * A named plugin folder under top-level directory.
 * A subfolder that contains the Controller plugin definition. Here
  ``pingpong``, which becomes the name of the loaded plugin in the
  Controller process.
 * An ``interpreter`` subfolder that contains the protocol interpreter code
   for the Agent process.
 * Any protocol schema for the plugin placed in a common ``schema`` folder.


```
plugins/
|-- myPingPongPlugin/
|   |-- pingpong/
|   |   |-- __init__.py
|   |   `-- ponger.py
|   `-- interpreter/
|       `-- phandler.py
`-- schema/
    `-- pingpong.yaml
```

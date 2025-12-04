"""
Copyright (c) 2023- ESnet

All rights reserved. This program and the accompanying materials
are made available under the terms of the Eclipse Public License v2.0
and Eclipse Distribution License v1.0 which accompany this distribution.
"""

import time
import logging
from quantnet_mq.schema.models import pingpong, Status as responseStatus
from quantnet_mq import Code
from quantnet_agent.hal.HAL import CMDInterpreter


log = logging.getLogger(__name__)


class PingPong(CMDInterpreter):

    def __init__(self, hal):
        super().__init__(hal)

    async def handle_ping(self, request):
        """
        Handle the RPC request of ping

        It sends the received request payload to attached driver and get result.
        """
        log.info("Received ping request: %s", request.serialize())

        device_configured = (
            f"Agent {self.hal._config.cid} is configured with the following drivers: "
            f"{', '.join([i for i in self.hal.devs])}"
        )

        # send data
        return pingpong.pong(timestamp=time.time(),
                             message=device_configured)

    def get_commands(self):
        commands = {"pingpong.ping": [self.handle_ping, "quantnet_mq.schema.models.pingpong.ping"]}
        return commands

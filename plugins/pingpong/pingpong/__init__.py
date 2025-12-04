import logging
from quantnet_controller.common.plugin import ProtocolPlugin, PluginType
from quantnet_controller.common.request import RequestManager, RequestType, RequestParameter
from quantnet_mq import Code
from quantnet_mq.schema.models import pingpong, Status as responseStatus
from pingponger import PingPonger

logger = logging.getLogger(__name__)


class PingPongProtocol(ProtocolPlugin):
    def __init__(self, context):
        super().__init__("pingpong", PluginType.PROTOCOL, context)
        self._client_commands = [
            ("pingpong.ping", None, "quantnet_mq.schema.models.pingpong.ping"),
        ]
        self._server_commands = [
            ("pingpong", self.handle_pingpong, "quantnet_mq.schema.models.pingpong.pingPongRequest"),
        ]
        self._msg_commands = list()
        self.ctx = context

        # Initialize RequestManager for protocol-type requests
        self.request_manager = RequestManager(
            context, plugin_schema=pingpong.pingPongRequest, request_type=RequestType.PROTOCOL
        )

        self._pingponger = PingPonger(config=context.config, rpcclient=context.rpcclient, msgclient=context.msgclient)

    def initialize(self):
        pass

    def destroy(self):
        pass

    def reset(self):
        pass

    async def handle_pingpong(self, request):
        """Handle pingpong request."""
        logger.info(f"Received pingpong request: {request.serialize()}")

        # Create plugin-specific payload object
        payload = pingpong.pingPongRequest(**request)

        rc = Code.OK

        if payload.payload.type == "ping":
            try:
                # Create Request object with custom function
                req = self.request_manager.new_request(
                    payload=payload, parameters=RequestParameter(), func=self._pingponger.pingpong
                )

                # Execute immediately without queueing
                rc = await self.request_manager.noSchedule(req, blocking=True)

            except Exception as e:
                logger.error(f"Could not schedule pingpong request: {e}")
                import traceback

                traceback.print_exc()
                rc = Code.FAILED
        else:
            logger.error(f"Unknown pingpong request type {payload.payload.type}")
            rc = Code.FAILED

        return pingpong.pingPongResponse(
            status=responseStatus(code=rc.value, value=Code(rc).name), token=payload.payload.token
        )

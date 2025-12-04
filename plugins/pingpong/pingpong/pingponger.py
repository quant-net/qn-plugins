import time
import logging
import asyncio
import json
import statistics as st
from dataclasses import dataclass, asdict
from quantnet_mq.schema.models import pingpong
from quantnet_controller.core import AbstractDatabase as DB

log = logging.getLogger(__name__)


class PingPonger():
    def __init__(self, config, rpcclient, msgclient):
        self._rpcclient = rpcclient
        self._msgclient = msgclient
        self._rpc_topic_prefix = config.rpc_client_topic
        self._db = DB().handler("PingPong")

    async def pingTask(self, agent_id, req):
        """ Ping task for a single destination (agent_id)
        """
        token = str(req.payload.token)
        iterations = int(req.payload.iterations)
        obj = pingpong.pingPongRecord(id=f"{agent_id}-{token}",
                                      agent=agent_id,
                                      phase="start",
                                      start_ts=time.time(),
                                      iterations=iterations)
        dbkey = {"id": f"{agent_id}-{token}"}
        self._db.upsert(dbkey, obj.as_dict())

        res_val = str()
        rtts = list()
        trials = list()
        for i in range(iterations):
            start = time.time()

            # send ping message to remote agent
            topic = f"{self._rpc_topic_prefix}/{agent_id}"
            log.info(f"{i} sending Ping message to {topic}")
            generationResp = self._rpcclient.call(
                "pingpong.ping",
                {"value": agent_id},
                topic=topic,
                timeout=2
            )
            try:
                generationResp = json.loads(await generationResp)
                end = time.time()
                rtt = (end-start)*1e3
                rtts.append(rtt)
                trials.append(True)
                log.info(f"Received Pong ({rtt:.1f} ms): {generationResp}")
                res_val = f"{generationResp}"
                await asyncio.sleep(1)
            except TimeoutError as e:
                log.error(f"Did not receive Pong: {e}")
                trials.append(False)

        if (trials.count(True) == iterations):
            phase_val = "done_success"
        else:
            phase_val = "done_failure"
        self._db.upsert(dbkey, {"phase": phase_val, "result": res_val,
                        "end_ts": time.time(), "successes": trials.count(True)})
        if rtts:
            self._db.upsert(dbkey, {"rtt_min": min(rtts), "rtt_max": max(rtts),
                            "rtt_avg": st.mean(rtts), "rtt_mdev": st.stdev(rtts) if len(rtts) > 1 else 0})
        # Get updated entry to publish
        rs = self._db.get(dbkey)
        await self._msgclient.publish(f"pong-{token}", rs)

    async def pingpong(self, req):
        if req.payload.type == "ping":
            remotes = req.payload.destinations
            for remote in remotes:
                asyncio.create_task(self.pingTask(str(remote), req))
        else:
            raise Exception(f"unknown type {type}")

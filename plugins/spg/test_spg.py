import os
import sys
import json
import asyncio
from quantnet_mq.rpcclient import RPCClient
from quantnet_mq.schema.models import Schema


class MySPG():
    def __init__(self, nodes, rate, duration):
        self._nodes = nodes
        self._rate = int(rate)
        self._duration = int(duration)

    async def do_spg(self):
        msg = {"nodes": self._nodes, "rate": self._rate, "duration": self._duration}
        return json.loads(await self._client.call("spgRequest", msg, timeout=120.0))

    async def do_query(self, rid):
        msg = {"rid": rid}
        return json.loads(await self._client.call("spgQuery", msg, timeout=20.0))

    async def main(self):
        Schema.load_schema("../schema/spg.yaml", ns="spg")
        self._client = RPCClient("spg-client", host=os.getenv("HOST", "localhost"))
        self._client.set_handler("spgRequest", None, "quantnet_mq.schema.models.spg.spgRequest")
        self._client.set_handler("spgQuery", None, "quantnet_mq.schema.models.spg.spgQuery")
        await self._client.start()

        while True:
            ret = await self.do_spg()
            print(ret)
            await asyncio.sleep(1)
            ret = await self.do_query(ret.get("rid", ""))
            print(ret)
            await asyncio.sleep(60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        node = sys.argv[1].split(",")
        rate = sys.argv[2]
        duration = sys.argv[3]
    else:
        nodes = ["LBNL-Q", "UCB-Q"]
        rate = 100
        duration = 30
    asyncio.run(MySPG(nodes, rate, duration).main())

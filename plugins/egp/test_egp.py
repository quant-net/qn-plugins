import os
import json
import asyncio
from quantnet_mq.rpcclient import RPCClient
from quantnet_mq.schema.models import Schema


async def do_egp(client, src, dst, fidelity):
    msg = {"source": src, "destination": dst, "pairs": 1, "bellState": "11", "fidelity": fidelity}
    return json.loads(await client.call("egpRequest", msg, timeout=120.0))


async def do_query(client, rid):
    msg = {"rid": rid}
    return json.loads(await client.call("egpQuery", msg, timeout=20.0))


async def main():
    Schema.load_schema("../schema/egp.yaml", ns="egp")
    client = RPCClient("egp-client", host=os.getenv("HOST", "localhost"))
    client.set_handler("egpRequest", None, "quantnet_mq.schema.models.egp.egpRequest")
    client.set_handler("egpQuery", None, "quantnet_mq.schema.models.egp.egpQuery")
    await client.start()
    ret = await do_egp(client, "LBNL-Q", "UCB-Q", 0.88)
    print(ret)
    await asyncio.sleep(1)
    ret = await do_query(client, ret.get("rid", ""))
    print(ret)


if __name__ == "__main__":
    asyncio.run(main())
